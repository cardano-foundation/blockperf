# Cardano blockPerf in python

## Installation

Clone repositoy into /opt/cardano/cnode/blockperf and run the install.sh script.

```
cd /opt/cardano/cnode
git clone git@github.com:cardano-foundation/blockperf.git

# cd into that directory and run the install script
cd blockperf
./install.sh
```

This will create a virtual environment in `/opt/cardano/cnode/blockperf/venv`.








```
ERROR: File "setup.py" not found. Directory cannot be installed in editable mode: /home/msch/src/cf/blockperf.py
(A "pyproject.toml" file was found, but editable mode currently requires a setup.py based build.)
```

## Configuration

Get your own IP: `curl -sf https://ipinfo.io/ip/`


## Notes from install in the dc

* Based on minimal ubuntu jammy 22.04

```
# for venv install
apt install python3.10-venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Configure the node

You will need a node.config with these settings enabled:

> Provide list of important config values to be set for blockperf to work.
> Or link to a sample one based on the current release of the node.

###


