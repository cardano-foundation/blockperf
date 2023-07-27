#!/usr/bin/env python3
import sys
from datetime import datetime

try:
    from systemd import journal
except ImportError:
    sys.stdout.write(
        "This script needs python3-systemd package.\n"
        "e.g.: https://packages.debian.org/bookworm/python3-systemd\n\n"
    )


def main():
    # Open a Reader to connect to journald
    jr = journal.Reader()
    # Specify a matcher, like -u in journalctl
    jr.add_match(_SYSTEMD_UNIT="cardano-node.service")
    # We want everything there is
    jr.log_level(journal.LOG_DEBUG)
    # move to the end
    jr.seek_realtime(datetime.now())
    while True:
        # wait blocks until there is some new event in the reader
        event = jr.wait()
        # Events can be of various kinds, we only want the ones that add stuff
        if event == journal.APPEND:
            # the reader is a generator of entries, give me all of them in a loop
            for entry in jr:
                # the entry has different fields (mostly journald specific)
                # MESSAGE is what was logged
                print(entry["MESSAGE"])

if __name__ == '__main__':
    main()