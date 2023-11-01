"""CLI Entrypoint for blockperf"""
import logging
from logging.config import dictConfig
import argparse
import sys
import os
from typing import Union
from pathlib import Path

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
                "level": "DEBUG",
                "handlers": ["logfile"]
            }
        },
        "root": {
            "level": level,
            "handlers": ["console"]
        }
    }
    dictConfig(logger_config)


def setup_argparse():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", help="Command to run blockperf with", choices=["run"]
    )
    parser.add_argument("--debug")
    return parser.parse_args()


def main():
    """
    This script is based on blockperf.sh which collects data from the cardano-node
    and sends it to an aggregation services for further analysis.
    """
    args = setup_argparse()
    print(f"args.debug {args.debug}")
    setup_logger(args.debug)

    if args.command == "run":
        cmd_run()
    else:
        sys.exit(f"I dont know what {args.command} means")


def cmd_run(config_file_path=None):
    # configure_logging(debug)
    logger.info(os.getcwd())

    if already_running():
        sys.exit("Blockperf is already running ... ")

    app_config = AppConfig(config_file_path)
    app_config.check_blockperf_config()
    app = App(app_config)
    app.run()


if __name__ == "__main__":
    main()
