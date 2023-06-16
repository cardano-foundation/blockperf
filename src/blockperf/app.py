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
from dataclasses import InitVar, dataclass, field
from pathlib import Path
from pprint import pprint
from urllib.error import URLError
from urllib.request import Request, urlopen

import paho.mqtt.client as mqtt

from blockperf import __version__ as blockperf_version
from blockperf.blocklog import Blocklog
from blockperf.config import AppConfig
from blockperf.exceptions import EkgError

logging.basicConfig(level=logging.DEBUG, format="(%(threadName)-9s) %(message)s")


@dataclass
class EkgResponse:
    """Holds all the relevant datafrom the ekg response json for later use."""

    response: InitVar[dict]
    block_num: int = field(init=False, default=0)
    slot_num: int = field(init=False, default=0)
    forks: int = field(init=False, default=0)

    def __post_init__(self, response: dict) -> None:
        # Assuming cardano.node.metrics will always be there
        metrics = response.get("cardano").get("node").get("metrics")
        assert "blockNum" in metrics, "blockNum not found"
        self.block_num = metrics.get("blockNum").get("int").get("val")

        self.slot_num = metrics.get("slotNum").get("int").get("val")
        self.forks = metrics.get("forks").get("int").get("val")


class BlocklogProducer(threading.Thread):
    q: queue.Queue
    ekg_url: str
    log_dir: str
    last_block_num: int = 0
    last_fork_height: int = 0
    last_slot_num: int = 0
    all_blocklogs: list = dict()

    def __init__(self, queue, ekg_url: str, log_dir: str, network_magic: int):
        super(BlocklogProducer, self).__init__(daemon=True, name="producer")
        self.q = queue
        self.ekg_url = ekg_url
        self.log_dir = log_dir
        logging.debug("Producer initialized")

    def run(self):
        """Runs the Producer. Will get called from the Thread once its ready.
        If run() finishes the thread will finish.
        """
        logging.debug(f"Starting Producer, {self.ekg_url} ")
        while True:
            EKG_RETRY_INTERVAL = 1  # seconds before trying ekg again, config?
            try:
                self._run()
                time.sleep(EKG_RETRY_INTERVAL)
            except EkgError:
                time.sleep(EKG_RETRY_INTERVAL)
            except Exception as e:
                logging.exception(e)
                time.sleep(EKG_RETRY_INTERVAL)

    def _run(self) -> None:
        # Call ekg to get current slot_num, block_num and fork_num
        ekg_response = self.call_ekg()
        # logging.debug(ekg_response)
        assert ekg_response.slot_num > 0, "EKG did not report a slot_num"
        assert ekg_response.block_num > 0, "EKG did not report a block_num"

        # The idea is noticing a diff between the currently announced
        # block_num/slot_num from ekg and the one that was seen before.
        # So in order to detect that difference there needs to be a preceding
        # value. If its the first round, there is none: So store and go to next.
        if not self.last_block_num and not self.last_slot_num:
            self.last_slot_num = ekg_response.slot_num
            self.last_block_num = ekg_response.block_num
            # last_fork_height = fork_height
            return

        # Produces a list of block_numbers, we want to check the logs for
        # e.g.: [45223, 45224], where these two are the block_nums th
        block_nums_to_report = self.calculate_block_nums_from_ekg(
            ekg_response.block_num
        )
        # If no change in block_nums_to_report is reported by ekg, start over
        if not block_nums_to_report:
            assert (
                ekg_response.forks != 0
            ), "No block_nums found; but forks are reported?"

            return
        logging.debug(f"Total block_nums received from ekg {len(block_nums_to_report)}")

        # Produces a list of blocklogs we want to report (based upon the block_nums from before)
        blocklogs_to_report = Blocklog.blocklogs_from_block_nums(
            block_nums_to_report, self.log_dir
        )
        # blocklogs_to_report is a list of Blocklogs that each represent hold
        # the data to be reported for one block.

        # Handling of forks ... is not implemted yet
        if ekg_response.forks > 0:
            # find the blocklog that is a fork and get its hash
            # blocklog_with_switch = for b in _blocklogs: b.is_forkswitch
            # blocklog_with_switch.all_trace_headers[0].block_num
            # find the blocklog that is a forkswitch
            # Wenn minimal verbosity in config kann newtip kurz sein (less then 64)
            # depending on the node.config
            #    If newtip is less than 64
            #
            # blocklog_from_fork_hash(newtip)
            pass

        if not blocklogs_to_report:
            logging.debug(f"No blocklogs to report found")

        for blocklog in blocklogs_to_report:
            print()
            self.to_cli_message(blocklog)
            print()
            self.q.put(blocklog)

        self.last_block_num = ekg_response.block_num
        self.last_slot_num = ekg_response.slot_num

        # self.all_blocklogs.update([(b.block_hash, b) for b in blocklogs_to_report])
        # Just wait a second
        time.sleep(1)

    def calculate_block_nums_from_ekg(self, current_block_num) -> list:
        """
        blocks will hold the block_nums from last_block_num + 1 until the
        currently reported one. So if last_block_num = 14 and ekg_response.block_num
        is 16, then blocks will be [15, 16]
        """
        # If there is no change, or the change is too big (node probably syncing)
        # return an empty list
        delta_block_num = current_block_num - self.last_block_num
        if not delta_block_num or delta_block_num >= 5:
            return []

        block_nums = []
        for num in range(1, delta_block_num + 1):
            block_nums.append(self.last_block_num + num)
        return block_nums

    def call_ekg(self) -> EkgResponse:
        """Calls the EKG Port for as long as needed and returns a response if
        there is one. It is not inspecting the block data itself, meaning it will
        just return a tuple of the block_num, the forks and slit_num."""
        try:
            req = Request(
                url=self.ekg_url,
                headers={"Accept": "application/json"},
            )
            response = urlopen(req, timeout=5)
            if response.status != 200:
                msg = f"Invalid HTTP response received {response}"
                logging.warning(msg)
                raise EkgError(msg)

            response = response.read()
            response = json.loads(response)
            # I should validate the content here, that all the required
            # fields are actually present in the response
            return EkgResponse(response)
        except URLError as _e:
            msg = f"URLError {_e.reason}; {self.ekg_url}"
            logging.warning(msg)
            raise EkgError(msg)
        except ConnectionResetError:
            raise EkgError("Could not open connection")

    def to_cli_message(self, blocklog: Blocklog):
        """
        The Goal is to print a messages like this per BlockPerf

        Block:.... 792747 ( f581876904 ...)
        Slot..... 24845021 (4s)
        ......... 2023-05-23 13:23:41
        Header... 2023-04-03 13:23:41,170 (+170 ms) from 207.180.196.63:3001
        RequestX. 2023-04-03 13:23:41,170 (+0 ms)
        Block.... 2023-04-03 13:23:41,190 (+20 ms) from 207.180.196.63:3001
        Adopted.. 2023-04-03 13:23:41,190 (+0 ms)
        Size..... 870 bytes
        delay.... 0.192301717 sec
        ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        """
        slot_num_delta = blocklog.slot_num - self.last_slot_num
        # ? blockSlot-slotHeightPrev -> Delta between this slot and the last one that had a block?
        msg = (
            f"Block:.... {blocklog.block_num} ({blocklog.block_hash_short})\n"
            f"Slot:..... {blocklog.slot_num} ({slot_num_delta}s)\n"
            f".......... {blocklog.slot_time}\n"  # Assuming this is the slot_time
            f"Header ... {blocklog.first_trace_header.at} ({blocklog.header_delta}) from {blocklog.header_remote_addr}:{blocklog.header_remote_port}\n"
            f"RequestX.. {blocklog.fetch_request_completed_block.at} ({blocklog.block_request_delta})\n"
            f"Block..... {blocklog.first_completed_block.at} ({blocklog.block_response_delta}) from {blocklog.block_remote_addr}:{blocklog.block_remote_port}\n"
            f"Adopted... {blocklog.block_adopt} ({blocklog.block_adopt_delta})\n"
            f"Size...... {blocklog.block_size} bytes\n"
            f"Delay..... {blocklog.block_delay} sec\n\n"
        )
        sys.stdout.write(msg)


