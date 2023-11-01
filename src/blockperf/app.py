import sys
import collections
import json
import logging
import queue
import os
import threading
import time
from pathlib import Path
from datetime import datetime, timedelta
from timeit import default_timer as timer

from blockperf import __version__ as blockperf_version
from blockperf.config import AppConfig

from blockperf.blocksample import BlockSample
from blockperf.nodelogs import LogEventKind, LogEvent
from blockperf.mqtt import MQTTClient


logger = logging.getLogger(__name__)


class App:
    q: queue.Queue
    app_config: AppConfig
    node_config: dict
    mqtt_client: MQTTClient

    logevents = {}  # holds a list of events for each block_hash
    published_hashes = collections.deque()

    def __init__(self, config: AppConfig) -> None:
        self.q = queue.Queue(maxsize=50)
        self.app_config = config

    def run(self):
        """Run the App by creating the two threads and starting them."""
        msg = (
            f"\n----------------------------------------------------\n"
            f"Node config:   {self.app_config.node_config_file}\n"
            f"Node logfile:  {self.app_config.node_logfile}\n"
            f"Client Name:   {self.app_config.name}\n"
            f"Networkmagic:  {self.app_config.network_magic}\n"
            # f"..... {blocksample.block_delay} sec\n\n"
            f"----------------------------------------------------\n\n"
        )
        sys.stdout.write(msg)
        self.mqtt_client = MQTTClient(
            ca_certfile=self.app_config.amazon_ca,
            client_certfile=self.app_config.client_cert,
            client_keyfile=self.app_config.client_key,
            host=self.app_config.broker_host,
            port=self.app_config.broker_port,
            keepalive=self.app_config.broker_keepalive
        )

        producer_thread = threading.Thread(
            target=self.blocksample_producer, args=(), daemon=True)
        producer_thread.start()

        consumer_thread = threading.Thread(
            target=self.blocksample_consumer, args=(), daemon=True)
        consumer_thread.start()

        # Blocks main thread until all joined threads are finished
        logger.info("App starting producer and consumer threads")
        producer_thread.join()
        consumer_thread.join()
        logger.info("App finished run().")

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

    def blocksample_consumer(self):
        while True:
            try:
                self._blocksample_consumer()
            except Exception:
                logger.exception(
                    "Exception in blocksample_consumer; Restarting Loop", exc_info=True)

    def _blocksample_consumer(self):
        """Consumer thread publishes each sample the consumer puts into the queue"""

        # Sometimes the connect took a moment to settle. To not have
        # the consumer accept messages (and not be able to publish)
        # i decided to ensure the connection is established this way
        while not self.mqtt_client.is_connected:
            logger.debug("Waiting for mqtt connection ... ")
            time.sleep(0.5)  # Wait until connected to broker

        while True:
            logger.debug(
                "Waiting for next item in queue, Current size: %s", self.q.qsize())
            blocksample = self.q.get()
            self.print_block_stats(blocksample)

            payload = self.mqtt_payload_from(blocksample)
            logger.debug(json.dumps(payload, indent=4,
                         sort_keys=True, ensure_ascii=False))

            # new
            topic = f"{self.app_config.topic}/{blocksample.block_hash}"
            self.mqtt_client.publish(topic, payload)

    def blocksample_producer(self):
        while True:
            try:
                self._blocksample_producer()
            except Exception:
                logger.exception(
                    "Exception in blocksample_producer; Restarting Loop", exc_info=True)

    def _blocksample_producer(self):
        """Producer thread that reads the logfile and puts blocksamples to queue.

        The for loop runs forever over all the events produced from the logfile.
        Not all events seen in the logfile will make it into the for loop below.
        See logevents(). The ones that do are stored.
        For every new hash seen a new list ist created and all subsequent events
        will be added to it. The list itself will be stored in a dictionary
        called self.logevents. The key for the dictionary is the blockhash
        and the value is the list of all events for that hash. Thus only events
        that have a hash can be bubbled up from the logfile.

        Every now and then an event is seen that indicates a block has been
        added to the local chain. When that happens a new BlockSample is created
        from all the events for that given block (hash). The sample is the
        put into the queue and subsequently send over mqtt to the blockperf
        backend.

        The recorded block events need to be delete at some point again. But
        they should not be deleted directly after the blocksample has been
        published. Therfore a deque is created that holds the hashs' of the
        last X published blocks. X is calculated based on the activeSlotCoef
        from the shelley config and the assumption to hold "the last hour" worth
        of blocks. Which currently is 180.
        """
        for event in self.logevents_logfile():
            if event.kind not in (
                LogEventKind.TRACE_DOWNLOADED_HEADER,
                LogEventKind.SEND_FETCH_REQUEST,
                LogEventKind.COMPLETED_BLOCK_FETCH,
                LogEventKind.ADDED_TO_CURRENT_CHAIN,
                LogEventKind.SWITCHED_TO_A_FORK
            ):
                continue

            if not event.is_valid():
                logger.debug("Invalid event %s", event)
                continue

            if not event.block_hash:
                logger.debug("Event %s has no hash", event)
            _block_hash = event.block_hash
            _block_hash_short = event.block_hash_short

            if not _block_hash in self.logevents:
                logger.info("New hash %s", _block_hash_short)
                # A new hash is seen, make a new list to store its events in
                self.logevents[_block_hash] = {}

            # All events recoreded are stored in different lists based
            # on the event kind within logevents.
            if not event.kind in self.logevents[_block_hash]:
                self.logevents[_block_hash][event.kind] = []
            self.logevents[_block_hash][event.kind].append(event)
            logger.debug(event)

            # Do not event try to republish
            if _block_hash in self.published_hashes:
                logger.debug("Already published %s", _block_hash)
                continue

            # Check that all needed events are recorded for current _block_hash
            if not (
                LogEventKind.TRACE_DOWNLOADED_HEADER in self.logevents[_block_hash].keys() and
                LogEventKind.SEND_FETCH_REQUEST in self.logevents[_block_hash].keys() and
                LogEventKind.COMPLETED_BLOCK_FETCH in self.logevents[_block_hash].keys() and (
                    LogEventKind.ADDED_TO_CURRENT_CHAIN in self.logevents[_block_hash].keys(
                    ) or LogEventKind.SWITCHED_TO_A_FORK in self.logevents[_block_hash].keys()
                )
            ):
                logger.debug(
                    "Not all event types collected for hash %s ", _block_hash_short)
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

            logger.info("Sample for %s created", _block_hash_short)
            self.q.put(new_sample)
            # Add hash to right side of deque
            self.published_hashes.append(_block_hash)
            if len(self.published_hashes) > self.app_config.active_slot_coef * 3600:
                # Remove from left of deque
                removed_hash = self.published_hashes.popleft()
                # Delete events for hash from logevents
                if removed_hash in self.logevents:
                    del self.logevents[removed_hash]
                    logger.debug(
                        "Removed %s from published_hashes", removed_hash)
                else:
                    logger.warning(
                        "Hash not found in logevents for deletion %s", removed_hash)
            logger.info("Recorded blocks %s - Published blocks %s",
                        len(self.logevents.keys()), len(self.published_hashes))

    def get_real_node_logfile(self) -> Path:
        """Return the path to the actual logfile that node.log points to"""
        while True:
            node_log_link = self.app_config.node_logfile
            if not node_log_link.exists():
                logger.warning(
                    "Node log file does not exist %s", node_log_link)
                time.sleep(2)
            try:
                real_node_log = os.path.realpath(
                    node_log_link, strict=True)
                return self.app_config.node_logdir.joinpath(real_node_log)
            except OSError:
                logger.warning(
                    "Real node log not found from link %s", node_log_link)
                time.sleep(2)

    def logevents_logfile(self):
        """Generator that "tails" the node log file and parses each. We are
        interested in certain things the node logs that indicate for example
        that a new header was announce by a peer or that the node initiated
        (or completed) the download of a given block. All these events of
        interest will the be yielded to the caller for further processing.
        See blocksample_producer()

        This function will only yield a given event if:
        * It is not older then a certain amount of time.
            For example, if a node needs to catch up to the network,
            it will add a quite a few new Blocks that are old and we are
            not interested in those. The age an event must be under is
            configure with the max_age setting.
        * It is of one of the interesting kinds

        The node writes its logs to a symlink. That will eventually rotate so
        this script can not open that file and receive new lines forever.
        The node will eventually create a new logfile and blockperf will need
        to cope with that. It does so by opening the file the symlink points to
        and constantly checking whether or not the symlinked has changed. If it
        does the new file is opened.

        """
        first_loop = True
        while True:
            real_node_log = self.get_real_node_logfile()
            lines_read = 0
            same_file = True
            with open(real_node_log, "r", 1, "utf-8") as fp:
                # Avoid reading through old node.log on fresh start
                if first_loop:
                    fp.seek(0, 2)
                    first_loop = False
                logger.info("Opened %s", real_node_log)
                while same_file:
                    new_line = fp.readline()
                    if not new_line:
                        # if no new_line is returned check if the symlink changed
                        if real_node_log.name != self.get_real_node_logfile().name:
                            logger.info("Symlink changed")
                            same_file = False
                        time.sleep(0.5)
                        continue
                    lines_read += 1
                    event = LogEvent.from_logline(new_line)
                    if event:
                        yield event

                # Currently opened logfile has change try to read all of the
                # rest in one go!
                # logger.debug("Reading the rest of it ... !!! ")
                # for line in fp.readlines():
                #    event = LogEvent.from_logline(line)
                #    if event:
                #        yield event
                logger.info("Read %s lines from %s ",
                            lines_read, real_node_log)
