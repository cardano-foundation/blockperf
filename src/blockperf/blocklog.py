from dataclasses import dataclass, field, InitVar
from pathlib import Path
import json
from enum import Enum
from datetime import datetime

BLOCKLOGSDIR="/home/msch/src/cf/blockperf.py/blocklogs"





class LogKind(Enum):
    """The Kind of a logline."""
    TRACE_DOWNLOADED_HEADER = "TraceDownloadedHeader"
    SEND_FETCH_REQUEST = "SendFetchRequest"
    COMPLETED_BLOCK_FETCH = "CompletedBlockFetch"
    ADDED_CURRENT_CHAIN = "AddedToCurrentChain"
    SWITCHED_TO_FORK = "SwitchedToAFork"
    UNKNOWN = "Unknown"

@dataclass
class BlocklogLine:
    """
    Note: Many of the attributes are only set for specific kinds of loglines!
    """
    logline: InitVar[dict]
    kind: LogKind = field(init=False, default=LogKind.UNKNOWN)
    at: datetime = field(init=False, default=None)
    block_hash: str = field(init=False, default="")
    block_num: int = field(init=False, default=0)
    slot_num: int = field(init=False, default=0)
    remote_addr: str = field(init=False, default="")
    remote_port: str = field(init=False, default="")
    local_addr: str = field(init=False, default="")
    local_port: str = field(init=False, default="")
    delay: float = field(init=False, default=0.0)
    size: int = field(init=False, default=0.0)
    newtip: str  = field(init=False, default="")
    chain_length_delta: int = field(init=False, default=0)
    env: str = field(init=False, default="")

    def __post_init__(self, logline: dict):
        """Initilize all class attributes by parsing the given logline.
        Assuming that at and data.kind fields will be there for all line types.
        All others are only dependant upon the lines' kind.

        dict.get() never raises KeyError because default is always set to None.
        However, that also means the defaults from above for the class attributes
        are not reliable ...
        """
        #self._logline = logline

        # Unfortunatly datetime.datetime.fromisoformat() can not actually handle
        # all ISO 8601 strings. At least not in versions below 3.11 ... :(
        self.at = datetime.strptime(logline.get("at"), "%Y-%m-%dT%H:%M:%S.%f%z")

        self.kind = self._fetch_kind(logline.get("data").get("kind"))

        if self.kind == LogKind.TRACE_DOWNLOADED_HEADER.name:
            self.block_hash = logline.get("data").get("block")
            self.block_num = logline.get("data").get("blockNo").get("unBlockNo")
            self.slot_num = logline.get("data").get("slot", 0)
            self.remote_addr = logline.get("data").get("peer").get("remote").get("addr")
            self.remote_port = logline.get("data").get("peer").get("remote").get("port")
        elif self.kind == LogKind.SEND_FETCH_REQUEST.name:
            self.block_hash = logline.get("data").get("head")
            self.remote_addr = logline.get("data").get("peer").get("remote").get("addr")
            self.remote_port = logline.get("data").get("peer").get("remote").get("port")
        elif self.kind == LogKind.COMPLETED_BLOCK_FETCH.name:
            self.env = logline.get("env")
            self.delay = logline.get("data").get("delay")
            self.size = logline.get("data").get("size")
            self.remote_addr = logline.get("data").get("peer").get("remote").get("addr")
            self.remote_port = logline.get("data").get("peer").get("remote").get("port")
            self.local_addr = logline.get("data").get("peer").get("local").get("addr")
            self.local_port = logline.get("data").get("peer").get("local").get("port")

        elif self.kind == LogKind.ADDED_CURRENT_CHAIN.name:
            self.newtip = logline.get("data").get("newtip")
            self.chain_length_delta = logline.get("data").get("chainLengthDelta")
        elif self.kind == LogKind.SWITCHED_TO_FORK.name:
            self.newtip = logline.get("data").get("newtip")
            self.chain_length_delta = logline.get("data").get("chainLengthDelta")
            self.real_fork = logline.get("data").get("realFork")
        elif self.kind == LogKind.UNKNOWN.name:
            pass
        else:
            pass

    def __str__(self):
        #print(self._logline)
        if self.kind in (LogKind.TRACE_DOWNLOADED_HEADER.name , LogKind.SEND_FETCH_REQUEST.name):
            return f"BlocklogLine(kind={self.kind}, at={self.at}, hash={self.block_hash[0:6]}, peer={self.peer_addr}:{self.peer_port})"
        elif self.kind == LogKind.COMPLETED_BLOCK_FETCH.name:
            return f"BlocklogLine(kind={self.kind}, at={self.at}, size={self.size}, peer={self.peer_addr}:{self.peer_port})"
        else:
            return f"BlocklogLine(kind={self.kind}, at={self.at})"

    def _fetch_kind(self, kind: str) -> LogKind:
        """Returns the LogKind attribute of given kind string"""
        for k in LogKind:
            if k.value in kind:
                return k.name
        return LogKind.UNKNOWN

