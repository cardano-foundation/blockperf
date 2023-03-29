from dataclasses import dataclass
import sys
import traceback
import os
import fcntl
from pathlib import Path
import time
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

logging.basicConfig(
    level=logging.DEBUG,
    format='(%(threadName)-9s) %(message)s'
)

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

    def __init__(self, queue, config: ConfigParser):
        super(BlocklogProducer,self).__init__(daemon=True, name="producer")
        self.q = queue
        self.ekg_url = config.get("DEFAULT", "ekg_url", fallback="http://127.0.0.1:12788")
        self.log_dir = config.get("DEFAULT", "node_logs_dir", fallback="/opt/cardano/cnode/logs")

    def calculate_block_nums_from_ekg(self, current_block_num) -> list:
        """
        blocks will hold the block_nums from last_block_num + 1 until the
        currently reported one. So if last_block_num = 14 and ekg_response.block_num
        is 16, then blocks will be [15, 16]
        """
        # If there is no change, or the change is too big (node probably syncing)
        # return an empty list
        _delta_block_num = current_block_num -self.last_block_num
        if not _delta_block_num or _delta_block_num >= 5:
            print(f"No delta or node is syncing {_delta_block_num}")
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
        print(f"Run: {self.count} - last_block_num: {self.last_block_num}")
        if self.count == 1: # If its the first round, set last_* values and continue
            self.last_slot_num = ekg_response.slot_num
            self.last_block_num = ekg_response.block_num
            #last_fork_height = fork_height
            return

        block_nums = self.calculate_block_nums_from_ekg(ekg_response.block_num)
        if not block_nums: # No change in block_num found, come back later
            return
        blocklogs = Blocklog.blocklogs_from_block_nums(block_nums, self.log_dir)

        self.last_block_num = ekg_response.block_num
        self.last_slot_num = ekg_response.slot_num

        # Now, For each id in blocks we want to create a
        # Blocklog which is a list of all the relevant entries of the logfile
        # That Blocklog is then pushed into the Queue, for the consumer to process
        for blocklog in blocklogs:
            print(f"Enqueue: {blocklog}")
            self.q.put(blocklog)
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


class BlocklogConsumer(threading.Thread):
    """Consumes every Blocklog that is put into the queue.

    Consuming means, taking its message and sending it through MQTT.


    """
    q: queue.Queue
    def __init__(self, queue):
        super(BlocklogConsumer,self).__init__(daemon=True)
        print("BlocklogConsumer::__init__")
        self.name = "consumer"
        self.q = queue

    def run(self):
        while True:
            # The call to get() blocks until there is something in the queue
            blocklog: Blocklog = self.q.get()
            print(f"Fetchin {blocklog} : {self.q.qsize()} items left ")
            # to be coded
            # If finished working, the queue needs to be told about that
            self.q.task_done()


class App:
    q: queue.Queue
    config: ConfigParser

    def __init__(self, config:str) -> None:
        self.config = ConfigParser()
        self.config.read(config)
        self.q = queue.Queue(maxsize=10)

    def _already_running(self) -> bool:
        """Checks if an instance is already running.

        Will not work on windows since fcntl is unavailable there!!

        """
        lock_file_fp = open("/tmp/blockperf.lock", 'a')
        try:
            fcntl.lockf(lock_file_fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
            lock_file_fp.seek(0)
            lock_file_fp.truncate()
            lock_file_fp.write(str(os.getpid()))
            lock_file_fp.flush()
            # Could acquire lock, instance is not running
            return False
        except (IOError, BlockingIOError):
            with open("/tmp/blockperf.lock", 'r') as fp:
                pid = fp.read()
                print(f"Already running as pid: {pid}")
            # Could not acquire lock, implement --force flag or something?
            return True

    def run(self):
        if self._already_running():
            sys.exit("Instance already running")

        producer = BlocklogProducer(queue=self.q, config=self.config)
        producer.start()
        consumer= BlocklogConsumer(queue=self.q)
        consumer.start()
        print("Created both")

        producer.join()
        print("producer joined")

        consumer.join()
        print("consumer joined")

        #self.q.join()
