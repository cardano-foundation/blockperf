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


class TraceEventKind(Enum):
    """All events from the log file are of a specific kind."""
    TRACE_DOWNLOADED_HEADER = "ChainSyncClientEvent.TraceDownloadedHeader"
    SEND_FETCH_REQUEST = "SendFetchRequest"
    COMPLETED_BLOCK_FETCH = "CompletedBlockFetch"
    SWITCHED_TO_A_FORK = "TraceAddBlockEvent.SwitchedToAFork"
    ADDED_TO_CURRENT_CHAIN = "TraceAddBlockEvent.AddedToCurrentChain"
    UNKNOWN = "Unknown"


class TraceEvent:
    """A TraceEvent represents a single trace line in the nodes log file.

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
        """Create a TraceEvent with `from_logline` method by passing in the json string
        as written to the nodes log. I have implemented access to the individual fiels
        with properties to keep the knowledge of how that value is retrieved out of
        the logline in this class."""
        self.at = datetime.strptime(event_data.get("at", None), "%Y-%m-%dT%H:%M:%S.%f%z")
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
        return f"<{__class__.__name__} {self.block_hash[0:10]} {self.at.strftime('%H:%M:%S.%f3')} {trace_kind} >"

    @classmethod
    def from_logline(cls, logline: str):
        """Takes a single line from the logs and creates a """
        try:
            _json_data = json.loads(logline)
            return cls(_json_data)
        except json.decoder.JSONDecodeError as e:
            LOG.error(f"Could not decode json from {logline} ")
            return None

    @property
    def block_hash(self) -> str:
        block_hash = ""
        if self.kind == TraceEventKind.SEND_FETCH_REQUEST:
            block_hash = self.data.get("head", "")
        elif self.kind in (
            TraceEventKind.COMPLETED_BLOCK_FETCH,
            TraceEventKind.TRACE_DOWNLOADED_HEADER
        ):
            block_hash = self.data.get("block", "")
        elif self.kind in (
            TraceEventKind.ADDED_TO_CURRENT_CHAIN,
            TraceEventKind.SWITCHED_TO_A_FORK
        ):
            newtip = self.data.get("newtip", "")
            block_hash = newtip.split("@")[0]

        if not block_hash:
            LOG.error(f"Could not determine block_hash for {self}")

        return str(block_hash)

    @property
    def kind(self) -> TraceEventKind:
        if not hasattr(self, "_kind"):
            _value = self.data.get("kind")
            for kind in TraceEventKind:
                if _value == kind.value:
                    self._kind = TraceEventKind(_value)
                    break
            else:
                self._kind = TraceEventKind(TraceEventKind.UNKNOWN)
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
            assert "unBlockNo" in _blockNo, "blockNo is a dict but does not have unBlockNo"
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


class BlockTrace:
    """BlockTrace represents all trace events for any given block hash.
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
    _first_trace_header: TraceEvent
    _first_completed_block: TraceEvent
    _fetch_request_completed_block: TraceEvent

    def __init__(self, events, app_config: AppConfig) -> None:
        # Make sure they are order by their time
        self.app_config = app_config
        events.sort(key=lambda x: x.at)
        self.tace_events = events

    #def __str__(self):
    #    return f"<{__class__.__name__}>"

    @property
    def first_trace_header(self) -> TraceEvent:
        """Returnms first TRACE_DOWNLOADED_HEADER received"""
        if not hasattr(self, "_first_trace_header"):
            for event in self.tace_events:
                if event.kind == TraceEventKind.TRACE_DOWNLOADED_HEADER:
                    self._first_trace_header = event
                    break
        assert self._first_trace_header, "Did not find first TRACE_DOWNLOADED_HEADER in events"
        return self._first_trace_header

    @property
    def first_completed_block(self) -> TraceEvent:
        """Returns first COMPLETED_BLOCK_FETCH received"""
        if not hasattr(self, "_first_completed_block"):
            for event in self.tace_events:
                if event.kind == TraceEventKind.COMPLETED_BLOCK_FETCH:
                    self._first_completed_block = event
                    break
        assert self._first_completed_block, "Did not find first COMPLETED_BLOCK_FETCH in events"
        return self._first_completed_block

    @property
    def fetch_request_completed_block(self) -> TraceEvent:
        """Returns SEND_FETCH_REQUEST corresponding to the first COMPLETED_BLOCK_FETCH received"""
        if not hasattr(self, "_fetch_request_completed_block"):
            for event in filter(lambda x: x.kind == TraceEventKind.SEND_FETCH_REQUEST, self.tace_events):
                if (
                    event.remote_addr == self.first_completed_block.remote_addr
                    and
                    event.remote_port == self.first_completed_block.remote_port
                ):
                    self._fetch_request_completed_block = event
                    break
            else:
                LOG.error(f"{self} has not found a FetchRequest for {self.first_completed_block}")
        return self._fetch_request_completed_block

    @property
    def slot_num_delta(self) -> timedelta:
        """Calculated the time betwenn when the given slot should have been,
        versus the actual time is has been."""
        return self.slot_num #- self.last_slot_num

    @property
    def header_remote_addr(self) -> str:
        return self.first_trace_header.remote_addr

    @property
    def header_remote_port(self) -> str:
        return self.first_trace_header.remote_port

    @property
    def slot_num(self) -> int:
        return self.first_trace_header.slot_num

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
        header_delta = self.first_trace_header.at - self.slot_time
        return int(header_delta.total_seconds() * 1000)

    @property
    def block_num(self) -> int:
        return self.first_trace_header.block_num

    @property
    def block_hash(self) -> str:
        return self.first_trace_header.block_hash

    @property
    def block_hash_short(self) -> str:
        return self.block_hash[0:10]

    @property
    def block_size(self) -> int:
        return self.first_completed_block.size

    @property
    def block_delay(self) -> float:
        return self.first_completed_block.delay

    @property
    def block_request_delta(self) -> int:
        """Block request delta in miliseconds

        The time it took the node from seeing a block first (the header was
        received) to actually requesting that block.
        """
        block_request_delta = self.fetch_request_completed_block.at - self.first_trace_header.at
        return int(block_request_delta.total_seconds() * 1000)

    @property
    def block_response_delta(self) -> int:
        """Block response deltain miliseconds

        The time it took to have completed the download of a given block
        after requesting it from a peer.
        """
        block_response_delta = self.first_completed_block.at - self.fetch_request_completed_block.at
        return int(block_response_delta.total_seconds() * 1000)

    @property
    def block_adopt(self) -> Union[TraceEvent, None]:
        """Return TraceEvent that this block was adopted with"""
        for event in self.tace_events:
            if event.kind in (
                TraceEventKind.ADDED_TO_CURRENT_CHAIN,
                TraceEventKind.SWITCHED_TO_A_FORK
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
        block_adopt = self.block_adopt
        if not block_adopt:
            return 0

        block_adopt_delta = self.block_adopt.at - self.first_completed_block.at
        return int(block_adopt_delta.total_seconds() * 1000)

    @property
    def block_g(self) -> str:
        return self.fetch_request_completed_block.deltaq_g

    @property
    def block_remote_addr(self) -> str:
        return self.first_completed_block.remote_addr

    @property
    def block_remote_port(self) -> str:
        return self.first_completed_block.remote_port

    @property
    def block_local_address(self) -> str:
        #return self.app_config.relay_public_ip
        return self.first_completed_block.local_addr

    @property
    def block_local_port(self) -> str:
        #return self.app_config.relay_public_port
        return self.first_completed_block.local_port


    def as_msg_string(self):
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
        # ? blockSlot-slotHeightPrev -> Delta between this slot and the last one that had a block?
        msg = (
            f"Block:.... {self.block_num} ({self.block_hash_short})\n"
            f"Slot:..... {self.slot_num} ({self.slot_num_delta}s)\n"
            f".......... {self.slot_time}\n"  # Assuming this is the slot_time
            f"Header ... {self.first_trace_header.at} ({self.header_delta}) from {self.header_remote_addr}:{self.header_remote_port}\n"
            f"RequestX.. {self.fetch_request_completed_block.at} ({self.block_request_delta})\n"
            f"Block..... {self.first_completed_block.at} ({self.block_response_delta}) from {self.block_remote_addr}:{self.block_remote_port}\n"
            f"Adopted... {self.block_adopt.at} ({self.block_adopt_delta})\n"
            f"Size...... {self.block_size} bytes\n"
            f"Delay..... {self.block_delay} sec\n\n"
        )
        return msg

    def as_payload_dict(self):
        """Return the data as a dict suitable to be sent to mqtt"""
        message = {
            "magic": str(self.app_config.network_magic),
            "bpVersion": f"v{blockperf_version}",
            "blockNo": str(self.block_num),
            "slotNo": str(self.slot_num),
            "blockHash": str(self.block_hash),
            "blockSize": str(self.block_size),
            "headerRemoteAddr": str(self.header_remote_addr),
            "headerRemotePort": str(self.header_remote_port),
            "headerDelta": str(self.header_delta),
            "blockReqDelta": str(self.block_request_delta),
            "blockRspDelta": str(self.block_response_delta),
            "blockAdoptDelta": str(self.block_adopt_delta),
            "blockRemoteAddress": str(self.block_remote_addr),
            "blockRemotePort": str(self.block_remote_port),
            "blockLocalAddress": str(self.block_local_address),
            "blockLocalPort": str(self.block_local_port),
            "blockG": str(self.block_g),
        }
        return message