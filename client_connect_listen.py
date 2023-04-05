#!/usr/bin/env python
import paho.mqtt.client as mqtt
from paho.mqtt.reasoncodes import ReasonCodes
from pathlib import Path
import os

MQTT_HOST = os.getenv("MQTT_HOST", None)

ROOTDIR = Path(__file__).parent
CERTID = "42d37198571a8bbabdf8789332807132d09d626ad9dc2ef68d7335d57d125e7f"
CA = Path(ROOTDIR).joinpath(f"./tmp/AmazonRootCA1.pem")
CERT = Path(ROOTDIR).joinpath(f"./tmp/{CERTID}-certificate.pem.crt")
KEY = Path(ROOTDIR).joinpath(f"./tmp/{CERTID}-private.pem.key")


def on_connect_callback(client, userdata, flags, reasonCode, properties):
    """
    Called when the broker responds to our connection request.
    """
    print("Connection returned " + str(reasonCode))

def on_subscribe_callback(client, userdata, mid, reasonCodes, properties):
    """
    Called when the broker responds to a subscribe request.
    You will want to ensure that the subscription was sucessfull
    by looking into the reasonCodes (list of paho.mqtt.reasoncodes.ReasonCodes)
    """
    reason: ReasonCodes
    for reason in reasonCodes:
        print(f"{reason.value} {reason}")

def on_message_callback(client, userdata, message: mqtt.MQTTMessage):
    print("on_message_callback")
    print(message)
    print(message.payload)


def main():
    # import pudb; pu.db
    mqtt_client = mqtt.Client(protocol=mqtt.MQTTv5)
    mqtt_client.on_connect = on_connect_callback
    mqtt_client.on_subscribe = on_subscribe_callback
    mqtt_client.on_message = on_message_callback
    mqtt_client
    mqtt_client.tls_set(
        ca_certs=CA,
        certfile=CERT,
        keyfile=KEY
    )

    mqtt_client.connect(MQTT_HOST, port=8883)
    topic = "develop/#"
    mqtt_client.subscribe(topic=topic)

    mqtt_client.loop_forever()

if __name__ == "__main__":
    main()