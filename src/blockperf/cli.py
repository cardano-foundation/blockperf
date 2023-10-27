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


def setup_logger():
    logger_config = yaml.safe_load(ROOTDIR.joinpath("logger.yaml").read_text())
    dictConfig(logger_config)

'''
def configure_logging(debug: bool = False):
    """Configures the root logger"""
    # Configure blockperf logger
    lvl = logging.DEBUG if debug else logging.INFO
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    formatter.datefmt = "%Y-%m-%d %H:%M:%S"
    stdout_handler = logging.StreamHandler()
    stdout_handler.setLevel(lvl)
    stdout_handler.setFormatter(formatter)
    logging.basicConfig(level=lvl, handlers=[stdout_handler])
'''


@click.group()
def main():
    """
    This script is based on blockperf.sh which collects data from the cardano-node
    and sends it to an aggregation services for further analysis.
    """
    # dont print() but click.echo()
    logger.info("Does main actually run with click?")
    logger.info("Do i even need click? ")



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
def cmd_run(config_file_path=None, verbose=False, debug=False):
    # configure_logging(debug)
    logger.info(os.getcwd())
    setup_logger()

    if already_running():
        click.echo(f"Is blockperf already running?")
        raise SystemExit

    if debug:
        click.echo("Debug enabled")


    app_config = AppConfig(config_file_path)
    app_config.check_blockperf_config()
    app = App(app_config)
    app.run()


main.add_command(cmd_run)
