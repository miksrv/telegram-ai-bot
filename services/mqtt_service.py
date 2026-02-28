""" MQTT Service
Handles communication with MQTT broker for sending and receiving CubeSat commands/status.
Integrates with Telegram bot via callbacks or direct calls.
"""

import json
import logging
import time
import threading
from queue import Queue, Empty

import paho.mqtt.client as mqtt

from config.settings import MQTT_BROKER, MQTT_PORT

logger = logging.getLogger(__name__)

# Reuse a single MQTT client
mqtt_client = mqtt.Client(client_id="telegram-ai-bot")
message_queue = Queue()  # For handling incoming MQTT messages asynchronously

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
        # logger.info(f"Received MQTT message on {topic}: {payload}")

        # Put the message in queue for Telegram bot to process (e.g., send to user)
        message_queue.put({
            "topic": topic,
            "payload": payload,
            "timestamp": time.time()
        })

        # Optional: Immediate processing if needed
        # But better to handle in bot's loop to avoid blocking

    except Exception as e:
        logger.error(f"Error processing MQTT message: {e}")

def on_disconnect(client, userdata, rc):
    logger.warning(f"Disconnected from MQTT, rc={rc}. Reconnecting...")
    time.sleep(5)
    client.reconnect()

def start_mqtt(background=True):
    """Starts the MQTT client loop."""
    # if MQTT_USERNAME and MQTT_PASSWORD:
    #     mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

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

def get_incoming_message(timeout: float = 1.0) -> dict | None:
    """Retrieves the next incoming MQTT message from queue (non-blocking).

    Returns:
        Dict with topic, payload, timestamp or None if no message.
    """
    try:
        return message_queue.get(timeout=timeout)
    except Empty:
        return None