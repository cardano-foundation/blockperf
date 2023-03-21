import click
from blockperf.commands import run
from blockperf.commands import check

@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enables verbose mode")
def main(verbose):
    #click.echo("Main runs")
    #print(verbose)
    pass



main.add_command(run.cli)
#main.add_command(check.cli)
