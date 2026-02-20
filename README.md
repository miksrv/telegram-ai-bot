# Telegram AI Bot

A Python-based Telegram bot powered by AI. This project supports multiple AI providers (OpenAI, GROQ, Google Gemini) and can be run locally or in Docker.

---

## Features

- Responds to user messages using AI (OpenAI, GROQ, or Google Gemini)
- Easy to configure and extend
- Written in Python
- SQLite user profile database (auto-created)
- Modular codebase for easy customization

---

## Project Structure

```
telegram-ai-bot/
├── main.py                  # Entry point
├── requirements.txt         # Python dependencies
├── Dockerfile, docker-compose.yml
├── config/                  # Settings
├── core/                    # AI logic, memory, prompts
├── database/                # DB logic
├── handlers/                # Telegram handlers
├── services/                # LLM, system, telegram services
├── utils/                   # Utilities
├── data/tars_user_profiles.db # SQLite DB (auto-created)
```

---

## How to Create a New Telegram Bot

1. Open Telegram and search for [@BotFather](https://t.me/BotFather).
2. Start a chat and send the command `/newbot`.
3. Follow the instructions to set a name and username for your bot.
4. After creation, BotFather will provide you with a **bot token**. Save this token—you will need it to run your bot.

---

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
3. **Set your environment variables:**
   - Create a `.env` file in the project root and add:
     ```env
     TELEGRAM_BOT_TOKEN=your_bot_token_here
     # Choose one of the following providers and set the corresponding key:
     OPENAI_API_KEY=your_openai_key
     GROQ_API_KEY=your_groq_key
     GEMINI_API_KEY=your_gemini_key
     # Optionally, set AI_PROVIDER=openai|groq|genai (default: openai)
     AI_PROVIDER=openai
     ```
   - Or export as environment variables:
     ```sh
     export TELEGRAM_BOT_TOKEN=your_bot_token_here
     export OPENAI_API_KEY=your_openai_key
     export AI_PROVIDER=openai
     ```
4. **Run the bot:**
   ```sh
   python main.py
   ```
   The database file (`data/tars_user_profiles.db`) will be created automatically on first run if it does not exist.

---

## Running with Docker

1. **Build and start the bot using Docker Compose:**
   ```sh
   docker-compose up --build
   ```
   - Set your environment variables in `.env` or in `docker-compose.yml` under `environment`.
   - The database will be created automatically in the `data/` directory inside the container.

2. **Alternatively, build and run manually:**
   ```sh
   docker build -t telegram-ai-bot .
   docker run -e TELEGRAM_BOT_TOKEN=your_bot_token_here \
              -e OPENAI_API_KEY=your_openai_key \
              -e AI_PROVIDER=openai \
              telegram-ai-bot
   ```

---

## AI Provider Support

The bot supports the following AI providers:

- **OpenAI** (default)
- **GROQ**
- **Google Gemini (genai)**

Set the provider via the `AI_PROVIDER` environment variable:
- `openai` for OpenAI
- `groq` for GROQ
- `genai` for Google Gemini

Set the corresponding API key as an environment variable (`OPENAI_API_KEY`, `GROQ_API_KEY`, or `GEMINI_API_KEY`).

---

## Troubleshooting

- **ModuleNotFoundError: No module named 'services'**
  - Make sure you run the bot from the project root directory.
  - If using Docker, check the `WORKDIR` in your Dockerfile.
- **Database file not created**
  - Ensure the `data/` directory exists and is writable.
  - The bot will auto-create the DB on first run if permissions are correct.
- **RemoteDisconnected or connection errors**
  - This may be due to network issues or API rate limits. Try switching providers or check your API key.

---

## License

MIT License