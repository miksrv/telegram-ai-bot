import time
from core.cooldown import CooldownManager


def test_first_message_always_allowed():
    cm = CooldownManager()
    assert cm.allowed(user_id=1) is True


def test_immediate_second_message_blocked():
    cm = CooldownManager()
    cm.allowed(1)
    assert cm.allowed(1) is False


def test_different_users_are_independent():
    cm = CooldownManager()
    assert cm.allowed(1) is True
    assert cm.allowed(2) is True
    assert cm.allowed(3) is True


def test_sliding_window_triggers_penalty():
    cm = CooldownManager()
    # Fill the sliding window (RATE_LIMIT_COUNT = 2)
    assert cm.allowed(1) is True
    cm._last_action[1] = 0  # bypass classic cooldown
    assert cm.allowed(1) is True  # second message — window full
    cm._last_action[1] = 0
    # Third attempt: window has 2 entries → penalty applied
    assert cm.allowed(1) is False
    assert 1 in cm._penalty_until


def test_penalty_blocks_subsequent_messages():
    cm = CooldownManager()
    # Force a penalty
    cm._penalty_until[1] = time.time() + 180
    assert cm.allowed(1) is False


def test_set_forces_cooldown():
    cm = CooldownManager()
    cm.set(1)
    assert cm.allowed(1) is False


def test_cleanup_removes_expired_classic_cooldown():
    cm = CooldownManager()
    cm.allowed(1)
    # Age the entry well past the expiry threshold (USER_COOLDOWN_SECONDS * 3)
    cm._last_action[1] = time.time() - 1000
    if 1 in cm._windows:
        cm._windows[1].clear()
    cm.cleanup()
    assert 1 not in cm._last_action


def test_cleanup_removes_expired_penalty():
    cm = CooldownManager()
    cm._penalty_until[1] = time.time() - 1  # already expired
    cm.cleanup()
    assert 1 not in cm._penalty_until


def test_size_reflects_active_users():
    cm = CooldownManager()
    cm.allowed(10)
    cm.allowed(20)
    assert cm.size() == 2
