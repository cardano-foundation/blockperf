[![Nix](https://github.com/cardano-foundation/blockperf/actions/workflows/nix.yml/badge.svg)](https://github.com/cardano-foundation/blockperf/actions/workflows/nix.yml)

# Cardano blockperf

Cardano blockperf constantly reads the cardano-node logfiles and measures block
propagation times in the network as seen from that node. The data created will
be sent to an MQTT Broker for collection and further analysis. The Broker
currently runs on AWS' IoT Core Platform and is operated by the Cardano Foundation.
Aggregated data sets of all single nodes' data points are published here on a daily basis: <https://data.blockperf.cardanofoundation.org/>
A visualized version will be publicly available soon.

If you want to contribute your nodes' propagation times, please get in touch with
the Cardano Foundation's OPS & Infrastructure team to receive your blockperf client certificate.
Most valuable are nodes located in geographically remote locations or outside hotspots.

## Configuration of cardano-node

For blockperf to be able to work you need to change the following
in the cardano-node configuration.

* Make the node log to a json file

```json
"defaultScribes": [
    [
      "FileSK",
      "/opt/cardano/cnode/logs/node.json"
    ]
]

"setupScribes": [
    {
    "scFormat": "ScJson",
    "scKind": "FileSK",
    "scName": "/opt/cardano/cnode/logs/node.json"
    }
]
```

* Enable tracers

The default configuration files from <https://book.world.dev.cardano.org/environments.html> have some tracers enabled. You need to enable the following:

```json
"TraceChainSyncClient": true,
"TraceBlockFetchClient": true,
```

## Installing blockperf

To install blockperf you need to clone it from the github repository. I recommend
you use a virtualenv. The topic of virtual environments in python can be daunting
if you are new to it. The way i would reccomend is the most simple way of creating
virtual environments by using the builtin venv module (examples see below)
<https://docs.python.org/3/library/venv.html>. This creates lightweight python
environments with their own installation path so you dont need to install things
in your system python environmnet. However, the way you install blockperf is
up to you, its just a python package after all.

```bash
# Create the folder you want blockperf to live in
# cd into it and clone the repo
mkdir -p /opt/blockperf
cd /opt/blockperf
git clone git@github.com:cardano-foundation/blockperf.git .

# Create a venv and activate it.
python3 -m venv .venv
source .venv/bin/activate

# Install blockperf via pip
pip install .

# Test it by issuing the command, it should print some help ...
blockperf --help
```

> **Note**
> You must activate the virtual environment everytime you want to work with
> blockperf. See docs if you are new to virtual environments:
> <https://docs.python.org/3/tutorial/venv.html>

**Test your installation**

```bash
# Remember to activate the virtual environment if not in the same shell as above
# source .venv/bin/activate
blockperf run
```

## Configuration of blockperf

To configure blockperf configure the following environment variables

```bash
# Path to you cardano-node's config
BLOCKPERF_NODE_CONFIG="/opt/cardano/cnode/files/config.json"
# Path to your cardano-node's logfile
BLOCKPERF_NODE_LOGFILE="/opt/cardano/cnode/logs/node.json"
# The public ip address your node is reachable at
BLOCKPERF_RELAY_PUBLIC_IP="x.x.x.x"
# your client identifier, will be given to you with the certificates
BLOCKPERF_NAME="XX"
# path to your client certificate file
BLOCKPERF_CLIENT_CERT="XXX"
# path to your client key file
BLOCKPERF_CLIENT_KEY="XXX"
# Comma separated list of ip addresses that you do not want to share
# You will most likely want to add your block producing node's ip address here
BLOCKPERF_MASKED_ADDRESSES="x.x.x.x,x.x.x.x"
# path to amazons ca file in pem format, find it here: https://www.amazontrust.com/repository/AmazonRootCA1.pem
BLOCKPERF_AMAZON_CA="XXX"
```

You could put all of the above in a file `/etc/default/blockperf` and then
have your shell load that with

```bash
set -a
source /etc/default/blockperf
```

**Systemd service**

A simple example of blockperf as service unit. Remember to set the
executable to blockperf within the virtual environment you have installed it in!

```ini
[Unit]
Description=Blockperf.py

[Service]
Type=simple
Restart=always
RestartSec=20
User=ubuntu
EnvironmentFile=/etc/default/blockperf
ExecStart=/opt/cardano/cnode/blockperf/.venv/bin/blockperf run
KillSignal=SIGINT
SyslogIdentifier=blockperf
TimeoutStopSec=5
```

## Development

* Create venv and activate if you have not yet already

```bash
python3 -m venv .venv
```

* Install development dependencies

```bash
pip install -r dev_requirements.txt
```

* Run tests

```bash
pytest
```

* run mypy

```bash
# prior to running mypy you need to install thes types from 3rd party libraries
pip install types-paho-mqtt
pip install types-psutil

# Then run mypy
mypy src
```
