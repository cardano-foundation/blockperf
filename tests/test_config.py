import os
import pytest
import json
import blockperf
from blockperf.config import AppConfig, ConfigError


def test_config_file_defaults():
    with pytest.raises(SystemExit):
        app_config = AppConfig(None)
        assert (
            app_config.node_config_file.as_posix()
            == "/opt/cardano/cnode/files/config.json"
        )
        assert app_config.node_configdir.as_posix() == "/opt/cardano/cnode/files"


def _test_other():
    os.environ["BLOCKPERF_NODE_CONFIG"] = "/this/config/does/not/exist"
    app_config = AppConfig(None)
    with pytest.raises(ConfigError) as e:
        config_file = app_config.node_config_file
        # assert config_file


def _test_shelley_genesis_file():
    app_config = AppConfig(None)
    _f = app_config._shelley_genesis_file
    assert _f == "shelley-genesis.json"


def test_active_slot_coef():
    with pytest.raises(SystemExit):
        app_config = AppConfig(None)
