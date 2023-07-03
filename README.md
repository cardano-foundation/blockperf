# Cardano blockPerf in python

## Installation

* Clone repositoy into /opt/cardano/cnode/blockperf and run the install.sh script.

```
cd /opt/cardano/cnode
git clone git@github.com:cardano-foundation/blockperf.git

# cd into that directory and run the install script
cd blockperf
./install.sh
```

This will create a virtual environment in `/opt/cardano/cnode/blockperf/venv`.

* Create a configuration file

In the contrib folder is a blockperf.ini example file. Use that file as base
for your own configuration. E.g. copy that file to `/opt/cardano/cnode/blockperf/blockperf.ini`.
In the file are some explanations for what each settings does.

* Create the service

In the contrib folder is a blockperf.service example file. Copy it over
to the /etc/systemd/system folder and enable the service.


## Configuration

### Configure the node

You will need a node.config with these settings enabled:

> Provide list of important config values to be set for blockperf to work.
> Or link to a sample one based on the current release of the node.

###


