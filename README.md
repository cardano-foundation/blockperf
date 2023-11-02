# Cardano blockperf

Cardano blockperf is a tool that constantly reads the cardano-node logfiles
to get measurements of block propagation in the network.

The data created from the logs will be sent to an MQTT Broker and collected for
further analysis. The Broker currently runs on AWS' IoT Core Platform.

## Configuration of cardano-node

For blockperf to be able to parse the logfiles you need to change the following
in the cardano-node configuration file.

* Make the node log to a json file

We do want to support a journald in blockperf, but for now we need to have
a file on disk that the cardano-node logs to.

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

The default configuration files from https://book.world.dev.cardano.org/environments.html
do already have tracers enabled. But you do need to enable the following as well:

```json
"TraceChainSyncClient": true,
"TraceBlockFetchClient": true,
```


## Installaing blockperf

* Below are the typical steps you would do to get it up and running
* It should not be that hard, clone the python code and get it to run
* You dont need to use pythons venv module but i would recommend you do.

```bash
# Create the folder you want blockperf to live in, cd into it and clone the repo
#
mkdir -p /opt/blockperf
cd /opt/blockperf
git clone git@github.com:cardano-foundation/blockperf.git .

# Create the venv, activate it and install blockperf via pip
python3 -m venv venv
source venv/bin/activate
pip install .

# Test it by issuing the command, it should print some help ...
blockperf --help
```

This will create a virtual environment in `/opt/blockperf/venv/`and install
blockperf in it. You will need to activate the environment everytime you
want to work with blockperf. See docs if you are new to virtual environments:
https://docs.python.org/3/tutorial/venv.html

> **Note**
> Install via pypi.org is not a thing until now, but i definetly want to
> have it at some point



## Configuration of blockperf

Blockperf needs some configuration to work. You can either write an ini
file for that or provide the values via environment variables.

**With environment variables**

```bash
# The following are all required to operate
# Your local cardano-node config
BLOCKPERF_NODE_CONFIG="/opt/cardano/cnode/files/config.json"
# The logfile the cardano-node is writing to, Usualy the symlink node.json
BLOCKPERF_NODE_LOGFILE="/opt/cardano/cnode/logs/node.json"
# The ip address your relay is reachable at
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

# The following may be set but are not required, defaults are shown in examples
# port your relay listens on
# BLOCKPERF_RELAY_PUBLIC_PORT="3001"
# Timeout for mqtt publishing
# BLOCKPERF_MQTT_PUBLISH_TIMEOUT="5"
# broker url to publish to
# BLOCKPERF_BROKER_URL="a12j2zhynbsgdv-ats.iot.eu-central-1.amazonaws.com"
```

## Running blockperf

**From the command line**

```bash
# If you have set up the env vars
blockperf run
```

**As a systemd service**

See a simple example of the service unit below. Remember to set the
executable to blockperf within the environment you have installed it in!

```
[Unit]
Description=Blockperf.py

[Service]
Type=simple
Restart=always
RestartSec=20
User=ubuntu
EnvironmentFile=/etc/default/blockperf
ExecStart=/opt/cardano/cnode/blockperf/venv/bin/blockperf run
KillSignal=SIGINT
SyslogIdentifier=blockperf
TimeoutStopSec=5
```

In the above example is an EnvironmentFile defined that sets the environment
variables from above. You could also just provide a path to the ini with
the run command. However: The environment variables will override the ini file
values.

## Receive client identifier, certificate and key

Our plan is to have a somehwat automated process that leverages CIP-22 to
have SPOs be able to identify themselves and retrieve certificates.
However, that is not in place right now so currently it is a  very manual
approach. Just ping me (Manuel) if you need to get one or create a new one.
