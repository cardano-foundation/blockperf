import os
import pytest
from blockperf.config import AppConfig, ConfigError


def test_config_file():
    # Testing the default
    config = AppConfig(None)
    config_file = config.node_config_file
    assert config_file.as_posix() == "/opt/cardano/cnode/files/config.json"

    os.environ["BLOCKPERF_NODE_CONFIG"] = "/this/config/does/not/exist"
    with pytest.raises(ConfigError):
        config = AppConfig(None)
        config_file = config.node_config_file




