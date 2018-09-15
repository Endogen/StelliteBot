import json
import logging
import os
import requests
import sys
import time
import threading
import datetime

import numpy as np
import matplotlib
matplotlib.use('agg')
import matplotlib.pyplot as plt
import TradeOgre as to
import twitter as twi

from coinmarketcap import Market
from flask import Flask, jsonify
from collections import OrderedDict, Counter
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from telegram import ParseMode, Chat, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Updater, CommandHandler, MessageHandler, ConversationHandler, RegexHandler
from telegram.ext.filters import Filters
from telegram.error import TelegramError, InvalidToken


# State names for ConversationHandler (poll)
SAVE_ANSWER, CREATE_TOPIC, CREATE_ANSWERS, CREATE_END, DELETE_POLL = range(5)

# Image file for poll results
POLL_IMG = "poll.png"
# Configuration file
CFG_FILE = "config.json"
# Log file for errors
LOG_FILE = "error.log"
# Resource folder
RES_FOLDER = "res"
# Key / Token / Secret folder
KEY_FOLDER = "key"
# File with bot token
BOT_KEY = "bot.key"
# File with Twitter keys / secrets
TWITTER_KEY = "twitter.key"

# Configuration file
config = None


# Read configuration file
def read_cfg():
    if os.path.isfile(CFG_FILE):
        with open(CFG_FILE) as config_file:
            global config
            config = json.load(config_file)
    else:
        exit(f"ERROR: No configuration file '{CFG_FILE}' found")


# Write configuration file
def write_cfg():
    if os.path.isfile(CFG_FILE):
        with open(CFG_FILE, "w") as cfg:
            json.dump(config, cfg, indent=4)
    else:
        exit(f"ERROR: No configuration file '{CFG_FILE}' found")


# Load config
read_cfg()


# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.DEBUG)
logger = logging.getLogger()

error_file = logging.FileHandler(LOG_FILE, delay=True)
error_file.setLevel(logging.ERROR)

logger.addHandler(error_file)


# Initialize Flask to get poll results via web
app = Flask(__name__)


# Make poll related data available over the web
def poll_web():
    app.run(host='0.0.0.0', port=config["poll_ws_port"])


# Runs the bot on a local development server
threading.Thread(target=poll_web).start()


# Access poll data via web
@app.route("/stellite-bot/<string:command>", methods=["GET"])
def poll_data(command):
    if command == "poll":
        return jsonify(success=True, message=config["poll"]["topic"], commad=command)
    if command == "answers":
        return jsonify(success=True, message=config["poll"]["answers"], commad=command)
    if command == "data":
        return jsonify(success=True, message=config["poll"]["data"], commad=command)
    else:
        return jsonify(success=False, message='Something went wrong...')


# Wait until webserver is started
time.sleep(1)


# Read bot token from file
if os.path.isfile(os.path.join(KEY_FOLDER, BOT_KEY)):
    with open(os.path.join(KEY_FOLDER, BOT_KEY), 'r') as f:
        bot_token = f.read().splitlines()
else:
    exit(f"ERROR: No key file '{BOT_KEY}' found in dir '{KEY_FOLDER}'")

# Set bot token, get dispatcher and job queue
try:
    updater = Updater(bot_token[0], request_kwargs={'read_timeout': 15, 'connect_timeout': 15})
    dispatcher = updater.dispatcher
    job_queue = updater.job_queue
except InvalidToken:
    exit("ERROR: Bot token not valid")


# Read Twitter keys / secrets from file
if os.path.isfile(os.path.join(KEY_FOLDER, TWITTER_KEY)):
    with open(os.path.join(KEY_FOLDER, TWITTER_KEY), 'r') as f:
        twitter_keys = f.read().splitlines()
else:
    exit(f"ERROR: No key file '{TWITTER_KEY}' found in dir '{KEY_FOLDER}'")

# Set tokens for Twitter access
twitter_api = twi.Api(consumer_key=twitter_keys[0],
                      consumer_secret=twitter_keys[1],
                      access_token_key=twitter_keys[2],
                      access_token_secret=twitter_keys[3])


