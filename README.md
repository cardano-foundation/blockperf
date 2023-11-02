# Cardano blockperf

Cardano blockperf constantly reads the cardano-node logfiles and measures block
propagation times in the network as seen from that node. The data created will
be sent to an MQTT Broker for collection and further analysis. The Broker
currently runs on AWS' IoT Core Platform.

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

The default configuration files from https://book.world.dev.cardano.org/environments.html have some tracers enabled. You need to enable the following:

```json
"TraceChainSyncClient": true,
"TraceBlockFetchClient": true,
```

## Installaing blockperf

To install blockperf

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
> https://docs.python.org/3/tutorial/venv.html


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
# path to amazons ca file in pem format, find it here: https://www.amazontrust.com/repository/
# https://www.amazontrust.com/repository/AmazonRootCA1.pem
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

## Receive client identifier, certificate and key

Our plan is to have a somehwat automated process that leverages CIP-22 to
have SPOs be able to identify themselves and retrieve certificates.
However, that is not in place right now so currently it is a  very manual
approach. Just ping me (Manuel) if you need to get one or create a new one.
