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

import paho.mqtt.client as mqtt

from blockperf import __version__ as blockperf_version
from blockperf import logger_name
from blockperf.config import AppConfig
from blockperf.sampling import BlockSample, LogEvent, LogEventKind

LOG = logging.getLogger(logger_name)
MQTTLOG = logging.getLogger("MQTT")


class App:
    q: queue.Queue
    app_config: AppConfig
    node_config: dict
    _mqtt_client: mqtt.Client

    recorded_events = dict()  # holds a list of events for each block_hash
    published_hashes = collections.deque()

    def __init__(self, config: AppConfig) -> None:
        self.q = queue.Queue(maxsize=20)
        self.app_config = config

    def run(self):
        """Run the App by creating the two threads and starting them."""
        producer_thread = threading.Thread(target=self.blocksample_producer, args=())
        producer_thread.start()
        # LOG.info("Producer thread started")

        # consumer = BlocklogConsumer(queue=self.q, app_config=self.app_config)
        consumer_thread = threading.Thread(target=self.blocksample_consumer, args=())
        consumer_thread.start()
        # LOG.info("Consumer thread started")

        # Blocks main thread until all joined threads are finished
        LOG.info(f"App starting producer and consumer threads")
        producer_thread.join()
        consumer_thread.join()
        LOG.info(f"App finished run().")

    @property
    def mqtt_client(self) -> mqtt.Client:
        # Returns the mqtt client, or creates one if there is none
        if not hasattr(self, "_mqtt_client"):
            LOG.info("(Re)Creating new mqtt client")
            # Every new client will start clean unless client_id is specified
            self._mqtt_client = mqtt.Client(protocol=mqtt.MQTTv5)
            self._mqtt_client.on_connect = self.on_connect_callback
            self._mqtt_client.on_disconnect = self.on_disconnect_callback
            self._mqtt_client.on_publish = self.on_publish_callback
            self._mqtt_client.on_log = self.on_log

            # tls_set has an argument 'ca_certs'. I used to provide a file
            # whith one of the certificates from https://www.amazontrust.com/repository/
            # But from readig the tls_set() code i suspect when i leave that out
            # thessl.SSLContext will try to autodownload that CA!?
            self._mqtt_client.tls_set(
                # ca_certs="/tmp/AmazonRootCA1.pem",
                certfile=self.app_config.client_cert,
                keyfile=self.app_config.client_key,
            )
        return self._mqtt_client

    def on_connect_callback(
        self, client, userdata, flags, reasonCode, properties
    ) -> None:
        """Called when the broker responds to our connection request.
        See paho.mqtt.client.py on_connect()"""
        if not reasonCode == 0:
            LOG.error("Connection error " + str(reasonCode))
            self._mqtt_connected = False
        else:
            self._mqtt_connected = True

    def on_disconnect_callback(self, client, userdata, reasonCode, properties) -> None:
        """Called when disconnected from broker
        See paho.mqtt.client.py on_disconnect()"""
        LOG.error(f"Connection lost {reasonCode}")

    def on_publish_callback(self, client, userdata, mid) -> None:
        """Called when a message is actually received by the broker.
        See paho.mqtt.client.py on_publish()"""
        # There should be a way to know which messages belongs to which
        # item in the queue and acknoledge that specifically
        # self.q.task_done()
        pass
        # LOG.debug(f"Message {mid} published to broker")

    def on_log(self, client, userdata, level, buf):
        """
        client:     the client instance for this callback
        userdata:   the private user data as set in Client() or userdata_set()
        level:      gives the severity of the message and will be one of
                    MQTT_LOG_INFO, MQTT_LOG_NOTICE, MQTT_LOG_WARNING,
                    MQTT_LOG_ERR, and MQTT_LOG_DEBUG.
        buf:        the message itself
        """
        MQTTLOG.debug(f"{level} - {buf}")

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
        LOG.info("\n" + msg)

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
                LOG.exception("Exception in blocksample_consumer; Restarting Loop")

    def _blocksample_consumer(self):
        """Consumer thread that listens to the queue and published each sample
        the the consumer puts into it."""
        self.mqtt_client
        broker_url, broker_port = (
            self.app_config.mqtt_broker_url,
            self.app_config.mqtt_broker_port,
        )
        LOG.debug(f"Connecting to {broker_url}:{broker_port}")
        self.mqtt_client.connect(broker_url, broker_port)
        self.mqtt_client.loop_start()  # Starts thread for pahomqtt to process messages
        # Sometimes the connect took a moment to settle. To not have
        # the consumer accept messages (and not be able to publish)
        # i decided to ensure the connection is established this way
        while not self.mqtt_client.is_connected:
            LOG.debug("Waiting for mqtt connection ... ")
            time.sleep(0.5)  # Wait until connected to broker

        while True:
            LOG.debug(f"Waiting for next item in queue, Current size: {self.q.qsize()}")
            blocksample = self.q.get()
            self.print_block_stats(blocksample)

            payload = self.mqtt_payload_from(blocksample)
            LOG.debug(json.dumps(payload, indent=4, sort_keys=True, ensure_ascii=False))
            start_publish = timer()
            message_info = self.mqtt_client.publish(
                topic=self.app_config.topic, payload=json.dumps(payload, default=str)
            )
            # blocks until timeout is reached
            message_info.wait_for_publish(self.app_config.mqtt_publish_timeout)
            end_publish = timer()
            publish_time = end_publish - start_publish
            self.last_slot_time = blocksample.slot_time
            if self.app_config.verbose:
                LOG.info(
                    f"Published {blocksample.block_hash_short} with mid='{message_info.mid}' to {self.app_config.topic} in {publish_time}"
                )
            if publish_time > float(self.app_config.mqtt_publish_timeout):
                LOG.error("Publish timeout reached")

    def blocksample_producer(self):
        while True:
            try:
                self._blocksample_producer()
            except Exception:
                LOG.exception("Exception in blocksample_producer; Restarting Loop")

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
                LOG.debug(
                    f"New hash {event.block_hash_short}"
                )
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
                    LOG.debug(f"Removed {removed_hash} from published_hashes")
                else:
                    LOG.warning(f"Hash not found in recorded_events for deletion '{removed_hash}'")
            LOG.debug(f"Recorded blocks {len(self.recorded_events.keys())} - Published blocks {len(self.published_hashes)}")

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
                    LOG.warning(f"Node log file does not exist '{node_log_link}'")
                    time.sleep(10)
                try:
                    real_node_log = os.path.realpath(node_log_link, strict=True)
                    # LOG.debug(f"Resolved {node_log_link} to {real_node_log}")
                    return self.app_config.node_logdir.joinpath(real_node_log)
                except OSError:
                    LOG.warning(f"Real node log not found from link '{node_log_link}'")
                    time.sleep(10)

        interesting_kinds = (
            LogEventKind.TRACE_DOWNLOADED_HEADER,
            LogEventKind.SEND_FETCH_REQUEST,
            LogEventKind.COMPLETED_BLOCK_FETCH,
            LogEventKind.ADDED_TO_CURRENT_CHAIN,
            LogEventKind.SWITCHED_TO_A_FORK
        )
        first_loop = True
        while True:
            real_node_log = _real_node_log()
            same_file = True
            with open(real_node_log, "r") as fp:
                # Only seek to the end of the file, if we just did a "fresh" start
                if first_loop == True:
                    fp.seek(0, 2)
                    first_loop = False
                LOG.debug(f"Opened {real_node_log}")
                while same_file:
                    new_line = fp.readline()
                    if not new_line:
                        # if no new_line is returned check if the symlink changed
                        if real_node_log.name != _real_node_log().name:
                            LOG.debug( f"Symlink changed" )
                            same_file = False
                        time.sleep(0.1)
                        continue
                    # Create LogEvent from the new line provided
                    event = LogEvent.from_logline(new_line, masked_addresses=self.app_config.masked_addresses)
                    if not event: # JSON Error decoding that line
                        continue
                    LOG.debug(event)
                    bad_before = int(datetime.now().timestamp()) - int(
                        timedelta(seconds=self.app_config.max_event_age).total_seconds()
                    )
                    # Too old event
                    if int(event.at.timestamp()) < bad_before:
                        continue
                    # Uninteresting event
                    if not event.kind in interesting_kinds:
                        continue
                    # Nice event, yield it
                    yield (event)