# Handler to handle config file changes
class CfgHandler(FileSystemEventHandler):
    @staticmethod
    def on_modified(event):
        if os.path.basename(event.src_path) == CFG_FILE:
            read_cfg()
            msg = "Config reloaded"
            updater.bot.send_message(config["dev_user_id"], msg)


# Watch for config file changes
observer = Observer()
observer.schedule(CfgHandler(), ".", recursive=True)
observer.start()


# Check Twitter timeline for new Tweets repeatably
def check_twitter(bot, job):
    # Return all new Tweets (newer then saved one)
    if config["last_tweet_id"]:
        twitter = config["twitter_account"]
        tweet_id = config["last_tweet_id"]

        timeline = twitter_api.GetUserTimeline(screen_name=twitter,
                                               since_id=tweet_id,
                                               include_rts=False,
                                               trim_user=True,
                                               exclude_replies=True)

        if timeline:
            for tweet in [i.AsDict() for i in reversed(timeline)]:
                msg = "[New Tweet from " + twitter + "](http://www.twitter.com/" + \
                      twitter + "/" + "status/" + str(tweet["id"]) + ")\n\n"

                bot.send_message(chat_id=config["chat_id"],
                                 parse_mode=ParseMode.MARKDOWN,
                                 text=msg)

                update_cfg("last_tweet_id", tweet["id"])

    # Return newest Tweet and save it as current one
    else:
        timeline = twitter_api.GetUserTimeline(screen_name=config["twitter_account"],
                                               count=1,
                                               include_rts=False,
                                               trim_user=True,
                                               exclude_replies=True)

        if timeline:
            update_cfg("last_tweet_id", timeline[0].AsDict()["id"])


# Post messages repeatably
def repost_msg(bot, job):
    bot.send_message(chat_id=config["chat_id"],
                     parse_mode=ParseMode.MARKDOWN,
                     text=job.context["text"])


# Add Telegram group admins to admin-list for this bot
def add_tg_admins(bot, update):
    tg_admins = bot.get_chat_administrators(config["chat_id"])
    tg_admin_list = [admin["user"].id for admin in tg_admins]

    if all(admin in config["adm_list"] for admin in tg_admin_list):
        return

    all_admins = list(set(config["adm_list"]) | set(tg_admin_list))
    update_cfg("adm_list", all_admins)


# Decorator to restrict access if user is not an admin
def restrict_access(func):
    def _restrict_access(bot, update, **kwargs):
        # Add Telegram group admins to admin list
        if config["add_tg_admins"]:
            add_tg_admins(bot, update)

        # Check if user of msg is in admin list
        if update.message.from_user.id in config["adm_list"]:
            return func(bot, update, **kwargs)

        msg = "Access denied \U0001F6AB"
        update.message.reply_text(msg)

    return _restrict_access


# Decorator to check if command can be used only in private chat with bot
def check_private_chat(func):
    def _check_private_chat(bot, update, **kwargs):
        # Check if command is "private only"
        cmd = update.message.text
        if cmd.replace("/", "").replace(bot.name, "").lower() in config["only_private"]:

            # Check if in a private chat with bot
            if bot.get_chat(update.message.chat_id).type != Chat.PRIVATE:
                msg = "This command is only available in a private chat with " + bot.name
                update.message.reply_text(msg)
                return

        return func(bot, update, **kwargs)

    return _check_private_chat


# Create a button menu to show in messages
def build_menu(buttons, n_cols=1, header_buttons=None, footer_buttons=None):
    menu = [buttons[i:i + n_cols] for i in range(0, len(buttons), n_cols)]

    if header_buttons:
        menu.insert(0, header_buttons)
    if footer_buttons:
        menu.append(footer_buttons)

    return menu


