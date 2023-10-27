"""
App Configuration is done either via Environment variables or the stdlib
configparser module.
"""
import sys
import ipaddress
import json
import os
from configparser import ConfigParser
from pathlib import Path
from typing import Union


class ConfigError(Exception):
    pass

# Maximum age of logfile event in seconds, events older then this are discarded
MAX_EVENT_AGE = 600
BROKER_URL = "a12j2zhynbsgdv-ats.iot.eu-central-1.amazonaws.com"
BROKER_PORT = 8883
BROKER_KEEPALIVE = 180
ROOTDIR = Path(__file__).parent

class AppConfig:
    config_parser: ConfigParser

    def __init__(self, config_file: Union[Path, None], verbose=False):
        self.config_parser = ConfigParser()
        if config_file:
            self.config_parser.read(config_file)
        self.verbose = verbose

    def check_blockperf_config(self):
        """Try to check whether or not everything that is fundamentally needed
            is actually configured, by asking for its value and triggering
            the implemented failer if not found.
        """
        self.node_config_file
        self.node_logdir
        self.name
        self.relay_public_ip
        self.client_cert
        self.client_key

        # Check for needed config values
        assert self.node_config.get("TraceChainSyncClient", False), "TraceChainSyncClient not enabled"
        assert self.node_config.get("TraceBlockFetchClient", False), "TraceBlockFetchClient not enabled"
        # What are the other possible values? This should allow everything that is above Normal
        assert self.node_config.get("TracingVerbosity", "") == "NormalVerbosity", "TracingVerbosity not enabled"

    @property
    def node_config_file(self) -> Path:
        node_config_file = os.getenv(
            "BLOCKPERF_NODE_CONFIG",
            self.config_parser.get(
                "DEFAULT",
                "node_config",
                fallback="/opt/cardano/cnode/files/config.json",
            ),
        )
        return Path(node_config_file)

    @property
    def node_config(self) -> dict:
        """Return Path to config.json file from env var, ini file or builtin default"""
        return json.loads(self.node_config_file.read_text())

    @property
    def mqtt_publish_timeout(self) -> int:
        """Timeout for publishing new blockperfs to broker"""
        mqtt_publish_timeout = os.getenv(
            "BLOCKPERF_MQTT_PUBLISH_TIMEOUT",
            self.config_parser.get(
                "DEFAULT",
                "mqtt_publish_timeout",
                fallback=5,
            )
        )
        return int(mqtt_publish_timeout)

    @property
    def node_configdir(self) -> Path:
        """Return Path to directory of config.json"""
        return self.node_config_file.parent

    @property
    def node_logdir(self) -> Path:
        return self.node_logfile.parent

    @property
    def node_logfile(self) -> Path:
        """Node logfile from env variable or read out of the config"""
        node_logfile = os.getenv("BLOCKPERF_NODE_LOGFILE")
        if node_logfile:
            node_logfile = Path(node_logfile)
        else:
            for ss in self.node_config.get("setupScribes", []):
                if ss.get("scFormat") == "ScJson" and ss.get("scKind") == "FileSK":
                    node_logfile = Path(ss.get("scName"))
                    break
        if not node_logfile:
            raise ConfigError(f"Logfile not given")
        return node_logfile

    @property
    def _shelley_genesis_file(self) -> Path:
        return self.node_config.get("ShelleyGenesisFile", None)

    @property
    def _shelley_genesis_data(self) -> dict:
        _f = self.node_configdir.joinpath(self._shelley_genesis_file)
        return json.loads(_f.read_text())

    @property
    def network_magic(self) -> int:
        """Retrieve network magic from ShelleyGenesisFile"""
        return int(self._shelley_genesis_data.get("networkMagic", 0))

    @property
    def active_slot_coef(self) -> float:
        active_slot_coef = self._shelley_genesis_data.get("activeSlotsCoeff", None)
        if not active_slot_coef:
            raise ConfigError("Error retrieving activeSlotsCoef from shelley-genesis")
        return float(active_slot_coef)

    @property
    def relay_public_ip(self) -> str:
        relay_public_ip = os.getenv(
            "BLOCKPERF_RELAY_PUBLIC_IP",
            self.config_parser.get("DEFAULT", "relay_public_ip", fallback=None),
        )
        if not relay_public_ip:
            raise ConfigError("'relay_public_ip' not set!")
        return relay_public_ip

    @property
    def relay_public_port(self) -> int:
        relay_public_port = int(
            os.getenv(
                "BLOCKPERF_RELAY_PUBLIC_PORT",
                self.config_parser.get("DEFAULT", "relay_public_port", fallback=3001),
            )
        )
        return relay_public_port

    @property
    def client_cert(self) -> str:
        client_cert = os.getenv(
            "BLOCKPERF_CLIENT_CERT",
            self.config_parser.get("DEFAULT", "client_cert", fallback=None),
        )
        if not client_cert:
            raise ConfigError("No client_cert set")
        return client_cert

    @property
    def client_key(self) -> str:
        client_key = os.getenv(
            "BLOCKPERF_CLIENT_KEY",
            self.config_parser.get("DEFAULT", "client_key", fallback=None),
        )
        if not client_key:
            raise ConfigError("No client_key set")
        return client_key

    @property
    def name(self) -> str:
        name = os.getenv(
            "BLOCKPERF_NAME",
            self.config_parser.get("DEFAULT", "name", fallback=None),
        )
        if not name:
            raise ConfigError("No name set")
        return name

    @property
    def topic_version(self) -> str:
        topic_base = os.getenv(
            "BLOCKPERF_TOPIC_VERSION",
            self.config_parser.get("DEFAULT", "topic_version", fallback="v1"),
        )
        return topic_base

    @property
    def topic(self) -> str:
        """"""
        return f"cf/blockperf/{self.topic_version}/{self.network_magic}/{self.name}/{self.relay_public_ip}"

    @property
    def masked_addresses(self) -> list:
        masked_addresses = os.getenv(
            "BLOCKPERF_MASKED_ADDRESSES",
            self.config_parser.get(
                "DEFAULT",
                "masked_addresses",
                fallback=None,
            )
        )
        if masked_addresses:
            _validated_addresses = list()
            # String split and return list
            for addr in masked_addresses.split(","):
                try:
                    ipaddress.ip_address(addr)
                    _validated_addresses.append(addr)
                except ValueError:
                    raise ConfigError(f"Given address {addr} is not a valid ip address")
            return _validated_addresses
        return list()

    @property
    def node_service_unit(self) -> str:
        node_service_unit = os.getenv(
            "BLOCKPERF_NODE_SERVICE_UNIT",
            self.config_parser.get(
                "DEFAULT",
                "node_service_unit",
                fallback="cardano-node.service",
            )
        )
        return node_service_unit