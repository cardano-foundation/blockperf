from dataclasses import dataclass
import sys
import traceback
import os
import fcntl
from pathlib import Path
import time
import json
import urllib
from urllib.request import Request, urlopen
from urllib.error import URLError
import json
import threading
import queue
from pprint import pprint
import random
import logging
from configparser import ConfigParser
from blockperf.blocklog import Blocklog
from dataclasses import dataclass, field, InitVar
import paho.mqtt.client as mqtt # ?


logging.basicConfig(level=logging.DEBUG, format="(%(threadName)-9s) %(message)s")

# Lockfile filepointer to determine if instance is already running
lockfile_fp = None


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
        self.slot_num = metrics.get("slotNum").get("int").get("val")
        self.block_num = metrics.get("blockNum").get("int").get("val")
        self.forks = metrics.get("forks").get("int").get("val")

    def is_valid(self) -> bool:
        if self.slot_num > 0 and self.block_num > 0:
            return True
        return False

class BlocklogProducer(threading.Thread):
    q: queue.Queue
    ekg_url: str
    log_dir: str
    last_block_num: int = 0
    last_fork_height: int = 0
    last_slot_num: int = 0
    count: int = 0
    all_blocklogs: list = dict()

    def __init__(self, queue, ekg_url: str, log_dir: str, network_magic: int):
        super(BlocklogProducer, self).__init__(daemon=True, name="producer")
        self.q = queue
        self.ekg_url = ekg_url
        self.log_dir = log_dir

    def calculate_block_nums_from_ekg(self, current_block_num) -> list:
        """
        blocks will hold the block_nums from last_block_num + 1 until the
        currently reported one. So if last_block_num = 14 and ekg_response.block_num
        is 16, then blocks will be [15, 16]
        """
        # If there is no change, or the change is too big (node probably syncing)
        # return an empty list
        _delta_block_num = current_block_num - self.last_block_num
        if not _delta_block_num or _delta_block_num >= 5:
            # print(f"No delta or node is syncing {_delta_block_num}")
            return []

        block_nums = []
        for num in range(1, _delta_block_num + 1):
            block_nums.append(self.last_block_num + num)
        return block_nums

    def _run(self) -> None:
        # Call ekg to get current slot_num, block_num and fork_num
        ekg_response = self._call_ekg()
        if not ekg_response.is_valid():
            print(f"Invalid EkgResponse received, skipping. {ekg_response}")
            return

        self.count += 1
        # print(f"Run: {self.count} - last_block_num: {self.last_block_num}")
        if self.count == 1:  # If its the first round, set last_* values and continue
            self.last_slot_num = ekg_response.slot_num
            self.last_block_num = ekg_response.block_num
            # last_fork_height = fork_height
            return

        block_nums = self.calculate_block_nums_from_ekg(ekg_response.block_num)
        if not block_nums:  # If no change in block_num found, we are not interested?
            assert (
                ekg_response.forks != 0
            ), "No block_nums found; but forks are reported?"
            return

        _blocklogs = Blocklog.blocklogs_from_block_nums(block_nums, self.log_dir)

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

        # Now, For each id in blocks we want to create a
        # Blocklog which is a list of all the relevant entries of the logfile
        # That Blocklog is then pushed into the Queue, for the consumer to process
        for blocklog in _blocklogs:
            #print(f"Enqueue: {blocklog}")
            print()
            self.to_cli_message(blocklog)
            print()
            self.q.put(blocklog)

        self.last_block_num = ekg_response.block_num
        self.last_slot_num = ekg_response.slot_num

        # self.all_blocklogs.update([(b.block_hash, b) for b in _blocklogs])
        # print(self.all_blocklogs)
        time.sleep(1)

    def run(self):
        """Runs the Producer, forever!
        The 'except Exception' is certainly something we want to discuss at some
        point. For now i wanted a simpler _run implementation that does  not need
        to worry about the loop or exceptions and still will keep
        the thread running.
        The loop could also be done in the App and then have the thread be
        recreated, see App::run()
        """
        while True:
            try:
                self._run()
            except Exception as e:
                print(f"Error: {e}")
                print(traceback.format_exc())
                time.sleep(1)

    def _call_ekg(self) -> EkgResponse:
        """Calls the EKG Port for as long as needed and returns a response if
        there is one. It is not inspecting the block data itself, meaning it will
        just return a tuple of the block_num, the forks and slit_num."""
        while True:
            try:
                req = Request(
                    url=self.ekg_url,
                    headers={"Accept": "application/json"},
                )
                response = urlopen(req)
                if response.status == 200:
                    return EkgResponse(json.loads(response.read()))
                else:
                    print(f"Got {response.status} {response.reason}")
            except URLError as _e:
                print(f"URLError {_e.reason}")
            except ConnectionResetError:
                print(f"ConnectionResetError")
            finally:
                time.sleep(1)

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
            f".......... {blocklog.slot_time}\n" # Assuming this is the slot_time
            f"Header ... {blocklog.first_trace_header.at} ({blocklog.header_delta}) from {blocklog.header_remote_addr}:{blocklog.header_remote_port}\n"
            f"RequestX.. {blocklog.fetch_request_completed_block.at} ({blocklog.block_request_delta})\n"
            f"Block..... {blocklog.first_completed_block.at} ({blocklog.block_response_delta}) from {blocklog.block_remote_addr}:{blocklog.block_remote_port}\n"
            f"Adopted... {blocklog.block_adopt} ({blocklog.block_adopt_delta})\n"
            f"Size...... {blocklog.block_size} bytes\n"
            f"Delay..... {blocklog.block_delay} sec\n"
        )
        print(msg)


