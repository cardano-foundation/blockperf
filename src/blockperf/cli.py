import logging
from logging.config import dictConfig
import json
import os
import yaml
from typing import Union
from pathlib import Path

import click
import psutil

from blockperf.app import App
from blockperf.config import AppConfig, ROOTDIR

logger = logging.getLogger(__name__)


def already_running() -> bool:
    """Checks if blockperf is already running."""
    blockperfs = []
    for proc in psutil.process_iter():
        if "blockperf" in proc.name():
            blockperfs.append(proc)
    if len(blockperfs) > 1:
        return True
    return False


def setup_logger(debug: bool):
    level = "DEBUG" if debug else "INFO"
    logger_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "simple": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            },
            "extra": {
                "format": "%(asctime)-16s %(name)-8s %(filename)-12s %(lineno)-6s %(funcName)-30s %(levelname)-8s %(message)s",
                "datefmt": "%m-%d %H:%M:%S"
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": level,
                "formatter": "simple",
                "stream": "ext://sys.stdout",
            },
            # "logfile": {
            #    "class": "logging.handlers.RotatingFileHandler",
            #    "level": "DEBUG",
            #    "filename": "blockperf.log",
            #    "formatter": "extra",
            #    "mode": "a",
            #    "maxBytes": 1000000,
            #    "backupCount": 2,
            # }
        },
        "loggers": {
            "blockperf": {
                "handlers": []
            }
        },
        "root": {
            "level": level,
            "handlers": ["console"]
        }
    }
    dictConfig(logger_config)


@click.group()
def main():
    """
    This script is based on blockperf.sh which collects data from the cardano-node
    and sends it to an aggregation services for further analysis.
    """
    pass


@click.command("run", short_help="Run blockperf")
@click.argument(
    "config_file_path", required=False, type=click.Path(resolve_path=True, exists=True)
)
@click.option(
    "-d",
    "--debug",
    is_flag=True,
    help="Enables debug mode (print even more than verbose)",
)
def cmd_run(config_file_path=None, debug=False):
    # configure_logging(debug)
    logger.info(os.getcwd())
    setup_logger(debug)

    if already_running():
        click.echo(f"Is blockperf already running?")
        raise SystemExit

    app_config = AppConfig(config_file_path)
    app_config.check_blockperf_config()
    app = App(app_config)
    app.run()


main.add_command(cmd_run)
