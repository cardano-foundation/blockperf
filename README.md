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
...
"setupScribes": [
    {
    "scFormat": "ScJson",
    "scKind": "FileSK",
    "scName": "/opt/cardano/cnode/logs/node.json",
    }
]
```

* Enable a bunch of tracers

I am not aware of a reference of all the trace options in the config.
But basically what you need to enable for now is the following.

```json
"TraceAcceptPolicy": true,
"TraceBlockFetchClient": true,
"TraceBlockFetchDecisions": true,
"TraceChainDb": true,
"TraceChainSyncClient": true,
"TraceConnectionManager": true,
"TraceDNSResolver": true,
"TraceDNSSubscription": true,
"TraceDiffusionInitialization": true,
"TraceErrorPolicy": true,
"TraceForge": true,
"TraceInboundGovernor": true,
"TraceIpSubscription": true,
"TraceLedgerPeers": true,
"TraceLocalErrorPolicy": true,
"TraceLocalRootPeers": true,
"TraceMempool": true,
"TracePeerSelection": true,
"TracePeerSelectionActions": true,
"TracePublicRootPeers": true,
"TraceServer": true,
"TracingVerbosity": "NormalVerbosity",
"TurnOnLogMetrics": true,
"TurnOnLogging": true,
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
# Point to your local cardano-node config
BLOCKPERF_NODE_CONFIG="/opt/cardano/cnode/files/config.json"
# The ip address your relay is reachable at
BLOCKPERF_RELAY_PUBLIC_IP="x.x.x.x"
# your client identifier, will be given to you with the certificates
BLOCKPERF_OPERATOR="XX"
# path to your client certificate
BLOCKPERF_CLIENT_CERT="XXX"
# path to your client key
BLOCKPERF_CLIENT_KEY="XXX"
# path of the topic you will publish to. Leave this as "blockperf" for now
BLOCKPERF_TOPIC_BASE="blockperf"

# The following may be set but are not required, defaults are shown in examples
# port your relay listens on
# BLOCKPERF_RELAY_PUBLIC_PORT="3001"
# Timeout for mqtt publishing
# BLOCKPERF_MQTT_PUBLISH_TIMEOUT="5"
# broker url to publish to
# BLOCKPERF_BROKER_URL="a12j2zhynbsgdv-ats.iot.eu-central-1.amazonaws.com"
```

**With ini file**

Write a file blockperf.ini. The config values are the same as the env vars
except being lower case without the leading `BLOCKPERF_`. All values must
reside in the DEFAULT section of the file.

```ini
[DEFAULT]
node_config=/opt/cardano/cnode/files/config.json
relay_public_ip = x.x.x.x
operator = xx
client_cert = /path/to/certificate.pem
client_key = /path/to/private.key
topic_base = blockperf
```

## Runnin blockperf



**From the command line**

```bash
# If you have set up the env vars
blockperf run
# Or specify the ini file
blockperf run /path/to/config.ini
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