class BlocklogConsumer(threading.Thread):
    """Consumes every Blocklog that is put into the queue.
    Consuming means, taking its message and sending it through MQTT.
    """

    q: queue.Queue
    _mqtt_client: mqtt.Client
    app_config: AppConfig
    app: "App"

    def __init__(self, queue, app_config: AppConfig):
        super(BlocklogConsumer, self).__init__(daemon=True)
        self.name = "consumer"  # set name of the thread
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

            # tls_set has an argument ca_certs. I used to provide a file
            # whith one of the certificates from https://www.amazontrust.com/repository/
            # Not sure if i would actually need that?
            self._mqtt_client.tls_set(
                # ca_certs="/home/msch/src/cf/blockperf.py/tmp/AmazonRootCA1.pem",
                certfile=self.app_config.client_cert,
                keyfile=self.app_config.client_key,
            )
        return self._mqtt_client

    def run(self):
        """Connects to the mqtt broker and runs the consumer forever."""
        self.mqtt_client.connect(
            "a12j2zhynbsgdv-ats.iot.eu-central-1.amazonaws.com", port=8883
        )
        self.mqtt_client.loop_start()  # Starts thread for pahomqtt to process messages

        # Sometimes the connect took a moment to settle. To not have
        # the consumer accept messages (and not be able to publish)
        # i decided to ensure the connection is established this way
        while not self.mqtt_client.is_connected:
            logging.debug("Waiting for mqtt connection ... ")
            time.sleep(1)  # Configurable value?

        while True:
            # The call to get() blocks until there is something in the queue
            logging.debug(
                f"Waiting for next item in queue, Current size: {self.q.qsize()}"
            )
            blocklog = self.q.get()
            if self.q.qsize() > 0:
                logging.debug(f"{self.q.qsize()} left in queue")
            payload = self.build_payload_from(blocklog)
            topic = self.get_topic()
            message_info = self.mqtt_client.publish(topic=topic, payload=payload)
            # wait_for_publish blocks until timeout for the message to be published
            message_info.wait_for_publish(10)

            logging.debug(
                f"Published {blocklog.block_hash_short} with mid='{message_info.mid}' to {topic}"
            )

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

    def on_disconnect_callback(client, userdata, reasonCode, properties):
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

    def _check_already_running(self) -> bool:
        """Checks if an instance is already running, exitst if it does!
        Will not work on windows since fcntl is unavailable there!!
        """
        lock_file_fp = open(self.app_config.lock_file, "a")
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
            sys.exit(f"Could not acquire exclusive lock on {self.lockfile_path}")

    def run(self):
        self._check_already_running()
        # The producers produces "Blocklogs", which each represent
        # one block worth of performance data. So for any given block
        # seen on chain, a Blocklog will be put into the queue
        producer = BlocklogProducer(
            queue=self.q,
            ekg_url=self.app_config.ekg_url,
            log_dir=self.app_config.node_logs_dir,
            network_magic=self.app_config.network_magic,
        )
        producer.start()

        # The consumer takes Blocklogs from the queue and sends them to
        # the mqtt broker. It creates the json structure needed from
        # any given Blocklog and handles the mqtt connection and publishing
        consumer = BlocklogConsumer(
            queue=self.q,
            app_config=self.app_config
            # client_cert=self.app_config.client_cert,
            # client_key=self.app_config.client_key,
            # app=self,
        )
        consumer.start()

        # Blocks main thread until all joined threads are finished
        producer.join()
        consumer.join()