class BlocklogConsumer(threading.Thread):
    """Consumes every Blocklog that is put into the queue.
    Consuming means, taking its message and sending it through MQTT.
    """

    q: queue.Queue

    def __init__(self, queue):
        super(BlocklogConsumer, self).__init__(daemon=True)
        print("BlocklogConsumer::__init__")
        self.name = "consumer"
        self.q = queue

    def run(self):
        while True:
            # The call to get() blocks until there is something in the queue
            blocklog: Blocklog = self.q.get()
            print(f"Fetchin {blocklog} : {self.q.qsize()} items left ")

            # If finished working, the queue needs to be told about that
            self.q.task_done()


class App:
    q: queue.Queue
    # config: ConfigParser
    node_config: dict = None
    network_magic: int = 0
    lockfile_path: str = "/tmp/blockperf.lock"

    def __init__(self, config: str) -> None:
        _config = ConfigParser()
        _config.read(config)
        self._read_config(_config)
        self.q = queue.Queue(maxsize=10)

    def _already_running(self) -> bool:
        """Checks if an instance is already running.

        Will not work on windows since fcntl is unavailable there!!

        """
        lock_file_fp = open(self.lockfile_path, "a")
        try:
            fcntl.lockf(lock_file_fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
            lock_file_fp.seek(0)
            lock_file_fp.truncate()
            lock_file_fp.write(str(os.getpid()))
            lock_file_fp.flush()
            # Could acquire lock, instance is not running
            return False
        except (IOError, BlockingIOError):
            with open(self.lockfile_path, "r") as fp:
                pid = fp.read()
                print(f"Already running as pid: {pid}")
            # Could not acquire lock, implement --force flag or something?
            return True

    def _read_config(self, config: ConfigParser):
        """ """
        node_config_path = Path(
            config.get(
                "DEFAULT",
                "node_config",
                fallback="/opt/cardano/cnode/files/config.json",
            )
        )
        node_config_folder = node_config_path.parent
        if not node_config_path.exists():
            sys.exit(f"Node Config not found {node_config_path}")

        self.node_config = json.loads(node_config_path.read_text())
        self.ekg_url = config.get(
            "DEFAULT", "ekg_url", fallback="http://127.0.0.1:12788"
        )
        self.log_dir = config.get(
            "DEFAULT", "node_logs_dir", fallback="/opt/cardano/cnode/logs"
        )

        # for now assuming that these are relative paths to config.json
        # print(self.node_config["AlonzoGenesisFile"])
        # print(self.node_config["ByronGenesisFile"])
        shelly_genesis = json.loads(
            node_config_folder.joinpath(
                self.node_config["ShelleyGenesisFile"]
            ).read_text()
        )
        self.network_magic = int(shelly_genesis["networkMagic"])
        print(self.network_magic)

    def run(self):
        if self._already_running():
            sys.exit("Instance already running")

        producer = BlocklogProducer(
            queue=self.q,
            ekg_url=self.ekg_url,
            log_dir=self.log_dir,
            network_magic=self.network_magic,
        )
        producer.start()
        consumer = BlocklogConsumer(queue=self.q)
        consumer.start()
        print("Created both")

        producer.join()
        print("producer joined")

        consumer.join()
        print("consumer joined")

        # self.q.join()
