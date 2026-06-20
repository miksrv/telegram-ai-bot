"""Tests for the starmap integration: availability tracking, the dynamic
command menu, and city → coordinates resolution."""

import threading

import handlers.starmap_handler as starmap_handler
import services.mqtt_service as mq
from services import weather_service
from services.telegram_service import _build_commands


def _reset_starmap_state():
    """Resets the module-level starmap availability state between tests."""
    with mq._starmap_lock:  # noqa: SLF001 - test-only access to module state
        mq._starmap_online = False
        mq._status_listeners.clear()


# ---------------------------------------------------------------------------
# Availability tracking
# ---------------------------------------------------------------------------


def test_starmap_starts_offline():
    _reset_starmap_state()
    assert mq.is_starmap_online() is False


def test_status_message_toggles_availability():
    _reset_starmap_state()
    mq._handle_starmap_status('{"status": "online"}')
    assert mq.is_starmap_online() is True
    mq._handle_starmap_status('{"status": "offline"}')
    assert mq.is_starmap_online() is False


def test_invalid_status_payload_is_ignored():
    _reset_starmap_state()
    mq._handle_starmap_status("not json")
    assert mq.is_starmap_online() is False


def test_unexpected_status_value_does_not_flip_offline():
    _reset_starmap_state()
    mq._handle_starmap_status('{"status": "online"}')
    assert mq.is_starmap_online() is True
    # A malformed payload missing/with an unknown status must be ignored,
    # not read as "offline".
    mq._handle_starmap_status("{}")
    assert mq.is_starmap_online() is True


def test_listener_syncs_immediately_on_register():
    _reset_starmap_state()
    seen = []
    mq.register_status_listener(seen.append)
    assert seen == [False]


def test_listener_fires_on_change_only():
    _reset_starmap_state()
    done = threading.Event()
    states = []

    def listener(online):
        states.append(online)
        done.set()

    mq.register_status_listener(listener)  # immediate sync -> False
    states.clear()
    done.clear()  # the initial sync set it; reset so wait() reflects the change

    mq._handle_starmap_status('{"status": "online"}')
    assert done.wait(timeout=2), "listener was not notified on change"
    assert states == [True]

    # Same status again must not re-notify.
    done.clear()
    mq._handle_starmap_status('{"status": "online"}')
    assert not done.wait(timeout=0.3)


# ---------------------------------------------------------------------------
# register_request capacity
# ---------------------------------------------------------------------------


def test_register_request_default_is_single_reply():
    q = mq.register_request("cubesat-req")
    try:
        assert q.maxsize == 1
    finally:
        mq.unregister_request("cubesat-req")


def test_register_request_can_be_unbounded():
    q = mq.register_request("starmap-req", maxsize=0)
    try:
        assert q.maxsize == 0
    finally:
        mq.unregister_request("starmap-req")


# ---------------------------------------------------------------------------
# Dynamic command menu
# ---------------------------------------------------------------------------


def test_menu_hides_starmap_commands_when_offline():
    assert len(_build_commands(False)) == 3


def test_menu_adds_starmap_commands_when_online():
    assert len(_build_commands(True)) == 7


# ---------------------------------------------------------------------------
# City -> coordinates resolution
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_get_coordinates_returns_lat_lon(monkeypatch):
    monkeypatch.setattr(
        weather_service.requests,
        "get",
        lambda *a, **k: _FakeResponse([{"lat": 55.75, "lon": 37.62}]),
    )
    assert weather_service.get_coordinates("Москва") == (55.75, 37.62)


def test_get_coordinates_raises_for_unknown_city(monkeypatch):
    monkeypatch.setattr(
        weather_service.requests,
        "get",
        lambda *a, **k: _FakeResponse([]),
    )
    try:
        weather_service.get_coordinates("Нетакогогорода")
        assert False, "expected ValueError"
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# image_path allowlist
# ---------------------------------------------------------------------------


def test_image_path_disabled_when_dir_unset(monkeypatch):
    monkeypatch.setattr(starmap_handler, "STARMAP_IMAGE_DIR", "")
    assert starmap_handler._is_allowed_image_path("/anything/chart.png") is False


def test_image_path_inside_dir_is_allowed(monkeypatch, tmp_path):
    monkeypatch.setattr(starmap_handler, "STARMAP_IMAGE_DIR", str(tmp_path))
    chart = tmp_path / "chart.png"
    chart.write_bytes(b"x")
    assert starmap_handler._is_allowed_image_path(str(chart)) is True


def test_image_path_traversal_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(starmap_handler, "STARMAP_IMAGE_DIR", str(tmp_path))
    assert starmap_handler._is_allowed_image_path(str(tmp_path / ".." / "etc" / "passwd")) is False
    assert starmap_handler._is_allowed_image_path("/etc/passwd") is False
