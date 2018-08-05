import json
import logging
import os

import TradeOgre

from telegram.ext import Updater, CommandHandler, MessageHandler
from telegram.ext.filters import Filters
from telegram import ParseMode

# Check if file 'config.json' exists. Exit if not.
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


# Get current price of XTL for a given asset pair
def price(bot, update):
	xtl_ticker = trade_ogre.ticker(config["pairing_asset"] + "-XTL")
	if xtl_ticker["success"]:
		price = xtl_ticker["price"]

		msg = "`" + "XTL on TradeOgre: " + price + " " + config["pairing_asset"] + "`"
		bot.send_message(chat_id=update.message.chat_id, text=msg, parse_mode=ParseMode.MARKDOWN)


def auto_reply(bot, update):
	text = update.message.text

	if "when moon".lower() in text.lower():
		video = open('soon_moon.mp4', 'rb')
		update.message.reply_video(video, parse_mode=ParseMode.MARKDOWN)


# TODO: Just for testing purposes
def fake_db(search):
	db = {"stellite": "Stellite solves issues that have been puzzling cryptocurrency developers for years on topics such as an efficient and decentralized method of distributing peer list without hard coding them, using the billions of small devices to combine their computing power and form a part of a huge Proof-of-work network which helps people use their own small devices to be not only a supporting factor to the network but also be provisioned a small reward in doing so. Stellite is unique in linking both the IPFS and ZeroNet technologies into a cryptocurrency and scaling it globally for both mobile and desktop usage.",
	"stellitepay": "Imagine having a platform like PayPal for crypto. Send and receive payments easily, easy integration for merchants."}

	if search.lower() in db:
		return db[search.lower()]
	else:
		return None


def wiki(bot, update, args):
	if len(args) > 0 and args[0]:
		result = fake_db(args[0])
		if result:
			msg = "`" + result + "`"
		else:
			msg = "`No entry found`"
	else:
		msg = "`No search argument provided`"

	bot.send_message(chat_id=update.message.chat_id, text=msg, parse_mode=ParseMode.MARKDOWN)


# TODO: Use for 'restart', ...
def is_admin(bot, update):
	# Telegram.ChatMember.status. used by bot.get_chat_member(chat_id, user_id). And then getting status in it.
	pass


def ban(bot, update):
	# http://python-telegram-bot.readthedocs.io/en/stable/telegram.chat.html#telegram.Chat.get_member
	# kick_member(*args, **kwargs)
	pass


# Handle all telegram and telegram.ext related errors
def handle_telegram_error(bot, update, error):
	error_str = "Update '%s' caused error '%s'" % (update, error)
	logger.log(logging.DEBUG, error_str)


# Log all errors
dispatcher.add_error_handler(handle_telegram_error)

# Add command handlers to dispatcher
dispatcher.add_handler(CommandHandler("price", price))
dispatcher.add_handler(CommandHandler("wiki", wiki, pass_args=True))
dispatcher.add_handler(MessageHandler(Filters.text, auto_reply))


updater.start_polling(clean=True)
updater.idle()
