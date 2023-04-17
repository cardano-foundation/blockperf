#!/usr/bin/env python
import paho.mqtt.client as mqtt
from pathlib import Path
import os
import json
import time
import logging
import sys

MQTT_HOST = os.getenv("MQTT_HOST", None)

ROOTDIR = Path(__file__).parent
CERTID = "42d37198571a8bbabdf8789332807132d09d626ad9dc2ef68d7335d57d125e7f"
CA = Path(ROOTDIR).joinpath(f"./tmp/AmazonRootCA1.pem")
CERT = Path(ROOTDIR).joinpath(f"./tmp/{CERTID}-certificate.pem.crt")
KEY = Path(ROOTDIR).joinpath(f"./tmp/{CERTID}-private.pem.key")

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
log_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(log_format)
logger.addHandler(handler)

def on_connect_callback(client, userdata, flags, reasonCode, properties):
    """
    Called when the broker responds to our connection request.
    """
    print("Connection returned " + str(reasonCode))

def on_connect_fail_callback(client, userdata):
     print("BADAM")
     print(client)
     print(userdata)

def on_disconnect_callback(client, userdata, reasonCode, properties):
    """Look into reasonCode for reason of disconnection
    """
    print("on_disconnect_callback")
    print(reasonCode)


def on_publish_callback(client, userdata, mid):
    print("on_publish_callback ")
    print(client)
    print(userdata)
    print(mid)

def main():
    mqtt_client = mqtt.Client(
        client_id="sometruerandomthing",
        protocol=mqtt.MQTTv5
    )
    print(mqtt_client)

    mqtt_client.on_connect_fail = on_connect_fail_callback
    mqtt_client.on_connect = on_connect_callback
    mqtt_client.on_publish = on_publish_callback
    mqtt_client.on_disconnect = on_disconnect_callback
    mqtt_client.tls_set(
        ca_certs=CA,
        certfile=CERT,
        keyfile=KEY
    )
    print(MQTT_HOST)
    # import pudb; pu.db
    mqtt_client.connect(MQTT_HOST, port=8883)

    # mqtt_client.loop_start()
    while True:
        time.sleep(1)
        payload = json.dumps({"message": "Foobar"})
        topic="develop/me"
        print(f"Publish to topic {topic}")
        mqtt_client.publish(topic=topic, payload=payload)
        mqtt_client.loop(1)

if __name__ == "__main__":
    main()
