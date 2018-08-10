# TODO: feedback senden mit '/f <feedback>'

import json
import logging
import os
import requests
import sys
import time
import threading

import TradeOgre

from telegram.ext import Updater, CommandHandler, MessageHandler
from telegram.ext.filters import Filters
from telegram import ParseMode

# Key name for temporary user in config
TMP_RSTR_USR = "restart_user"

# Read configuration file
if os.path.isfile("config.json"):
    # Read configuration
    with open("config.json") as config_file:
        config = json.load(config_file)
else:
    exit("No configuration file 'config.json' found")

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.DEBUG)
logger = logging.getLogger()

# Set bot token, get dispatcher and job queue
updater = Updater(token=config["bot_token"])
dispatcher = updater.dispatcher
job_queue = updater.job_queue

# Initialize TradeOgre API
trade_ogre = TradeOgre.API()


# Decorator to restrict access if user is not an admin
def restrict_access(func):
    def _restrict_access(bot, update):
        user_id = update.message.from_user.id
        admin_list = bot.get_chat_administrators(update.message.chat_id)

        access = False

        for admin in admin_list:
            if user_id == admin.user.id:
                access = True

        if access:
            return func(bot, update)
        else:
            update.message.reply_text("Access denied - you are not an admin")
            return

    return _restrict_access


# Automatically reply to user if specific content is posted
def auto_reply(bot, update):
    text = update.message.text

    if "when moon" in text.lower():
        moon = open(os.path.join(config["res_folder"], "soon_moon.mp4"), 'rb')
        update.message.reply_video(moon, parse_mode=ParseMode.MARKDOWN)
    elif "hodl" in text.lower():
        caption = "HODL HARD! ;-)"
        hodl = open(os.path.join(config["res_folder"], "HODL.jpg"), 'rb')
        update.message.reply_photo(hodl, caption=caption, parse_mode=ParseMode.MARKDOWN)
    elif "ico?" in text.lower():
        caption = "BTW: Stellite had no ICO"
        ico = open(os.path.join(config["res_folder"], "ICO.jpg"), 'rb')
        update.message.reply_photo(ico, caption=caption, parse_mode=ParseMode.MARKDOWN)
    elif "in it for the tech" in text.lower():
        caption = "Who is in it for the tech? ;-)"
        tech = open(os.path.join(config["res_folder"], "in_it_for_the_tech.jpg"), 'rb')
        update.message.reply_photo(tech, caption=caption, parse_mode=ParseMode.MARKDOWN)


# Get current price of XTL for a given asset pair
def price(bot, update):
    xtl_ticker = trade_ogre.ticker(config["pairing_asset"] + "-XTL")
    xtl_price = xtl_ticker["price"]

    if xtl_ticker["success"]:
        msg = "`" + "XTL on TradeOgre: " + xtl_price + " " + config["pairing_asset"] + "`"
        update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    else:
        msg = "`Couldn't retrieve current XTL price`"
        update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


# Display summaries for specific topics
def wiki(bot, update, args):
    if len(args) > 0 and args[0]:
        path = str()

        if args[0].lower() in config["wiki"]:
            path = config["wiki"][args[0].lower()]

        if path:
            image = open(os.path.join(config["res_folder"], path), 'rb')
            update.message.reply_photo(image, parse_mode=ParseMode.MARKDOWN)
            return
        else:
            msg = "`No entry found`"
            update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
            return
    else:
        msg = "`No search term provided. Here is a list of all possible terms:\n\n`"

        # Iterate over wiki-term dict and build a str out of it
        terms = str()
        for term in config["wiki"]:
            terms += term + "\n"

        # Add markdown code block
        terms = "`" + terms + "`"

        update.message.reply_text(msg + terms, parse_mode=ParseMode.MARKDOWN)


