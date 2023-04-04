# This pulls the version from the installed package only.

import sys
import importlib.metadata

##if sys.version_info >= 3.8:
__version__ = importlib.metadata.version("blockperf")
