# Cardano blockberf

Cardano blockperf is a tool that measures block propagation times in the network
as seen from the local node. It will read the cardano-node's logs and determine
timings of the blocks that are produced and distributed in the network.

The data created from the logs will be sent to an MQTT Broker and collected for
further analysis. The Broker currently runs on AWS' IoT Core Platform.

## Installation/Usage

* Clone repositoy, create virtualenv and install

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


## Configuration

### Configure the node

You will need a node.config with these settings enabled:

> Provide list of important config values to be set for blockperf to work.
> Or link to a sample one based on the current release of the node.

###


