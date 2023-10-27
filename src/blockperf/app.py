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
from pprint import pprint

try:
    from systemd import journal
except ImportError:
    sys.exit(
        "This script needs python3-systemd package.\n"
        "https://pypi.org/project/systemd-python/\n\n"
    )

try:
    import paho.mqtt.client as mqtt
    from paho.mqtt.properties import Properties
    from paho.mqtt.packettypes import PacketTypes
except ImportError:
    sys.exit(
        "This script needs paho-mqtt package.\n"
        "https://pypi.org/project/paho-mqtt/\n\n"
    )

from blockperf import __version__ as blockperf_version
from blockperf.config import AppConfig, MAX_EVENT_AGE
from blockperf.blocksample import BlockSample
from blockperf.nodelogs import LogEventKind, LogEvent
from blockperf.mqtt import MQTTClient


logger = logging.getLogger(__name__)


class App:
    q: queue.Queue
    app_config: AppConfig
    node_config: dict
    mqtt_client: MQTTClient

    recorded_events = dict()  # holds a list of events for each block_hash
    published_hashes = collections.deque()

    def __init__(self, config: AppConfig) -> None:
        self.q = queue.Queue(maxsize=20)
        self.app_config = config
        self.mqtt_client = MQTTClient()
        self.mqtt_client.tls_set(
            # ca_certs="/tmp/AmazonRootCA1.pem",
            certfile=self.app_config.client_cert,
            keyfile=self.app_config.client_key,
        )
        self.mqtt_client.run()

    def run(self):
        """Run the App by creating the two threads and starting them."""
        producer_thread = threading.Thread(target=self.blocksample_producer, args=())
        producer_thread.start()
        # logger.info("Producer thread started")

        # consumer = BlocklogConsumer(queue=self.q, app_config=self.app_config)
        consumer_thread = threading.Thread(target=self.blocksample_consumer, args=())
        consumer_thread.start()
        # logger.info("Consumer thread started")

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
            f".......... {blocksample.slot_time.strftime('%Y-%m-%d %H:%M:%S')}\n"  # Assuming this is the slot_time
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
                print("Call consumer")
                self._blocksample_consumer()
            except Exception:
                logger.exception("Exception in blocksample_consumer; Restarting Loop")

    def _blocksample_consumer(self):
        """
        Consumer thread that listens to the queue and published each sample the the consumer puts into it.
        """
        #self.mqtt_client
        #broker_url, broker_port = (
        #    self.app_config.mqtt_broker_url,
        #    self.app_config.mqtt_broker_port,
        #)
        #logger.debug(f"Connecting to {broker_url}:{broker_port}")
        #self.mqtt_client.connect(broker_url, broker_port)
        #self.mqtt_client.loop_start()  # Starts thread for pahomqtt to process messages

        # Sometimes the connect took a moment to settle. To not have
        # the consumer accept messages (and not be able to publish)
        # i decided to ensure the connection is established this way
        while not self.mqtt_client.is_connected:
            logger.debug("Waiting for mqtt connection ... ")
            time.sleep(0.5)  # Wait until connected to broker

        while True:
            logger.debug(f"Waiting for next item in queue, Current size: {self.q.qsize()}")
            blocksample = self.q.get()
            self.print_block_stats(blocksample)

            payload = self.mqtt_payload_from(blocksample)
            logger.debug(json.dumps(payload, indent=4, sort_keys=True, ensure_ascii=False))
            start_publish = timer()

            publish_properties = Properties(PacketTypes.PUBLISH)
            publish_properties.MessageExpiryInterval=3600
            message_info = self.mqtt_client.publish(
                topic=f"{self.app_config.topic}/{blocksample.block_hash}",
                payload=json.dumps(payload, default=str),
                properties=publish_properties
            )
            # blocks until timeout is reached
            message_info.wait_for_publish(self.app_config.mqtt_publish_timeout)
            end_publish = timer()
            publish_time = end_publish - start_publish
            self.last_slot_time = blocksample.slot_time
            if self.app_config.verbose:
                logger.info(
                    f"Published {blocksample.block_hash_short} with mid='{message_info.mid}' to {self.app_config.topic} in {publish_time}"
                )
            if publish_time > float(self.app_config.mqtt_publish_timeout):
                logger.error("Publish timeout reached")

    def blocksample_producer(self):
        while True:
            try:
                print("calling producer")
                self._blocksample_producer()
            except Exception:
                logger.exception("Exception in blocksample_producer; Restarting Loop")

    def _blocksample_producer(self):
        """Producer thread that reads the logfile and puts blocksamples to queue.

        The for loop runs forever over all the events produced from the logfile.
        Not all events seen in the logfile will make it into the for loop below.
        See logevents(). The ones that do are stored.
        For every new hash seen a new list ist created and all subsequent events
        will be added to it. The list itself will be stored in a dictionary
        called self.recorded_events. The key for the dictionary is the blockhash
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
        adopting_block_kinds = (
            LogEventKind.ADDED_TO_CURRENT_CHAIN,
            LogEventKind.SWITCHED_TO_A_FORK,
        )
        for event in self.logevents():
            _block_hash = event.block_hash
            assert _block_hash, f"Found event that has no hash {event}!"

            if not _block_hash in self.recorded_events:
                logger.debug("New hash %s", event.block_hash_short)
                # A new hash is seen, make a new list to store its events in
                self.recorded_events[_block_hash] = list()
            self.recorded_events[_block_hash].append(event)

            # If the current event is not indicating that a block has been added
            # to the chain dont bother; Move on to the next
            if event.kind not in adopting_block_kinds:
                continue

            # If block is added create a BlockSample and publish it
            events = self.recorded_events[_block_hash]
            new_sample = BlockSample(events, self.app_config)
            self.q.put(new_sample)
            # Add hash to right side of deque
            self.published_hashes.append(_block_hash)
            if len(self.published_hashes) > self.app_config.active_slot_coef * 3600:
                # Remove from left of deque
                removed_hash = self.published_hashes.popleft()
                # Delete events for hash from recorded_events
                if removed_hash in self.recorded_events:
                    del self.recorded_events[removed_hash]
                    logger.debug("Removed %s from published_hashes", removed_hash)
                else:
                    logger.warning("Hash not found in recorded_events for deletion %s", removed_hash)
            logger.debug("Recorded blocks %s - Published blocks %s", len(self.recorded_events.keys()), len(self.published_hashes))

    def logevents_systemd(self):
        """Generator that produces LogEvent Instances by reading the journald
        """
        jr = journal.Reader()
        _service_unit = self.app_config.node_service_unit
        jr.add_match(_SYSTEMD_UNIT=_service_unit)
        logger.debug("Listeing to service unit: %s", _service_unit)
        jr.log_level(journal.LOG_DEBUG)
        jr.seek_realtime(datetime.now())
        while True:
            event = jr.wait()
            if event == journal.APPEND:
                for entry in jr:
                    message = entry["MESSAGE"]
                    event = LogEvent.from_logline(message, masked_addresses=self.app_config.masked_addresses)
                    if not event: # JSON Error decoding that line
                        continue
                    logger.debug(event)

                    # Filter out events that are too far from the past
                    bad_before = int(datetime.now().timestamp()) - int(
                        timedelta(seconds=MAX_EVENT_AGE).total_seconds()
                    )
                    if int(event.at.timestamp()) < bad_before:
                        continue

                    # Only yield event of a specific kind
                    if event.kind in (
                        LogEventKind.TRACE_DOWNLOADED_HEADER,
                        LogEventKind.SEND_FETCH_REQUEST,
                        LogEventKind.COMPLETED_BLOCK_FETCH,
                        LogEventKind.ADDED_TO_CURRENT_CHAIN,
                        LogEventKind.SWITCHED_TO_A_FORK
                    ):
                        yield event

    def logevents(self):
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

        def _real_node_log() -> Path:
            """Read the link that node_log points to and return the file path
            """
            while True:
                node_log_link = self.app_config.node_logfile
                if not node_log_link.exists():
                    logger.warning("Node log file does not exist %s", node_log_link)
                    time.sleep(10)
                try:
                    real_node_log = os.path.realpath(node_log_link, strict=True)
                    # logger.debug(f"Resolved {node_log_link} to {real_node_log}")
                    return self.app_config.node_logdir.joinpath(real_node_log)
                except OSError:
                    logger.warning("Real node log not found from link %s", node_log_link)
                    time.sleep(10)

        first_loop = True
        while True:
            real_node_log = _real_node_log()
            same_file = True
            with open(real_node_log, "r") as fp:
                # Only seek to the end of the file, if we just did a "fresh" start
                if first_loop == True:
                    fp.seek(0, 2)
                    first_loop = False
                logger.debug("Opened %s", real_node_log)
                while same_file:
                    new_line = fp.readline()
                    if not new_line:
                        # if no new_line is returned check if the symlink changed
                        if real_node_log.name != _real_node_log().name:
                            logger.debug("Symlink changed" )
                            same_file = False
                        time.sleep(0.1)
                        continue

                    # Create LogEvent from the new line provided
                    event = LogEvent.from_logline(
                        new_line,
                        masked_addresses=self.app_config.masked_addresses
                    )
                    if event:
                        yield event
                else:
                    # Currently opened logfile has change try to read all of the
                    # rest in one go!
                    logger.debug("Reading the rest of it ... !!! ")
                    for line in fp.readlines():

                        event = LogEvent.from_logline(
                            line,
                            masked_addresses=self.app_config.masked_addresses
                        )
                        if event:
                            yield event
