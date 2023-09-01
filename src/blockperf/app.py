import collections
import json
import logging
import queue
import os
import threading
import time
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
        producer_thread.join()
        consumer_thread.join()

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
            payload = self.mqtt_payload_from(blocksample)
            LOG.debug(json.dumps(payload, indent=4, sort_keys=True, ensure_ascii=False))
            self.print_block_stats(blocksample)
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
        """Producer thread that reads the logfile and puts blocksamples to queue.

        The for loop runs forever over all the events produced from the logfile.

        """
        adopting_block_kinds = (
            LogEventKind.ADDED_TO_CURRENT_CHAIN,
            LogEventKind.SWITCHED_TO_A_FORK,
        )
        for event in self.logevents():
            _block_hash = event.block_hash
            assert _block_hash, f"Found event that has no hash {event}!"
            # If the same hash has already been seen and published, dont bother
            if _block_hash in self.published_hashes:
                continue

            LOG.debug(event)
            if not _block_hash in self.recorded_events:
                LOG.debug(
                    f"Creating new list for {event.block_hash_short}. {len(self.recorded_events)}"
                )
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
            self.published_hashes.append(_block_hash)
            if len(self.published_hashes) >= 10:
                # Remove from left; Latest 10 hashes published will be in deque
                removed_hash = self.published_hashes.popleft()
                # Delete that events for hash from recorded_events
                del self.recorded_events[removed_hash]
                LOG.debug(f"Removed {removed_hash} from published_hashes")

            LOG.debug(
                f"Recorded blocks: {len(self.recorded_events.keys())} \n[{' '.join([ h[0:10] for h in self.recorded_events.keys()])}]"
            )
            LOG.debug(f"Published hash queue size {len(self.published_hashes)}")

    def logevents(self):
        """Generator that yields new lines from the logfile as they come in.

        The node writes events to its logfile. This function constantly reads
        that file and yields the lines as they come in. But it will only yield
        a given event/line if:
            * It is not older then MAX_EVENT_AGE
            * It is of one of the interesting kinds

        The logfile configured is a symlink. Instead of opening the symlink
        the file it points to is opened. The node will eventually create
        a new logfile and the opened file will not receive new entries.
        When no new lines are read from readline() checks whether the logfile
        has changed and opens the new one.
        """
        interesting_kinds = (
            LogEventKind.TRACE_DOWNLOADED_HEADER,
            LogEventKind.SEND_FETCH_REQUEST,
            LogEventKind.COMPLETED_BLOCK_FETCH,
            LogEventKind.ADDED_TO_CURRENT_CHAIN,
        )
        node_log = self.app_config.node_logfile
        if not node_log.exists():
            LOG.critical(f"{node_log} does not exist!")
            raise SystemExit
        LOG.debug(f"Found node_logfile at {node_log}")
        while True:
            real_node_log = self.app_config.node_logdir.joinpath(os.readlink(node_log))
            same_file = True
            with open(real_node_log, "r") as fp:
                fp.seek(0, 2)
                LOG.debug(f"Opened {real_node_log}")
                while same_file:
                    new_line = fp.readline()
                    if not new_line:
                        # if no new_line is returned check if the symlink changed
                        if real_node_log.name != os.readlink(node_log):
                            LOG.debug(
                                f"Symlink changed from {real_node_log.name} to {os.readlink(node_log)} "
                            )
                            same_file = False
                        time.sleep(0.1)
                        continue

                    # Create LogEvent from the new line provided
                    event = LogEvent.from_logline(new_line)
                    if not event: # JSON Error decoding that line
                        continue
                    # Make sure that we do not get too old events. For that the
                    # config setting max_event_age sets a limit in seconds
                    # within which a given event is considered valid. If it is
                    # older then max_avent_age seconds ago, it should be discarded.
                    # In other words: The timestamp of the event needs to be
                    # higher (later in time) then what max_age is.
                    LOG.debug(f"{event}")
                    bad_before = int(datetime.now().timestamp()) - int(
                        timedelta(seconds=self.app_config.max_event_age).total_seconds()
                    )
                    if int(event.at.timestamp()) < bad_before:
                        continue

                    if not event.kind in interesting_kinds:
                        continue

                    # There is an event, that is not too old and its
                    # of a kind that we are interested in -> yield it!
                    yield (event)
