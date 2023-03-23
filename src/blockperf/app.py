from dataclasses import dataclass
import sys
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

BLOCKLOGSDIR="/home/msch/src/cf/blockperf.py/blocklogs"

logging.basicConfig(
    level=logging.DEBUG,
    format='(%(threadName)-9s) %(message)s'
)

"""
line_tsv=$(jq -r '[
   .cardano.node.metrics.blockNum.int.val //0,
   .cardano.node.metrics.forks.int.val //0,
   .cardano.node.metrics.slotNum.int.val //0
   ] | @tsv' <<< "$(curl -s -H 'Accept: application/json' http://${EKG_HOST}:${EKG_PORT}/)")
"""

@dataclass
class Blocklog:
    value: int
    lines: list

    def __init__(self, lines: list) -> None:
        self.lines = lines

    def __repr__(self) -> str:
        return f"Blocklog {len(self.lines)} lines"

@dataclass
class EKGResponse:
    slot_num: int = 0
    block_num: int = 0
    forks: int = 0

    def __init__(self, ekg: dict):
        _metrics = ekg.get("cardano").get("node").get("metrics")
        #pprint(_metrics)
        self.slot_num = _metrics.get("slotNum").get("int").get("val")
        self.block_num = _metrics.get("blockNum").get("int").get("val")
        # self.forks = _metrics.get("forks").get("int").get("val")

    def is_valid(self) -> bool:
        if self.slot_num > 0 and self.block_num > 0: # and self.forks > 0:
            return True
        return False

class BlocklogProducer(threading.Thread):
    q: queue.Queue
    ekg_url: str
    log_dir: str

    def __init__(self, queue, config: ConfigParser):
        super(BlocklogProducer,self).__init__(daemon=True, name="producer")
        self.q = queue
        self.ekg_url = config.get("DEFAULT", "ekg_url", fallback="http://127.0.0.1:12788")
        self.log_dir = config.get("DEFAULT", "node_logs_dir", fallback="/opt/cardano/cnode/logs")

    def run(self):
        last_block_num = 0
        last_fork_height = 0
        last_slot_num = 0
        count = 0
        while True:
            # block_num, fork_height, slot_num = self._call_ekg()
            _ekg = self._call_ekg()
            count += 1

            # If its the first round, just set the last_ values and continue
            if count == 1:
                last_slot_num = _ekg.slot_num
                last_block_num = _ekg.block_num
                #last_fork_height = _ekg.fork_height
                continue

            # blocks and forks should hold the numbers of the blocks/forks that
            # have been reported by ekg.
            blocks, forks = [], []
            _db = _ekg.block_num - last_block_num
            # print(f"_db {_db}")
            if _db and not _db > 5:
                for i in range(1, _db + 1):
                    #print(f"Range {i}")
                    blocks.append(last_block_num + i)

            last_block_num = _ekg.block_num

            # Same thing for forks ...

            # Now, For each id in blocks (and forks), we want to create a
            # Blocklog which is a list of all the relevant entries of the logfile
            # That Blocklog is then pushed into the Queue, for the consumer to process
            for _blocklog in self._blocklogs(blocks):
                print(f"Putting {_blocklog} in Queue.")
                self.q.put(_blocklog)

            time.sleep(1)

    def _blocklogs(self, blocks: list):
        # Read all logfiles into a list of all lines
        loglines = self._read_logfiles()
        def _find_hash_by_num(block_num: str):
            for line in reversed(loglines):
                if block_num in line:
                    # Parse the line into a dict and return the hash
                    line = dict(json.loads(line))
                    hash = line.get("data").get("block")
                    print(f"Found {hash}")
                    return hash

        def _find_lines_by_hash(hash):
            lines = []
            for line in loglines:
                if hash in line:
                    lines.append(line)
            # Debug output in file
            filepath = Path(BLOCKLOGSDIR).joinpath(f"{hash[0:6]}.blocklog")
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with filepath.open("w", encoding="utf-8") as f:
                f.writelines(lines)
            return lines

        for block in blocks:
            print(f"Find blocklogs for {block}")
            hash = _find_hash_by_num(str(block))
            lines = _find_lines_by_hash(hash)
            yield Blocklog(lines)

    def _read_logfiles(self) -> list:
        # import pudb; pu.db
        from timeit import default_timer as timer
        start = timer()
        logfiles = list(Path(self.log_dir).glob("node-*"))
        logfiles.sort()
        # pprint(logfiles)
        log_lines = []
        for logfile in logfiles[-3:]:
            with logfile.open() as f:
                log_lines.extend(f.readlines())
        end = timer()
        res = end - start # time it took to run
        return log_lines

    def _call_ekg(self) -> EKGResponse:
        """Calls the EKG Port for as long as needed and returns a response if
        there is one. It is not inspecting the block data itself, meaning it will
        just return a tuple of the block_num, the forks and slit_num."""
        while True:
            try:
                # sys.stdout.write(f"Requesting ekg on {self.ekg_url} \n")
                req = Request(
                    url=self.ekg_url,
                    headers={"Accept": "application/json"},
                )
                response = urlopen(req)
                if response.status == 200:
                    # pprint(json.loads(response.read()))
                    ekg_response = EKGResponse(json.loads(response.read()))
                    if ekg_response.is_valid():
                        #pprint(ekg_response)
                        return ekg_response
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
    q: queue.Queue
    def __init__(self, queue):
        super(BlocklogConsumer,self).__init__(daemon=True)
        print("BlocklogConsumer::__init__")
        self.name = "consumer"
        self.q = queue

    def run(self):
        while True:
            print("consumer run")
            obj = self.q.get()
            print(f"Fetchin {obj} : {self.q.qsize()} items left ")
            # time.sleep(2)
            self.q.task_done()

class App:
    _q: queue.Queue
    config: ConfigParser

    def __init__(self, config:str) -> None:
        self.config = ConfigParser()
        self.config.read(config)
        self.q = queue.Queue(maxsize=10)

    def run(self):
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
