"""MQTT Client
"""
import sys
import logging
try:
    import paho.mqtt.client as mqtt
    from paho.mqtt.properties import Properties
    from paho.mqtt.packettypes import PacketTypes
except ImportError:
    sys.exit(
        "This script needs paho-mqtt package.\n"
        "https://pypi.org/project/paho-mqtt/\n\n"
    )

from blockperf.config import BROKER_URL, BROKER_PORT, BROKER_KEEPALIVE

logger = logging.getLogger(__name__)
logger.debug("Mqtt Module ")


class MQTTClient(mqtt.Client):
    """Mqt Client
    """

    def __init__(self, ) -> None:
        print("Creating MQTT Client")
        super().__init__(protocol=mqtt.MQTTv5)
        self.broker_url = ""
        self.broker_port = ""

    def run(self):
        print("Run MQTT Client")
        self.connect(host=BROKER_URL, port=BROKER_PORT,
                     keepalive=BROKER_KEEPALIVE)
        # self.subscribe("$SYS/#", 0)

        rc = 0
        while rc == 0:
            print("Mqtt Loop")
            rc = self.loop_start()
        return rc

    def on_connect(self, client, userdata, flags, reasonCode, properties):
        logger.debug("Connected: %s ", str(reasonCode))

    def on_connect_fail(self, client, obj):
        logger.debug("Connection Failed")

    def on_disconnect(self, client, userdata, reasonCode) -> None:
        """Called when disconnected from broker
        See paho.mqtt.client.py on_disconnect()"""
        logger.debug("Connection disconnected %s", reasonCode)

    def on_publish(self, client, userdata, mid) -> None:
        """Called when a message is actually received by the broker.
        See paho.mqtt.client.py on_publish()"""
        # There should be a way to know which messages belongs to which
        # item in the queue and acknoledge that specifically
        # self.q.task_done()
        logger.debug("Message %s published to broker", mid)

    def on_log(self, client, userdata, level, buf):
        """
        client:     the client instance for this callback
        userdata:   the private user data as set in Client() or userdata_set()
        level:      gives the severity of the message and will be one of
                    MQTT_LOG_INFO, MQTT_LOG_NOTICE, MQTT_LOG_WARNING,
                    MQTT_LOG_ERR, and MQTT_LOG_DEBUG.
        buf:        the message itself
        """
        logger.debug("%s - %s", level, buf)