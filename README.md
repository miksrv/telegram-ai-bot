# Telegram AI Bot

A Python-based Telegram bot powered by AI. This project uses pip for dependency management and supports both local and Docker-based deployment.

## Features

- Responds to user messages using AI
- Easy to configure and extend
- Written in Python

## How to Create a New Telegram Bot

1. Open Telegram and search for [@BotFather](https://t.me/BotFather).
2. Start a chat and send the command `/newbot`.
3. Follow the instructions to set a name and username for your bot.
4. After creation, BotFather will provide you with a **bot token**. Save this token—you will need it to run your bot.

## Local Installation & Usage

1. **Clone the repository:**
   ```sh
   git clone https://github.com/yourusername/telegram-ai-bot.git
   cd telegram-ai-bot
   ```
2. **Install dependencies:**
   ```sh
   pip install -r requirements.txt
   ```
3. **Set your Telegram bot token:**
   - Option 1: Create a `.env` file in the project root and add:
     ```env
     TELEGRAM_BOT_TOKEN=your_bot_token_here
     ```
   - Option 2: Export as an environment variable:
     ```sh
     export TELEGRAM_BOT_TOKEN=your_bot_token_here
     ```
4. **Run the bot:**
   ```sh
   python main.py
   ```
   The database file (`data/tars_user_profiles.db`) will be created automatically on first run if it does not exist.

## Running with Docker

1. **Build and start the bot using Docker Compose:**
   ```sh
   docker-compose up --build
   ```
   - The `TELEGRAM_BOT_TOKEN` should be set in your environment or in the `docker-compose.yml` file under `environment`.
   - The database will be created automatically in the `data/` directory inside the container.

2. **Alternatively, build and run manually:**
   ```sh
   docker build -t telegram-ai-bot .
   docker run -e TELEGRAM_BOT_TOKEN=your_bot_token_here telegram-ai-bot
   ```

## Configuration

- Edit the configuration file or set environment variables as needed.
- Ensure the `data/` directory exists and is writable for database storage.

## License

MIT License