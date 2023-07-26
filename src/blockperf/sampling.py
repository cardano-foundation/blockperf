import json
import sys
from enum import Enum
from typing import Union
from datetime import datetime, timezone, timedelta
import logging

from blockperf import logger_name
from blockperf import __version__ as blockperf_version
from blockperf.config import AppConfig

# logging.basicConfig(level=logging.DEBUG, format="(%(threadName)-9s) %(message)s")
LOG = logging.getLogger(logger_name)


# Unixtimestamps of the starttimes of different networks. Needed to determine
# when a given slot is meant to exist in time.
network_starttime = {
    "preprod": 1660003200,
    "mainnet": 1591566291,
    "preview": 1655683200,
}


class LogEventKind(Enum):
    """All events from the log file are of a specific kind."""

    TRACE_DOWNLOADED_HEADER = "ChainSyncClientEvent.TraceDownloadedHeader"
    SEND_FETCH_REQUEST = "SendFetchRequest"
    COMPLETED_BLOCK_FETCH = "CompletedBlockFetch"
    SWITCHED_TO_A_FORK = "TraceAddBlockEvent.SwitchedToAFork"
    ADDED_TO_CURRENT_CHAIN = "TraceAddBlockEvent.AddedToCurrentChain"
    UNKNOWN = "Unknown"


class LogEvent:
    """A LogEvent represents a single line in the nodes log file.

    TraceDownloadedHeader
    A (new) Header was announced (downloaded) to the node. Emitted each time a
    header is received from any given peer. We are mostly interested in the
    time the first header of any given Block was received (announced).

    SendFetchRequest
    The node requested a peer to send a specific Block. It may send multiple
    request to different peers.

    CompletedBlockFetch
    A Block has finished to be downloaded. For each CompletedBlockFetch
    there is a previous SendFetchRequest. This is important to be able
    to determine the time it took from asking for a block until actually
    receiving it.

    AddedToCurrentChain
    The node has added a block to its chain.

    SwitchedToAFork
    The node switched to a (new) Fork.
    """

    at: datetime
    data: dict
    env: str
    ns: str

    def __init__(self, event_data: dict) -> None:
        """Create a LogEvent with `from_logline` method by passing in the json string
        as written to the nodes log."""
        self.at = datetime.strptime(
            event_data.get("at", None), "%Y-%m-%dT%H:%M:%S.%f%z"
        )
        self.data = event_data.get("data", {})
        if not self.data:
            LOG.error(f"{self} has not data")
        self.env = event_data.get("env", "")
        # ns seems to always be a single entry list ...
        self.ns = event_data.get("ns", [""])[0]

    def __str__(self):
        trace_kind = self.kind.value
        if "." in trace_kind:
            trace_kind = trace_kind.split(".")[1]
        return f"{trace_kind} {self.block_hash_short} {self.at.strftime('%H:%M:%S.%f')[:-3]}>"

    @classmethod
    def from_logline(cls, logline: str):
        """Takes a single line from the logs and creates a"""
        try:
            _json_data = json.loads(logline)
            return cls(_json_data)
        except json.decoder.JSONDecodeError as e:
            LOG.error(f"Could not decode json from {logline} ")
            return None

    @property
    def block_hash(self) -> str:
        block_hash = ""
        if self.kind == LogEventKind.SEND_FETCH_REQUEST:
            block_hash = self.data.get("head", "")
        elif self.kind in (
            LogEventKind.COMPLETED_BLOCK_FETCH,
            LogEventKind.TRACE_DOWNLOADED_HEADER,
        ):
            block_hash = self.data.get("block", "")
        elif self.kind in (
            LogEventKind.ADDED_TO_CURRENT_CHAIN,
            LogEventKind.SWITCHED_TO_A_FORK,
        ):
            newtip = self.data.get("newtip", "")
            block_hash = newtip.split("@")[0]

        if not block_hash:
            LOG.error(f"Could not determine block_hash for {self}")

        return str(block_hash)

    @property
    def block_hash_short(self) -> str:
        return self.block_hash[0:10]

    @property
    def atstr(self) -> str:
        """Returns at as formatted string"""
        return self.at.strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]

    @property
    def kind(self) -> LogEventKind:
        if not hasattr(self, "_kind"):
            _value = self.data.get("kind")
            for kind in LogEventKind:
                if _value == kind.value:
                    self._kind = LogEventKind(_value)
                    break
            else:
                self._kind = LogEventKind(LogEventKind.UNKNOWN)
        return self._kind

    @property
    def delay(self) -> float:
        _delay = self.data.get("delay", 0.0)
        if not _delay:
            LOG.error(f"{self} has no delay {self.data}")
        return _delay

    @property
    def size(self) -> int:
        _size = self.data.get("size", 0)
        if not _size:
            LOG.error(f"{self} has no size {self.data}")
        return _size

    @property
    def local_addr(self) -> str:
        _local_addr = self.data.get("peer", {}).get("local", {}).get("addr", "")
        if not _local_addr:
            LOG.error(f"{self} has no local_addr {self.data}")
        return _local_addr

    @property
    def local_port(self) -> str:
        _local_port = self.data.get("peer", {}).get("local", {}).get("port", "")
        if not _local_port:
            LOG.error(f"{self} has no local_port {self.data}")
        return _local_port

    @property
    def remote_addr(self) -> str:
        _remote_addr = self.data.get("peer", {}).get("remote", {}).get("addr", "")
        if not _remote_addr:
            LOG.error(f"{self} has no remote_addr {self.data}")
        return _remote_addr

    @property
    def remote_port(self) -> str:
        _remote_port = self.data.get("peer", {}).get("remote", {}).get("port", "")
        if not _remote_port:
            LOG.error(f"{self} has no remote_port {self.data}")
        return _remote_port

    @property
    def slot_num(self) -> int:
        _slot_num = self.data.get("slot", 0)
        if not _slot_num:
            LOG.error(f"{self} has no slot_num {_slot_num} {self.data}")
        return _slot_num

    @property
    def block_num(self) -> int:
        """
        In prior version blockNo was a dict, that held and unBlockNo key
        Since 8.x its only data.blockNo
        """
        _blockNo = self.data.get("blockNo", 0)
        if type(_blockNo) is dict:
            # If its a dict, it must have unBlockNo key
            assert (
                "unBlockNo" in _blockNo
            ), "blockNo is a dict but does not have unBlockNo"
            _blockNo = _blockNo.get("unBlockNo", 0)
        if not _blockNo:
            LOG.error(f"{self} has no block_num")
        return _blockNo

    @property
    def deltaq_g(self) -> str:
        _deltaq_g = self.data.get("deltaq", {}).get("G", "")
        if not _deltaq_g:
            LOG.error(f"{self} has no deltaq_g {self.data}")
        return _deltaq_g

    @property
    def chain_length_delta(self) -> int:
        _chain_length_delta = self.data.get("chainLengthDelta", 0)
        if not _chain_length_delta:
            LOG.error(f"{self} has no chain_length_delta {self.data}")
        return _chain_length_delta

    @property
    def newtip(self):
        _newtip = self.data.get("newtip", "")
        if not _newtip:
            LOG.error(f"{self} has no newtip {self.data}")
        else:
            _newtip = _newtip.split("@")[0]
        return _newtip


