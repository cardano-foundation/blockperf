import logging
from datetime import datetime, timezone
from typing import Union
from blockperf.nodelogs import LogEvent, LogEventKind, LogEventNs

# logging.basicConfig(level=logging.DEBUG, format="(%(threadName)-9s) %(message)s")
logger = logging.getLogger(__name__)

NETWORK_STARTTIMES = {
    # mainnet
    764824073: 1591566291,
    # preprod
    1: 1655683200,
    # preview
    2: 1666656000,
}


def slot_time_of(slot_num: int, network: int) -> datetime:
    """Calculate the timestamp that given slot should have occurred.
    Works only if the networks slots are 1 second lengths!
    """
    logger.debug("slot_time_of(%s, %s)", slot_num, network)
    if network not in NETWORK_STARTTIMES:
        raise ValueError(f"No starttime for {network} available")

    _network_start = NETWORK_STARTTIMES.get(network, 0)
    _slot_time = _network_start + slot_num
    slot_time = datetime.fromtimestamp(_slot_time, tz=timezone.utc)
    return slot_time


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

    trace_events: list = []

    def __init__(self, events: list, network_magic: int, legacy_tracing: bool = True) -> None:
        """Creates LogEvent and orders the events by at field"""
        events.sort(key=lambda x: x.at)
        self.trace_events = events
        self.network_magic = network_magic
        self.legacy_tracing = legacy_tracing

    def __str__(self):
        """ """
        return (
            f"block_num: {self.block_num} \n"
            f"slot_num {self.slot_num} \n"
            f"block_hash len: {len(self.block_hash)} \n"
            f"block_size: {self.block_size} \n"
            f"header_delta {self.header_delta} \n"
            f"block_request_delta {self.block_request_delta}\n"
            f"block_response_delta  {self.block_response_delta}\n"
            f"block_adopt_delta {self.block_adopt_delta} \n"
        )

    def is_complete(self) -> bool:
        """Determines if all needed LogEvents are in this sample"""
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
        """Returns first DOWNLOADED_HEADER received"""
        for event in self.trace_events:
            if (
                self.legacy_tracing and event.kind == LogEventKind.DOWNLOADED_HEADER
                or not self.legacy_tracing and event.ns == LogEventNs.DOWNLOADED_HEADER
            ):
                logger.debug("Found first TraceHeader %s", event.atstr)
                return event
        return None

    @property
    def first_completed_block(self) -> Union[LogEvent, None]:
        """Returns first COMPLETED_BLOCK_FETCH received"""
        for event in self.trace_events:
            if (
                self.legacy_tracing and event.kind == LogEventKind.COMPLETED_BLOCK_FETCH
                or not self.legacy_tracing and event.ns == LogEventNs.COMPLETED_BLOCK_FETCH
            ):
                return event
        return None

    @property
    def fetch_request_completed_block(self) -> Union[LogEvent, None]:
        """Returns SEND_FETCH_REQUEST corresponding to the first COMPLETED_BLOCK_FETCH received"""
        if not (fcb := self.first_completed_block):
            return None
        for event in filter(
            lambda x: x.kind == LogEventKind.SEND_FETCH_REQUEST if self.legacy_tracing else x.ns == LogEventNs.SEND_FETCH_REQUEST, self.trace_events
        ):
            if (
                event.remote_addr == fcb.remote_addr
                and event.remote_port == fcb.remote_port
            ):
                return event
        return None

    @property
    def block_adopt(self) -> Union[LogEvent, None]:
        """Return the event that this block was adopted with"""
        for event in self.trace_events:
            if (
                self.legacy_tracing and event.kind in (LogEventKind.ADDED_TO_CURRENT_CHAIN, LogEventKind.SWITCHED_TO_A_FORK)
                or not self.legacy_tracing and event.ns in (LogEventNs.ADDED_TO_CURRENT_CHAIN, LogEventNs.SWITCHED_TO_A_FORK)
            ):
                return event
        return None

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
        """Determine the time that current slot_num should have happened."""
        _slot_time = slot_time_of(self.slot_num, self.network_magic)
        return _slot_time

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

    def is_sane(self) -> bool:
        """Checks all values are within acceptable ranges.

        Also checks for block_num and slot_num being not too old.

        sane :: BlockSample -> Bool
        sane BlockSample{..} = not (
            T.length bsBpVersion > 10 ||
            T.length bsBlockHash > 128 ||
            T.length bsBlockHash == 0 ||
            T.length bsHeaderRemoteAddr > 32 ||
            T.length bsBlockRemoteAddr > 32 ||
            bsSize == 0 ||
            bsSize > 10_000_000 ||
            bsHeaderDelta > 600000 ||
            bsHeaderDelta < (-6000) ||
            bsBlockReqDelta > 600000 ||
            bsBlockReqDelta < (-6000) ||
            bsBlockRspDelta > 600000||
            bsBlockRspDelta < (-6000) ||
            bsBlockAdoptDelta > 600000 ||
            bsBlockAdoptDelta < (-6000) ||
            invalidAddress bsHeaderRemoteAddr ||
            invalidAddress bsBlockRemoteAddr
        )
        """
        if (
            0 < self.block_num
            and 0 < self.slot_num
            and 0 < len(self.block_hash) < 128
            and 0 < self.block_size < 10000000
            and -6000 < self.header_delta < 600000
            and -6000 < self.block_request_delta < 600000
            and -6000 < self.block_response_delta < 600000
            and -6000 < self.block_adopt_delta < 600000
        ):
            return True
        return False
