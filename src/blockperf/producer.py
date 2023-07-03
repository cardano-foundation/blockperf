import queue
import json
import threading
from dataclasses import InitVar, dataclass, field
from pathlib import Path
import time
import logging
import sys
from urllib.error import URLError
from urllib.request import Request, urlopen

from blockperf import logger_name
from blockperf.config import AppConfig
from blockperf.errors import EkgError
#from blockperf.blocklog import Blocklog, BlocklogLine
from blockperf.tracing import BlockTrace, TraceEvent, TraceEventKind

logging.basicConfig(level=logging.DEBUG, format="(%(threadName)-9s) %(message)s")
logger = logging.getLogger(logger_name)

class Producer(threading.Thread):
    q: queue.Queue
    app_config: AppConfig

    def __init__(self, queue, app_config: AppConfig):
        super(Producer, self).__init__(daemon=True, name=self.__class__.__name__)
        self.q = queue
        self.app_config = app_config
        #logger.debug(f"{self.__class__.__name__} __init__")

    def read_logfiles(self) -> list:
        """Reads the last three logfiles from the logdir."""
        from timeit import default_timer as timer

        start = timer()
        logfiles = list(self.app_config.node_logs_dir.glob("node-*"))
        logfiles.sort()
        loglines = []
        for logfile in logfiles[-1:]:
            print(logfile.name)
            with logfile.open() as f:
                loglines.extend(f.readlines())
        end = timer()
        res = end - start  # time it took to run
        print(f"Read in {res}")
        return loglines


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


class EkgProducer(Producer):
    """The EKG Producer is scraping the ekg port of the node and tries to determine
    new blocks by comparing the current block height with the previous one.
    """

    last_block_num: int = 0
    last_fork_height: int = 0
    last_slot_num: int = 0

    # def __init__(self, queue, app_config: AppConfig):
    #    super(EkgProducer, self).__init__(daemon=True, name="producer")
    #    self.q = queue
    #    self.app_config = app_config
    #    logger.debug("Producer initialized")
    #
    def run(self):
        """Runs the Producer thread. Will get called from Thread base once ready.
        If run() finishes the thread will finish.
        """
        logger.debug(
            f"Running {self.__class__.__name__} on {self.app_config.ekg_url} "
        )
        while True:
            EKG_RETRY_INTERVAL = 1  # configurable?
            try:
                self._run()
            except EkgError as e:
                msg = f"EkgError {e.reason}"
                logger.error(e)
            except URLError as e:
                msg = f"URLError {e.reason}; {self.app_config.ekg_url}"
                logger.error(msg)
            finally:
                time.sleep(EKG_RETRY_INTERVAL)

    def is_first_round(self):
        """
        The idea is noticing a diff between the currently announced
        block_num/slot_num from ekg and the one that was seen before.
        So in order to detect that difference there needs to be a preceding
        value. If its the first round, there is none: So store and go to next.
        """
        return bool(not self.last_block_num and not self.last_slot_num)

    def _run(self) -> None:
        """Implements the lifecycle of this thread.
        Looks for nee block announcments from the ekg port.
        If there are, tries to find that blocks hash and all the relevant trace
        data from the node log files. Once all that is collected, it creates
        a Blocklog which then calculates and represent a single blocks
        performance as seen from this node. Every new Blocklog is then
        put into the queue for being sent to the mqtt broker.

        """
        ekg_response = self.call_ekg()
        if self.is_first_round():
            self.last_slot_num = ekg_response.slot_num
            self.last_block_num = ekg_response.block_num
            # last_fork_height = fork_height
            return

        # Calculate list of announced block_nums
        block_nums_announced = self.get_announced_block_nums(ekg_response.block_num)
        if not block_nums_announced:
            # Nothing announced, start over
            return
        logger.debug(f"block_nums received from ekg {block_nums_announced}")

        # Create list of Blocklogs for the given block_nums
        blocklogs_found = self.blocklogs_from_block_nums(block_nums_announced)

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

        if not blocklogs_found:
            logger.debug(f"No blocklogs to report found")

        for blocklog in blocklogs_found:
            print()
            self.to_cli_message(blocklog)
            print()
            self.q.put(blocklog)

        self.last_block_num = ekg_response.block_num
        self.last_slot_num = ekg_response.slot_num

        # self.all_blocklogs.update([(b.block_hash, b) for b in blocklogs_to_report])
        # Just wait a second
        time.sleep(1)

    def get_announced_block_nums(self, current_block_num) -> list:
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
            block_nums.append(str(self.last_block_num + num))
        return block_nums

    def call_ekg(self) -> EkgResponse:
        """Calls the EKG Port for as long as needed and returns a response if
        there is one. It is not inspecting the block data itself, meaning it will
        just return a tuple of the block_num, the forks and slit_num."""
        req = Request(
            url=self.app_config.ekg_url, headers={"Accept": "application/json"}
        )
        response = urlopen(req, timeout=3)
        if response.status != 200:
            msg = f"HTTP response received {response}"
            raise EkgError(msg)
        response = response.read()
        response = json.loads(response)
        ekg_response = EkgResponse(response)
        assert ekg_response.slot_num > 0, "EKG did not report a slot_num"
        assert ekg_response.block_num > 0, "EKG did not report a block_num"
        return ekg_response

    def blocklogs_from_block_nums(self, block_nums: list):
        # Read all logfiles into a giant list of lines
        loglines = self.read_logfiles()

        def find_hash_by_block_num(block_num: str) -> str:
            for line in reversed(loglines):
                # Find line that is a TraceHeader and has given block_num in it to determine block_hash
                if (
                    block_num in line
                    and "ChainSyncClientEvent.TraceDownloadedHeader" in line
                ):
                    line = dict(json.loads(line))
                    hash = line.get("data").get("block")
                    return hash

        def _find_lines_by_hash(hash: str) -> list:
            lines = []
            # lines = list(filter(lambda x: hash in x, loglines))
            for line in loglines:
                if hash in line:
                    lines.append(line)
            if self.app_config.enable_tracelogs:
                self.write_debug_tracelogs(hash, lines)
            return lines

        blocktraces = []  # The list i want to populated with Blocktraces
        for block_num in block_nums:
            hash = find_hash_by_block_num(block_num)
            lines = [BlocklogLine(line) for line in _find_lines_by_hash(hash)]
            blocktraces.append(Blocklog(lines))
        return blocktraces

    def write_debug_tracelogs(self, hash, lines):
        if tracelogs_dir := self.app_config.tracelogs_dir:
            tracelogs_dir = Path(tracelogs_dir)
        else:
            tracelogs_dir = Path(self.app_config.node_logs_dir).joinpath("blocklogz")

        print(tracelogs_dir)
        if not tracelogs_dir.exists():
            print("Does not ")
            tracelogs_dir.mkdir()

        filepath = tracelogs_dir.joinpath(f"{hash[0:6]}.blocklog")
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with filepath.open("w", encoding="utf-8") as f:
            f.writelines(lines)


