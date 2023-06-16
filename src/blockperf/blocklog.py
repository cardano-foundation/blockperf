from dataclasses import dataclass, field, InitVar
from pathlib import Path
import json
from enum import Enum
from datetime import datetime, timezone
from blockperf import __version__ as blockperf_version
from typing import Union

BLOCKLOGSDIR = "/home/msch/src/cf/blockperf.py/blocklogs"


# Unixtimestamps of starttimes of different networks
# See https://www.epochconverter.com/
network_starttime = {
    "preprod": 1660003200,
    "mainnet": 1591566291,
    "preview": 1655683200,
}


class LogKind(Enum):
    """Possible kinds of loglines."""

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
    deltaq_g: float = field(init=False, default=0.0)
    remote_addr: str = field(init=False, default="")
    remote_port: str = field(init=False, default="")
    local_addr: str = field(init=False, default="")
    local_port: str = field(init=False, default="")
    delay: float = field(init=False, default=0.0)
    size: int = field(init=False, default=0.0)
    newtip: str = field(init=False, default="")
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
        # self._logline = logline

        # Unfortunatly datetime.datetime.fromisoformat() can not actually handle
        # all ISO 8601 strings. At least not in versions below 3.11 ... :(
        self.at = datetime.strptime(logline.get("at"), "%Y-%m-%dT%H:%M:%S.%f%z")

        self.kind = self._fetch_kind(logline.get("data").get("kind"))

        if self.kind == LogKind.TRACE_DOWNLOADED_HEADER.name:
            self.block_hash = logline.get("data").get("block")
            self.block_num = logline.get("data").get("blockNo")
            self.slot_num = logline.get("data").get("slot", 0)
            self.remote_addr = logline.get("data").get("peer").get("remote").get("addr")
            self.remote_port = logline.get("data").get("peer").get("remote").get("port")
        elif self.kind == LogKind.SEND_FETCH_REQUEST.name:
            self.block_hash = logline.get("data").get("head")
            self.deltaq_g = logline.get("data").get("deltaq").get("G")
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
        # print(self._logline)
        if self.kind in (
            LogKind.TRACE_DOWNLOADED_HEADER.name,
            LogKind.SEND_FETCH_REQUEST.name,
        ):
            return f"BlocklogLine(slot_num={self.slot_num}, kind={self.kind}, at={self.at}, hash={self.block_hash[0:6]}, peer={self.remote_addr}:{self.remote_port})"
        elif self.kind == LogKind.COMPLETED_BLOCK_FETCH.name:
            return f"BlocklogLine(slot_num={self.slot_num}, kind={self.kind}, at={self.at}, size={self.size}, peer={self.remote_addr}:{self.remote_port})"
        else:
            return f"BlocklogLine(slot_num={self.slot_num}, kind={self.kind}, at={self.at})"

    # def __eq__(self, other):

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


    Calculating slot_time:
    To calculate the slottime we must know the networks starttime. From there
    add the number of slots plus their slot lenght. For simpliciy, we currently
    assume that the slot time is 1 second. If the network has a different slot
    lenght, this must be taken into account! So if the slot_length is 1
    then we can just add the number of slots to the unixtimestamp of the network
    starttime (see `network_starttime` above).
    Example:slot_time of slot 24494589 in preprod is:
            slot_time = 24494589 + 1660003200

    """

    blocklog_lines: InitVar[BlocklogLine]
    _lines: list = field(init=False, default_factory=list)
    first_trace_header: BlocklogLine = field(init=False, default=None)
    first_completed_block: BlocklogLine = field(init=False, default=None)
    fetch_request_completed_block: BlocklogLine = field(init=False, default=None)
    first_add_to_chain: BlocklogLine = field(init=False, default=None)
    first_switch_to_fork: BlocklogLine = field(init=False, default=None)
    is_forkswitch: bool = field(init=False, default=False)
    is_addtochain: bool = field(init=False, default=False)

    def __post_init__(self, blocklog_lines):
        # Ensure lines are ordered by 'at'
        blocklog_lines.sort(key=lambda x: x.at)
        self._lines = blocklog_lines  # TODO: Remove !?
        _trace_headers, _fetch_requests, _completed_blocks, _addstocurrentchain = (
            [],
            [],
            [],
            [],
        )
        line: BlocklogLine
        for line in blocklog_lines:
            if line.kind == LogKind.TRACE_DOWNLOADED_HEADER.name:
                _trace_headers.append(line)
            elif line.kind == LogKind.SEND_FETCH_REQUEST.name:
                _fetch_requests.append(line)
            elif line.kind == LogKind.COMPLETED_BLOCK_FETCH.name:
                _completed_blocks.append(line)
            elif line.kind == LogKind.ADDED_CURRENT_CHAIN.name:
                self.is_addtochain = True
                _addstocurrentchain.append(line)
            elif line.kind == LogKind.SWITCHED_TO_FORK.name:
                self.is_forkswitch = True
                self.first_switch_to_fork = line

        self.first_trace_header = _trace_headers[0] if _trace_headers else None
        self.first_completed_block = _completed_blocks[0] if _completed_blocks else None

        # Some assumptions
        # It should never happen that AddedToChain and SwitchedToFork are present both True or both false
        # if self.is_addtochain or self.is_forkswitch:
        #    msg = f"Blocklog for {self.block_hash_short} has AddedToCurrentChain and SwitchedToAFork!"
        #    print(msg)
        # if not self.is_addtochain and not self.is_forkswitch:
        #    msg = f"Blocklog for {self.block_hash_short} has neither AddedToCurrentChain or SwitchedToAFork!"
        #    print(msg)

        self.first_add_to_chain = (
            _addstocurrentchain[0] if _addstocurrentchain else None
        )

        # Find the FetchRequest for the first CompletedBlock by comparing remote_addr and _port
        _fetch_request = list(
            filter(
                lambda x: x.remote_addr == self.first_completed_block.remote_addr
                and x.remote_port == self.first_completed_block.remote_port,
                _fetch_requests,
            )
        )
        assert _fetch_request, f"No FetchRequest found for {self.first_completed_block}"
        self.fetch_request_completed_block = _fetch_request.pop()

        # Find the TraceHeader for previously found FetchRequest (the one for the CompletedBlock)
        # _trace_header = list(
        #    filter(
        #        lambda x: x.remote_addr == self.fetch_request_completed_block.remote_addr
        #        and x.remote_port == self.fetch_request_completed_block.remote_port,
        #        _trace_headers
        #    )
        # )
        # assert _trace_header, f"No TraceHeader found for {self.fetch_request_completed_block}"
        # trace_header_completed_block = _trace_header.pop()

    def __str__(self) -> str:
        len_lines = len(self._lines)
        # len_headers = len(_trace_headers)
        # len_fetch_requests = len(_fetch_requests)
        # len_completed_blocks = len(_completed_blocks)
        # return f"Blocklog(lines={len_lines}, headers_received={len_headers}, fetch_requests={len_fetch_requests}, completed_blocks={len_completed_blocks})"
        return f"Blocklog(hash={self.block_hash_short}, lines={len_lines}, remote={self.block_remote_addr}:{self.block_remote_port}, header_delta={self.header_delta})"

    @property
    def header_remote_addr(self) -> str:
        if not self.first_trace_header:
            return ""
        return self.first_trace_header.remote_addr

    @property
    def header_remote_port(self) -> str:
        if not self.first_trace_header:
            return ""
        return self.first_trace_header.remote_port

    @property
    def header_delta(self) -> Union[datetime, int]:
        if not self.first_trace_header or not self.slot_time:
            return 0
        return self.first_trace_header.at - self.slot_time

    @property
    def block_num(self) -> int:
        if not self.first_trace_header:
            return 0
        return self.first_trace_header.block_num

    @property
    def block_hash(self) -> str:
        if not self.first_trace_header:
            return ""
        return self.first_trace_header.block_hash

    @property
    def block_hash_short(self) -> str:
        if not self.block_hash:
            return ""
        return self.block_hash[0:10]

    @property
    def slot_num(self) -> int:
        if not self.first_trace_header:
            return 0
        return self.first_trace_header.slot_num

    @property
    def slot_time(self) -> datetime:
        _network_start = network_starttime.get("preview")
        # print(f"_network_start {_network_start} self.slot_num {self.slot_num}")
        _slot_time = _network_start + self.slot_num
        # print(f"_slot_time {_slot_time}  # unixtimestamp")
        slot_time = datetime.fromtimestamp(_slot_time, tz=timezone.utc)
        # print(f"slot_time {slot_time} # real datetime ")
        return slot_time

    @property
    def block_size(self) -> int:
        if not self.first_completed_block:
            return 0
        return self.first_completed_block.size

    @property
    def block_delay(self) -> int:
        if not self.first_completed_block:
            return 0
        return self.first_completed_block.delay

    @property
    def block_request_delta(self) -> datetime:
        if not self.fetch_request_completed_block:
            return 0
        return self.fetch_request_completed_block.at - self.first_trace_header.at

    @property
    def block_response_delta(self) -> datetime:
        if not self.fetch_request_completed_block:
            return 0
        return self.first_completed_block.at - self.fetch_request_completed_block.at

    @property
    def block_adopt(self):
        if self.first_add_to_chain:
            return self.first_add_to_chain.at
        elif self.first_switch_to_fork:
            self.first_switch_to_fork.at
        else:
            return 0

    @property
    def block_adopt_delta(self) -> Union[datetime, int]:
        if self.first_add_to_chain:
            return self.first_add_to_chain.at - self.first_completed_block.at
        elif self.first_switch_to_fork:
            self.first_switch_to_fork.at - self.first_completed_block.at
        else:
            return 0

    @property
    def block_g(self) -> float:
        if not self.fetch_request_completed_block:
            return 0
        return self.fetch_request_completed_block.deltaq_g

    @property
    def block_remote_addr(self) -> str:
        if not self.first_completed_block:
            return ""
        return self.first_completed_block.remote_addr

    @property
    def block_remote_port(self) -> str:
        if not self.first_completed_block:
            return ""
        return self.first_completed_block.remote_port

    def block_local_address(self) -> str:
        if not self.first_completed_block:
            return ""
        return self.first_completed_block.local_addr

    def block_local_port(self) -> str:
        if not self.first_completed_block:
            return ""
        return self.first_completed_block.local_port

    def __to_message(self) -> str:
        """Obsolete !!
        first_trace_header

        * headerRemoteAddr  fill in from peer that first send TraceHeader
        * headerRemotePort  fill in from peer that first send TraceHeader
        * headerDelta       Is the time from the slot_time of this block
                            until the node received the first header
                            FirstTraceHeader.at - slot_time
                            We want to know the delta between when the header could
                            be available (beginning of the slot)  until its actually
                            available to this node (trace header received)

        * blockReqDelta     Find the FetchRequest that belongs to first CompletedBlock
                            FetchRequest.at - first TraceHeader.at
                            We want to know how long it took the node from first
                            seeing the header until it requested that header

        * blockRspDelta     Find the FetchRequest that belongs to first CompletedBlock
                            CompletedBlock at - FetchRequest at
                            We want to know how long it took the other node to
                            complete the send of the block after requesting it

        * blockAdoptDelta   We want to know how long it took the node to successfully
                            adopt a block after it has completed receiving it
                            first AddToCurrentChain.at - first CompletedBlock.at

        * blockRemoteAddress  # fill in from peer that first resulted in CompletedBlock
        * blockRemotePort     # fill in from peer that first resulted in CompletedBlock
        * blockLocalAddress   # Taken from blockperf config
        * blockLocalPort      # Taken from blockperf config
        * blockG              # Find FetchRequest for first CompletedBlock (remote addr/port match)
                              # Take deltaq.G from that FetchRequest
        """
        print()
        message = {
            "magic": "XXX",
            "bpVersion": blockperf_version,
            "blockNo": self.block_num,
            "slotNo": self.slot_num,
            "blockHash": self.block_hash,
            "blockSize": self.size,
            "headerRemoteAddr": self.header_remote_addr,
            "headerRemotePort": self.header_remote_port,
            "headerDelta": self.header_delta,
            "blockReqDelta": self.block_request_delta,
            "blockRspDelta": self.block_response_delta,
            "blockAdoptDelta": self.block_adopt_delta,
            "blockRemoteAddress": self.block_remote_addr,
            "blockRemotePort": self.block_remote_port,
            "blockLocalAddress": "",  # Taken from blockperf config
            "blockLocalPort": "",  # Taken from blockperf config
            "blockG": self.block_g,
        }

        # from pprint import pprint
        # pprint(message)

        return json.dumps(message, default=str)

    @classmethod
    def read_all_logfiles(cls, log_dir: str) -> list:
        """Reads all logfiles from"""
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
        res = end - start  # time it took to run
        return log_lines

    @classmethod
    def blocklogs_from_block_nums(
        cls: "Blocklog", block_nums: list, log_dir: str
    ) -> None:
        """Receives a list of block_num's and returns a list of Blocklogs for given block_nums"""
        # Read all logfiles into a giant list of lines
        loglines = Blocklog.read_all_logfiles(log_dir)

        def _find_hash_by_num(block_num: str) -> str:
            for line in reversed(loglines):
                # Find line that is a TraceHeader and has given block_num in it to determine block_hash
                if (
                    block_num in line
                    and "ChainSyncClientEvent.TraceDownloadedHeader" in line
                ):
                    line = dict(json.loads(line))
                    hash = line.get("data").get("block")
                    # print(f"Found {hash}")
                    return hash

        def _has_kind(line):
            pass

        def _find_lines_by_hash(hash: str) -> list:
            lines = []
            # lines = list(filter(lambda x: hash in x, loglines))
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
            # Find the hash for given block_num, by searching for ChainSyncClientEvent.TraceDownloadedHeader event
            hash = _find_hash_by_num(str(block_num))
            # Find all lines that have that hash
            lines = [
                BlocklogLine(json.loads(line)) for line in _find_lines_by_hash(hash)
            ]
            blocklogs.append(Blocklog(lines))
        return blocklogs
