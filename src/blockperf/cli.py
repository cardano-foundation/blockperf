import sys
from pathlib import Path

import click

from blockperf.app import App
from blockperf.config import AppConfig

# Either config setting work out of config.json


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enables verbose mode")
def main(verbose):
    """Main CLI Entrypoint."""
    click.echo("Main runs")
    pass


@click.command("run", short_help="Run blockPerf")
@click.argument(
    "config_file_path", required=True, type=click.Path(resolve_path=True, exists=True)
)
# @pass_environment
def cmd_run(config_file_path):
    """Runs blockPerf"""
    app = App(AppConfig(config_file_path))
    app.run()


main.add_command(cmd_run)
# main.add_command(check.cli)
