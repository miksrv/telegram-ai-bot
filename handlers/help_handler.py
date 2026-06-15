"""
Telegram Help Handler
Handles /help command — short bot description and command list in Russian.
"""

from telebot import TeleBot, types

HELP_TEXT = (
    "🤖 TARS — ИИ-помощник астрономического сообщества @astronom_chat.\n"
    "Назван в честь робота из фильма «Интерстеллар». Общается на темы астрономии, "
    "анализирует фотографии неба и управляет наземной станцией спутника CubeSat.\n\n"
    "Как обратиться: упомяните «ТАРС» в сообщении или ответьте на сообщение бота — "
    "он подключится к разговору. Можно прислать фотографию с подписью для разбора.\n\n"
    "Команды:\n"
    "• /help — это сообщение\n"
    "• /weather <город> — текущая погода для наблюдений\n"
    "• /status — телеметрия спутника CubeSat\n"
    "• /photo — снимок с камеры CubeSat\n"
    "• /stats — статистика бота"
)


def handle_help(bot: TeleBot, message: types.Message, allowed_chat_ids: set):
    """
    Обрабатывает команду /help: краткое описание бота и список команд.
    Работает в разрешённых чатах и в личных сообщениях.
    """
    chat_id = message.chat.id

    if chat_id not in allowed_chat_ids and message.chat.type != "private":
        return

    bot.reply_to(message, HELP_TEXT)
