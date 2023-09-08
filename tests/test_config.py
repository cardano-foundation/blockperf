import os
import pytest
import json
import blockperf
from blockperf.config import AppConfig, ConfigError


def test_config_file_defaults():
    app_config = AppConfig(None)
    assert app_config.node_config_file.as_posix() == "/opt/cardano/cnode/files/config.json"
    assert type(app_config.node_config) == dict
    assert app_config.max_event_age == 600
    assert app_config.mqtt_publish_timeout == 5
    assert app_config.node_configdir.as_posix() == "/opt/cardano/cnode/files"
    assert app_config.node_logdir.as_posix() == "/opt/cardano/cnode/logs"
    assert app_config.node_logfile.as_posix() == "/opt/cardano/cnode/logs/node.json"


def _test_other():
    os.environ["BLOCKPERF_NODE_CONFIG"] = "/this/config/does/not/exist"
    app_config = AppConfig(None)
    with pytest.raises(ConfigError) as e:
        config_file = app_config.node_config_file
        # assert config_file

def test_shelley_genesis_file():
    app_config = AppConfig(None)
    _f = app_config._shelley_genesis_file
    assert _f == "shelley-genesis.json"

def test_active_slot_coef():
    app_config = AppConfig(None)
