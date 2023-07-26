# Cardano blockperf

Cardano blockperf is a tool that measures block propagation times in the network
as seen from the local node. It reads the cardano-node logs and determines
timings of blocks that are produced and distributed in the network.

The data created from the logs will be sent to an MQTT Broker and collected for
further analysis. The Broker currently runs on AWS' IoT Core Platform.

## Installation

* Clone repositoy, create virtualenv and install package

```bash
mkdir -p /opt/blockperf
cd opt/blockperf
git clone git@github.com:cardano-foundation/blockperf.git

# cd into that directory and run the install script
cd blockperf
python -m venv venv
source venv/bin/activate
pip install .
```

This will create a virtual environment in `venv/`and install blockperf in it.
You will need to activate the environment everytime you want to work with
blockperf. See docs if you are new to virtual environments:
https://docs.python.org/3/tutorial/venv.html

* Install via pypi.org

Installing this package via pypi will eventually become available. Currently
installing from source is the only option.

## Usage/Configuration

Blockperf needs some configuration to work.

* Via environment variables:

```bash
# The following are all required to operate
# Point to your local node config
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
# BLOCKPERF_RELAY_PUBLIC_PORT="3001"  # port your relay listens on
# BLOCKPERF_MQTT_PUBLISH_TIMEOUT="5"    # Timeout for mqtt publishing
# BLOCKPERF_BROKER_URL="a12j2zhynbsgdv-ats.iot.eu-central-1.amazonaws.com"  # broker to publish to
```

* Via an ini file

All the values

```ini
[DEFAULT]
node_config=/opt/cardano/cnode/files/config.json
relay_public_ip = 213.216.27.62
operator = devmanuel
client_cert = /home/msch/src/cf/blockperf.py/tmp/devmanuel-certificate.pem
client_key = /home/msch/src/cf/blockperf.py/tmp/devmanuel-private.key
topic_base = blockperf
```

All values must reside in the DEFAULT section of the file. The names are similar
to the variables with the leading BLOCKPERF_ and written in lowercase.

```bash
blockperf run   # To use the environmentvariables for config
blockperf run /path/to/config.ini   # to use the ini configuration
```

## Writing a service unit

See a simple example of the service unit below. Remember to set the
executable to blockperf within the environment you have installed it in.

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

While we do plan to provide a more automated aproach it is currently a very manual
approach. Just ping me (Manuel) if you need to get one or create a new one.

