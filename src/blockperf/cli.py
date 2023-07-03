import sys
from pathlib import Path
import logging
import click

from blockperf import logger_name
from blockperf.app import App
from blockperf.config import AppConfig

# Either config setting work out of config.json

logging.basicConfig(
    level=logging.DEBUG,
    filename='/home/ubuntu/src/blockperf/blockperf.log',
    filemode='w',
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt='%H:%M:%S'
)

LOG = logging.getLogger(logger_name)

@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enables verbose mode")
def main(verbose):
    """Blockperf.py - Cardano-network block performance measurement and analysis.

    This script is based off of blockperf.sh which collects certain metrics from
    the cardano-node and sends it to an aggregation services for further
    analysis.
    """
    # dont print() but click.echo()
    click.echo("Main runs")
    pass


@click.command("run", short_help="Runs blockperf with given configuration")
@click.argument(
    "config_file_path", required=True, type=click.Path(resolve_path=True, exists=True)
)
def cmd_run(config_file_path):
    """Run blockperf with given configuration"""
    LOG.info("Start blockperf")
    app = App(AppConfig(config_file_path))
    app.run()
    LOG.info("Goodbye!")

main.add_command(cmd_run)
