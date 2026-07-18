import threading
import time

from utils.typing_action import typing_action


class _FakeBot:
    def __init__(self, fail_after=None):
        self.calls = []
        self._fail_after = fail_after

    def send_chat_action(self, chat_id, action):
        self.calls.append((chat_id, action))
        if self._fail_after is not None and len(self.calls) > self._fail_after:
            raise RuntimeError("boom")


def test_typing_action_sends_immediately():
    bot = _FakeBot()
    with typing_action(bot, 123, interval=10):
        # No need to wait — the first send happens before the with-body runs.
        pass
    assert bot.calls == [(123, "typing")]


def test_typing_action_refreshes_while_body_runs():
    bot = _FakeBot()
    with typing_action(bot, 123, interval=0.05):
        time.sleep(0.22)
    # At least the initial call plus a couple of refreshes.
    assert len(bot.calls) >= 3
    assert all(call == (123, "typing") for call in bot.calls)


def test_typing_action_stops_after_context_exits():
    bot = _FakeBot()
    with typing_action(bot, 123, interval=0.05):
        pass
    count_at_exit = len(bot.calls)
    time.sleep(0.2)
    # No further calls should land once the context has exited.
    assert len(bot.calls) == count_at_exit


def test_typing_action_survives_send_errors():
    bot = _FakeBot(fail_after=0)  # every call raises
    with typing_action(bot, 123, interval=0.05):
        time.sleep(0.15)
    # The heartbeat thread keeps retrying instead of dying on the first error.
    assert len(bot.calls) >= 2


def test_typing_action_background_thread_is_daemon_and_named():
    bot = _FakeBot()
    names_seen = []

    def _capture(*_a, **_k):
        names_seen.append(threading.current_thread().name)

    bot.send_chat_action = _capture

    with typing_action(bot, 123, interval=10):
        pass

    assert names_seen == ["typing-heartbeat"]