# Save value for given key in config and store it on filesystem
def update_cfg(key, value, preload=False):
    def recursive_update(haystack, needle, new_value):
        if isinstance(haystack, dict):
            for key, value_dict in haystack.items():
                if needle == key:
                    haystack[key] = new_value
                elif isinstance(value_dict, list) or isinstance(value_dict, dict):
                    recursive_update(value_dict, needle, new_value)
        elif isinstance(haystack, list):
            for value_list in haystack:
                if isinstance(value_list, dict):
                    recursive_update(value_list, needle, new_value)

        return haystack

    global config

    # Load config
    if preload:
        read_cfg()

    # Set new value
    recursive_update(config, key, value)

    # Save config
    write_cfg()


# Change permissions of a user
@check_private_chat
@restrict_access
def usr_to_admin(bot, update):
    # Message has to be a reply
    if update.message.reply_to_message is None:
        return

    # Has to be in a group, not in private chat
    if bot.get_chat(update.message.chat_id).type == Chat.PRIVATE:
        return

    chat_id = update.message.chat_id
    user_id = update.message.reply_to_message.from_user.id

    success = bot.promote_chat_member(
        chat_id,
        user_id,
        can_delete_messages=True,
        can_restrict_members=True,
        can_pin_messages=True)

    if success:
        username = update.message.reply_to_message.from_user.username
        first_name = update.message.reply_to_message.from_user.first_name

        if username:
            msg = "User @" + username + " is admin"
        else:
            msg = first_name + " is admin"

        bot.send_message(chat_id=chat_id, text=msg, disable_notification=True)


# Change bot settings on the fly
@check_private_chat
@restrict_access
def change_cfg(bot, update, args):
    if len(args) == 0:
        msg = "`No setting provided`"
        update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        return

    # Extract key / value pairs and save in dictionary
    settings = dict(s.split('=', 1) for s in args)

    # Set new values for settings
    for key, value in settings.items():
        if key in config:
            if value.lower() in ["true", "yes", "1"]:
                update_cfg(key, True)
            elif value.lower() in ["false", "no", "0"]:
                update_cfg(key, False)
            else:
                update_cfg(key, value)

    # Restart bot to activate new settings
    restart_bot(bot, update)


# TODO: Do one msg for every usr in list
# TODO: Only one msg in group - delete old msg if new join
# Greet new members with a welcome message
def welcome(bot, update):
    if config["welcome_new_usr"]:
        try:
            if config["rem_joined_msg"]:
                # Remove default user-joined message
                update.message.delete()
        except TelegramError:
            # Bot doesn't have admin rights
            pass

        for user in update.message.new_chat_members:
            if user.username:
                msg = "Welcome @" + user.username
            else:
                msg = "Welcome <b>" + user.first_name + "</b>"

            pinned_msg = bot.get_chat(update.message.chat_id).pinned_message

            # If config has welcome message, use it
            if config["welcome_msg"]:
                welcome_msg = "".join(config["welcome_msg"])
            else:
                if pinned_msg:
                    url = "t.me/" + config["chat_id"][1:] + "/" + str(pinned_msg.message_id)

                    welcome_msg = ['Please take a minute to read the <a href="' + url +
                                   '">pinned message</a>. It includes rules for this group '
                                   'and also important information regarding Stellite.']
                else:
                    return

            bot.send_message(
                chat_id=update.message.chat.id,
                text=msg + ". " + "".join(welcome_msg),
                disable_notification=True,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True)


