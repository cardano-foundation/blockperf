import json
from enum import Enum
from typing import Union
from datetime import datetime, timezone
import logging

logging.basicConfig(level=logging.DEBUG, format="(%(threadName)-9s) %(message)s")


class TraceKind(Enum):
    """Possible kinds of loglines."""

    # The interesting ones
    TRACE_DOWNLOADED_HEADER = "ChainSyncClientEvent.TraceDownloadedHeader"

    SEND_FETCH_REQUEST = "SendFetchRequest"
    COMPLETED_BLOCK_FETCH = "CompletedBlockFetch"
    SWITCHED_TO_A_FORK = "TraceAddBlockEvent.SwitchedToAFork"

    TRACE_FOUND_INTERSECTION = "ChainSyncClientEvent.TraceFoundIntersection"
    TRY_SWITCH_TO_A_FORK = "TraceAddBlockEvent.TrySwitchToAFork"

    TRACE_ROLLED_BACK = "ChainSyncClientEvent.TraceRolledBack"

    COMPLETED_FETCH_BATCH = "CompletedFetchBatch"
    ADDED_TO_CURRENT_CHAIN = "TraceAddBlockEvent.AddedToCurrentChain"

    STARTED_FETCH_BATCH = "StartedFetchBatch"
    ADDED_FETCH_REQUEST = "AddedFetchRequest"
    ACKNOWLEDGED_FETCH_REQUEST = "AcknowledgedFetchRequest"
    PEER_STATUS_CHANGED = "PeerStatusChanged"
    MUX_ERRORED = "MuxErrored"
    INBOUND_GOVERNOR_COUNTERS = "InboundGovernorCounters"
    DEMOTE_ASYNCHRONOUS = "DemoteAsynchronous"
    DEMOTED_TO_COLD_REMOTE = "DemotedToColdRemote"
    PEER_SELECTION_COUNTERS = "PeerSelectionCounters"
    PROMOTE_COLD_PEERS = "PromoteColdPeers"
    PROMOTE_COLD_DONE = "PromoteColdDone"
    PROMOTE_COLD_FAILED = "PromoteColdFailed"
    PROMOTE_WARM_PEERS = "PromoteWarmPeers"
    PROMOTE_WARM_DONE = "PromoteWarmDone"
    CONNECTION_MANAGER_COUNTERS = "ConnectionManagerCounters"
    CONNECTION_HANDLER = "ConnectionHandler"
    CONNECT_ERROR = "ConnectError"
    UNKNOWN = "Unknown"


class TraceEvent:
    at: datetime
    data: dict

    def __init__(self, log_line: str) -> None:
        _data = json.loads(log_line)
        self.at = datetime.strptime(_data.get("at"), "%Y-%m-%dT%H:%M:%S.%f%z")
        self.data = _data.get("data")
        self.peer = _data.get("data").get("peer")
        self.env = _data.get("env")

    def __str__(self):
        return f"<TraceEvent <{self.kind}>>"

    @property
    def block_hash(self) -> Union[str, None]:
        if not "block" in self.data:
            logging.error(f"{self} has no block_hash")
        return str(self.data.get("block"))

    @property
    def kind(self) -> TraceKind:
        kind_value = self.data.get("kind")
        for kind in TraceKind:
            if kind_value == kind.value:
                return TraceKind(kind_value)
        return TraceKind(TraceKind.UNKNOWN)

    @property
    def delay(self):
        if self.kind == TraceKind.COMPLETED_BLOCK_FETCH:
            return self.data.get("delay")
        logging.warning(f"{self} has no delay")
        return None

    @property
    def size(self) -> Union[int, None]:
        if self.kind == TraceKind.COMPLETED_BLOCK_FETCH:
            return self.data.get("size")
        logging.warning(f"{self} has no size")
        return None

    @property
    def local_addr(self) -> Union[int, None]:
        if self.kind == TraceKind.COMPLETED_BLOCK_FETCH:
            return self.peer.get("local").get("addr")
        logging.warning(f"{self} has no local_addr")
        return None

    @property
    def local_port(self) -> Union[int, None]:
        if self.kind == TraceKind.COMPLETED_BLOCK_FETCH:
            return self.peer.get("local").get("port")
        logging.warning(f"{self} has no local_port")
        return None

    @property
    def remote_addr(self) -> Union[str, None]:
        if self.kind in (
            TraceKind.TRACE_DOWNLOADED_HEADER,
            TraceKind.SEND_FETCH_REQUEST,
        ):
            return self.peer.get("remote").get("addr")
        logging.warning(f"{self} has no remote_addr")
        return None

    @property
    def remote_port(self) -> Union[str, None]:
        if self.kind in (
            TraceKind.TRACE_DOWNLOADED_HEADER,
            TraceKind.SEND_FETCH_REQUEST,
        ):
            return self.peer.get("remote").get("port")
        logging.warning(f"{self} has no remote_port")
        return None


class BlockTrace:
    events = list()

    def __init__(self) -> None:
        pass

    def add_line(self, log_line: str):
        log_line = json.loads(log_line)
        trace_event = TraceEvent(log_line)
        self.events.append(trace_event)
