import sys
import collections
from datetime import datetime, timezone, timedelta
import json
import logging
import queue
import os
import threading
import time
from pathlib import Path

from blockperf import __version__ as blockperf_version
from blockperf.config import AppConfig

from blockperf.blocksample import BlockSample, slot_time_of
from blockperf.nodelogs import LogEventKind, LogEvent
from blockperf.mqtt import MQTTClient


logger = logging.getLogger(__name__)


class App:
    app_config: AppConfig
    node_config: dict
    mqtt_client: MQTTClient
    start_time: int

    # holds a dictionairy for each kind of events for each block_hash
    logevents: dict = {}
    # the list of all published hashes, to not publish a hash twice
    published_blocks: list = []
    # Stores the last X hashes before they are deleted from logevents and published_blocks
    working_hashes: collections.deque = collections.deque()

    def __init__(self, config: AppConfig) -> None:
        self.q: queue.Queue = queue.Queue(maxsize=50)
        self.app_config = config
        self.start_time = int(datetime.now().timestamp())

    def run(self):
        """Runs the App by creating the mqtt client and two threads.
        One thread produces reads from the node logs and produces blocksamples
        while the other consumes these samples and publishes them to mqtt broker.
        """
        try:
            self.mqtt_client = MQTTClient(
                ca_certfile=self.app_config.amazon_ca,
                client_certfile=self.app_config.client_cert,
                client_keyfile=self.app_config.client_key,
                host=self.app_config.broker_host,
                port=self.app_config.broker_port,
                keepalive=self.app_config.broker_keepalive,
            )

            # Sometimes the connect took a moment to settle. To not have
            # the consumer accept messages (and not be able to publish)
            # i decided to ensure the connection is established this way
            while not self.mqtt_client.is_connected:
                logger.debug("Waiting for mqtt connection ... ")
                time.sleep(0.5)  # Wait until connected to broker

            self.run_blocksample_loop()
        except KeyboardInterrupt:
            sys.stdout.write("Closed")
            return

    def print_block_stats(self, blocksample: BlockSample) -> None:
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
        slot_delta = 0
        if hasattr(self, "last_slot_time"):
            slot_delta = int(
                blocksample.slot_time.timestamp() - self.last_slot_time.timestamp()
            )

        msg = (
            f"Block:.... {blocksample.block_num} ({blocksample.block_hash_short})\n"
            f"Slot:..... {blocksample.slot_num} ({slot_delta}s)\n"
            # Assuming this is the slot_time
            f".......... {blocksample.slot_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Header ... {blocksample.first_trace_header.atstr if blocksample.first_trace_header else 'X'} (+{blocksample.header_delta} ms) from {blocksample.header_remote_addr}:{blocksample.header_remote_port}\n"
            f"RequestX.. {blocksample.fetch_request_completed_block.atstr if blocksample.fetch_request_completed_block else 'X'} (+{blocksample.block_request_delta} ms)\n"
            f"Block..... {blocksample.first_completed_block.atstr if blocksample.first_completed_block else 'X'} (+{blocksample.block_response_delta} ms) from {blocksample.block_remote_addr}:{blocksample.block_remote_port}\n"
            f"Adopted... {blocksample.block_adopt.atstr if blocksample.block_adopt else 'X'} (+{blocksample.block_adopt_delta} ms)\n"
            f"Size...... {blocksample.block_size} bytes\n"
            f"Delay..... {blocksample.block_delay} sec\n\n"
        )
        logger.info("\n" + msg)

    def mqtt_payload_from(self, sample: BlockSample) -> dict:
        """Returns a dictionary for use as payload when publishing the sample."""
        payload = {
            "magic": str(self.app_config.network_magic),
            "bpVersion": f"v{blockperf_version}",
            "blockNo": str(sample.block_num),
            "slotNo": str(sample.slot_num),
            "blockHash": str(sample.block_hash),
            "blockSize": str(sample.block_size),
            "headerRemoteAddr": str(sample.header_remote_addr),
            "headerRemotePort": str(sample.header_remote_port),
            "headerDelta": str(sample.header_delta),
            "blockReqDelta": str(sample.block_request_delta),
            "blockRspDelta": str(sample.block_response_delta),
            "blockAdoptDelta": str(sample.block_adopt_delta),
            "blockRemoteAddress": str(sample.block_remote_addr),
            "blockRemotePort": str(sample.block_remote_port),
            "blockLocalAddress": str(self.app_config.relay_public_ip),
            "blockLocalPort": str(self.app_config.relay_public_port),
            "blockG": str(sample.block_g),
        }
        return payload

    def ensure_maxblocks(self):
        """
        * logevents holds all events recorded for all hashes seen.
        * published_blocks holds hashes of all published blocks.

        LogEvents hashes eventually get adopted (or not). But this may
        take some time. I want to wait for some time (config.max_concurrent_blocks)
        before i drop that hash.

        Samples for blocks that already have a sample published should not get
        republished. Thus the list of published_blocks.

        To not have both lists grow indefinetly i use the deque in self.working_hashes.
        Once it reaches a certain size, the hashes that are added first will
        get popped of and delete from the other two lists.
        """
        if len(self.working_hashes) > self.app_config.max_concurrent_blocks:
            removed_hash = self.working_hashes.popleft()
            # Delete events for hash from logevents
            if removed_hash in self.logevents:
                del self.logevents[removed_hash]
                logger.debug("Removed %s from working_hashes", removed_hash)
            if removed_hash in self.published_blocks:
                del self.published_blocks[self.published_blocks.index(removed_hash)]
                logger.debug("Removed %s from published_blocks", removed_hash)

    def run_blocksample_loop(self):
        """Create samples for the blocks seen in the logfile and publishes them.

        The for loop is supposed to run forever over the events from the logfile
        produced by logevents_logfile(). Each event is a nodelogs.LogEvent.

        From all the events that are possibly read from the logfile only
        some are of interest.

            * Must be of a specific kind
                TRACE_DOWNLOADED_HEADER, SEND_FETCH_REQUEST, COMPLETED_BLOCK_FETCH,
                ADDED_TO_CURRENT_CHAIN, SWITCHED_TO_A_FORK
            * Must not be too old (invalid)
            * Must have a blockhash
        These are already filtered out in logevents_logfile()

        A sample can only be created if all the required LogEvents have been
        recorded for that given block. All required LogEvents means that
        for each hash there must at least be one TRACE_DOWNLOADED_HEADER, one SEND_FETCH_REQUEST
        and one COMPLETED_BLOCK_FETCH as well es one of the two possible adoption
        kinds which are ADDED_TO_CURRENT_CHAIN and SWITCHED_TO_A_FORK.

        To make that test somewhat simple there self.logevents holds all events
        in dictionaries for their respective types. That makes it rather simple
        to test if all required LogEvents have been collected yet.

        Once that is the case a new sample is created by collecting all events
        and instanciating BlockSample(). If the sample is complete it published.

        The
        """

        for event in self.logevents_logfile():
            # Make sure lists dont fill up
            self.ensure_maxblocks()

            _block_hash = event.block_hash
            _block_hash_short = event.block_hash_short

            if _block_hash not in self.logevents:
                logger.debug("New hash %s", _block_hash_short)
                # A new hash is seen, make a new list to store its events in
                self.logevents[_block_hash] = {}

            if _block_hash not in self.working_hashes:
                self.working_hashes.append(_block_hash)

            # All events recoreded are stored in different lists based
            # on the event kind within logevents
            if event.kind not in self.logevents[_block_hash]:
                self.logevents[_block_hash][event.kind] = []
            self.logevents[_block_hash][event.kind].append(event)
            logger.debug(event)

            # Do not event try to republish
            if _block_hash in self.published_blocks:
                logger.debug("Already published %s", _block_hash)
                continue

            # Check that all needed events are recorded for current _block_hash
            if not (
                LogEventKind.TRACE_DOWNLOADED_HEADER
                in self.logevents[_block_hash].keys()
                and LogEventKind.SEND_FETCH_REQUEST
                in self.logevents[_block_hash].keys()
                and LogEventKind.COMPLETED_BLOCK_FETCH
                in self.logevents[_block_hash].keys()
                and (
                    LogEventKind.ADDED_TO_CURRENT_CHAIN
                    in self.logevents[_block_hash].keys()
                    or LogEventKind.SWITCHED_TO_A_FORK
                    in self.logevents[_block_hash].keys()
                )
            ):
                logger.debug(
                    "Not all event types collected for hash %s ", _block_hash_short
                )
                continue

            # Flatten the events to feed all of them into BlockSample
            all_events = []
            for event_kind_list in self.logevents[_block_hash].values():
                all_events.extend(event_kind_list)

            new_sample = BlockSample(all_events)

            # Check BlockSample has all needed Events to produce sample
            if not new_sample.is_complete():
                logger.debug("Incomplete LogEvents for %s", _block_hash_short)
                continue

            # Check values are in acceptable ranges
            if not new_sample.is_sane():
                logger.debug("Insane values for sample %s", new_sample)
                continue

            logger.info("Sample for %s created", _block_hash_short)

            # The sample is ready to be published, create the payload for mqtt,
            # determine the topic and publish that sample
            self.print_block_stats(new_sample)
            payload = self.mqtt_payload_from(new_sample)
            logger.debug(
                json.dumps(payload, indent=4, sort_keys=True, ensure_ascii=False)
            )
            topic = f"{self.app_config.topic}/{new_sample.block_hash}"
            self.mqtt_client.publish(topic, payload)

            self.published_blocks.append(_block_hash)
            logger.info(
                "LogEvents for %s blocks - Working on %s blocks, Published %s samples ",
                len(self.logevents.keys()),
                len(self.working_hashes),
                len(self.published_blocks),
            )

    def get_real_node_logfile(self) -> Path:
        """Return the path to the logfile that node.log points to"""
        while True:
            node_log_link = self.app_config.node_logfile
            # At this point there must not be an empty logfile
            assert node_log_link, "Node logfile not found"
            if not node_log_link.exists():
                logger.warning("Node log file does not exist %s", node_log_link)
                time.sleep(2)
            try:
                real_node_log = os.path.realpath(node_log_link, strict=True)
                node_logdir = self.app_config.node_logdir
                assert node_logdir, "Node logdir not found"
                return node_logdir.joinpath(real_node_log)
            except OSError:
                logger.warning("Real node log not found from link %s", node_log_link)
                time.sleep(2)

    def slot_is_too_old(self, logevents: list) -> bool:
        """Given a list of logevents it finds the TraceDownloadedHeader event
        and determines whether the current slot_num is too old for us.
        """
        trace_headers = [
            event
            for event in logevents
            if event.kind == LogEventKind.TRACE_DOWNLOADED_HEADER
        ]

        # Without TraceHeaders we cant even calcualte the slot_time
        if not trace_headers:
            return False

        # If there is one, check its slot_time
        trace_header = trace_headers.pop(0)
        slot_time = slot_time_of(trace_header.slot_num)
        if slot_time < datetime.now(tz=timezone.utc) - timedelta(hours=12):
            logger.info(
                "Slot %s is too old (%s)",
                trace_header.slot_num,
                slot_time,
            )
            return True
        return False

    def logevents_logfile(self):
        """Generator that "tails" the nodes log file and produces LogEvents
        for each new line. The nodes logfile is actually a symlink and just
        opening up that symlink will not work since it eventually will be
        relinked to a new file and the file handle will be invalid.

        Thats why i open the file the symlink points to. If no newlines
        are being written to that file the symlink is checked again whether
        it has a new target. If so the new logfile is opened and again read
        line by line producing LogEvent instances.
        """
        seek_file = True
        while True:
            real_node_log = self.get_real_node_logfile()
            lines_read = 0
            with open(real_node_log, "r", 1, "utf-8") as fp:
                logger.info("Opened %s", real_node_log)
                # Avoid reading through old node.log on fresh start
                if seek_file:
                    logger.debug("Seek to end of file")
                    fp.seek(0, 2)
                    seek_file = False
                while True:
                    new_lines = fp.readlines()
                    # Create logevents from lines
                    logevents = map(
                        lambda line: LogEvent.from_logline(
                            line, self.app_config.masked_addresses, self.start_time
                        ),
                        new_lines,
                    )
                    # Filter out None's
                    logevents = [event for event in logevents if event is not None]

                    # Check if the current slot is too old. If it is, sleep
                    # a while and start over. This is important for when the node
                    # is syncing from scratch and producing alot of old logevents.
                    if self.slot_is_too_old(logevents):
                        time.sleep(250)
                        seek_file = True
                        break

                    # Yield all events
                    # logger.debug(f"Found {len(logevents)} logevents")
                    yield from logevents

                    # If no new_lines are returned check if the symlink changed
                    # If it did not change, wait and retry readlines()
                    # If it did change, return to outer while and restart
                    if not new_lines and (
                        real_node_log.name != self.get_real_node_logfile().name
                    ):
                        logger.info("Symlink changed")
                        break
                    time.sleep(0.5)
