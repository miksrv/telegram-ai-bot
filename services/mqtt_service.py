""" MQTT Service
Handles communication with MQTT broker for sending and receiving CubeSat commands/status.
Integrates with Telegram bot via callbacks or direct calls.
"""

import json
import logging
import time
import threading
from queue import Queue, Full, Empty

import paho.mqtt.client as mqtt

from config.settings import MQTT_BROKER, MQTT_PORT

logger = logging.getLogger(__name__)

# Reuse a single MQTT client
mqtt_client = mqtt.Client(client_id="telegram-ai-bot")

# Per-request response queues keyed by request_id.
# Handlers register before sending a command to avoid missing a fast response.
_pending_lock = threading.Lock()
_pending: dict[str, Queue] = {}


def register_request(request_id: str) -> Queue:
    """Creates and registers a private response queue for the given request_id.

    Must be called before send_command to avoid a race where the CubeSat
    replies before the caller starts waiting.

    Returns:
        A Queue that will receive exactly one dict {topic, payload, timestamp}
        when the matching response arrives.
    """
    q: Queue = Queue(maxsize=1)
    with _pending_lock:
        _pending[request_id] = q
    return q


def unregister_request(request_id: str):
    """Removes the response queue for the given request_id."""
    with _pending_lock:
        _pending.pop(request_id, None)


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        logger.info("Connected to MQTT broker")
        client.subscribe("cubesat/telemetry/data", qos=1)
        client.subscribe("cubesat/payload/photo", qos=1)
    else:
        logger.error(f"Failed to connect to MQTT, rc={rc}")


def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode('utf-8')
        topic = msg.topic

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
    logger.warning(f"Disconnected from MQTT, rc={rc}. Reconnecting...")
    time.sleep(5)
    client.reconnect()


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