@dataclass
class Blocklog:
    """
    Config setting: MaxConcurrencyDeadline sets how many concurent blocks could be
        evaluated; Currently set to 4 so up to 8 simultanious fetch requests.

    TraceDownloadedHeader  TDH
        * Retrieved from each peer the node recevied a header from
        * Store first X header statistics
        * For each TraceDownloadedHeader, store peer address/port/timing

    SendFetchRequest SFR
        * Find the one that resulted in the CompletedBlockFetch
        * For each TDH received a SFR is sent, but not for all at once, but only for
            according to the config variable for this node.
        * If not responded within a certain amount of time, a new batch is sent out
            But only for say 8 in total
        * Eventually one of these will result in a block received
        * Relevant is only the one SFR that resulted in a CBF

    CompletedBlockFetch  CBF
        * Find SFR for address/port i received block from
        * Also find the number of all the FetchRequests

    AddedToCurrentChain
    SwitchedToAFork

    """
    blocklog_lines: InitVar[BlocklogLine]
    _lines: list = field(init=False, default_factory=list)
    block_hash: str = field(init=False)
    block_num: str = field(init=False)
    slot_num: str = field(init=False)
    trace_headers: list = field(init=False, default_factory=list)
    fetch_requests: list = field(init=False, default_factory=list)
    completed_blocks: list = field(init=False, default_factory=list)
    size: int = field(init=False, default=0.0)
    chain_length_delta: int = field(init=False, default=0)
    is_forkswitch: bool = field(init=False, default=False)
    is_addtochain: bool = field(init=False, default=False)

    def __post_init__(self, blocklog_lines):
        # Ensure lines are ordered by 'at'
        blocklog_lines.sort(key=lambda x: x.at)

        self._lines = blocklog_lines  # TODO: Remove !?

        line: BlocklogLine
        for line in blocklog_lines:
            if line.kind == LogKind.TRACE_DOWNLOADED_HEADER.name:
                self.trace_headers.append(line)
                self.block_hash = line.block_hash
                self.slot_num = line.slot_num
                self.block_num = line.block_num
            elif line.kind == LogKind.SEND_FETCH_REQUEST.name:
                self.fetch_requests.append(line)
            elif line.kind == LogKind.COMPLETED_BLOCK_FETCH.name:
                self.completed_blocks.append(line)
                self.size = line.size
                self.block_hash = line.block_hash
            elif line.kind == LogKind.ADDED_CURRENT_CHAIN.name:
                self.is_addtochain = True
                self.chain_length_delta = line.chain_length_delta
            elif line.kind == LogKind.SWITCHED_TO_FORK.name:
                self.is_forkswitch = True
                self.chain_length_delta = line.chain_length_delta

        # It should never happen that AddedToChain and SwitchedToFork are present
        # within the same Blocklog ... what if it does ?
        assert not self.is_addtochain or not self.is_forkswitch, f"Blocklog for {line.block_hash[0:11]} has AddedToCurrentChain and SwitchedToAFork!"
        # self.sanity_check()

    def __str__(self) -> str:
        return f"Blocklog(lines={len(self._lines)}, headers_received={len(self.trace_headers)}, fetch_requests={len(self.fetch_requests)}, completed_blocks={len(self.completed_blocks)})"

    def sanity_check(self):
        if self.is_addtochain and self.is_forkswitch:
            # this should really not happen... but what if it does?
            print("This Blocklog seems to be both, a forkswtich and addedtochain")

    def to_message(self) -> str:
        """Might as well live outside of this class ... """
        message = dict({
            "magic": "magic",
            "bpVersion" : "$bpVersion" ,
            "blockNo" : "$blockNo" ,
            "slotNo" : "$slotNo" ,
            "blockHash" : "$blockHash",
            "blockSize" : "$blockSize",
            "headerRemoteAddr" : "$headerRemoteAddr",
            "headerRemotePort" : "$headerRemotePort",
            "headerDelta" : "$headerDelta",
            "blockReqDelta" : "$blockReqDelta",
            "blockRspDelta" : "$blockRspDelta",
            "blockAdoptDelta" : "$blockAdoptDelta",
            "blockRemoteAddress": "$blockRemoteAddress",
            "blockRemotePort": "$blockRemotePort",
            "blockLocalAddress" : "$blockLocalAddress",
            "blockLocalPort": "$blockLocalPort",
            "blockG" : "$blockG"
        })
        return json.dumps(message)

    @classmethod
    def read_logfiles(cls, log_dir: str) -> list:
        """Reads all logfiles from """
        from timeit import default_timer as timer
        start = timer()
        logfiles = list(Path(log_dir).glob("node-*"))
        logfiles.sort()
        # pprint(logfiles)
        log_lines = []
        for logfile in logfiles[-3:]:
            with logfile.open() as f:
                log_lines.extend(f.readlines())
        end = timer()
        res = end - start # time it took to run
        return log_lines

    @classmethod
    def blocklogs_from_block_nums(cls: "Blocklog", block_nums: list, log_dir: str) -> None:
        """Receives a list of block_num's and yields a Blocklog Instance for each.
        """
        loglines = Blocklog.read_logfiles(log_dir)
        def _find_hash_by_num(block_num: str) -> str:
            for line in reversed(loglines):
                if block_num in line:
                    # Parse the line into a dict and return the hash
                    line = dict(json.loads(line))
                    hash = line.get("data").get("block")
                    print(f"Found {hash}")
                    return hash

        def _find_lines_by_hash(hash: str) -> list:
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

        blocklogs = []
        for block_num in block_nums:
            print(f"Find blocklogs for {block_num}")
            hash = _find_hash_by_num(str(block_num))
            lines = [BlocklogLine(json.loads(line)) for line in _find_lines_by_hash(hash)]
            blocklogs.append(Blocklog(lines))
        return blocklogs