# Analyze message and react on specific content
def check_msg(bot, update):
    # Ban bots if they try to post a message
    if config["ban_bots"] and update.message.from_user.is_bot:
        ban(bot, update, auto_ban=True)
        return

    # Automatically reply to predefined content
    if config["auto_reply"]:
        # Save message to analyze content
        txt = update.message.text.lower()

        if "when moon" in txt or "wen moon" in txt:
            moon = open(os.path.join(RES_FOLDER, "soon_moon.mp4"), 'rb')
            update.message.reply_video(moon, parse_mode=ParseMode.MARKDOWN)
        elif "hodl" in txt:
            caption = "HODL HARD! ;-)"
            hodl = open(os.path.join(RES_FOLDER, "HODL.jpg"), 'rb')
            update.message.reply_photo(hodl, caption=caption, parse_mode=ParseMode.MARKDOWN)
        elif "airdrop" in txt:
            caption = "Airdrops? Stellite doesn't have any since the premine was only 0.6%"
            tech = open(os.path.join(RES_FOLDER, "AIRDROP.jpg"), 'rb')
            update.message.reply_photo(tech, caption=caption, parse_mode=ParseMode.MARKDOWN)
        elif "ico?" in txt:
            caption = "BTW: Stellite had no ICO"
            ico = open(os.path.join(RES_FOLDER, "ICO.jpg"), 'rb')
            update.message.reply_photo(ico, caption=caption, parse_mode=ParseMode.MARKDOWN)
        elif "when binance" in txt:
            moon = open(os.path.join(RES_FOLDER, "when_binance.mp4"), 'rb')
            update.message.reply_video(moon, parse_mode=ParseMode.MARKDOWN)
        elif "in it for the tech" in txt:
            caption = "Who's in it for the tech? ;-)"
            tech = open(os.path.join(RES_FOLDER, "in_it_for_the_tech.jpg"), 'rb')
            update.message.reply_photo(tech, caption=caption, parse_mode=ParseMode.MARKDOWN)


# Get info about coin from CoinMarketCap
@check_private_chat
def cmc(bot, update):
    # Get coin id if not already known
    if not config["cmc_coin_id"]:
        listings = Market().listings()
        for listing in listings["data"]:
            if config["ticker_symbol"].upper() == listing["symbol"].upper():
                update_cfg("cmc_coin_id", listing["id"])
                break

    ticker = Market().ticker(config["cmc_coin_id"], convert="BTC")

    coin = ticker["data"]
    symbol = coin["symbol"]
    slug = coin["website_slug"]
    rank = str(coin["rank"])
    sup_c = "{0:,}".format(int(coin["circulating_supply"]))

    usd = coin["quotes"]["USD"]
    p_usd = "{0:.8f}".format(usd["price"])
    v_24h = "{0:,}".format(int(usd["volume_24h"]))
    m_cap = "{0:,}".format(int(usd["market_cap"]))
    c_1h = str(usd["percent_change_1h"])
    c_24h = str(usd["percent_change_24h"])
    c_7d = str(usd["percent_change_7d"])

    btc = coin["quotes"]["BTC"]
    p_btc = "{0:.8f}".format(float(btc["price"]))

    msg = "`" + symbol + " " + p_usd + " USD | " + p_btc + " BTC\n" + \
        "1h " + c_1h + "% | 24h " + c_24h + "% | 7d " + c_7d + "%\n\n" + \
        "CMC Rank: " + rank + "\n" + \
        "Volume 24h: " + v_24h + " USD\n" + \
        "Market Cap: " + m_cap + " USD\n" + \
        "Circ. Supply: " + sup_c + " " + symbol + "`\n\n" + \
        "[Stats from CoinMarketCap](https://coinmarketcap.com/currencies/" + slug + ")"

    update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)


# Get current price of XTL for all given asset pairs
@check_private_chat
def price(bot, update):
    msg = "TradeOgre:\n"

    for pair_dict in to.API().markets():
        for pair, data in pair_dict.items():
            if config["ticker_symbol"] in pair:
                xtl_ticker = to.API().ticker(pair)
                msg += xtl_ticker["price"] + " " + pair.split("-")[0].upper() + "\n"
            break

    update.message.reply_text("`" + msg + "`", parse_mode=ParseMode.MARKDOWN)


# Display summaries for specific topics
@check_private_chat
def wiki(bot, update, args):
    # Check if there are arguments
    if len(args) > 0:
        value = str()

        # Lookup provided argument in config
        if args[0].lower() in config["wiki"]:
            value = "".join(config["wiki"][args[0].lower()])

        if value:
            # Check if value is an existing image
            if os.path.isfile(os.path.join(RES_FOLDER, value)):
                image = open(os.path.join(RES_FOLDER, value), 'rb')
                update.message.reply_photo(image)
            else:
                update.message.reply_text(value, parse_mode=ParseMode.MARKDOWN)
        else:
            msg = "`No entry found`"
            update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    else:
        msg = "`No search term provided. Here is a list of all possible terms:\n\n`"

        # Iterate over wiki-term dict and build a str out of it
        terms = str()

        for term in sorted(list(config["wiki"])):
            terms += term + "\n"

        update.message.reply_text(msg + "`" + terms + "`", parse_mode=ParseMode.MARKDOWN)


