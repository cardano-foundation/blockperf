[![Nix](https://github.com/cardano-foundation/blockperf/actions/workflows/nix.yml/badge.svg)](https://github.com/cardano-foundation/blockperf/actions/workflows/nix.yml)

# Cardano blockperf

Blockperf measures block propagation times in the network. By reading the nodes
log file (watching for specific traces in it) it is able to tell when and from
where block header/body arrived or block has been adopted. This data is then send
to a backend run by the Cardano Foundation for further analyzation.

Aggregated data sets of all single nodes' data points are published on a daily
basis: <https://data.blockperf.cardanofoundation.org/>. A visualized version will
be publicly available soon.

If you want to contribute, please get in touch with the Cardano Foundation's
OPS & Infrastructure team to receive a openssl client certificate.
This certificate is needed to authenticate to the mqtt broker service. Most valuable
are nodes located in geographically remote locations or outside hotspots.

## Configuring the cardano-node with the legacy tracing system

For blockperf to work the node config needs to have the following configured.
Keep in mind, the path is your choice. It's only important that you then later
tell blockperf the same where to find them.

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

* Enable these traces

```json
"TraceChainSyncClient": true,
"TraceBlockFetchClient": true,
```

## Configuring the cardano-node with the new tracing system

Similar to the above section using cardano-node with the legacy tracing system,
for blockperf to work with the new tracing system, the node config needs to
have the following configured.

* Make the node log to a json file by including at least `Forwarder` in the
backends, and the following five specific tracers:

```json
"UseTraceDispatcher": true,
"TraceOptions": {
  "": {
    "backends": [
      "Forwarder",
    ],
  },
  "BlockFetch.Client.CompletedBlockFetch": {
    "details": "DNormal",
    "maxFrequency": 0.0,
    "severity": "Info"
  },
  "BlockFetch.Client.SendFetchRequest": {
    "details": "DNormal",
    "maxFrequency": 0.0,
    "severity": "Info"
  },
  "ChainDB.AddBlockEvent.AddedToCurrentChain": {
    "details": "DNormal",
    "maxFrequency": 0.0,
    "severity": "Info"
  },
  "ChainDB.AddBlockEvent.SwitchedToAFork": {
    "details": "DNormal",
    "maxFrequency": 0.0,
    "severity": "Info"
  },
  "ChainSync.Client.DownloadedHeader": {
    "details": "DNormal",
    "maxFrequency": 0.0,
    "severity": "Info"
  }
}
```

* Make cardano-tracer log the forwarded output it receives from cardano-node to
a file which blockperf can follow and parse by including logging and rotation
declarations in cardano-tracer's config:

```json
"logging": [
  {
    "logFormat": "ForMachine",
    "logMode": "FileMode",
    "logRoot": "/opt/cardano/cnode/logs"
  }
],
"rotation": {
  "rpFrequencySecs": 60,
  "rpKeepFilesNum": 14,
  "rpLogLimitBytes": 10000000,
  "rpMaxAgeHours": 24
}
```

* Note that the logRoot example above is `/opt/cardano/cnode/logs`, and the actual file
blockperf will need to parse will be `/opt/cardano/cnode/logs/$HOSTNAME/node.json`.


## Configuring blockperf

Blockperf needs access to the nodes config file. It also needs to know the file
where the node logs to.

Blockperf sends its data using mqtt to AWS' IoT Core Broker service. Therefore
blockperf needs to authenticate. We use X.509 client certificates to do that.
These need to be registered in aws in order to allow clients access. Contact CF
for how to get one such certificate. Once you have your certificate and private
key for it, store it somewhere on disk. As well as the certificate from the
signing Root CA from Amazon Trust Services which you can find here [AmazonRootCA1.pem](https://www.amazontrust.com/repository/AmazonRootCA1.pem)

With the certificate you will also receive a "client identifier" or name. This name
is also part of the certificate and is needed to properly authenticate and more
importantly publish message to a specific mqtt topic.

To send the data blockperf also needs to know the public IP Address (and Port)
whith which that relay is being accessed over. The IP address will be send
along with the other data. If you do not want that you can specify a list of
addresses that you never want to disclose.

The following are the environment variables for these previously described
configurations. You'll need to adapt to your environment. I usually store these
in a file `/etc/default/blockperf` and reference that from the systemd unit.

```bash
# Your cardano-node's config and logfiles.
BLOCKPERF_NODE_CONFIG="/opt/cardano/cnode/files/config.json"
BLOCKPERF_NODE_LOGFILE="/opt/cardano/cnode/logs/node.json"

# If you are using the new tracing system, the logfile is passed as
# cardano-tracer logRoot with hostname and node.json file appended:
# BLOCKPERF_NODE_LOGFILE="/opt/cardano/cnode/logs/$HOSTNAME/node.json"

# X.509 client certificate, key and signing CA
BLOCKPERF_CLIENT_CERT="XXX" # path to client certificate
BLOCKPERF_CLIENT_KEY="XXX"  # path to certificate key
BLOCKPERF_AMAZON_CA="XXX"   # grab from https://www.amazontrust.com/repository/AmazonRootCA1.pem

# your client identifier, this is like unique id/name whith which we cann attache
# policies to the certificates below to authenticate. You can not just invent this
# this will be given to you with the ssl certificates that you'll need.
BLOCKPERF_NAME="XX"
BLOCKPERF_RELAY_PUBLIC_IP="x.x.x.x"
BLOCKPERF_RELAY_PUBLIC_PORT="3001"
# If you do not want to share certain ips of your setup, list them here and
# blockperf will not send these out to the broker.
BLOCKPERF_MASKED_ADDRESSES="x.x.x.x,x.x.x.x"

# Optional: Specify a port number for prometheus metrics server, defaults to disabled
BLOCKPERF_METRICS_PORT="8082"

# Optional: Can be used to disable publishing for temporary machines or testnets, defaults to True
BLOCKPERF_PUBLISH="True"

# Optional: Can be used to switch to new node tracing system, defaults to True
BLOCKPERF_LEGACY_TRACING="True"
```


### Run (without docker)

I assume you have some understanding of python virtualenvironments. If not:
the basic idea is to create isolated environments to run applications in. These
environment will then get all the dependencies of the application installed into
them instead of your system. If you are interested you might find this link
usefull <https://realpython.com/python-virtual-environments-a-primer/>

The [venv module](https://docs.python.org/3/library/venv.html) is part of the
standard library of python since 3.3. However debian/ubuntu have seperated it
into its own package. So you might need to install `apt install python3-venv`.

Create a folder where you create the virtual environment in.

```bash
# Create the folder you want blockperf to live in
mkdir -p ~/blockperf
cd ~/blockperf

# Create the venv and activate it.
python3 -m venv venv
source venv/bin/activate

# Install blockperf via pip
pip install git+https://github.com/cardano-foundation/blockperf

# Test it by issuing the command, it should print some help ...
blockperf --help
```

Now blockperf is installed within the virtual environment. Make sure to reactivate
it should you have changed shells using the  `source .venv/bin/activate` command.


> **Note**
> Generally speaking: What you need to do is to provide the environment variable
> configuration and run blockperf from within the venv you just created.


**Systemd Unit**

Here is an example of a systemd unit that runs blockperf from within its
virtual environment. Remember to check the specific values. You may have different paths
or other settings need to be changed!

```ini
[Unit]
Description=Blockperf.py

[Service]
Type=simple
Restart=always
RestartSec=20
User=ubuntu
EnvironmentFile=/etc/default/blockperf
ExecStart=/home/ubuntu/blockperf/.venv/bin/blockperf run
KillSignal=SIGINT
SyslogIdentifier=blockperf
TimeoutStopSec=5
```

Once you have written the above into e.g. `/etc/systemd/system/blockperf.service` you
need to reload systemd and start the service.

```bash
sudo systemctl daemon-reloadsudo systemctl daemon-reload
sudo systemctl start blockperf
```

Inspect logs with

```bash
journalctl -fu blockperf
```

### Using Docker

There is a basic Dockerfile that will build an image with python3.12 and blockperf
installed in it. Have a look into it and build your image. You would then
need to find a way to provide all the files we discussed above into the container.

The most straight forward example might be using bind mounts with a docker run
call similar to this. All your paths obviously need to be adopted to match your
environment. Keep in mind: The paths you specify in the environment variables
must match the environment the process sees within the container.

```bash
docker run -it --env-file blockperf.env                                                                           \
  --mount type=bind,source=/opt/cardano/cnode/files/config.json,target=/opt/cardano/config.json                   \
  --mount type=bind,source=/opt/cardano/cnode/logs/node.json,target=/opt/cardano/logs/node.json                   \
  --mount type=bind,source=/etc/blockperf/client.pem,target=/opt/cardano/client.pem                               \
  --mount type=bind,source=/etc/blockperf/client.key,target=/opt/cardano/client.key                               \
  --mount type=bind,source=/etc/blockperf/amazonca.pem,target=/opt/cardano/amazonca.pem                           \
  --mount type=bind,source=/opt/cardano/cnode/files/shelley-genesis.json,target=/opt/cardano/shelley-genesis.json \
  blockperf blockperf run
```
