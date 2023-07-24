import logging
from pathlib import Path

import click
import psutil

from blockperf import logger_name
from blockperf.app import App
from blockperf.config import AppConfig

LOCKFILE = Path("/run/lock/blockperf.lock")


def already_running():
    blockperfs = []
    for proc in psutil.process_iter():
        if "blockperf" in proc.name():
            blockperfs.append(proc)
    if len(blockperfs) > 1:
        return True
    return False

def configure_logging(debug: bool = False):
    # Configure blockperf logger
    lvl = logging.DEBUG if debug else logging.INFO
    stdout_handler = logging.StreamHandler()
    stdout_handler.setLevel(lvl)
    logging.basicConfig(
        level=lvl,
        handlers=[stdout_handler]
    )

@click.group()
def main():
    """Blockperf.py - Cardano-network block performance measurement and analysis.

    This script is based on blockperf.sh which collects data from the cardano-node
    and sends it to an aggregation services for further analysis.
    """
    # dont print() but click.echo()
    pass


@click.command("run", short_help="Runs blockperf")
@click.argument(
    "config_file_path", required=False, type=click.Path(resolve_path=True, exists=True)
)
@click.option("-d", "--debug", is_flag=True, help="Enables debug mode (print even more than verbose)")
def cmd_run(config_file_path=None, verbose=False, debug=False):
    """Run blockperf with given configuration"""

    click.echo(f"Starting blockperf {LOCKFILE}")
    if already_running():
        click.echo(f"Is blockperf already running?")
        raise SystemExit
    if debug:
        click.echo("Debug enabled")
    configure_logging(debug)
    app_config = AppConfig(config_file_path)
    app = App(app_config)
    app.run()


main.add_command(cmd_run)