# Show info about bot and all available commands
@check_private_chat
def help(bot, update):
    # Check if user is admin
    if update.message.from_user.id in config["adm_list"]:
        msg = "".join(config["help_msg_adm"])
        update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    else:
        msg = "".join(config["help_msg"])
        update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)


# Send feedback about bot to bot-developer
@check_private_chat
def feedback(bot, update, args):
    if args and args[0]:
        msg = "Thank you for the feedback! \U0001F44D"
        update.message.reply_text(msg)

        # Send feedback to developer
        user = update.message.from_user.username

        if user:
            feedback_msg = "Feedback from @" + user + ": " + " ".join(args)
            bot.send_message(chat_id=config["dev_user_id"], text=feedback_msg)
        else:
            feedback_msg = "Feedback: " + " ".join(args)
            bot.send_message(chat_id=config["dev_user_id"], text=feedback_msg)
    else:
        msg = "No feedback entered \U00002757"
        update.message.reply_text(msg)


# Poll functionality for users
@check_private_chat
def poll(bot, update, args):
    # Normal poll
    if len(args) == 0:
        # Check if there is an active poll
        if not config["poll"]["topic"]:
            msg = "There is currently no active poll"
            update.message.reply_text(msg)
            return

        # Check if end-date is reached
        if config["poll"]["end"]:
            now = datetime.datetime.utcnow()
            end = datetime.datetime.strptime(config["poll"]["end"], "%Y-%m-%d %H:%M:%S")

            if now > end:
                ended = "Poll already ended.\nSee results with `/poll results`"
                update.message.reply_text(ended, parse_mode=ParseMode.MARKDOWN)
                return

        # Check if user already gave an answer
        user_name = update.message.from_user.first_name
        if user_name in config["poll"]["data"]:
            answered = "You already gave an answer but you can change it if you like"
            update.message.reply_text(answered)

        question = config["poll"]["topic"]
        answers = config["poll"]["answers"]

        # No answers predefined - user can enter what he wants
        if answers[0] == "none":
            menu = build_menu(["cancel"])
            markup = ReplyKeyboardMarkup(menu, resize_keyboard=True)
            update.message.reply_text(question, reply_markup=markup)

        # Predefined answers, use has to choose from keyboard
        else:
            # Set number of columns for answer-buttons
            if len(answers) > 3:
                cols = 3
            else:
                cols = len(answers)

            menu = build_menu(answers, n_cols=cols, footer_buttons=["cancel"])
            markup = ReplyKeyboardMarkup(menu, resize_keyboard=True)
            update.message.reply_text(question, reply_markup=markup)

        return SAVE_ANSWER

    # Generate image of poll results
    if args[0].lower() == "results":
        return poll_results(bot, update)

    # Create new poll
    if args[0].lower() == "create":
        # Check if a poll already exists
        if config["poll"]["topic"]:
            msg = "There is already an active poll.\nRemove it first with `/poll delete`"
            update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
            return ConversationHandler.END

        msg = "Tell me the topic of the poll"
        update.message.reply_text(msg)
        return CREATE_TOPIC

    # Delete currently active poll
    if args[0].lower() == "delete":
        if config["poll"]["topic"]:
            msg = "Do you really want to remove the current poll?"
            menu = build_menu(["yes", "no"], n_cols=2)
            keyboard = ReplyKeyboardMarkup(menu, one_time_keyboard=True, resize_keyboard=True)
            update.message.reply_text(msg, reply_markup=keyboard)
            return DELETE_POLL
        else:
            msg = "Nothing to delete - no active poll"
            update.message.reply_text(msg)
            return ConversationHandler.END


