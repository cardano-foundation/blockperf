import fcntl
import json
import logging
import os
import queue
import random
import sys
import threading
import time
import traceback
import urllib
from timeit import default_timer as timer
from dataclasses import InitVar, dataclass, field
from pathlib import Path
from pprint import pprint

import paho.mqtt.client as mqtt

from blockperf import __version__ as blockperf_version
from blockperf.blocklog import Blocklog
from blockperf.config import AppConfig
from blockperf.producer import EkgProducer, LogfilesProducer

logging.basicConfig(level=logging.DEBUG, format="(%(threadName)-9s) %(message)s")


class BlocklogConsumer(threading.Thread):
    """Consumes every Blocklog that is put into the queue.
    Consuming means, taking its message and sending it through MQTT.
    """

    q: queue.Queue
    _mqtt_client: mqtt.Client
    app_config: AppConfig
    app: "App"

    def __init__(self, queue, app_config: AppConfig):
        super(BlocklogConsumer, self).__init__(
            daemon=True, name=self.__class__.__name__
        )
        self.q = queue
        self.app_config = app_config
        logging.debug("Consumer initialized")

    def build_payload_from(self, blocklog: Blocklog) -> str:
        """Converts a given Blocklog into a json payload for sending to mqtt broker"""
        message = {
            "magic": self.app_config.network_magic,
            "bpVersion": blockperf_version,
            "blockNo": blocklog.block_num,
            "slotNo": blocklog.slot_num,
            "blockHash": blocklog.block_hash,
            "blockSize": blocklog.block_size,
            "headerRemoteAddr": blocklog.header_remote_addr,
            "headerRemotePort": blocklog.header_remote_port,
            "headerDelta": blocklog.header_delta,
            "blockReqDelta": blocklog.block_request_delta,
            "blockRspDelta": blocklog.block_response_delta,
            "blockAdoptDelta": blocklog.block_adopt_delta,
            "blockRemoteAddress": blocklog.block_remote_addr,
            "blockRemotePort": blocklog.block_remote_port,
            # "blockLocalAddress": blocklog.block_local_address,
            # "blockLocalPort": blocklog.block_local_port,
            "blockG": blocklog.block_g,
        }
        return json.dumps(message, default=str)

    @property
    def mqtt_client(self) -> mqtt.Client:
        # Returns the mqtt client, or creates one if there is none
        if not hasattr(self, "_mqtt_client"):
            logging.info("(Re)Creating new mqtt client")
            # Every new client will start clean unless client_id is specified
            self._mqtt_client = mqtt.Client(protocol=mqtt.MQTTv5)
            self._mqtt_client.on_connect = self.on_connect_callback
            self._mqtt_client.on_disconnect = self.on_disconnect_callback
            self._mqtt_client.on_publish = self.on_publish_callback

            # tls_set has an argument 'ca_certs'. I used to provide a file
            # whith one of the certificates from https://www.amazontrust.com/repository/
            # But from readig the tls_set() code i suspect when i leave that out
            # thessl.SSLContext will try to autodownload that CA!?
            self._mqtt_client.tls_set(
                # ca_certs="/tmp/AmazonRootCA1.pem",
                certfile=self.app_config.client_cert,
                keyfile=self.app_config.client_key,
            )
        return self._mqtt_client

    def run(self):
        """Runs the Consumer thread. Will get called from Thread base once ready.
        If run() finishes, the thread will finish.
        """
        broker_url, broker_port = (
            self.app_config.mqtt_broker_url,
            self.app_config.mqtt_broker_port,
        )
        logging.debug(
            f"Running {self.__class__.__name__} on {broker_url}:{broker_port}"
        )
        self.mqtt_client.connect(broker_url, broker_port)
        self.mqtt_client.loop_start()  # Starts thread for pahomqtt to process messages

        # Sometimes the connect took a moment to settle. To not have
        # the consumer accept messages (and not be able to publish)
        # i decided to ensure the connection is established this way
        while not self.mqtt_client.is_connected:
            logging.debug("Waiting for mqtt connection ... ")
            time.sleep(0.5)  # Block until connected

        while True:
            logging.debug(
                f"Waiting for next item in queue, Current size: {self.q.qsize()}"
            )
            # The call to get() blocks until there is something in the queue
            blocklog = self.q.get()
            if self.q.qsize() > 0:
                logging.debug(f"{self.q.qsize()} left in queue")
            payload = self.build_payload_from(blocklog)
            topic = self.get_topic()
            start_publish = timer()
            message_info = self.mqtt_client.publish(topic=topic, payload=payload)
            # wait_for_publish blocks until timeout for the message to be published
            message_info.wait_for_publish(5)
            end_publish = timer()
            publish_time = end_publish - start_publish
            logging.info(
                f"Published {blocklog.block_hash_short} with mid='{message_info.mid}' to {topic} in {publish_time}"
            )
            if publish_time > 5.0:
                logging.warning("Publish time > 5.0")

    def get_topic(self) -> str:
        return f"{self.app_config.topic_base}/{self.app_config.operator}/{self.app_config.relay_public_ip}"

    def on_connect_callback(self, client, userdata, flags, reasonCode, properties):
        """Called when the broker responds to our connection request.
        See paho.mqtt.client.py on_connect()"""
        if not reasonCode == 0:
            logging.error("Connection error " + str(reasonCode))
            self._mqtt_connected = False
        else:
            self._mqtt_connected = True

    def on_disconnect_callback(self, client, userdata, reasonCode, properties):
        """Called when disconnected from broker
        See paho.mqtt.client.py on_disconnect()"""
        logging.error(f"Connection lost {reasonCode}")

    def on_publish_callback(self, client, userdata, mid):
        """Called when a message is actually received by the broker.
        See paho.mqtt.client.py on_publish()"""
        logging.info(f"Message {mid} published")
        # There should be a way to know which messages belongs to which
        # item in the queue and acknoledge that specifically
        # self.q.task_done()


class App:
    q: queue.Queue
    app_config: AppConfig
    node_config: dict

    def __init__(self, config: AppConfig) -> None:
        # config.validate_config()
        self.app_config = config
        self.q = queue.Queue(maxsize=20)
        logging.debug("App init finished")

    def _check_already_running(self) -> None:
        """Checks if an instance is already running, exitst if it does!
        Will not work on windows since fcntl is unavailable there!!
        """
        lock_file = self.app_config.lock_file
        lock_file_fp = open(lock_file, "a")
        try:
            # Try to get exclusive lock on lockfile
            fcntl.lockf(lock_file_fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
            lock_file_fp.seek(0)
            lock_file_fp.truncate()
            lock_file_fp.write(str(os.getpid()))
            lock_file_fp.flush()
            # Could acquire lock, do nothing and go on
        except (IOError, BlockingIOError):
            # Could not acquire lock, maybe implement some --force/--ignore flag
            # that would delete and recreate the file?
            sys.exit(f"Could not acquire exclusive lock on {lock_file}")

    def run(self):
        self._check_already_running()
        # The producers produces "Blocklogs", which each represent
        # one block worth of performance data. So for any given block
        # seen on chain, a Blocklog will be put into the queue

        # producer = EkgProducer(queue=self.q, app_config=self.app_config)
        producer = LogfilesProducer(queue=self.q, app_config=self.app_config)
        producer.start()

        # The consumer takes Blocklogs from the queue and sends them to
        # the mqtt broker. It creates the json structure needed from
        # any given Blocklog and handles the mqtt connection and publishing
        consumer = BlocklogConsumer(queue=self.q, app_config=self.app_config)
        consumer.start()

        # Blocks main thread until all joined threads are finished
        producer.join()
        consumer.join()
