# BatchLibraryBot

A Telegram bot built with **aiogram** that manages course materials posted in a channel, archives them, stores metadata in MongoDB, and allows users to browse and retrieve materials interactively.

# Environment Variables

```env
# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token_here
CHANNEL_ID=-1001234567890          # Your source channel ID
ARCHIVE_CHANNEL=-1000987654321     # Your archive channel ID

# MongoDB
MONGO_HOST=localhost               # or your MongoDB host
MONGO_PORT=27017
MONGO_USER=your_username           # optional
MONGO_PASS=your_password           # optional
MONGO_NAME=bot_database            # database name

# Webhook (optional, for production)
HOST_URL=https://yourdomain.com
WEBHOOK_ENDPOINT=webhook
WEBHOOK_SECRET=random_secret_string
```

# Bot Setup

- Add the bot as administrator to both channels
- Enable `Post Messages` permission in both channels
- Ensure the bot can delete messages in the archive channel

# Usage

In your source channel, post media (video / document / audio) using the following caption format:

Course Name (Course Instructor) | Material Title

The bot automatically calculates the **Level** and **Term** based on the current date, relative to the start year defined in `app/utils.py`, and stores this information in the database.