# Generate image for poll results
def poll_results(bot, update):
    # Count and sort answers
    counted = Counter(config["poll"]["data"].values())
    data = OrderedDict(sorted(counted.items(), key=lambda t: t[1]))

    answers = tuple(data.keys())
    y_pos = np.arange(len(answers))
    fig = plt.figure()
    # Create horizontal bars
    plt.barh(y_pos, list(data.values()))
    # Create names on the y-axis
    plt.yticks(y_pos, answers)

    # Add title and axis names
    plt.title("Topic: " + config["poll"]["topic"])
    plt.xlabel("number of answers")
    plt.ylabel("answers")

    # Create image
    fig.savefig(os.path.join(RES_FOLDER, POLL_IMG))

    plot = open(os.path.join(RES_FOLDER, POLL_IMG), 'rb')

    user_name = update.message.from_user.first_name

    # Get user answer
    if user_name in config["poll"]["data"]:
        caption = "Your answer was '" + config["poll"]["data"][user_name] + "'"
    else:
        caption = "You didn't participate in the poll yet"

    # Add total answers
    data = len(config["poll"]["data"])
    caption += "\nTotal answers: " + str(data)

    # Add user participation
    if config["chat_id"]:
        members = bot.get_chat_members_count(config["chat_id"])
        caption += " (participation: " + "{:.2f}".format(data / members * 100) + "%)"

    # Add end-date for the poll
    caption += "\nThe survey will end on " + config["poll"]["end"]

    update.message.reply_photo(
        plot,
        caption=caption,
        parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END


# Set new topic for the poll
@check_private_chat
@restrict_access
def poll_create_topic(bot, update, user_data):
    user_data["topic"] = update.message.text

    msg = "What are the possible answers? Comma separated like this: `yes, no, maybe` " \
          "or send `none` if users can enter what they want."
    update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    return CREATE_ANSWERS


# Set possible answers for poll
def poll_create_answers(bot, update, user_data):
    user_data["answers"] = [answer.lower().strip() for answer in update.message.text.split(",")]

    # Check entered answers
    if len(user_data["answers"]) == 1 and user_data["answers"][0] != "none":
        msg = "Wrong answers entered. Enter `none` for free choice " \
              "or comma separated list like this: `yes, no, maybe`"
        update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        return CREATE_ANSWERS

    msg = "When should the poll end? Enter date and time in this form: `YYYY-MM-DD HH:MM:SS`"
    update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    return CREATE_END


# Set the end-date for the current poll
def poll_create_end(bot, update, user_data):
    try:
        # Check if given datetime is valid
        datetime.datetime.strptime(update.message.text, '%Y-%m-%d %H:%M:%S')
    except ValueError as ex:
        msg = "Wrong format for end date entered. " \
              "Enter date and time in this form: `YYYY-MM-DD HH:MM:SS`"
        update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        return CREATE_END

    user_data["end"] = update.message.text

    config["poll"]["topic"] = user_data["topic"]
    config["poll"]["answers"] = user_data["answers"]
    config["poll"]["data"] = dict()
    config["poll"]["end"] = user_data["end"]

    user_data.clear()

    update_cfg("poll", config["poll"])

    msg = "Poll is live! Let's get some answers \U0001F603"
    update.message.reply_text(msg)

    return ConversationHandler.END


# Delete currently active poll
@check_private_chat
@restrict_access
def poll_delete(bot, update):
    if update.message.text == "yes":
        config["poll"]["topic"] = str()
        config["poll"]["answers"] = list()
        config["poll"]["data"] = dict()
        config["poll"]["end"] = str()

        update_cfg("poll", config["poll"])

        msg = "Poll cleared"
        update.message.reply_text(msg, reply_markup=ReplyKeyboardRemove())

    else:
        msg = "Canceled"
        update.message.reply_text(msg, reply_markup=ReplyKeyboardRemove())

    return ConversationHandler.END


# Save answer to poll in config
def poll_save_answer(bot, update):
    answer = update.message.text.lower()

    if answer == "cancel":
        msg = "Poll canceled"
        update.message.reply_text(msg, reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    global config

    # Check if answer is valid
    answers = config["poll"]["answers"]
    if answers[0] != "none" and answer not in answers:
        msg = "Answer not allowed. Please try again"
        update.message.reply_text(msg)
        return SAVE_ANSWER

    user = update.message.from_user.first_name
    config["poll"]["data"][user] = answer.lower()

    # Save config
    write_cfg()

    update.message.reply_text(
        "Your answer has been saved \U0001F44D",
        reply_markup=ReplyKeyboardRemove())

    return ConversationHandler.END


# Check if there is an update available for this bot
@check_private_chat
@restrict_access
def version_bot(bot, update):
    # Get newest version of this script from GitHub
    headers = {"If-None-Match": config["update_hash"]}
    github_file = requests.get(config["update_url"], headers=headers)

    # Status code 304 = Not Modified (same hash / same version)
    if github_file.status_code == 304:
        msg = "Bot is up to date"
    # Status code 200 = OK (different hash / not the same version)
    elif github_file.status_code == 200:
        msg = "New version available"
    # Every other status code
    else:
        msg = "Unexpected status code: " + github_file.status_code

    update.message.reply_text(msg)


# Update the bot to newest version on GitHub
@check_private_chat
@restrict_access
def update_bot(bot, update):
    # Get newest version of this script from GitHub
    headers = {"If-None-Match": config["update_hash"]}
    github_script = requests.get(config["update_url"], headers=headers)

    # Status code 304 = Not Modified
    if github_script.status_code == 304:
        msg = "You are running the latest version"
        update.message.reply_text(msg)
    # Status code 200 = OK
    elif github_script.status_code == 200:
        msg = "Bot is updating..."
        update.message.reply_text(msg)

        # Get github 'config.json' file
        last_slash_index = config["update_url"].rfind("/")
        github_config_path = config["update_url"][:last_slash_index + 1] + CFG_FILE
        github_config_file = requests.get(github_config_path)
        github_config = json.loads(github_config_file.text)

        # Compare current config keys with config keys from github-config
        if set(config) != set(github_config):
            # Go through all keys in github-config and
            # if they are not present in current config, add them
            for key, value in github_config.items():
                if key not in config:
                    config[key] = value

        # Save current ETag (hash) of bot script in config
        update_cfg("update_hash", github_script.headers.get("ETag"))

        # Get the name of the currently running script
        path_split = os.path.split(str(sys.argv[0]))
        filename = path_split[len(path_split)-1]

        # Save the content of the remote file
        with open(filename, "w") as file:
            file.write(github_script.text)

        msg = "Update finished..."
        update.message.reply_text(msg)

        # Restart the bot
        restart_bot(bot, update)


# Restart bot (for example to reload changed config)
@check_private_chat
@restrict_access
def restart_bot(bot, update):
    msg = "Restarting bot..."
    update.message.reply_text(msg)

    # Set restart-user in config
    update_cfg("restart_usr", update.message.chat_id, preload=True)

    # Restart bot
    time.sleep(0.2)
    os.execl(sys.executable, sys.executable, *sys.argv)


# This needs to be run on a new thread because calling 'updater.stop()' inside a
# handler (shutdown_cmd) causes a deadlock because it waits for itself to finish
def shutdown():
    updater.stop()
    updater.is_idle = False


# Terminate this script
@check_private_chat
@restrict_access
def shutdown_bot(bot, update):
    update.message.reply_text("Shutting down...")
    # See comments on the 'shutdown' function
    threading.Thread(target=shutdown).start()


# Ban the user you are replying to
@restrict_access
def ban(bot, update, auto_ban=False):
    chat_id = update.message.chat_id

    # For auto-banning bots
    if auto_ban:
        user_id = update.message.from_user.id
    else:
        # Message has to be a reply
        if update.message.reply_to_message is None:
            return

        # Has to be in a group, not in private chat
        if bot.get_chat(update.message.chat_id).type == Chat.PRIVATE:
            return

        user_id = update.message.reply_to_message.from_user.id

    success = bot.kick_chat_member(chat_id=chat_id, user_id=user_id)

    if success:
        username = update.message.reply_to_message.from_user.username
        first_name = update.message.reply_to_message.from_user.first_name

        if username:
            msg = "User @" + username + " banned"
        else:
            msg = first_name + " banned"

        bot.send_message(chat_id=chat_id, text=msg, disable_notification=True)


# Delete the message that you are replying to
@restrict_access
def delete(bot, update):
    original_msg = update.message.reply_to_message

    if original_msg:
        chat_id = update.message.chat_id
        bot.delete_message(chat_id=chat_id, message_id=original_msg.message_id)


# Cancel a poll-conversation with the bot
def poll_cancel(bot, update):
    update.message.reply_text("Poll canceled", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# Handle all telegram and telegram.ext related errors
def handle_telegram_error(bot, update, error):
    # Log error
    logger.error("Update '%s' caused error '%s'" % (update, error))

    # Send message to user if source of error is a message
    if update and update.message:
        msg = "Oh, something went wrong \U00002639"
        update.message.reply_text(msg)

    # Send error to admin
    if config["send_error"]:
        msg = type(error).__name__ + ": " + str(error)
        bot.send_message(chat_id=config["dev_user_id"], text=msg)


# Log all errors
dispatcher.add_error_handler(handle_telegram_error)


# CommandHandlers to provide commands
dispatcher.add_handler(CommandHandler("cmc", cmc))
dispatcher.add_handler(CommandHandler("ban", ban))
dispatcher.add_handler(CommandHandler("help", help))
dispatcher.add_handler(CommandHandler("start", help))
dispatcher.add_handler(CommandHandler("price", price))
dispatcher.add_handler(CommandHandler("delete", delete))
dispatcher.add_handler(CommandHandler("update", update_bot))
dispatcher.add_handler(CommandHandler("admin", usr_to_admin))
dispatcher.add_handler(CommandHandler("version", version_bot))
dispatcher.add_handler(CommandHandler("restart", restart_bot))
dispatcher.add_handler(CommandHandler("shutdown", shutdown_bot))
dispatcher.add_handler(CommandHandler("wiki", wiki, pass_args=True))
dispatcher.add_handler(CommandHandler("config", change_cfg, pass_args=True))
dispatcher.add_handler(CommandHandler("feedback", feedback, pass_args=True))


# ConversationHandler for poll
poll_handler = ConversationHandler(
    entry_points=[CommandHandler("poll", poll, pass_args=True)],
    states={
        SAVE_ANSWER: [MessageHandler(Filters.text, poll_save_answer)],
        CREATE_TOPIC: [MessageHandler(Filters.text, poll_create_topic, pass_user_data=True)],
        CREATE_ANSWERS: [MessageHandler(Filters.text, poll_create_answers, pass_user_data=True)],
        CREATE_END: [MessageHandler(Filters.text, poll_create_end, pass_user_data=True)],
        DELETE_POLL: [RegexHandler("^(yes|no)$", poll_delete)]
    },
    fallbacks=[CommandHandler('cancel', poll_cancel)],
    allow_reentry=True)
dispatcher.add_handler(poll_handler)


# MessageHandlers that filter on specific content
dispatcher.add_handler(MessageHandler(Filters.status_update.new_chat_members, welcome))
dispatcher.add_handler(MessageHandler(Filters.text, check_msg))


# Start the bot
updater.start_polling(clean=True)


# Check for new Tweets
if config["twitter_account"]:
    job_queue.run_repeating(check_twitter, config["check_tweet"], first=0)


# Repost messages at given time
for repost in config["reposts"]:
    if repost["text"]:
        interval = repost["repeat_min"] * 60
        start = repost["start_min"] * 60
        job_queue.run_repeating(repost_msg, interval, first=start, context=repost)


# Send message that bot is started after restart
if config["restart_usr"]:
    msg = "Bot started..."
    updater.bot.send_message(chat_id=config["restart_usr"], text=msg)

    # Set key to empty value
    update_cfg("restart_usr", None)


# Change to idle mode
updater.idle()
