"""CLI Entrypoint for blockperf"""
import logging
from logging.config import dictConfig
import argparse
import sys
import psutil

from blockperf.app import App
from blockperf.config import AppConfig

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
    """Configures logging"""
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
                "datefmt": "%m-%d %H:%M:%S",
            },
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
        "loggers": {"blockperf": {"level": "DEBUG", "handlers": []}},
        "root": {"level": level, "handlers": ["console"]},
    }
    dictConfig(logger_config)


def setup_argparse():
    """Configures argparse"""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", help="Command to run blockperf with", choices=["run"]
    )
    parser.add_argument("--debug", help="Write more debug output", action="store_true")
    return parser.parse_args()


def main():
    """
    This script is based on blockperf.sh which collects data from the cardano-node
    and sends it to an aggregation services for further analysis.
    """
    args = setup_argparse()
    setup_logger(args.debug)
    # Ensure there is only one instance of blockperf running
    if already_running():
        sys.exit("Blockperf is already running")

    app_config = AppConfig()
    app = App(app_config)

    if args.command == "run":
        app.run()
    else:
        sys.exit(f"I dont know what {args.command} means")


if __name__ == "__main__":
    main()
