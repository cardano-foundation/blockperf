from dataclasses import dataclass, field, InitVar
from pathlib import Path
import json
from enum import Enum
from datetime import datetime

BLOCKLOGSDIR="/home/msch/src/cf/blockperf.py/blocklogs"

def read_logfiles(log_dir: str) -> list:
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

def blocklogs(block_nums: list, log_dir: str) -> None:
    """Receives a list of block_num's and yields a Blocklog Instance for each.
    """
    loglines = read_logfiles(log_dir)
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

    for block_num in block_nums:
        print(f"Find blocklogs for {block_num}")
        hash = _find_hash_by_num(str(block_num))
        lines = [BlocklogLine(json.loads(line)) for line in _find_lines_by_hash(hash)]
        yield Blocklog(lines)

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
    peer_addr: str = field(init=False, default="")
    peer_port: str = field(init=False, default="")
    delay: float = field(init=False, default=0.0)
    newtip: str  = field(init=False, default="")
    chain_length_delta: int = field(init=False, default=0)

    def __post_init__(self, logline: dict):
        # Assuming that at and data.kind are the only fields that are always
        # at the same position, everything else is depending on the kind!
        #self._logline = logline
        self.at = self._fetch_at(logline.get("at"))
        _data = logline.get("data")
        self.kind = self._fetch_kind(_data.get("kind"))
        if self.kind == LogKind.TRACE_DOWNLOADED_HEADER.name:
            self.block_hash = _data.get("block")
            self.block_num = _data.get("blockNo").get("unBlockNo")
            self.slot_num = _data.get("slot", 0)
            self.peer_addr, self.peer_port = self._fetch_peer(_data.get("peer"))
        elif self.kind == LogKind.SEND_FETCH_REQUEST.name:
            self.block_hash = _data.get("head")
            self.peer_addr, self.peer_port = self._fetch_peer(_data.get("peer"))
        elif self.kind == LogKind.COMPLETED_BLOCK_FETCH.name:
            self.peer_addr, self.peer_port = self._fetch_peer(_data.get("peer"))
            self.delay = _data.get("delay")
        elif self.kind == LogKind.ADDED_CURRENT_CHAIN.name:
            self.newtip = _data.get("newtip")
            self.chain_length_delta = _data.get("chainLengthDelta")
        elif self.kind == LogKind.SWITCHED_TO_FORK.name:
            pass
        elif self.kind == LogKind.UNKNOWN.name:
            pass
        else:
            pass

    def __str__(self):
        #print(self._logline)
        if self.kind in (LogKind.TRACE_DOWNLOADED_HEADER.name , LogKind.SEND_FETCH_REQUEST.name):
            return f"BlocklogLine(kind={self.kind}, at={self.at}, hash={self.block_hash[0:6]}, peer={self.peer_addr}:{self.peer_port})"
        elif self.kind == LogKind.COMPLETED_BLOCK_FETCH.name:
            return f"BlocklogLine(kind={self.kind}, at={self.at}, peer={self.peer_addr}:{self.peer_port})"
        else:
            return f"BlocklogLine(kind={self.kind}, at={self.at})"

    def _fetch_at(self, at: str) -> datetime:
        """ Return datetime object from ISO8601 String

        Unfortunatly datetime.datetime.fromisoformat() can not actually handle
        all ISO 8601 strings. At least not in versions below 3.11 ...

        the dateutil library could be an option or as i did for now with strptime()

        https://dateutil.readthedocs.io/en/stable/parser.html#dateutil.parser.isoparse
        """
        # example: 2023-03-28T08:25:10.48Z
        return datetime.strptime(at, "%Y-%m-%dT%H:%M:%S.%f%z")

    def _fetch_kind(self, kind: str) -> LogKind:
        for k in LogKind:
            if k.value in kind:
                return k.name
        return LogKind.UNKNOWN

    def _fetch_peer(self, peer: str) -> tuple:
        _addr = peer.get("remote").get("addr")
        _port = peer.get("remote").get("port")
        return (_addr, _port)

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

    def __post_init__(self, blocklog_lines):
        from pprint import pprint
        # TODO: More sophisticated processing ...
        # Ensure lines are ordered by 'at'
        blocklog_lines.sort(key=lambda x: x.at)
        self._lines = blocklog_lines

        #line: BlocklogLine = blocklog_lines[0]
        #self.block_hash = line.block_hash
        #self.block_num = line.block_num
        #self.slot_num = line.slot_num

        for line in blocklog_lines:
            if line.kind == LogKind.TRACE_DOWNLOADED_HEADER.name:
                self.trace_headers.append(line)
            elif line.kind == LogKind.SEND_FETCH_REQUEST.name:
                self.fetch_requests.append(line)
            elif line.kind == LogKind.COMPLETED_BLOCK_FETCH.name:
                self.completed_blocks.append(line)

    def __str__(self) -> str:
        return f"Blocklog(lines={len(self._lines)}, headers_received={len(self.trace_headers)}, fetch_requests={len(self.fetch_requests)}, completed_blocks={len(self.completed_blocks)})"

    def to_message(self) -> str:
        pass

    def is_forkswitch(self) -> bool:
        pass


    def is_addtochain(self) -> bool:
        pass
