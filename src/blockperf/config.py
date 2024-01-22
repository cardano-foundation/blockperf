"""
App Configuration is done either via Environment variables or the stdlib
configparser module.
"""
import ipaddress
import json
import os
import sys
import logging
from configparser import ConfigParser
from pathlib import Path
from typing import Union

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    pass


BROKER_HOST = "a12j2zhynbsgdv-ats.iot.eu-central-1.amazonaws.com"
BROKER_PORT = 8883
BROKER_KEEPALIVE = 180
ROOTDIR = Path(__file__).parent


class AppConfig:
    """App Configuration class provides a common interface to access all kinds
    of configuration values.
    """

    config_parser: ConfigParser

    def __init__(self, config_file: Union[Path, None] = None, verbose=False):
        self.config_parser = ConfigParser()
        if config_file:
            self.config_parser.read(config_file)
        self.verbose = verbose
        self.check_blockperf_config()
        msg = (
            f"\n----------------------------------------------------\n"
            f"Node config:   {self.node_config_file}\n"
            f"Node logfile:  {self.node_logfile}\n"
            f"Client Name:   {self.name}\n"
            f"Networkmagic:  {self.network_magic}\n"
            f"Public IP:     {self.relay_public_ip}:{self.relay_public_port}\n"
            # f"..... {blocksample.block_delay} sec\n\n"
            f"----------------------------------------------------\n\n"
        )
        sys.stdout.write(msg)

    def check_blockperf_config(self):
        """Try to check whether or not everything that is fundamentally needed
        is actually configured, by asking for its value and triggering
        the implemented failer if not found.
        """
        if not self.node_config_file or not self.node_config_file.exists():
            logger.error(
                "Node config '%s' config does not exist", self.node_config_file
            )
            sys.exit()

        if not self.node_logfile or not self.node_logfile.exists():
            logger.error("Node logfile '%s' does not exist", self.node_logfile)
            sys.exit()

        # logdir is taken from the .parent of node_logfile
        if not self.node_logdir or not self.node_logdir.exists():
            logger.error("Node logdir '%s' does not exist", self.node_logdir)
            sys.exit()

        if not self.name:
            logger.error("NAME is not set")
            sys.exit()

        if not self.relay_public_ip:
            logger.error("RELAY_PUBLIC_IP is not set")
            sys.exit()

        if not Path(self.client_cert).exists():
            logger.error("Client cert '%s' does not exist", self.client_cert)
            sys.exit()

        if not Path(self.client_key).exists():
            logger.error("Client key '%s' does not exist", self.client_key)
            sys.exit()

        if not Path(self.amazon_ca).exists():
            logger.error("Amazon CA '%s' does not exist", self.amazon_ca)
            sys.exit()

        if self.active_slot_coef <= 0.0:
            logger.error("Could not retrieve active_slot_coef")
            sys.exit()

        # Check for needed config values
        assert self.node_config.get(
            "TraceChainSyncClient", False
        ), "TraceChainSyncClient not enabled"
        assert self.node_config.get(
            "TraceBlockFetchClient", False
        ), "TraceBlockFetchClient not enabled"
        # What are the other possible values? This should allow everything that is above Normal
        assert (
            self.node_config.get("TracingVerbosity", "")
            in ("NormalVerbosity", "MaximalVerbosity"),
        ), "TracingVerbosity not enabled"

    @property
    def broker_host(self) -> str:
        broker_host = os.getenv(
            "BLOCKPERF_BROKER_HOST",
            self.config_parser.get(
                "DEFAULT",
                "broker_host",
                fallback=BROKER_HOST,
            ),
        )
        return broker_host

    @property
    def broker_port(self) -> int:
        broker_port = os.getenv(
            "BLOCKPERF_BROKER_PORT",
            self.config_parser.get(
                "DEFAULT",
                "broker_port",
                fallback=BROKER_PORT,
            ),
        )
        return int(broker_port)

    @property
    def broker_keepalive(self) -> int:
        return BROKER_KEEPALIVE

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
    def node_configdir(self) -> Path:
        """Return Path to directory of config.json"""
        return self.node_config_file.parent

    @property
    def node_logdir(self) -> Union[Path, None]:
        if not self.node_logfile:
            return None
        return self.node_logfile.parent

    @property
    def node_logfile(self) -> Union[Path, None]:
        """Node logfile from env variable or read
        Idealy this would look into the config to determine the logfile from there

        e.g.:
        for ss in self.node_config.get("setupScribes", []):
           if ss.get("scFormat") == "ScJson" and ss.get("scKind") == "FileSK":
               node_logfile = Path(ss.get("scName"))
               break
        """
        node_logfile = os.getenv("BLOCKPERF_NODE_LOGFILE", None)
        if not node_logfile:
            return None
        return Path(node_logfile)

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
        active_slot_coef = self._shelley_genesis_data.get("activeSlotsCoeff", 0.0)
        return float(active_slot_coef)

    @property
    def relay_public_ip(self) -> str:
        relay_public_ip = os.getenv(
            "BLOCKPERF_RELAY_PUBLIC_IP",
            self.config_parser.get("DEFAULT", "relay_public_ip", fallback=""),
        )
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
            self.config_parser.get("DEFAULT", "client_cert", fallback=""),
        )
        return client_cert

    @property
    def client_key(self) -> str:
        client_key = os.getenv(
            "BLOCKPERF_CLIENT_KEY",
            self.config_parser.get("DEFAULT", "client_key", fallback=""),
        )
        return client_key

    @property
    def amazon_ca(self) -> str:
        amazon_ca = os.getenv(
            "BLOCKPERF_AMAZON_CA",
            self.config_parser.get("DEFAULT", "amazon_ca", fallback=""),
        )
        return amazon_ca

    @property
    def name(self) -> str:
        name = os.getenv(
            "BLOCKPERF_NAME",
            self.config_parser.get("DEFAULT", "name", fallback=""),
        )
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
    def node_service_unit(self) -> str:
        node_service_unit = os.getenv(
            "BLOCKPERF_NODE_SERVICE_UNIT",
            self.config_parser.get(
                "DEFAULT",
                "node_service_unit",
                fallback="cardano-node.service",
            ),
        )
        return node_service_unit

    @property
    def max_concurrent_blocks(self) -> float:
        return self.active_slot_coef * 3600

    @property
    def masked_addresses(self) -> list:
        _masked_addresses = os.getenv("BLOCKPERF_MASKED_ADDRESSES", None)
        if not _masked_addresses:
            return []

        validated_addresses = []
        # String split and return list
        for addr in _masked_addresses.split(","):
            try:
                _addr = addr.strip()
                ipaddress.ip_address(_addr)
                validated_addresses.append(_addr)
            except ValueError as exc:
                raise ConfigError(
                    f"Given address {addr} is not a valid ip address"
                ) from exc
        return validated_addresses
