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
from telegram import ParseMode, Chat, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Updater, CommandHandler, MessageHandler, ConversationHandler, RegexHandler
from telegram.ext.filters import Filters
from telegram.error import TelegramError, InvalidToken


# State name for ConversationHandler
SAVE_VOTE, CREATE_VOTE_TOPIC, CREATE_VOTE_ANSWERS, CREATE_VOTE_END, DELETE_VOTE = range(5)

# Image file for voting results
VOTE_IMG = "voting.png"
# Configuration file
CFG_FILE = "config.json"
# Log file for errors
LOG_FILE = "error.log"


# Initialize Flask to get voting results via web
app = Flask(__name__)


# Read configuration file
if os.path.isfile(CFG_FILE):
    # Load configuration
    with open(CFG_FILE) as config_file:
        config = json.load(config_file)
else:
    exit("ERROR: No configuration file 'config.json' found")


# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.DEBUG)
logger = logging.getLogger()

error_file = logging.FileHandler(LOG_FILE, delay=True)
error_file.setLevel(logging.ERROR)

logger.addHandler(error_file)


# Set bot token, get dispatcher and job queue
try:
    updater = Updater(token=config["bot_token"])
    dispatcher = updater.dispatcher
    job_queue = updater.job_queue
except InvalidToken:
    exit("ERROR: Bot token not valid")


# Set tokens for Twitter access
twitter_api = twi.Api(consumer_key=config["twitter_consumer_key"],
                      consumer_secret=config["twitter_consumer_secret"],
                      access_token_key=config["twitter_access_token_key"],
                      access_token_secret=config["twitter_access_token_secret"])


# Access voting data via web
@app.route("/StelliteBot/<string:command>", methods=["GET"])
def voting_data(command):
    if command == "topic":
        return jsonify(success=True, message=config["voting"]["topic"], commad=command)
    if command == "answers":
        return jsonify(success=True, message=config["voting"]["answers"], commad=command)
    if command == "votes":
        return jsonify(success=True, message=config["voting"]["votes"], commad=command)
    else:
        return jsonify(success=False, message='Something went wrong...')


# Make voting related data available over the web
def voting_web():
    # TODO: Enable again when it's working
    # https://github.com/pallets/flask/issues/651
    # https://stackoverflow.com/questions/12269537/is-the-server-bundled-with-flask-safe-to-use-in-production
    #app.run()
    pass


# Check Twitter timeline for new Tweets
def check_twitter(bot, update):
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


# Save value for given key in config and store in file
def update_cfg(key, value):
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

    # Read config because it could have been changed
    with open(CFG_FILE) as cfg:
        config = json.load(cfg)

    # Set new value
    recursive_update(config, key, value)

    # Save config
    with open(CFG_FILE, "w") as cfg:
        json.dump(config, cfg, indent=4)


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


# Greet new members with a welcome message
def welcome(bot, update):
    if config["welcome_new_usr"]:
        try:
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

            # If config has welcome message, use it
            if config["welcome_msg"]:
                welcome_msg = "".join(config["welcome_msg"])
            else:
                pinned_msg = bot.get_chat(update.message.chat_id).pinned_message
                url = "t.me/" + config["chat_id"][1:] + "/" + str(pinned_msg.message_id)

                welcome_msg = ['Please take a minute to read the <a href="' + url +
                               '">pinned message</a>. It includes rules for this group '
                               'and also important information regarding Stellite.']

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
            moon = open(os.path.join(config["res_folder"], "soon_moon.mp4"), 'rb')
            update.message.reply_video(moon, parse_mode=ParseMode.MARKDOWN)
        elif "hodl" in txt:
            caption = "HODL HARD! ;-)"
            hodl = open(os.path.join(config["res_folder"], "HODL.jpg"), 'rb')
            update.message.reply_photo(hodl, caption=caption, parse_mode=ParseMode.MARKDOWN)
        elif "airdrop" in txt:
            caption = "Airdrops? Stellite doesn't have any since the premine was only 0.6%"
            tech = open(os.path.join(config["res_folder"], "AIRDROP.jpg"), 'rb')
            update.message.reply_photo(tech, caption=caption, parse_mode=ParseMode.MARKDOWN)
        elif "ico?" in txt:
            caption = "BTW: Stellite had no ICO"
            ico = open(os.path.join(config["res_folder"], "ICO.jpg"), 'rb')
            update.message.reply_photo(ico, caption=caption, parse_mode=ParseMode.MARKDOWN)
        elif "when binance" in txt:
            moon = open(os.path.join(config["res_folder"], "when_binance.mp4"), 'rb')
            update.message.reply_video(moon, parse_mode=ParseMode.MARKDOWN)
        elif "in it for the tech" in txt:
            caption = "Who's in it for the tech? ;-)"
            tech = open(os.path.join(config["res_folder"], "in_it_for_the_tech.jpg"), 'rb')
            update.message.reply_photo(tech, caption=caption, parse_mode=ParseMode.MARKDOWN)