class BlockSample:
    """BlockSample represents all trace events for any given block hash.
    It provides a unified interface to think about what happend with a
    specific block. When was its header first announced, when did it first
    completed downloading etc.

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

    tace_events = list()
    app_config: AppConfig

    def __init__(self, events, app_config: AppConfig) -> None:
        # Make sure they are order by their time
        self.app_config = app_config
        events.sort(key=lambda x: x.at)
        self.tace_events = events

    @property
    def first_trace_header(self) -> Union[LogEvent, None]:
        """Returnms first TRACE_DOWNLOADED_HEADER received"""
        for event in self.tace_events:
            if event.kind == LogEventKind.TRACE_DOWNLOADED_HEADER:
                return event
        # That would be really odd to not find a TRACE_DOWNLOADED_HEADER
        LOG.error(f"No first {LogEventKind.TRACE_DOWNLOADED_HEADER} found for {self}")
        return None

    @property
    def first_completed_block(self) -> Union[LogEvent, None]:
        """Returns first COMPLETED_BLOCK_FETCH received"""
        for event in self.tace_events:
            if event.kind == LogEventKind.COMPLETED_BLOCK_FETCH:
                return event
        LOG.error(f"No first {LogEventKind.COMPLETED_BLOCK_FETCH} found for {self}")
        return None

    @property
    def fetch_request_completed_block(self) -> Union[LogEvent, None]:
        """Returns SEND_FETCH_REQUEST corresponding to the first COMPLETED_BLOCK_FETCH received"""
        if not (fcb := self.first_completed_block):
            return None
        for event in filter(
            lambda x: x.kind == LogEventKind.SEND_FETCH_REQUEST, self.tace_events
        ):
            if (
                event.remote_addr == fcb.remote_addr
                and event.remote_port == fcb.remote_port
            ):
                return event
        LOG.error(f"No {LogEventKind.SEND_FETCH_REQUEST} found for {fcb}")
        return None

    @property
    def slot_num_delta(self) -> int:
        """Slot delta in miliseconds

        The time difference in miliseconds
        """
        return 0  # self.slot_num #- self.last_slot_num

    @property
    def header_remote_addr(self) -> str:
        if not (fth := self.first_trace_header):
            return ""
        return fth.remote_addr

    @property
    def header_remote_port(self) -> str:
        if not (fth := self.first_trace_header):
            return ""
        return fth.remote_port

    @property
    def slot_num(self) -> int:
        if not (fth := self.first_trace_header):
            return 0
        return fth.slot_num

    @property
    def slot_time(self) -> datetime:
        """Time the slot_num should have happened."""
        _network_start = network_starttime.get("mainnet", 0)
        # print(f"_network_start {_network_start} self.slot_num {self.slot_num}")
        _slot_time = _network_start + self.slot_num
        # print(f"_slot_time {_slot_time}  # unixtimestamp")
        slot_time = datetime.fromtimestamp(_slot_time, tz=timezone.utc)
        # print(f"slot_time {slot_time} # real datetime ")
        return slot_time

    @property
    def header_delta(self) -> int:
        """Header delta in miliseconds

        The time from the slot_time of this block until the node received the
        first header. When could this header be received vs when was
        it actually received.
        """
        if not (fth := self.first_trace_header):
            return 0
        header_delta = fth.at - self.slot_time
        return int(header_delta.total_seconds() * 1000)

    @property
    def block_num(self) -> int:
        if not (fth := self.first_trace_header):
            return 0
        return fth.block_num

    @property
    def block_hash(self) -> str:
        if not (fth := self.first_trace_header):
            return ""
        return fth.block_hash

    @property
    def block_hash_short(self) -> str:
        if not (fth := self.first_trace_header):
            return ""
        return fth.block_hash_short

    @property
    def block_size(self) -> int:
        if not (fcb := self.first_completed_block):
            return 0
        return fcb.size

    @property
    def block_delay(self) -> float:
        if not (fcb := self.first_completed_block):
            return 0.0
        return fcb.delay

    @property
    def block_request_delta(self) -> int:
        """Block request delta in miliseconds

        The time it took the node from seeing a block first (the header was
        received) to actually requesting that block.
        """
        frcb, fth = self.fetch_request_completed_block, self.first_trace_header
        if not frcb or not fth:
            return 0
        block_request_delta = frcb.at - fth.at
        return int(block_request_delta.total_seconds() * 1000)

    @property
    def block_response_delta(self) -> int:
        """Block response delta in miliseconds

        The time it took to have completed the download of a given block
        after requesting it from a peer.
        """
        fcb, frcb = self.first_completed_block, self.fetch_request_completed_block
        if not fcb or not frcb:
            return 0
        block_response_delta = fcb.at - frcb.at
        return int(block_response_delta.total_seconds() * 1000)

    @property
    def block_adopt(self) -> Union[LogEvent, None]:
        """Return TraceEvent that this block was adopted with"""
        for event in self.tace_events:
            if event.kind in (
                LogEventKind.ADDED_TO_CURRENT_CHAIN,
                LogEventKind.SWITCHED_TO_A_FORK,
            ):
                return event
        LOG.error(f"{self.block_hash_short} has not been adopted!")
        return None

    @property
    def block_adopt_delta(self) -> int:
        """Block adopt delta in miliseconds

        The time it took the node to successfully adopt a block after it
        has completed receiving it.
        """
        block_adopt, fcb = self.block_adopt, self.first_completed_block
        if not block_adopt or not fcb:
            return 0
        block_adopt_delta = block_adopt.at - fcb.at
        return int(block_adopt_delta.total_seconds() * 1000)

    @property
    def block_g(self) -> str:
        if not (frcb := self.fetch_request_completed_block):
            return "0"
        return frcb.deltaq_g

    @property
    def block_remote_addr(self) -> str:
        if not (fcb := self.first_completed_block):
            return ""
        return fcb.remote_addr

    @property
    def block_remote_port(self) -> str:
        if not (fcb := self.first_completed_block):
            return ""
        return fcb.remote_port

    @property
    def block_local_address(self) -> str:
        if not (fcb := self.first_completed_block):
            return ""
        return fcb.local_addr

    @property
    def block_local_port(self) -> str:
        if not (fcb := self.first_completed_block):
            return ""
        return fcb.local_port