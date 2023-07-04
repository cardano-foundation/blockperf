"""App Configuration based on pythons stdlib configparser module.
Why configparser? Because its simple. There is a blockperf.ini file in the
contrib/ folder which has all options and a short explanation of what they do.
"""
from pathlib import Path
from configparser import ConfigParser
import os
import json


class ConfigError(Exception):
    pass


class AppConfig:
    config_parser: ConfigParser

    def __init__(self, config: Path):
        self.config_parser = ConfigParser()
        self.config_parser.read(config)

    # def validate_config(self):
    #    node_config_folder = node_config_path.parent
    #    if not node_config_path.exists():
    #        sys.exit(f"Node config not found {node_config_path}!")
    #    self.node_config = json.loads(node_config_path.read_text())

    #@property
    #def _node_config_file(self) -> Path:
    #    return node_config

    @property
    def node_config_file(self) -> Path:
        node_config_file = os.getenv(
            "BLOCKPERF_NODE_CONFIG",
            self.config_parser.get(
                "DEFAULT",
                "node_config",
                fallback="/opt/cardano/cnode/files/config.json",
            )
        )
        node_config = Path(node_config_file)
        if not node_config.exists():
            raise ConfigError(f"Could not open {node_config_file}")
        return node_config

    @property
    def node_config(self) -> dict:
        """Return Path to config.json file from env var, ini file or builtin default"""
        return json.loads(self.node_config_file.read_text())

    @property
    def node_configdir(self) -> Path:
        """Return Path to directory of config.json"""
        return self.node_config_file.parent

    @property
    def node_logdir(self) -> Path:
        for ss in self.node_config.get("setupScribes", []):
            if ss.get("scFormat") == "ScJson" and ss.get("scKind") == "FileSK":
                _node_logdir = Path(ss.get("scName")).parent
                return _node_logdir
        else:
            raise ConfigError(f"Could not determine node logdir")

    @property
    def network_magic(self) -> int:
        """Retrieve network magic from ShelleyGenesisFile"""
        shelley_genesis = json.loads(
            self.node_configdir.joinpath(
                self.node_config.get("ShelleyGenesisFile", "")
            ).read_text()
        )
        return int(shelley_genesis.get("networkMagic", 0))

    @property
    def relay_public_ip(self) -> str:
        relay_public_ip = self.config_parser.get("DEFAULT", "relay_public_ip")
        if not relay_public_ip:
            raise ConfigError("'relay_public_ip' not set!")
        return relay_public_ip

    @property
    def relay_public_port(self) -> int:
        relay_public_port = int(self.config_parser.get("DEFAULT", "relay_public_port", fallback=3001))
        return relay_public_port

    @property
    def client_cert(self) -> str:
        client_cert = self.config_parser.get("DEFAULT", "client_cert")
        if not client_cert:
            raise ConfigError("No client_cert set")
        return client_cert

    @property
    def client_key(self) -> str:
        client_key = self.config_parser.get("DEFAULT", "client_key")
        if not client_key:
            raise ConfigError("No client_key set")
        return client_key

    @property
    def operator(self) -> str:
        operator = self.config_parser.get("DEFAULT", "operator")
        if not operator:
            raise ConfigError("No operator set")
        return operator

    @property
    def lock_file(self) -> str:
        return self.config_parser.get("DEFAULT", "lock_file", fallback="/tmp/blockperf.lock")

    @property
    def topic_base(self) -> str:
        return self.config_parser.get("DEFAULT", "topic_base", fallback="develop")

    @property
    def mqtt_broker_url(self) -> str:
        return str(
            self.config_parser.get(
                "DEFAULT",
                "mqtt_broker_url",
                fallback="a12j2zhynbsgdv-ats.iot.eu-central-1.amazonaws.com",
            )
        )

    @property
    def mqtt_broker_port(self) -> int:
        return int(self.config_parser.get("DEFAULT", "mqtt_broker_port", fallback=8883))

    @property
    def enable_tracelogs(self) -> bool:
        return bool(self.config_parser.get("DEFAULT", "enable_tracelogs", fallback=False))

    @property
    def tracelogs_dir(self) -> str:
        return str(self.config_parser.get("DEFAULT", "tracelogs_dir", fallback=""))

    # def _read_config(self, config: ConfigParser):
    #    """ """
    #    # Try to check whether CN of cert matches given operator
    #    cert = x509.load_pem_x509_certificate(Path(self.client_cert).read_bytes())
    #    name_attribute = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME).pop()
    #    assert (
    #        name_attribute.value == self.operator
    #    ), "Given operator does not match CN in certificate"
