from unittest.mock import MagicMock

from config.settings import ADMIN_IDS, ALLOWED_CHAT_IDS, LLM_ENGINE
from services.startup_notifier import _format_startup_message, send_startup_notification


def test_format_startup_message_includes_chats_and_engine():
    text = _format_startup_message(mqtt_connected=True)
    assert "TARS запущен" in text
    for chat_id in ALLOWED_CHAT_IDS:
        assert str(chat_id) in text
    assert LLM_ENGINE in text
    assert "подключён" in text


def test_format_startup_message_reports_mqtt_down():
    text = _format_startup_message(mqtt_connected=False)
    assert "недоступен" in text


def test_send_startup_notification_messages_every_admin():
    bot = MagicMock()
    send_startup_notification(bot, mqtt_connected=True)
    assert bot.send_message.call_count == len(ADMIN_IDS)
    sent_to = {call.args[0] for call in bot.send_message.call_args_list}
    assert sent_to == ADMIN_IDS


def test_send_startup_notification_survives_one_admin_failing():
    bot = MagicMock()
    bot.send_message.side_effect = Exception("blocked by user")
    # Should not raise even though every admin send fails.
    send_startup_notification(bot, mqtt_connected=True)
    assert bot.send_message.call_count == len(ADMIN_IDS)
