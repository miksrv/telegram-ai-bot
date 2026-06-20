"""MQTT Service
Handles communication with MQTT broker for sending and receiving CubeSat commands/status.
Integrates with Telegram bot via callbacks or direct calls.
"""

import json
import logging
import threading
import time
from queue import Empty, Full, Queue

import paho.mqtt.client as mqtt

from config.settings import (
    MQTT_BROKER,
    MQTT_PORT,
    STARMAP_RESULT_TOPIC,
    STARMAP_STATUS_TOPIC,
)

logger = logging.getLogger(__name__)

# Reuse a single MQTT client
mqtt_client = mqtt.Client(client_id="telegram-ai-bot")

# Per-request response queues keyed by request_id.
# Handlers register before sending a command to avoid missing a fast response.
_pending_lock = threading.Lock()
_pending: dict[str, Queue] = {}

# Availability of the starmap-service, tracked from its retained status topic.
# Starts as "offline" until a status message proves otherwise.
_starmap_lock = threading.Lock()
_starmap_online = False
_status_listeners: list = []


def register_request(request_id: str, maxsize: int = 1) -> Queue:
    """Creates and registers a private response queue for the given request_id.

    Must be called before send_command to avoid a race where the service
    replies before the caller starts waiting.

    Args:
        request_id: correlation id echoed back in every reply.
        maxsize: queue capacity. Use 1 for single-reply services (CubeSat);
            use 0 (unbounded) for multi-reply contracts such as starmap, which
            sends a `queued` acknowledgement followed by a final `ok`/`error`.

    Returns:
        A Queue that receives dicts {topic, payload, timestamp} as matching
        responses arrive.
    """
    q: Queue = Queue(maxsize=maxsize)
    with _pending_lock:
        _pending[request_id] = q
    return q


def is_starmap_online() -> bool:
    """Returns the last known availability of the starmap-service."""
    with _starmap_lock:
        return _starmap_online


def register_status_listener(callback) -> None:
    """Registers a callback invoked with the new bool state on starmap status changes.

    The callback is also invoked once immediately with the current state, so a
    listener registered after the retained status has already arrived is not
    left out of sync.
    """
    with _starmap_lock:
        _status_listeners.append(callback)
        current = _starmap_online
    try:
        callback(current)
    except Exception:
        logger.exception("Starmap status listener failed on initial sync")


def _handle_starmap_status(payload: str) -> None:
    """Updates cached starmap availability and notifies listeners on change."""
    global _starmap_online
    try:
        status = json.loads(payload).get("status")
    except (json.JSONDecodeError, AttributeError):
        logger.warning("Non-JSON starmap status payload, ignoring: %s", payload[:120])
        return

    # Only the two contract values are meaningful. A malformed payload (e.g. {})
    # must not be read as "offline" and flip the menu — ignore it.
    if status not in ("online", "offline"):
        logger.warning("Unexpected starmap status value, ignoring: %s", status)
        return

    online = status == "online"
    with _starmap_lock:
        changed = online != _starmap_online
        _starmap_online = online
        listeners = list(_status_listeners)

    logger.info("Starmap service status: %s", "online" if online else "offline")

    if not changed:
        return

    def _notify():
        for cb in listeners:
            try:
                cb(online)
            except Exception:
                logger.exception("Starmap status listener failed")

    # Run listeners off the MQTT network loop so a slow callback (e.g. a
    # set_my_commands HTTP call) never blocks keepalive pings.
    threading.Thread(target=_notify, daemon=True).start()


def unregister_request(request_id: str):
    """Removes the response queue for the given request_id."""
    with _pending_lock:
        _pending.pop(request_id, None)


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        logger.info("Connected to MQTT broker")
        client.subscribe("cubesat/telemetry/data", qos=1)
        client.subscribe("cubesat/payload/photo", qos=1)
        # Starmap render results plus its retained availability status.
        client.subscribe(STARMAP_RESULT_TOPIC, qos=1)
        client.subscribe(STARMAP_STATUS_TOPIC, qos=1)
    else:
        logger.error(f"Failed to connect to MQTT, rc={rc}")


def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode("utf-8")
        topic = msg.topic

        # Starmap availability is a standalone (retained) status, not a request reply.
        if topic == STARMAP_STATUS_TOPIC:
            _handle_starmap_status(payload)
            return

        try:
            data = json.loads(payload)
            request_id = str(data.get("request_id", ""))
        except (json.JSONDecodeError, AttributeError):
            logger.warning(f"Non-JSON MQTT message on {topic}, cannot route")
            return

        if not request_id:
            logger.debug(f"MQTT message on {topic} has no request_id, dropping")
            return

        with _pending_lock:
            q = _pending.get(request_id)

        if q is not None:
            try:
                q.put_nowait({"topic": topic, "payload": payload, "timestamp": time.time()})
            except Full:
                logger.warning(f"Response queue full for request_id={request_id}")
        else:
            logger.debug(f"No pending request for request_id={request_id} on {topic}")

    except Exception as e:
        logger.error(f"Error processing MQTT message: {e}")


def on_disconnect(client, userdata, rc):
    if rc == 0:
        return  # intentional disconnect from stop_mqtt(); do not reconnect
    logger.warning(f"Disconnected from MQTT (rc={rc}). Starting reconnect loop...")

    def _reconnect_loop():
        delay = 5
        max_delay = 300  # cap at 5 minutes
        max_retries = 10
        for attempt in range(1, max_retries + 1):
            time.sleep(delay)
            try:
                client.reconnect()
                logger.info(f"Reconnected to MQTT broker (attempt {attempt})")
                return
            except Exception as e:
                next_delay = min(delay * 2, max_delay)
                logger.warning(
                    f"MQTT reconnect attempt {attempt}/{max_retries} failed: {e}. " f"Retrying in {next_delay}s"
                )
                delay = next_delay
        logger.error("MQTT reconnect exhausted all retries, giving up")

    threading.Thread(target=_reconnect_loop, daemon=True).start()


def start_mqtt(background=True):
    """Starts the MQTT client loop."""
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    mqtt_client.on_disconnect = on_disconnect

    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    except Exception as e:
        logger.error(f"Failed to connect to MQTT: {e}")
        return False

    if background:
        thread = threading.Thread(target=mqtt_client.loop_forever, daemon=True)
        thread.start()
        logger.info("MQTT loop started in background thread")
    else:
        mqtt_client.loop_forever()

    return True


def stop_mqtt():
    """Cleanly disconnects the MQTT client. Safe to call from the shutdown handler."""
    try:
        mqtt_client.disconnect()
        logger.info("MQTT client disconnected")
    except Exception as e:
        logger.error(f"Error disconnecting MQTT: {e}")


def send_command(command: dict, topic: str = "cubesat/command") -> bool:
    """Sends a command to CubeSat via MQTT.

    Args:
        command: Dict with command details, e.g., {"action": "deploy_antenna", "params": {}}
        topic: MQTT topic to publish to (default: cubesat/command)

    Returns:
        True if published successfully, else False
    """
    try:
        payload = json.dumps(command)
        result = mqtt_client.publish(topic, payload, qos=1, retain=False)
        result.wait_for_publish(timeout=5)
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            logger.info(f"Command sent to {topic}: {payload}")
            return True
        else:
            logger.error(f"Failed to publish command, rc={result.rc}")
            return False
    except Exception as e:
        logger.error(f"Error sending command: {e}")
        return False
