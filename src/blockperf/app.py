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
from blockperf import logger_name
from blockperf.config import AppConfig
from blockperf.tracing import BlockTrace, TraceEvent, TraceEventKind

logging.basicConfig(level=logging.DEBUG, format="(%(threadName)-9s) %(message)s")
logger = logging.getLogger(logger_name)


class App:
    q: queue.Queue
    app_config: AppConfig
    node_config: dict
    _mqtt_client: mqtt.Client
    trace_events = dict()  # The list of blocks seen from the logfile

    def __init__(self, config: AppConfig) -> None:
        self.app_config = config
        self.q = queue.Queue(maxsize=20)
        logger.debug("App init finished")

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
        """Run the App by creating the two threads and starting them."""
        self._check_already_running()

        # consumer = BlocklogConsumer(queue=self.q, app_config=self.app_config)
        consumer_thread = threading.Thread(target=self.consume_blocktrace, args=())
        consumer_thread.start()

        producer_thread = threading.Thread(target=self.produce_blocktraces, args=())
        producer_thread.start()

        # Blocks main thread until all joined threads are finished
        producer_thread.join()
        consumer_thread.join()

    @property
    def mqtt_client(self) -> mqtt.Client:
        # Returns the mqtt client, or creates one if there is none
        if not hasattr(self, "_mqtt_client"):
            logger.info("(Re)Creating new mqtt client")
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

    def get_topic(self) -> str:
        return f"{self.app_config.topic_base}/{self.app_config.operator}/{self.app_config.relay_public_ip}"

    def on_connect_callback(self, client, userdata, flags, reasonCode, properties) -> None:
        """Called when the broker responds to our connection request.
        See paho.mqtt.client.py on_connect()"""
        if not reasonCode == 0:
            logger.error("Connection error " + str(reasonCode))
            self._mqtt_connected = False
        else:
            self._mqtt_connected = True

    def on_disconnect_callback(self, client, userdata, reasonCode, properties) -> None:
        """Called when disconnected from broker
        See paho.mqtt.client.py on_disconnect()"""
        logger.error(f"Connection lost {reasonCode}")

    def on_publish_callback(self, client, userdata, mid) -> None:
        """Called when a message is actually received by the broker.
        See paho.mqtt.client.py on_publish()"""
        logger.info(f"Message {mid} published")
        # There should be a way to know which messages belongs to which
        # item in the queue and acknoledge that specifically
        # self.q.task_done()

    def consume_blocktrace(self):
        """Runs the Consumer thread. Will get called from Thread base once ready.
        If run() finishes, the thread will finish.
        """
        self.mqtt_client
        broker_url, broker_port = (
            self.app_config.mqtt_broker_url,
            self.app_config.mqtt_broker_port,
        )
        logger.debug(
            f"Connecting to {broker_url}:{broker_port}"
        )
        self.mqtt_client.connect(broker_url, broker_port)
        self.mqtt_client.loop_start()  # Starts thread for pahomqtt to process messages

        # Sometimes the connect took a moment to settle. To not have
        # the consumer accept messages (and not be able to publish)
        # i decided to ensure the connection is established this way
        while not self.mqtt_client.is_connected:
            logger.debug("Waiting for mqtt connection ... ")
            time.sleep(0.5)  # Block until connected

        while True:
            logger.debug(
                f"Waiting for next item in queue, Current size: {self.q.qsize()}"
            )
            # The call to get() blocks until there is something in the queue
            blocktrace = self.q.get()
            if self.q.qsize() > 0:
                logger.debug(f"{self.q.qsize()} left in queue")
            payload = blocktrace.as_payload_dict()
            pprint(payload)
            topic = self.get_topic()
            start_publish = timer()
            message_info = self.mqtt_client.publish(
                topic=topic,
                payload=json.dumps(payload, default=str)
            )
            # wait_for_publish blocks until timeout for the message to be published
            message_info.wait_for_publish(5)
            end_publish = timer()
            publish_time = end_publish - start_publish
            logger.info(
                f"Published {blocktrace.block_hash_short} with mid='{message_info.mid}' to {topic} in {publish_time}"
            )
            if publish_time > 5.0:
                logger.warning("Publish time > 5.0")

    def generate_log_events(self):
        """Generator that yields new lines from the logfile as they come in."""
        interesting_kinds = (
            TraceEventKind.TRACE_DOWNLOADED_HEADER,
            TraceEventKind.SEND_FETCH_REQUEST,
            TraceEventKind.COMPLETED_BLOCK_FETCH,
            TraceEventKind.ADDED_TO_CURRENT_CHAIN,
        )
        node_log_path = Path(self.app_config.node_logs_dir).joinpath("node.json")
        if not node_log_path.exists():
            sys.exit(f"{node_log_path} does not exist!")
        logger.debug(f"Generating events from {node_log_path}")

        # Open logfile and constantly read it,
        with open(node_log_path, "r") as node_log:
            # Move fp to end to only see "new" lines
            node_log.seek(0,2)
            while True:
                new_line = node_log.readline()
                # wait a moment to avoid incomplete lines bubbling up ...
                if not new_line:
                    time.sleep(0.1)
                    continue
                event = TraceEvent.from_logline(new_line)
                if event and event.kind in interesting_kinds:
                    yield (event)

    def produce_blocktraces(self):
        finished_block_kinds = (
            TraceEventKind.ADDED_TO_CURRENT_CHAIN,
            TraceEventKind.SWITCHED_TO_A_FORK,
        )
        while True:
            for event in self.generate_log_events():
                logger.debug(event)
                assert event.block_hash, f"Found a trace that has no hash {event}"

                # Add event to list in identified by event.block_hash
                if not event.block_hash in self.trace_events:
                    self.trace_events[event.block_hash] = list()
                self.trace_events[event.block_hash].append(event)

                # If the event is not finishing a block move on
                if not event.kind in finished_block_kinds:
                    continue

                _h = event.block_hash[0:9]
                logger.debug(f"Found {len(self.trace_events[event.block_hash])} events for {_h}")
                logger.debug(f"Blocks tracked {len(self.trace_events.keys())}")
                # Get all events for given hash and delete from list
                events = self.trace_events.pop(event.block_hash)
                bt = BlockTrace(events, self.app_config)
                sys.stdout.write(bt.as_msg_string())
                self.q.put(bt)