def help(bot, update):
    info = "Developed by @endogen for [Stellite](https://stellite.cash)\n\n" \
           "Available commands (normal user):\n\n" \
           "`/price` - Shows the current [TradeOgre](https://tradeogre.com) price for XTL\n\n" \
           "`/wiki <search-term>` - Shows information about the given topic. " \
           "List all available search-terms by not providing a search-term.\n\n" \
           "Available commands (administrator):\n\n" \
           "`/ban` - Ban a user by replaying to his message with this command\n\n" \
           "`/delete` - Remove a message by replaying to it with this command\n\n" \
           "`/update` - Update bot to newest version on GitHub\n\n" \
           "`/restart` - Restart bot and reload configuration\n\n" \
           "`/shutdown` - Shut the bot down\n\n" \
           "This bot is open source and you can download it on " \
           "[GitHub](https://github.com/Endogen/StelliteBot)"

    update.message.reply_text(info, parse_mode=ParseMode.MARKDOWN)


# Update the bot to newest version on GitHub
@restrict_access
def update_bot(bot, update):
    msg = "Bot is updating..."
    update.message.reply_text(msg)

    # Get newest version of this script from GitHub
    headers = {"If-None-Match": config["update_hash"]}
    github_script = requests.get(config["update_url"], headers=headers)

    # Status code 304 = Not Modified
    if github_script.status_code == 304:
        msg = "You are running the latest version"
        update.message.reply_text(msg)
    # Status code 200 = OK
    elif github_script.status_code == 200:
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

        # Save current ETag (hash) of bot script in github-config
        e_tag = github_script.headers.get("ETag")
        config["update_hash"] = e_tag

        # Save changed github-config as new config
        with open("config.json", "w") as cfg:
            json.dump(config, cfg, indent=4)

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
@restrict_access
def restart_bot(bot, update):
    msg = "Restarting bot..."
    update.message.reply_text(msg)

    global config

    # Read configuration file because it could have been changed
    if os.path.isfile("config.json"):
        # Read configuration
        with open("config.json") as config_file:
            config = json.load(config_file)
    else:
        exit("No configuration file 'config.json' found")

    # Set temporary restart-user in config
    config[TMP_RSTR_USR] = update.message.chat_id

    # Save changed config
    with open("config.json", "w") as cfg:
        json.dump(config, cfg, indent=4)

    # Restart bot
    time.sleep(0.2)
    os.execl(sys.executable, sys.executable, *sys.argv)


# This needs to be run on a new thread because calling 'updater.stop()' inside a
# handler (shutdown_cmd) causes a deadlock because it waits for itself to finish
def shutdown():
    updater.stop()
    updater.is_idle = False


# Terminate this script
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

    # Ban user
    bot.kick_chat_member(chat_id=chat_id, user_id=user_id)


# Delete the message that you are replying to
@restrict_access
def delete(bot, update):
    chat_id = update.message.chat_id
    original_msg = update.message.reply_to_message

    # Delete message
    bot.delete_message(chat_id=chat_id, message_id=original_msg.message_id)


# Handle all telegram and telegram.ext related errors
def handle_telegram_error(bot, update, error):
    error_str = "Update '%s' caused error '%s'" % (update, error)
    logger.log(logging.DEBUG, error_str)


# Log all errors
dispatcher.add_error_handler(handle_telegram_error)

# Add command handlers to dispatcher
dispatcher.add_handler(CommandHandler("ban", ban))
dispatcher.add_handler(CommandHandler("help", help))
dispatcher.add_handler(CommandHandler("price", price))
dispatcher.add_handler(CommandHandler("delete", delete))
dispatcher.add_handler(CommandHandler("update", update_bot))
dispatcher.add_handler(CommandHandler("restart", restart_bot))
dispatcher.add_handler(CommandHandler("shutdown", shutdown_bot))
dispatcher.add_handler(CommandHandler("wiki", wiki, pass_args=True))
dispatcher.add_handler(MessageHandler(Filters.text, auto_reply))

# Start the bot
updater.start_polling(clean=True)

# Send message that bot is started after restart
if TMP_RSTR_USR in config:
    msg = "Bot started..."
    updater.bot.send_message(chat_id=config[TMP_RSTR_USR], text=msg)

    # Remove temporary key from config
    config.pop(TMP_RSTR_USR, None)

    # Save changed config
    with open("config.json", "w") as cfg:
        json.dump(config, cfg, indent=4)

# Change to idle mode
updater.idle()
