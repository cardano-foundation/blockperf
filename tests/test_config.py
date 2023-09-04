import os
import pytest
from blockperf.config import AppConfig, ConfigError


def test_config_file():
    # Testing the default
    config = AppConfig(None)
    config_file = config.node_config_file
    assert config_file.as_posix() == "/opt/cardano/cnode/files/config.json"


def _test_other():
    os.environ["BLOCKPERF_NODE_CONFIG"] = "/this/config/does/not/exist"
    with pytest.raises(ConfigError):
        config = AppConfig(None)
        config_file = config.node_config_file

def test_shelley_genesis_file():
    config = AppConfig(None)
    _f = config._shelley_genesis_file
    assert _f == "shelley-genesis.json"

def test_active_slot_coef():
    config = AppConfig(None)
    assert config.active_slot_coef == 0.05