class LogfilesProducer(Producer):
    """The LogfilesProducer is only scraping the nodes logfiles and does not rely on ekg.

    As the EkgProducer it runs in a loop and regularly reads in the logfiles.
    For all these logfiles, it searchs the individual hashes it finds.
    """
    trace_events = dict()  # The list of blocks seen from the logfile

    def __init__(self, queue, app_config: AppConfig):
        super(LogfilesProducer, self).__init__(queue=queue, app_config = app_config)

    def run(self):
        """Runs the Producer thread. Will get called from Thread base once ready.
        If run() finishes the thread will finish.
        """
        while True:
            try:
                self._run()
            except Exception as e:
                logger.exception(e)
            finally:
                print("Thread Sleeping ... ")
                time.sleep(3)

    def _run(self):
        logger.debug(
            f"{self.__class__.__name__}::_run()"
        )
        finished_block_kinds = (
            TraceEventKind.ADDED_TO_CURRENT_CHAIN,
            TraceEventKind.SWITCHED_TO_A_FORK,
        )
        for event in self.node_log_events():
            logger.debug(event)
            assert event.block_hash, f"Found a trace that has no hash {event}"
            if not event.block_hash in self.trace_events:
                self.trace_events[event.block_hash] = list()
            self.trace_events[event.block_hash].append(event)

            if event.kind in finished_block_kinds:
                _h = event.block_hash[0:9]
                logger.debug(f"Found {len(self.trace_events[event.block_hash])} events for {_h}")
                logger.debug(f"Blocks tracked {len(self.trace_events.keys())}")
                self.send_blocktrace(event.block_hash)

    def node_log_events(self):
        """Generator that constantly reads the log file and yields new lines from that.
        It will only yield lines of certain event kinds, because we are only
        interested in those for now.
        """
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

        # Constantly read the new lines from the logfile and yield each
        # fp is moved to end of file first, to only "see" new lines written now
        with open(node_log_path, "r") as node_log:
            node_log.seek(0,2)
            while True:
                new_line = node_log.readline()
                if not new_line:
                    # wait a moment to avoid incomplete lines bubbling up ...
                    time.sleep(0.1)
                    continue
                event = TraceEvent.from_logline(new_line)
                if event and event.kind in interesting_kinds:
                    yield (event)

    def send_blocktrace(self, block_hash):
        """Sends a blocktrace, for given hash"""
        events = self.trace_events.pop(block_hash)
        bt = BlockTrace(events)
        sys.stdout.write(bt.msg_string())
        self.q.put(bt)
        # self.to_cli_message(bt)
        #print()
        # self.q.put(blocklog)



#
# blocklogs = []
# te = self.trace_events.popitem()
# print(te)
# blocklogs.append(Blocklog(tv))

# _current = blocklogs[-1]
# self.to_cli_message(_current)
# self.q.put(_current)
