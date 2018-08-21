import json
import logging
import os
import requests
import sys
import time
import threading

import numpy as np
import matplotlib.pyplot as plt
import TradeOgre as to

from inspect import signature
from coinmarketcap import Market
from flask import Flask, jsonify
from telegram import ParseMode, Chat, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Updater, CommandHandler, MessageHandler, ConversationHandler, RegexHandler
from telegram.ext.filters import Filters
from telegram.error import TelegramError, InvalidToken


# State name for ConversationHandler
SAVE_VOTE = range(1)

# Key name for temporary user in config
RST_MSG = "restart_msg"
RST_USR = "restart_usr"

# Image file for voting results
VOTE_IMG = "voting.png"


# Initialize Flask to get voting results via web
app = Flask(__name__)


# Read configuration file
if os.path.isfile("config.json"):
    # Read configuration
    with open("config.json") as config_file:
        config = json.load(config_file)
else:
    exit("ERROR: No configuration file 'config.json' found")


# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.DEBUG)
logger = logging.getLogger()


# Set bot token, get dispatcher and job queue
try:
    updater = Updater(token=config["bot_token"])
    dispatcher = updater.dispatcher
    job_queue = updater.job_queue
except InvalidToken:
    exit("ERROR: Bot token not valid")


@app.route("/execute/<string:command>", methods=["GET"])
def execute(command):
    if command == "vote":
        return jsonify(success=True, message=config["voting"]["vote"], commad=command)
    if command == "answers":
        return jsonify(success=True, message=config["voting"]["answers"], commad=command)
    if command == "votes":
        return jsonify(success=True, message=config["voting"]["votes"], commad=command)
    else:
        return jsonify(success=False, message='Something went wrong...')


# Add Telegram group admins to admin-list for this bot
def add_tg_admins(bot, update):
    if bot.get_chat(update.message.chat_id).type != Chat.PRIVATE:
        tg_admins = bot.get_chat_administrators(update.message.chat_id)

        tg_admin_list = [admin["user"].id for admin in tg_admins]

        if all(admin in config["adm_list"] for admin in tg_admin_list):
            return

        all_admins = list(set(config["adm_list"]) | set(tg_admin_list))
        change_config("adm_list", all_admins)


# Decorator to restrict access if user is not an admin
def restrict_access(func):
    def _restrict_access(bot, update, args=None):
        # Add Telegram group admins to admin list
        if config["add_tg_admins"]:
            add_tg_admins(bot, update)

        # Check if user of msg is in admin list
        if update.message.from_user.id in config["adm_list"]:
            if len(signature(func).parameters) == 3:
                return func(bot, update, args)
            else:
                return func(bot, update)

        msg = "Access denied \U0001F6AB"
        update.message.reply_text(msg)

    return _restrict_access


# Decorator to check if command can be used only in private chat with bot
def check_private(func):
    def _only_private(bot, update, args=None):
        # Check if command is "private only"
        if update.message.text.replace("/", "").replace(bot.name, "") in config["only_private"]:
            # Check if in a private chat with bot
            if bot.get_chat(update.message.chat_id).type != Chat.PRIVATE:
                msg = "This command is only available in a private chat with " + bot.name
                update.message.reply_text(msg)
                return

        if len(signature(func).parameters) == 3:
            return func(bot, update, args)
        else:
            return func(bot, update)

    return _only_private


# Create a button menu to show in messages
def build_menu(buttons, n_cols=1, header_buttons=None, footer_buttons=None):
    menu = [buttons[i:i + n_cols] for i in range(0, len(buttons), n_cols)]

    if header_buttons:
        menu.insert(0, header_buttons)
    if footer_buttons:
        menu.append(footer_buttons)

    return menu


# Save value for given key in config and store in file
def change_config(key, value):
    global config

    # Read config
    with open("config.json") as cfg:
        config = json.load(cfg)

    # Set new value
    config[key] = value

    # Save config
    with open("config.json", "w") as cfg:
        json.dump(config, cfg, indent=4)


# Change permissions of a user
@check_private
@restrict_access
def usr_to_admin(bot, update):
    if update.message.reply_to_message is None:
        return

    chat_id = update.message.chat_id
    user_id = update.message.reply_to_message.from_user.id

    success = bot.promote_chat_member(
        chat_id,
        user_id,
        can_delete_messages=True,
        can_restrict_members=True,
        can_pin_messages=True)

    username = update.message.reply_to_message.from_user.username
    if success and username:
        msg = "User @" + username + " is admin"
        # TODO: Why not using 'message.reply_text'?
        bot.send_message(chat_id=chat_id, text=msg, disable_notification=True)


