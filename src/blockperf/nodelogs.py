"""
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Union

logger = logging.getLogger(__name__)


class LogEventKind(Enum):
    """All events from the log file are of a specific kind."""

    ADDED_TO_CURRENT_CHAIN = "TraceAddBlockEvent.AddedToCurrentChain"
    COMPLETED_BLOCK_FETCH = "CompletedBlockFetch"
    SEND_FETCH_REQUEST = "SendFetchRequest"
    SWITCHED_TO_A_FORK = "TraceAddBlockEvent.SwitchedToAFork"
    TRACE_DOWNLOADED_HEADER = "ChainSyncClientEvent.TraceDownloadedHeader"

    UNKNOWN = "Unknown"


class LogEvent:
    """A LogEvent represents a single line in the nodes log file.

    DownloadedHeader or TraceDownloadedHeader (legacy tracing)
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
    atstr: str
    data: dict
    size: int
    delay: float
    slot_num: int
    deltaq_g: float
    chain_length_delta: int
    newtip: str
    local_addr: str
    local_port: str
    remote_addr: str
    remote_port: str

    def __init__(self, event_data: dict, legacy_tracing: bool) -> None:
        """Create a LogEvent with `from_logline` method by passing in the json string
        as written to the nodes log."""

        # Parse datetime string from either micro or nanoseconds with TZ offset
        if _at := event_data.get("at", None):
            if legacy_tracing:
                self.at = datetime.strptime(_at, "%Y-%m-%dT%H:%M:%S.%f%z")
            else:
                # Nanoseconds logging is variable length
                dt, suffix = _at.split(".")
                if match := re.match(r'^(\d+)(\D.*)', suffix):
                    ns, tz = match.groups()
                    usec = ns[:6]
                    self.at = datetime.strptime(f"{dt}.{usec}{tz}", "%Y-%m-%dT%H:%M:%S.%f%z")

        # Truncate from micro to milliseconds
        if hasattr(self, "at"):
            self.atstr = self.at.strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]

        self.data = event_data.get("data", {})
        if not self.data:
            logger.error("%s has not data", self)

        self.size = self.data.get("size", 0)
        self.delay = self.data.get("delay", 0.0)
        self.slot_num = self.data.get("slot", 0)
        self.deltaq_g = self.data.get("deltaq", {}).get("G", 0.0)
        self.chain_length_delta = self.data.get("chainLengthDelta", 0)

        self.newtip = self.data.get("newtip", "")
        if self.newtip:
            self.newtip = self.newtip.split("@")[0]

        if self.kind in (
            LogEventKind.TRACE_DOWNLOADED_HEADER,
            LogEventKind.SEND_FETCH_REQUEST,
            LogEventKind.COMPLETED_BLOCK_FETCH,
        ):
            self.local_addr = self.data.get("peer", {}).get("local", {}).get("addr", "")
            self.local_port = self.data.get("peer", {}).get("local", {}).get("port", "")
            self.remote_addr = (
                self.data.get("peer", {}).get("remote", {}).get("addr", "")
            )
            self.remote_port = (
                self.data.get("peer", {}).get("remote", {}).get("port", "")
            )

    def __repr__(self):
        _kind = self.kind.value
        if "." in _kind:
            _kind = f"{_kind.split('.')[1]}"
        _repr = f"LogEvent {_kind}"

        if self.kind == LogEventKind.UNKNOWN:
            _repr += f" {self.data.get('kind')}"

        if self.block_hash:
            _repr += f" Hash: {self.block_hash[0:10]}"
        if self.block_num:
            _repr += f" BlockNo: {self.block_num}"
        return _repr

    @classmethod
    def from_logline(
        cls,
        logline: str,
        legacy_tracing: bool,
        masked_addresses: list = [],
        bad_before: Union[int, None] = None,
    ) -> Union["LogEvent", None]:
        """Takes a single line from the logs and creates a LogEvent.
        Will return None if the LogEvent could not be created due to various reason.
        Either because the json is invalid, the LogKind is not of interest,
        the event is tool old or it does not have a block_hash.
        """
        # Most stupid (simple) way to remove ip addresss given
        if masked_addresses:
            for addr in masked_addresses:
                logline = logline.replace(addr, "0.0.0.0")

        _event = None
        try:
            json_data = json.loads(logline)
            _event = cls(json_data, legacy_tracing)
        except json.decoder.JSONDecodeError:
            logger.error("Invalid JSON %s", logline)
            return None

        if _event.kind not in (
            LogEventKind.TRACE_DOWNLOADED_HEADER,
            LogEventKind.SEND_FETCH_REQUEST,
            LogEventKind.COMPLETED_BLOCK_FETCH,
            LogEventKind.ADDED_TO_CURRENT_CHAIN,
            LogEventKind.SWITCHED_TO_A_FORK,
        ):
            return None

        if bad_before and _event.at.timestamp() < bad_before:
            return None

        if not _event.block_hash:
            return None

        return _event

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
        return str(block_hash)

    @property
    def block_hash_short(self) -> str:
        return self.block_hash[0:10]

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
        return _blockNo