# Get info about coin from CoinMarketCap
@check_private_chat
@restrict_access
def cmc(bot, update):
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

    for asset in config["pairing_asset"]:
        xtl_ticker = to.API().ticker(asset + "-XTL")
        msg += xtl_ticker["price"] + " " + asset.upper() + "\n"

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
            if os.path.isfile(os.path.join(config["res_folder"], value)):
                image = open(os.path.join(config["res_folder"], value), 'rb')
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


# Voting functionality for users
@check_private_chat
def vote(bot, update, args):
    # Normal voting
    if len(args) == 0:
        # Check if there is something to vote on
        if not config["voting"]["topic"]:
            msg = "There is currently nothing to vote on"
            update.message.reply_text(msg)
            return

        # Check if end-date is reached
        if config["voting"]["end"]:
            now = datetime.datetime.utcnow()
            end = datetime.datetime.strptime(config["voting"]["end"], "%Y-%m-%d %H:%M:%S")

            if now > end:
                ended = "Voting already ended.\nSee results with `/vote results`"
                update.message.reply_text(ended, parse_mode=ParseMode.MARKDOWN)
                return

        # Check if user already voted
        user_name = update.message.from_user.first_name
        if user_name in config["voting"]["votes"]:
            voted = "You already voted but you can change your vote if you like"
            update.message.reply_text(voted)

        question = config["voting"]["topic"]
        answers = config["voting"]["answers"]

        # Set number of columns for answer-buttons
        if len(answers) > 3:
            cols = 3
        else:
            cols = len(answers)

        menu = build_menu(answers, n_cols=cols, footer_buttons=["cancel"])
        update.message.reply_text(question, reply_markup=ReplyKeyboardMarkup(menu))
        return SAVE_VOTE

    # Generate image of voting results
    if args[0].lower() == "results":
        return vote_results(bot, update)

    # Create new topic to vote on
    if args[0].lower() == "create":
        # Check for existing vote
        if config["voting"]["topic"]:
            msg = "Voting already active.\nRemove it first with `/vote delete`"
            update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
            return ConversationHandler.END

        msg = "Tell me the topic to vote on"
        update.message.reply_text(msg)
        return CREATE_VOTE_TOPIC

    # Delete currently active voting
    if args[0].lower() == "delete":
        if config["voting"]["topic"]:
            msg = "Do you really want to remove the current vote?"
            menu = build_menu(["yes", "no"], n_cols=2)
            keyboard = ReplyKeyboardMarkup(menu, one_time_keyboard=True)
            update.message.reply_text(msg, reply_markup=keyboard)
            return DELETE_VOTE
        else:
            msg = "Nothing to delete - no active voting"
            update.message.reply_text(msg)
            return ConversationHandler.END


