from dataclasses import dataclass
import sys
import pathlib
import time
import urllib
import json
import threading
import queue

import random
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='(%(threadName)-9s) %(message)s'
)

LOGDIR="/opt/cardano/cnode/logs/"

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
        self.slot_num = _metrics.get("slotNum").get("int").get("val")
        self.block_num = _metrics.get("blockNum").get("int").get("val")
        self.forks = _metrics.get("forks").get("int").get("val")

    def is_valid(self) -> bool:
        if self.slot_num > 0 and self.block_num > 0 and self.forks > 0:
            return True
        return False

class BlocklogProducer(threading.Thread):
    q: queue.Queue

    def __init__(self, queue):
        super(BlocklogProducer,self).__init__(daemon=True)
        print("BlocklogProducer::__init__")
        self.name = "producer"
        self.q = queue

    def run(self):
        last_block_height = 0
        last_fork_height = 0
        last_slot_num = 0
        count = 0
        while True:
            # block_height, fork_height, slot_num = self._call_ekg()
            _ekg = self._call_ekg()
            count += 1

            # If its the first round, just set the last_ values and continue
            if count == 1:
                last_slot_num = _ekg.slot_num
                last_block_height = _ekg.block_num
                last_fork_height = _ekg.fork_height
                continue

            # blocks and forks should hold the numbers of the blocks/forks that
            # have been reported by ekg.
            blocks, forks = [], []
            _db = _ekg.block_height - last_block_height
            print(f"_db {_db}")
            if _db and not _db > 5:
                for i in range(1, _db + 1):
                    print(f"Range {i}")
                    blocks.append(last_block_height + i)

            last_block_height = _ekg.block_height

            # Same thing for forks ...

            # Now, For each id in blocks (and forks), we want to create a
            # Blocklog which is a list of all the relevant entries of the logfile
            # That Blocklog is then pushed into the Queue, for the consumer to process
            for _blocklog in self._blocklogs(blocks):
                print(f"Putting {_blocklog} in Queue.")
                self.q.put(_blocklog)

            time.sleep(1)


    def _blocklogs(self, blocks: list):
        # Read Logfile
        loglines = self._read_logfiles()

        def _find_hash_by_height(height):
            for line in reversed(loglines):
                print(line)
                if height in line:
                    # Parse the line into a dict and return the hash
                    line = dict(json.loads(line))
                    hash = line.get("data").get("block")
                    return hash

        def _find_lines_by_hash(hash):
            lines = []
            for line in loglines:
                if hash in line:
                    lines.append(line)
            return lines

        for block in blocks:
            hash = _find_hash_by_height(block)
            lines = _find_lines_by_hash(hash)
            yield Blocklog()



    def _read_logfiles() -> list:
        from timeit import default_timer as timer
        start = timer()
        logfiles = list(pathlib.Path(LOGDIR).glob("node-*"))
        logfiles.sort()
        log_lines = []
        for logfile in logfiles[-3:]:
            with logfile.open() as f:
                # log_lines.extend(f.readlines ) anyone ??
                for l in f:
                    print(l)
                    log_lines.append(l)
            #with open(f, "rb") as f:
            #    map_file = mmap.mmap(f.fileno(), 0, prot=mmap.PROT_READ)
            #    log_lines += map_file.read()
            #    print(type(log_lines))
            #    #for line in iter(map_file.readline, b""):
            #        #print(line)
            #    #    time.sleep(1)
        #pprint(log_lines)
        end = timer()
        res = end - start # time it took to run
        print(f"Took {res}")
        return log_lines


    def _call_ekg(self) -> EKGResponse:
        """Calls the EKG Port for as long as needed and returns a response if
        there is one. It is not inspecting the block data itself, meaning it will
        just return a tuple of the block_num, the forks and slit_num."""
        _ekg_url = "http://127.0.0.1:12788/"
        while True:
            try:
                sys.stdout.write(f"Requesting ekg on {_ekg_url}")
                req = urllib.request.Request(
                    url=_ekg_url,
                    headers={"Accept": "application/json"},
                )
                response = urllib.request.urlopen(req)
                if response.status == 200:
                    ekg_response = EKGResponse(json.loads(response.read()))
                    if ekg_response.is_valid():
                        return ekg_response
                    else:
                        print(f"Invalid EKG Response returned {response}")
                else:
                    print(f"Got {response.status} {response.reason}")
                    time.sleep(2)
            except urllib.error.URLError as _e:
                print(f"URLError {_e.reason}")
                time.sleep(2)
            except ConnectionResetError:
                print(f"ConnectionResetError")
                time.sleep(2)

    def _extract_valus_from_ekg_response(response: dict) -> tuple:
        """Extracts the values from the response dict.
        Throws Exception if something is odd"""



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
    ekg: None
    q: queue.Queue

    def __init__(self) -> None:
        self.q = queue.Queue(maxsize=10)

    def run(self):
        producer = BlocklogProducer(queue=self.q)
        producer.start()
        consumer= BlocklogConsumer(queue=self.q)
        consumer.start()
        print("Created both")
        producer.join()
        print("producer joined")
        consumer.join()

        print("consumer joined")
        #self.q.join()


    def oldrun(self):
        """Runs the app.
        * Creates the Queue
        * creates the Produce
        * creates the consumer
        * manages these
        """
        #_blocklog_gen = self._blocklog_generator()
        _gen = self._blocklog_generator()
        while True:
            print("Outer while")
            blocks, forks = next(_gen)
            # prcoess blocklog and yield control back via send()
            print(f"Returned blocks {blocks} forks {forks}")

    def _enrich_from_logfile(self, blocks: list):
        # Given a list of block ids, search
        with open(STAT_FILE, "r+b") as f:
            map_file = mmap.mmap(f.fileno(), 0, prot=mmap.PROT_READ)
            for line in iter(map_file.readline, b""):
                # whatever
                pass

