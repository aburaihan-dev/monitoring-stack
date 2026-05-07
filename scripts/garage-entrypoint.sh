#!/bin/sh
# Garage server entrypoint — generates garage.toml from env vars then starts the server.
set -e

cat > /tmp/garage.toml << TOML
metadata_dir = "/var/lib/garage/meta"
data_dir     = "/var/lib/garage/data"
db_engine    = "lmdb"

# Single-node: no replication. For multi-node HA, change to "2" or "3".
replication_factor = 1

rpc_bind_addr   = "[::]:3901"
rpc_public_addr = "garage:3901"
rpc_secret      = "${GARAGE_RPC_SECRET}"

[s3_api]
s3_region    = "garage"
api_bind_addr = "[::]:3900"
root_domain  = ".s3.garage"

[admin]
api_bind_addr = "[::]:3903"
admin_token   = "${GARAGE_ADMIN_TOKEN}"
TOML

exec /garage -c /tmp/garage.toml server