# TODO: Add title to diagram
# Generate image of voting results
def vote_results(bot, update):
    # Count and sort answers
    counted = Counter(config["voting"]["votes"].values())
    votes = OrderedDict(sorted(counted.items(), key=lambda t: t[1]))

    answers = tuple(votes.keys())
    y_pos = np.arange(len(answers))
    fig = plt.figure()
    # Create horizontal bars
    plt.barh(y_pos, list(votes.values()))
    # Create names on the y-axis
    plt.yticks(y_pos, answers)

    # Add title and axis names
    plt.title("Topic: " + config["voting"]["topic"])
    plt.xlabel("number of votes")
    plt.ylabel("answers")

    # Create image
    fig.savefig(os.path.join(config["res_folder"], VOTE_IMG))

    plot = open(os.path.join(config["res_folder"], VOTE_IMG), 'rb')

    user_name = update.message.from_user.first_name

    # Get user vote
    if user_name in config["voting"]["votes"]:
        caption = "You voted for '" + config["voting"]["votes"][user_name] + "'"
    else:
        caption = "You didn't vote yet"

    # Add total votes
    votes = len(config["voting"]["votes"])
    caption += "\nTotal votes: " + str(votes)

    # Add user participation
    if config["chat_id"]:
        members = bot.get_chat_members_count(config["chat_id"])
        caption += " (participation: " + "{:.2f}".format(votes / members * 100) + "%)"

    update.message.reply_photo(
        plot,
        caption=caption,
        parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END


# Set new topic to vote on
@check_private_chat
@restrict_access
def vote_create_topic(bot, update, user_data):
    user_data["topic"] = update.message.text

    msg = "What are the possible choices? Comma separated like this: `yes, no, maybe`"
    update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    return CREATE_VOTE_ANSWERS


# Set possible answers for voting
def vote_create_answers(bot, update, user_data):
    user_data["answers"] = [answer.lower().strip() for answer in update.message.text.split(",")]

    msg = "When should voting end? In this form: `YYYY-MM-DD HH:MM:SS`"
    update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    return CREATE_VOTE_END


# Set the end-date for the current voting
def vote_create_end(bot, update, user_data):
    user_data["end"] = update.message.text

    config["voting"]["topic"] = user_data["topic"]
    config["voting"]["answers"] = user_data["answers"]
    config["voting"]["votes"] = dict()
    config["voting"]["end"] = user_data["end"]

    user_data.clear()

    update_cfg("voting", config["voting"])

    msg = "Voting is live! Let's get some votes :-)"
    update.message.reply_text(msg)

    return ConversationHandler.END


# Delete currently active voting
@check_private_chat
@restrict_access
def vote_delete(bot, update):
    if update.message.text == "yes":
        config["voting"]["topic"] = str()
        config["voting"]["answers"] = list()
        config["voting"]["votes"] = dict()
        config["voting"]["end"] = str()

        update_cfg("voting", config["voting"])

        msg = "Voting cleared"
        update.message.reply_text(msg, reply_markup=ReplyKeyboardRemove())

    else:
        msg = "Canceled"
        update.message.reply_text(msg, reply_markup=ReplyKeyboardRemove())

    return ConversationHandler.END


# Save user-vote in config
def save_vote(bot, update):
    answer = update.message.text

    if answer.lower() == "cancel":
        msg = "Voting canceled"
        update.message.reply_text(msg, reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    global config

    if answer.lower() not in config["voting"]["answers"]:
        msg = "Answer not allowed. Please try again"
        update.message.reply_text(msg)
        return SAVE_VOTE

    # Load config
    with open(CFG_FILE) as cfg:
        config = json.load(cfg)

    user = update.message.from_user.first_name
    config["voting"]["votes"][user] = answer.lower()

    # Save config
    with open(CFG_FILE, "w") as cfg:
        json.dump(config, cfg, indent=4)

    update.message.reply_text(
        "Your vote has been saved",
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
    update_cfg("restart_usr", update.message.chat_id)

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


# Cancel a voting-conversation with the bot
def vote_cancel(bot, update):
    update.message.reply_text("Voting canceled", reply_markup=ReplyKeyboardRemove())
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


# ConversationHandler for voting
voting_handler = ConversationHandler(
    entry_points=[CommandHandler("vote", vote, pass_args=True)],
    states={
        SAVE_VOTE: [MessageHandler(Filters.text, save_vote)],
        CREATE_VOTE_TOPIC: [MessageHandler(Filters.text, vote_create_topic, pass_user_data=True)],
        CREATE_VOTE_ANSWERS: [MessageHandler(Filters.text, vote_create_answers, pass_user_data=True)],
        CREATE_VOTE_END: [MessageHandler(Filters.text, vote_create_end, pass_user_data=True)],
        DELETE_VOTE: [RegexHandler("^(yes|no)$", vote_delete)]
    },
    fallbacks=[CommandHandler('cancel', vote_cancel)],
    allow_reentry=True)
dispatcher.add_handler(voting_handler)


# MessageHandlers that filter on specific content
dispatcher.add_handler(MessageHandler(Filters.status_update.new_chat_members, welcome))
dispatcher.add_handler(MessageHandler(Filters.text, check_msg))


# Start the bot
updater.start_polling(clean=True)


# Runs the bot on a local development server
# TODO: Change to run with 'deployment'?
threading.Thread(target=voting_web).start()


# Check for new Tweets
if config["twitter_account"]:
    job_queue.run_repeating(check_twitter, 30, first=0)


# Send message that bot is started after restart
if config["restart_usr"]:
    msg = "Bot started..."
    updater.bot.send_message(chat_id=config["restart_usr"], text=msg)

    # Set key to empty value
    update_cfg("restart_usr", None)


# Change to idle mode
updater.idle()
