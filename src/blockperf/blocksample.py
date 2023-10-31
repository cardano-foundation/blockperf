import json
import sys
from enum import Enum
from typing import Union
from datetime import datetime, timezone, timedelta
import logging

from blockperf import __version__ as blockperf_version
from blockperf.config import AppConfig
from blockperf.nodelogs import LogEventKind, LogEvent
# logging.basicConfig(level=logging.DEBUG, format="(%(threadName)-9s) %(message)s")
logger = logging.getLogger(__name__)


# Unixtimestamps of the starttimes of different networks. Needed to determine
# when a given slot is meant to exist in time.
network_starttime = {
    "preprod": 1660003200,
    "mainnet": 1591566291,
    "preview": 1655683200,
}


class BlockSample:
    """BlockSample represents the data fetched from the logs for a given block.
    It is
      trace events for any given block hash.
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

    trace_events = list()
    app_config: AppConfig

    def __init__(self, events, app_config: AppConfig) -> None:
        # Make sure they are order by their time
        self.app_config = app_config
        events.sort(key=lambda x: x.at)
        self.trace_events = events

    def is_complete(self) -> bool:
        """
        """
        if not self.first_trace_header:
            return False
        if not self.first_completed_block:
            return False
        if not self.fetch_request_completed_block:
            return False
        if not self.block_adopt:
            return False
        return True

    @property
    def first_trace_header(self) -> Union[LogEvent, None]:
        """Returnms first TRACE_DOWNLOADED_HEADER received"""
        for event in self.trace_events:
            if event.kind == LogEventKind.TRACE_DOWNLOADED_HEADER:
                return event
        # If there is no TRACE_DOWNLOADED_HEADER, we cant even figure out block_num or block_hash (currently)
        logger.warning("No first %s", LogEventKind.TRACE_DOWNLOADED_HEADER)
        return None

    @property
    def first_completed_block(self) -> Union[LogEvent, None]:
        """Returns first COMPLETED_BLOCK_FETCH received"""
        for event in self.trace_events:
            if event.kind == LogEventKind.COMPLETED_BLOCK_FETCH:
                return event
        logger.warning(
            "No first %s; BlockNo: %s Hash: %s",
            LogEventKind.COMPLETED_BLOCK_FETCH, self.block_num, self.block_hash
        )
        return None

    @property
    def fetch_request_completed_block(self) -> Union[LogEvent, None]:
        """Returns SEND_FETCH_REQUEST corresponding to the first COMPLETED_BLOCK_FETCH received"""
        if not (fcb := self.first_completed_block):
            return None
        for event in filter(
            lambda x: x.kind == LogEventKind.SEND_FETCH_REQUEST, self.trace_events
        ):
            if (
                event.remote_addr == fcb.remote_addr
                and event.remote_port == fcb.remote_port
            ):
                return event
        logger.error(
            "No %s found for %s",
            LogEventKind.SEND_FETCH_REQUEST, fcb)
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
        for event in self.trace_events:
            if event.kind in (
                LogEventKind.ADDED_TO_CURRENT_CHAIN,
                LogEventKind.SWITCHED_TO_A_FORK,
            ):
                return event
        logger.error("%s has not been adopted!", self.block_hash_short)
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
        _block_adopt_delta = block_adopt.at - fcb.at
        block_adopt_delta = int(_block_adopt_delta.total_seconds() * 1000)
        if block_adopt_delta < 0:
            return 0
        else:
            return block_adopt_delta

    @property
    def block_g(self) -> float:
        if not (frcb := self.fetch_request_completed_block):
            return 0.0
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
