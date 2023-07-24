import fcntl
import logging
import os
from pathlib import Path

import click

from blockperf import logger_name
from blockperf.app import App
from blockperf.config import AppConfig

LOCKFILE = "/run/lock/blockperf.lock"


def configure_logging(debug: bool = False):
    # Configure blockperf logger
    lvl = logging.DEBUG if debug else logging.INFO
    #logger = logging.getLogger(logger_name)
    stdout_handler = logging.StreamHandler()
    stdout_handler.setLevel(lvl)
    #stdout_handler.formatter = logging.Formatter(
    #    fmt="%(name)s %(threadName)s [%(asctime)s %(levelname)s] %(message)s",
    #    datefmt='%H:%M:%S'
    #)
    #logger.addHandler(stdout_handler)
    logging.basicConfig(
        level=lvl,
        handlers=[stdout_handler]
    )



def already_running() -> bool:
    """Checks if an instance is already running, exitst if it does!
    Will not work on windows since fcntl is unavailable there!!
    """
    lock_file_fp = open(LOCKFILE, "a")
    try:
        # Try to get exclusive lock on lockfile
        fcntl.lockf(lock_file_fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_file_fp.seek(0)
        lock_file_fp.truncate()
        lock_file_fp.write(str(os.getpid()))
        lock_file_fp.flush()
        # Could acquire lock, return False
        return False
    except (IOError, BlockingIOError):
        # Could not acquire lock; Assuming its already running
        # Maybe implement some --force flag to override?
        return True


@click.group()
def main():
    """Blockperf.py - Cardano-network block performance measurement and analysis.

    This script is based on blockperf.sh which collects data from the cardano-node
    and sends it to an aggregation services for further analysis.
    """
    # dont print() but click.echo()
    #click.echo("Main runs")
    pass


@click.command("run", short_help="Runs blockperf")
@click.argument(
    "config_file_path", required=False, type=click.Path(resolve_path=True, exists=True)
)
@click.option("-d", "--debug", is_flag=True, help="Enables debug mode (print even more than verbose)")
def cmd_run(config_file_path=None, verbose=False, debug=False):
    """Run blockperf with given configuration"""
    try:
        click.echo("Starting blockperf")
        if already_running():
            click.echo(f"Could not acquire lock on {LOCKFILE}; Is it already running?")
            raise SystemExit

        if debug:
            click.echo("Debug enabled")

        configure_logging(debug)
        app_config = AppConfig(config_file_path)
        app = App(app_config)
        app.run()
    except Exception:
        logging.exception(f"Exception occured")

main.add_command(cmd_run)
