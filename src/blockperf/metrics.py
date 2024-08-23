import logging
import os

from prometheus_client import Counter, Gauge, start_http_server

logger = logging.getLogger(__name__)


class Metrics:
    enabled: bool = False
    header_delta: Gauge = None
    block_request_delta: Gauge = None
    block_response_delta: Gauge = None
    block_adopt_delta: Gauge = None
    block_delay: Gauge = None
    block_no: Gauge = None
    valid_samples: Counter = None
    invalid_samples: Counter = None

    def __init__(self):
        port = os.getenv("BLOCKPERF_METRICS_PORT", None)
        # If not given or not a number, dont setup anything
        if not port or not port.isdigit():
            return
        port = int(port)
        self.enabled = True
        self.header_delta = Gauge(
            "blockperf_header_delta",
            "time from when a block was forged until received (ms)",
        )
        self.block_request_delta = Gauge(
            "blockperf_block_req_delta",
            "time between the header was received until the block request was sent (ms)",
        )
        self.block_response_delta = Gauge(
            "blockperf_block_rsp_delta",
            "time between the block request was sent until the block responce was received (ms)",
        )
        self.block_adopt_delta = Gauge(
            "blockperf_block_adopt_delta", "time for adopting the block (ms)"
        )
        self.block_delay = Gauge("blockperf_block_delay", "Total block delay (ms)")
        self.block_no = Gauge("blockperf_block_no", "Block number of latest sample")
        self.valid_samples = Counter(
            "blockperf_valid_samples", "valid samples collected"
        )
        self.invalid_samples = Counter(
            "blockperf_invalid_samples", "invalid samples discarded"
        )
        start_http_server(port)

    def set(self, metric, value):
        """Calls set() on given metric with given value"""
        if not self.enabled:
            return
        logger.info("set %s to %s", metric, value)
        prom_metric = getattr(self, metric)
        prom_metric.set(value)

    def inc(self, metric):
        """Calls inc() on given metric"""
        if not self.enabled:
            return
        logger.info("inc %s", metric)
        prom_metric = getattr(self, metric)
        prom_metric.inc()
