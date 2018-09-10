# StelliteBot

Python bot to manage the Stellite supergroup on [Telegram](https://telegram.org)

## Overview
This Python script is a polling (not [webhook](https://github.com/python-telegram-bot/python-telegram-bot/wiki/Webhooks)) based Telegram bot, must be self hosted and doesn't need any database.

## Files
In the following list you will find detailed information all the files that the project consists of - and if they are necessary to run the bot or not.

- __.gitignore__: Only relevant if you use [git](https://git-scm.com) as your Source Code Management. If you put a filename in that file, then that file will not be commited to the repository. If you don't intend to code yourself, the file is _not needed_.
- __config.json__: The configuration file for this bot. This file is _needed_.
- __Procfile__: This file is only necessary if you want to host the bot on [Heroku](https://www.heroku.com). Otherwise, this file is _not needed_.
- __README.md__: The readme file you are reading right now. Includes instructions on how to run and use the bot. The file is _not needed_.
- __requirements.txt__: This file holds all dependencies (Python modules) that are required to run the bot. Once all dependencies are installed, the file is _not needed_ anymore. If you need to know how to install the dependencies from this file, take a look at the [dependencies](#dependencies) section.
- __stellite\_bot.py__: The bot itself. This file has to be executed with Python to run. For more details, see the [installation](#installation) section. This file is _needed_.
- __TradeOgre.py__: This is the [TradeOgre](https://tradeogre.com) API to access the current XTL price there. Has its own project [here](https://github.com/Endogen/TradeOgrePy). The file is _needed_. 

#### Summary
These are the files that are important to run the bot:

- `config.json` (Configuration)
- `stellite_bot.py` (Bot itself)
- `TradeOgre.py` (Access to TradeOgre API)

## Configuration
Before starting up the bot you have to take care of some settings in `config.json`:

This file holds the configuration for your bot. You have to at least edit the values for __bot_token__, __wiki__ and __admin_user_id__. After a value has been changed you have to restart the bot for the applied changes to take effect.

- __bot_token__: The token that identifies your bot. You will get this from Telegram bot `BotFather` when you create your bot. If you don't know how to register your bot, follow these [instructions](https://core.telegram.org/bots#3-how-do-i-create-a-bot)
- __pairing_asset__: Relevant for the `/price` command. For which base currency do you want to get the price.
- __update_url__: URL to the latest GitHub version of the script. This is needed for the update functionality. Per default this points to my repository and if you don't have your own repo with some changes then you should use the default value
- __update_hash__: Hash of the latest version of the script. __Please don't change this__. Will be set automatically after updating. There is not need to play around with this
- __res_folder__: Folder with pictures and videos relevant for the `/wiki` command.
- __wiki__: List of all terms that can be searched for in the wiki and their corresponding file to post.
- __admin_user_id__: Telegram user ID that will receive the feedback messages from the `/feedback` command. 

<a name="installation"></a>
## Installation
In order to run the bot you need to execute the script `stellite_bot.py`. If you don't have any idea where to host it, take a look at [Where to host Telegram Bots](https://github.com/python-telegram-bot/python-telegram-bot/wiki/Where-to-host-Telegram-Bots). You can also run the script locally on your computer for testing purposes.

### Prerequisites
##### Python version
You can use Python 2 or 3 to execute the script.

<a name="dependencies"></a>
##### Installing needed modules from `requirements.txt`
Install a set of module-versions that is known to work together for sure (__highly recommended__):
```shell
pip install -r requirements.txt
```

##### Install newest versions of needed modules
If you want to install the newest versions of the needed modules, execute the following:
```shell
pip install python-telegram-bot -U
pip install requests -U
```

### Starting
To start the script, execute
```shell
python stellite_bot.py &
```

### Stopping
To stop the script, execute
```shell
pkill python
```

Which will kill __every__ Python process that is currently running. Or shut the bot down with the `/shutdown` command (__recommended__).

## Usage
Add this bot as an admin to your Telegram group / channel / supergroup so that he can execute bans or delete messages.

### Available commands
##### Related to Stellite
- `/price`: Return current price for XTL on TradeOgre
- `/ban`: Ban a user from the channel
- `/delete`: Remove a message form the channel
- `/wiki`: Search the wiki for a specific, XTL related, topic
- `/poll`: Create a poll and get answers from users
- `/help`: General bot-info an overview of all commands
- `/feedback`: Send feedback to bot developer

##### Related to bot
- `/update`: Update the bot to the latest version on GitHub
- `/restart`: Restart the bot
- `/shutdown`: Shutdown the bot

If you want to show a list of available commands as you type, open a chat with Telegram user `BotFather` and send the command `/setcommands`. Then choose the bot you want to activate the list for and after that send the list of commands with description. Something like this:
```
price - current price on TradeOgre
cmc - info about XTL on CoinMarketCap.com
wiki - get info about a specific topic
help - general info about bot commands
feedback - let us know what you think
poll - take part in the current survey
```

## Development
I know that it is unusual to have the whole source code in just one file. At some point i should have been switching to object orientation and multiple files but i kind of like the idea to have it all in just one file and object orientation would only blow up the code. This also makes the `/update` command much simpler :)

## Donating
If you find __StelliteBot__ helpful, please consider donating whatever amount you like to:

#### Monero (XMR)
```
46tUdg4LnqSKroZBR1hnQ2K6NnmPyrYjC8UBLhHiKYufCipQUaACfxcBeQUmYGFvqCdU3ghCpYq2o5Aqyj1nH6mfLVNka26
```

#### Ethereum (ETH)
```
0xccb2fa97f47f0d58558d878f359013fef4097937
```

#### How else can you support me?
If you can't or don't want to donate, please consider signing up on listed exchanges below. They are really good and by using these links to register an account i get a share of the trading-fee that you pay to the exchange if you execute a trade.

- [Binance](https://www.binance.com/?ref=16770868)
- [Qryptos](https://accounts.qryptos.com/sign-up?affiliate=wVZoZ4uG269520)