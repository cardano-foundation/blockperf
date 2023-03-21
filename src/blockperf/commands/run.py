import click
import time
import sys
import urllib.request
import json
from pprint import pprint

import pathlib
import mmap
from timeit import default_timer as timer

from blockperf.app import App


from timeit import default_timer as timer
start = timer()
# ...
end = timer()
res = end - start # time it took to run


QUERY_INTERVAL = 2

LOGDIR="/Users/msch/src/pyporf/logs"

# https://stackoverflow.com/questions/8151684/how-to-read-lines-from-a-mmapped-file

@click.command("run", short_help="Run blockPerf")
@click.argument("path", required=False, type=click.Path(resolve_path=True))
#@pass_environment
def cli(path):
    """Runs blockPerf"""
    app = App()
    app.run()


def loadlogfiles():
