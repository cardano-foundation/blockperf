"""
App Configuration is done either via Environment variables or the stdlib
configparser module.
"""

import base64
import hashlib
import ipaddress
import json
import logging
import os
import sys
from configparser import ConfigParser
from pathlib import Path
from typing import Union

from blockperf import __version__ as blockperf_version

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    pass


BROKER_HOST = "a12j2zhynbsgdv-ats.iot.eu-central-1.amazonaws.com"
BROKER_PORT = 8883
BROKER_KEEPALIVE = 180
LEGACY_TRACING = "True"
PUBLISH = "True"
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
            f"Publish:         {self.publish}\n"
            f"Legacy Tracing:  {self.legacy_tracing}\n"
            f"Node config:     {self.node_config_file}\n"
            f"Node logfile:    {self.node_logfile}\n"
            f"Client Name:     {self.name}\n"
            f"Client ID:       {self.clientid}\n"
            f"Networkmagic:    {self.network_magic}\n"
            f"Public IP:       {self.relay_public_ip}:{self.relay_public_port}\n"
            f"Version:         v{blockperf_version}\n"
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

        if self.publish is True:
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
        if self.legacy_tracing:
            if self.node_config.get("UseTraceDispatcher", {}) != False:  # noqa: E712
                logger.error(
                    'The legacy tracing system does not appear to be in use as "UseTraceDispatcher" is not declared false'
                )
                logger.error(
                    "Please adjust your node configuration or the BLOCKPERF_LEGACY_TRACING environment var and try again"
                )
                sys.exit()

            assert self.node_config.get("TraceChainSyncClient", False), (
                "TraceChainSyncClient not enabled"
            )

            assert self.node_config.get("TraceBlockFetchClient", False), (
                "TraceBlockFetchClient not enabled"
            )

            # What are the other possible values? This should allow everything that is above Normal
            assert self.node_config.get("TracingVerbosity", "") in (
                "NormalVerbosity",
                "MaximalVerbosity",
            ), "TracingVerbosity must be NormalVerbosity or MaximalVerbosity"
        else:

            def checkCfg(target, level, inheritPath, cfg):
                details = cfg.get("details", None)
                maxFrequency = cfg.get("maxFrequency", None)
                severity = cfg.get("severity", None)

                error = False

                if details not in ["DNormal", "DDetailed", "DMaximum"]:
                    logger.error(
                        f"For tracer '{target}' the {level} was found, but details of '{details}' is not DNormal, DDetailed, DMaximum"
                    )
                    error = True

                if maxFrequency not in [0, None]:
                    logger.error(
                        f"For tracer '{target}' the {level} was found, but maxFrequency of '{maxFrequency}' is not 0.0 or undeclared"
                    )
                    error = True

                if severity not in ["Info", "Debug"]:
                    logger.error(
                        f"For tracer '{target}' the {level} was found, but severity of '{severity}' is not Info or Debug"
                    )
                    error = True

                if level != "target":
                    logger.warning(
                        f"Ideal config for TraceOptions tracer '{target}' is to declare it rather than inherit from {level} of '{inheritPath}' with:"
                    )
                    logger.warning(
                        f'{{"{target}":{{"details":"DNormal","maxFrequency":0.0,"severity":"Info"}}'
                    )
                elif error:
                    logger.error(
                        f"Ideal config for TraceOptions tracer '{target}' is to declare it explicitly with:"
                    )
                    logger.error(
                        f'{{"{target}":{{"details":"DNormal","maxFrequency":0.0,"severity":"Info"}}'
                    )

                if error:
                    sys.exit()

            requiredTraceOptions = [
                "BlockFetch.Client.CompletedBlockFetch",
                "BlockFetch.Client.SendFetchRequest",
                "ChainDB.AddBlockEvent.AddedToCurrentChain",
                "ChainDB.AddBlockEvent.SwitchedToAFork",
                "ChainSync.Client.DownloadedHeader",
            ]

            if self.node_config.get("UseTraceDispatcher", {}) == False:  # noqa: E712
                logger.error(
                    'The legacy tracing system appears to be in use as "UseTraceDispatcher" is declared false'
                )
                logger.error(
                    "Please adjust your node configuration or the BLOCKPERF_LEGACY_TRACING environment var and try again"
                )
                sys.exit()

            cfg = self.node_config.get("TraceOptions", {})

            # Given that default values for node tracer config may drift over
            # time, let's depend on explicit node config to verify expected
            # functionality.
            if not cfg:
                logger.error("TraceOptions are empty in the node config")
                logger.error("A 'Forwarder' backend is required to log to file")
                logger.error("TraceOptions tracer declarations also required are:")
                logger.error(" ".join(requiredTraceOptions))
                sys.exit()

            root = cfg.get("", {})

            if "Forwarder" not in root.get("backends", []):
                logger.warning(
                    "A 'Forwarder' is not defined in the 'TraceOptions.\"\".backends' list"
                )
                logger.warning(
                    "In this case, an explicit 'Forwarder' backend will need to be declared or inherited to each required tracer:"
                )
                logger.warning(" ".join(requiredTraceOptions))

            for tracer in requiredTraceOptions:
                parent = ".".join(tracer.split(".")[0:2])
                grandparent = tracer.split(".")[0]

                if tCfg := cfg.get(tracer, {}):
                    logger.info(f"Found tracer {tracer}")
                    checkCfg(tracer, "target", tracer, tCfg)

                elif pCfg := cfg.get(parent, {}):
                    logger.info(f"Found tracer parent {parent}")
                    checkCfg(tracer, "parent", parent, pCfg)

                elif gCfg := cfg.get(grandparent, {}):
                    logger.info(f"Found tracer grandparent {grandparent}")
                    checkCfg(tracer, "grandparent", grandparent, gCfg)

                elif root:
                    logger.info(f"Found tracer root {root}:")
                    checkCfg(tracer, "root", '""', root)

                else:
                    logger.error(
                        f"Tracer '{tracer}' not found explictly or implicitly via inheritence, please declare it"
                    )
                    sys.exit()

    @property
    def clientid(self) -> str:
        if self.publish is True:
            certid = ""
            with open(self.client_cert, mode="r") as f:
                cert_string = "".join(f.readlines()[1:-1])
                certid = hashlib.sha256(base64.b64decode(cert_string)).hexdigest()
            return certid
        else:
            return ""

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
    def publish(self) -> bool:
        publish = os.getenv(
            "BLOCKPERF_PUBLISH",
            self.config_parser.get(
                "DEFAULT",
                "publish",
                fallback=PUBLISH,
            ),
        )
        return publish == "True"

    @property
    def legacy_tracing(self) -> bool:
        legacy_tracing = os.getenv(
            "BLOCKPERF_LEGACY_TRACING",
            self.config_parser.get(
                "DEFAULT",
                "legacy_tracing",
                fallback=LEGACY_TRACING,
            ),
        )
        return legacy_tracing == "True"

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

    @property
    def prometheus_endpoint(self) -> [str, None]:
        has_prometheus = self.node_config.get("hasPrometheus")
        if (
            not has_prometheus
            or not isinstance(has_prometheus, list)
            or not len(has_prometheus) == 2
            or not isinstance(has_prometheus[1], int)
        ):
            return None
        return f"http://127.0.0.1:{has_prometheus[1]}/metrics"
