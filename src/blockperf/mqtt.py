"""MQTT Client
"""
import sys
import logging
import json
from paho.mqtt.client import MQTTMessageInfo
from paho.mqtt.properties import Properties as Properties

try:
    import paho.mqtt.client as mqtt
    from paho.mqtt.properties import Properties
    from paho.mqtt.packettypes import PacketTypes
except ImportError:
    sys.exit(
        "This script needs paho-mqtt package.\n"
        "https://pypi.org/project/paho-mqtt/\n\n"
    )

PUBLISH_TIMEOUT = 30  # publish timeout in seconds
MESSAGE_EXPIRY_INTERVAL = 3600

logger = logging.getLogger(__name__)


class MQTTClient(mqtt.Client):
    """MQTT Client"""

    def __init__(
        self,
        ca_certfile: str,
        client_certfile: str,
        client_keyfile: str,
        host: str,
        port: int,
        keepalive: int,
    ) -> None:
        super().__init__(protocol=mqtt.MQTTv5)
        self.tls_set(
            ca_certs=ca_certfile,
            certfile=client_certfile,
            keyfile=client_keyfile,
        )
        logger.info("Connecting to %s:%s", host, port)
        self.connect(host=host, port=port, keepalive=keepalive)
        self.loop_start()

    def on_connect(self, client, userdata, flags, reasonCode, properties):
        logger.info("Connected: %s ", str(reasonCode))

    def on_connect_fail(self, client, obj):
        logger.warning("Connection Failed")

    def on_disconnect(self, client, userdata, reasonCode, properties) -> None:
        """Called when disconnected from broker
        See paho.mqtt.client.py on_disconnect()"""
        logger.warning("Connection disconnected %s", reasonCode)

    def on_publish(self, client, userdata, mid) -> None:
        """Called when a message is actually received by the broker.
        See paho.mqtt.client.py on_publish()"""
        # There should be a way to know which messages belongs to which
        # item in the queue and acknoledge that specifically
        # self.q.task_done()
        logger.debug("Message %s published to broker", mid)

    def __on_log(self, client, userdata, level, buf):
        """
        client:     the client instance for this callback
        userdata:   the private user data as set in Client() or userdata_set()
        level:      gives the severity of the message and will be one of
                    MQTT_LOG_INFO, MQTT_LOG_NOTICE, MQTT_LOG_WARNING,
                    MQTT_LOG_ERR, and MQTT_LOG_DEBUG.
        buf:        the message itself
        """
        logger.debug("%s - %s", level, buf)

    def publish(self, topic: str, payload: dict):
        """

        MQTTClient publish:
        publish(self, topic: str, payload: _Payload | None = None, qos: int = 0, retain: bool = False, properties: Properties | None = None) -> MQTTMessageInfo:
        """
        try:
            json_payload = json.dumps(payload)
            publish_properties = Properties(PacketTypes.PUBLISH)
            publish_properties.MessageExpiryInterval = MESSAGE_EXPIRY_INTERVAL
            logger.info("Publishing sample to %s", topic)
            # call the actuall clients publish method and receive the message_info
            message_info: MQTTMessageInfo = super().publish(
                topic=topic, payload=json_payload, properties=publish_properties
            )
            # The message_info might not yet have been published,
            # wait_for_publish() blocks until TIMEOUT for that message to be published
            message_info.wait_for_publish(PUBLISH_TIMEOUT)
        except ValueError as exc:
            logger.exception(exc, exc_info=True)
        except RuntimeError as exc:
            logger.exception(exc, exc_info=True)