# Change bot settings on the fly
@check_private
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
                change_config(key, True)
            elif value.lower() in ["false", "no", "0"]:
                change_config(key, False)
            else:
                change_config(key, value)

    # Restart bot to activate new settings
    restart_bot(bot, update)


# Greet new members with a welcome message
def welcome(bot, update):
    try:
        # Remove default user-joined message
        update.message.delete()
    except TelegramError:
        # Bot doesn't have admin rights
        pass

    # FIXME: Why is 'pinned' None?
    #chat = bot.get_chat(update.message.chat_id)
    #pinned = chat.pinned_message
    #print(str(pinned))

    for user in update.message.new_chat_members:
        msg = "Welcome *" + user.first_name + "*. " + "".join(config["welcome_msg"])
        bot.send_message(
            chat_id=update.message.chat.id,
            text=msg,
            disable_notification=True,
            parse_mode=ParseMode.MARKDOWN)


# Ban user if he is a bot and writes a message
def ban_bots(bot, update):
    if update.message.from_user.is_bot:
        ban(bot, update)


# Automatically reply to user if specific content is posted
def auto_reply(bot, update):
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
    elif "in it for the tech" in txt:
        caption = "Who's in it for the tech? ;-)"
        tech = open(os.path.join(config["res_folder"], "in_it_for_the_tech.jpg"), 'rb')
        update.message.reply_photo(tech, caption=caption, parse_mode=ParseMode.MARKDOWN)


# Get info about coin from CoinMarketCap
@check_private
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
@check_private
def price(bot, update):
    msg = "TradeOgre:\n"

    for asset in config["pairing_asset"]:
        xtl_ticker = to.API().ticker(asset + "-XTL")
        msg += xtl_ticker["price"] + " " + asset.upper() + "\n"

    update.message.reply_text("`" + msg + "`", parse_mode=ParseMode.MARKDOWN)


# Display summaries for specific topics
@check_private
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
@check_private
def help(bot, update):
    # Check if user is admin
    if update.message.from_user.id in config["adm_list"]:
        msg = "".join(config["help_msg_adm"])
        update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    else:
        msg = "".join(config["help_msg"])
        update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)


# Send feedback about bot to bot-developer
@check_private
def feedback(bot, update, args):
    if args and args[0]:
        msg = "Thank you for the feedback! \U0001F44D"
        update.message.reply_text(msg)

        # Send feedback to developer
        user = update.message.from_user.username

        if user:
            feedback_msg = "Feedback from @" + user + ": " + " ".join(args)
            bot.send_message(chat_id=config["admin_user_id"], text=feedback_msg)
        else:
            feedback_msg = "Feedback: " + " ".join(args)
            bot.send_message(chat_id=config["admin_user_id"], text=feedback_msg)
    else:
        msg = "No feedback entered \U00002757"
        update.message.reply_text(msg)


# TODO: Think about which texts should really be NOT markdown.
# Voting functionality for users
@check_private
def vote(bot, update, args):
    # Voting on specific topic
    if len(args) == 0:
        # Check if voting is active
        if not config["voting"]["vote"]:
            msg = "There is currently no voting active"
            update.message.reply_text(msg)
            return

        # Check if user already voted
        user_name = update.message.from_user.first_name
        if user_name in config["voting"]["votes"]:
            voted = "You already voted but you can change your vote if you like"
            # TODO: Integrate this

        question = config["voting"]["vote"]
        # TODO: Is having more answers problematic?
        answers = config["voting"]["answers"]

        keyboard = ReplyKeyboardMarkup(
            build_menu(answers, n_cols=len(answers), footer_buttons=["cancel"]),
            one_time_keyboard=True)

        update.message.reply_text(question, reply_markup=keyboard)
        return SAVE_VOTE

    # Image of voting results
    # Add webservice for voting-results
    if args[0].lower() == "results":
        # TODO: Dict has to be ordered
        # TODO: Do this in a better way
        voting_data = dict()
        for key, value in config["voting"]["votes"].items():
            if value in voting_data:
                voting_data[value] += 1
            else:
                voting_data[value] = 1

        answers = tuple(voting_data.keys())
        y_pos = np.arange(len(answers))
        fig = plt.figure()
        # Create horizontal bars
        plt.barh(y_pos, list(voting_data.values()))
        # Create names on the y-axis
        plt.yticks(y_pos, answers)
        # Create image
        fig.savefig(VOTE_IMG)

        # Show results
        plot = open(VOTE_IMG, 'rb')  # TODO: Maybe integrate 'res_folder'?
        caption = "`Here are the results`"

        # Generate some statistics
        #total_members = bot.get_chat_members_count(update.message.chat_id)  # TODO: How to get correct id here?
        #total_votes = len(config["voting"]["votes"])
        #participation = total_votes / total_members * 100

        # "Participation: " + "{:.2f}".format(participation) + "%`"

        update.message.reply_photo(
            plot,
            caption=caption,
            parse_mode=ParseMode.MARKDOWN)

        return ConversationHandler.END

    if args[0].lower() == "create":
        # Create new vote
        # TODO: Do this as a command for admins
        return
    if args[0].lower() == "delete":
        # Clear config for 'voting' key
        # TODO: Do this as a command for admins
        return


