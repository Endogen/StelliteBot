import json
import logging
import os
import requests
import sys
import time
import threading

import TradeOgre

from inspect import signature
from coinmarketcap import Market
from telegram.ext import Updater, CommandHandler, MessageHandler
from telegram.ext.filters import Filters
from telegram import ParseMode


# Key name for temporary user in config
RST_MSG = "restart_msg"
RST_USR = "restart_usr"

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


# Decorator to restrict access if user is not an admin
def restrict_access(func):
    def _restrict_access(bot, update, args=None):
        user_id = update.message.from_user.id

        # Check if in a private conversation and thus no admins
        chat = bot.get_chat(update.message.chat_id)

        if chat.type == chat.PRIVATE:
            msg = "Access denied: not possible in private chat"
            update.message.reply_text(msg)
            return

        admin_list = bot.get_chat_administrators(update.message.chat_id)
        access = False

        for admin in admin_list:
            if user_id == admin.user.id:
                access = True

        if access:
            sig = signature(func)

            if len(sig.parameters) == 3:
                return func(bot, update, args)
            else:
                return func(bot, update)
        else:
            msg = "Access denied: not an admin"
            update.message.reply_text(msg)
            return

    return _restrict_access


# Change permissions of a user
@restrict_access
def usr_to_admin(bot, update):
    if update.message.reply_to_message is None:
        return

    chat_id = update.message.chat.id
    user_id = update.message.reply_to_message.from_user.id

    success = bot.promote_chat_member(chat_id,
                                      user_id,
                                      can_delete_messages=True,
                                      can_restrict_members=True,
                                      can_pin_messages=True)

    username = update.message.reply_to_message.from_user.username
    if success and username:
        msg = "User @" + username + " is admin"
        bot.send_message(chat_id=chat_id, text=msg, disable_notification=True)


# Change bot settings on the fly
@restrict_access
def change_cfg(bot, update, args):
    if len(args) == 0:
        msg = "`No settings provided`"
        update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        return

    # Extract key / value pairs and save in dictionary
    settings = dict(s.split('=', 1) for s in args)

    global config

    # Read configuration because it could have been changed
    with open("config.json") as config_file:
        config = json.load(config_file)

    # Set new values for settings
    for key, value in settings.items():
        if key in config:
            if value.lower() in ["true", "yes", "1"]:
                config[key] = True
            elif value.lower() in ["false", "no", "0"]:
                config[key] = False
            else:
                config[key] = value

    # Save changed config
    with open("config.json", "w") as cfg:
        json.dump(config, cfg, indent=4)

    # Restart bot to activate new settings
    restart_bot(bot, update)


# Greet new members with a welcome message
def new_user(bot, update):
    # Remove default user-joined message
    update.message.delete()

    for user in update.message.new_chat_members:
        if user.username:
            msg = "Welcome @" + user.username + ". " + "".join(config["welcome_msg"])
            bot.send_message(chat_id=update.message.chat.id, text=msg, disable_notification=True)


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


# Get current price of XTL for a given asset pair
def price(bot, update):
    xtl_ticker = TradeOgre.API().ticker(config["pairing_asset"] + "-XTL")
    xtl_price = xtl_ticker["price"]

    if xtl_ticker["success"]:
        msg = "`" + "TradeOgre: " + xtl_price + " " + config["pairing_asset"] + "`"
        update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    else:
        msg = "`Couldn't retrieve current XTL price`"
        update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


# Display summaries for specific topics
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

        # Add markdown code block
        terms = "`" + terms + "`"
        update.message.reply_text(msg + terms, parse_mode=ParseMode.MARKDOWN)


# Show general info about bot and all available commands with description
def help(bot, update):
    info = "".join(config["help_msg"])
    update.message.reply_text(info, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)


# Send feedback about bot to bot-developer
def feedback(bot, update, args):
    if args and args[0]:
        msg = "Thank you for the feedback!"
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
        msg = "No feedback entered"
        update.message.reply_text(msg)


# Check if there is an update available for this bot
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

    # Read configuration because it could have been changed
    with open("config.json") as config_file:
        config = json.load(config_file)

    # Set temporary restart-user in config
    config[RST_USR] = update.message.chat_id
    config[RST_MSG] = update.message.message_id

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
    original_msg = update.message.reply_to_message

    if original_msg:
        chat_id = update.message.chat_id
        bot.delete_message(chat_id=chat_id, message_id=original_msg.message_id)


# Handle all telegram and telegram.ext related errors
def handle_telegram_error(bot, update, error):
    error_str = "Update '%s' caused error '%s'" % (update, error)
    logger.log(logging.DEBUG, error_str)


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

# MessageHandlers that filter on specific content
if config["welcome_new_usr"]:
    dispatcher.add_handler(MessageHandler(Filters.status_update.new_chat_members, new_user))
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

# Change to idle mode
updater.idle()
