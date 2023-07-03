"""App Configuration based on pythons stdlib configparser module.
Why configparser? Because its simple. There is a blockperf.ini file in the
contrib/ folder which has all options and a short explanation of what they do.
"""
from pathlib import Path
from configparser import ConfigParser
import logging
import sys
import json
#from cryptography import x509
#from cryptography.x509.oid import NameOID


class ConfigError(Exception):
    pass


class AppConfig:
    _config: ConfigParser

    def __init__(self, config: Path):
        self._config = ConfigParser()
        self._config.read(config)

    # def validate_config(self):
    #    node_config_folder = node_config_path.parent
    #    if not node_config_path.exists():
    #        sys.exit(f"Node config not found {node_config_path}!")
    #    self.node_config = json.loads(node_config_path.read_text())

    @property
    def node_config_file(self) -> Path:
        config_file = Path(
            self._config.get(
                "DEFAULT",
                "node_config",
                fallback="/opt/cardano/cnode/files/config.json",
            )
        )
        if not config_file.exists():
            raise ConfigError(f"{config_file} does not exist")
        return config_file

    @property
    def node_config(self) -> dict:
        node_config = self.node_config_file.read_text()
        return json.loads(node_config)

    @property
    def node_logs_dir(self) -> Path:
        log_dir = Path(
            self._config.get(
                "DEFAULT", "node_logs_dir", fallback="/opt/cardano/cnode/logs"
            )
        )
        if not log_dir.exists():
            raise ConfigError(f"{log_dir} does not exist")
        return log_dir

    @property
    def ekg_url(self) -> str:
        return self._config.get("DEFAULT", "ekg_url", fallback="http://127.0.0.1:12788")

    @property
    def network_magic(self) -> int:
        # for now assuming that these are relative paths to config.json
        node_config_folder = self.node_config_file.parent
        shelly_genesis = json.loads(
            node_config_folder.joinpath(
                self.node_config.get("ShelleyGenesisFile")
            ).read_text()
        )
        return int(shelly_genesis.get("networkMagic"))

    @property
    def relay_public_ip(self) -> str:
        relay_public_ip = self._config.get("DEFAULT", "relay_public_ip")
        if not relay_public_ip:
            raise ConfigError("'relay_public_ip' not set!")
        return relay_public_ip

    @property
    def relay_public_port(self) -> int:
        relay_public_port = int(self._config.get("DEFAULT", "relay_public_port", fallback=3001))
        return relay_public_port

    @property
    def client_cert(self) -> str:
        client_cert = self._config.get("DEFAULT", "client_cert")
        if not client_cert:
            raise ConfigError("No client_cert set")
        return client_cert

    @property
    def client_key(self) -> str:
        client_key = self._config.get("DEFAULT", "client_key")
        if not client_key:
            raise ConfigError("No client_key set")
        return client_key

    @property
    def operator(self) -> str:
        operator = self._config.get("DEFAULT", "operator")
        if not operator:
            raise ConfigError("No operator set")
        return operator

    @property
    def lock_file(self) -> str:
        return self._config.get("DEFAULT", "lock_file", fallback="/tmp/blockperf.lock")

    @property
    def topic_base(self) -> str:
        return self._config.get("DEFAULT", "topic_base", fallback="develop")

    @property
    def mqtt_broker_url(self) -> str:
        return str(
            self._config.get(
                "DEFAULT",
                "mqtt_broker_url",
                fallback="a12j2zhynbsgdv-ats.iot.eu-central-1.amazonaws.com",
            )
        )

    @property
    def mqtt_broker_port(self) -> int:
        return int(self._config.get("DEFAULT", "mqtt_broker_port", fallback=8883))

    @property
    def enable_tracelogs(self) -> bool:
        return bool(self._config.get("DEFAULT", "enable_tracelogs", fallback=False))

    @property
    def tracelogs_dir(self) -> str:
        return str(self._config.get("DEFAULT", "tracelogs_dir", fallback=""))

    # def _read_config(self, config: ConfigParser):
    #    """ """
    #    # Try to check whether CN of cert matches given operator
    #    cert = x509.load_pem_x509_certificate(Path(self.client_cert).read_bytes())
    #    name_attribute = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME).pop()
    #    assert (
    #        name_attribute.value == self.operator
    #    ), "Given operator does not match CN in certificate"