# Save the user-vote to config
def save_vote(bot, update):
    user = update.message.from_user.first_name
    answer = update.message.text

    config["voting"]["votes"][user] = answer

    # TODO: Do this somehow with 'change_config'
    # Save config
    with open("config.json", "w") as cfg:
        json.dump(config, cfg, indent=4)

    update.message.reply_text(
        "`Your vote has been saved`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardRemove())

    return ConversationHandler.END


# Check if there is an update available for this bot
@check_private
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
@check_private
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
        github_config_path = config["update_url"][:last_slash_index + 1] + "config.json"
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
        change_config("update_hash", github_script.headers.get("ETag"))

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
@check_private
@restrict_access
def restart_bot(bot, update):
    msg = "Restarting bot..."
    update.message.reply_text(msg)

    # Set temporary restart-user and msg ID in config
    change_config(RST_USR, update.message.chat_id)
    change_config(RST_MSG, update.message.message_id)

    # Restart bot
    time.sleep(0.2)
    os.execl(sys.executable, sys.executable, *sys.argv)


# This needs to be run on a new thread because calling 'updater.stop()' inside a
# handler (shutdown_cmd) causes a deadlock because it waits for itself to finish
def shutdown():
    updater.stop()
    updater.is_idle = False


# Terminate this script
@check_private
@restrict_access
def shutdown_bot(bot, update):
    update.message.reply_text("Shutting down...")

    # See comments on the 'shutdown' function
    threading.Thread(target=shutdown).start()


# Ban the user you are replying to
@restrict_access
def ban(bot, update):
    chat_id = update.message.chat_id
    user_id = update.message.reply_to_message.from_user.id

    bot.kick_chat_member(chat_id=chat_id, user_id=user_id)


# Delete the message that you are replying to
@restrict_access
def delete(bot, update):
    original_msg = update.message.reply_to_message

    if original_msg:
        chat_id = update.message.chat_id
        bot.delete_message(chat_id=chat_id, message_id=original_msg.message_id)


# Cancel a conversation with the bot
def cancel(bot, update):
    update.message.reply_text("Voting canceled", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# Handle all telegram and telegram.ext related errors
def handle_telegram_error(bot, update, error):
    msg = "Upps, something went wrong \U00002639"
    update.message.reply_text(msg)

    error_str = "Update '%s' caused error '%s'" % (update, error)
    logger.log(logging.ERROR, error_str)


# Log all errors
dispatcher.add_error_handler(handle_telegram_error)


# CommandHandlers to provide commands
dispatcher.add_handler(CommandHandler("cmc", cmc))
dispatcher.add_handler(CommandHandler("ban", ban))
dispatcher.add_handler(CommandHandler("help", help))
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
        SAVE_VOTE: [RegexHandler("^(yes|no)$", save_vote),
                    RegexHandler("^(cancel)$", cancel)]
    },
    fallbacks=[CommandHandler('cancel', cancel)],
    allow_reentry=True)
dispatcher.add_handler(voting_handler)


# MessageHandlers that filter on specific content
if config["welcome_new_usr"]:
    dispatcher.add_handler(MessageHandler(Filters.status_update.new_chat_members, welcome))
if config["ban_bots"]:
    dispatcher.add_handler(MessageHandler(Filters.text, ban_bots))
if config["auto_reply"]:
    dispatcher.add_handler(MessageHandler(Filters.text, auto_reply))


# Start the bot
updater.start_polling(clean=True)


# Send message that bot is started after restart
if RST_MSG in config and RST_USR in config:
    msg = "Bot started..."
    updater.bot.send_message(chat_id=config[RST_USR], reply_to_message_id=config[RST_MSG], text=msg)

    # Remove temporary keys from config
    config.pop(RST_MSG, None)
    config.pop(RST_USR, None)

    # Save changed config
    with open("config.json", "w") as cfg:
        json.dump(config, cfg, indent=4)


def stellite_web():
    # TODO: https://github.com/pallets/flask/issues/651
    if __name__ == '__main__':
        app.run()


# Runs the bot on a local development server
# TODO: Change to run with 'deployment'
threading.Thread(target=stellite_web).start()


# Change to idle mode
updater.idle()
