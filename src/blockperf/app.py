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
from blockperf.blocklog import Blocklog, blocklogs


logging.basicConfig(
    level=logging.DEBUG,
    format='(%(threadName)-9s) %(message)s'
)

# Lockfile filepointer to determine if instance is already running
lockfile_fp = None

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

    def _run(self):
        # Call ekg to get current slot_num, block_num and fork_num
        slot_num, block_num = self._call_ekg()
        self.count += 1
        print(f"Run: {self.count} - last_block_num: {self.last_block_num}")
        # If its the first round, just set the last_ values and continue
        if self.count == 1:
            self.last_slot_num = slot_num
            self.last_block_num = block_num
            #last_fork_height = fork_height
            return

        # blocks and forks should hold the numbers of the blocks/forks that
        # have been reported by ekg.
        blocks, forks = [], []
        _db = block_num - self.last_block_num
        # print(f"_db {_db}")
        if _db and not _db > 5:
            for i in range(1, _db + 1):
                #print(f"Range {i}")
                blocks.append(self.last_block_num + i)
        self.last_block_num = block_num
        # Now, For each id in blocks we want to create a
        # Blocklog which is a list of all the relevant entries of the logfile
        # That Blocklog is then pushed into the Queue, for the consumer to process
        for blocklog in blocklogs(blocks, self.log_dir):
            print(f"Putting in Queue.")
            print(blocklog)
            self.q.put(blocklog)
        # Same thing for forks ...
        self.last_slot_num = slot_num
        time.sleep(1)

    def run(self):
        while True:
            try:
                self._run()
            except Exception as e:
                print(f"Error: {e}")
                print(traceback.format_exc())
                time.sleep(1)

    def _call_ekg(self) -> tuple:
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
                    ekg_data = json.loads(response.read())
                    # pprint(json.loads(response.read()))
                    metrics = ekg_data.get("cardano").get("node").get("metrics")
                    slot_num = metrics.get("slotNum").get("int").get("val")
                    block_num = metrics.get("blockNum").get("int").get("val")
                    # forks = _metrics.get("forks").get("int").get("val")
                    # forks may or may not be in ekg.json
                    if slot_num > 0 and block_num > 0: # and forks > 0:
                        return (slot_num, block_num) #, forks)
                    else:
                        print(f"Invalid EKG Response returned {response}")
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
