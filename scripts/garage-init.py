#!/usr/bin/env python3
"""
Garage initialization script — runs once on first startup.
Sets up node layout, imports the access key, creates and authorizes buckets.
Targets the Garage v2.x admin API.
"""
import urllib.request
import urllib.error
import json
import os
import sys
import time

ADMIN_URL         = "http://garage:3903"
ADMIN_TOKEN       = os.environ["GARAGE_ADMIN_TOKEN"]
ACCESS_KEY_ID     = os.environ["GARAGE_ACCESS_KEY_ID"]
SECRET_ACCESS_KEY = os.environ["GARAGE_SECRET_ACCESS_KEY"]
BUCKETS           = ["loki", "tempo", "mimir"]
# Capacity hint for layout algorithm (GiB). Set GARAGE_CAPACITY_GB in .env
# to match your actual available disk space. Default: 100 GiB.
_capacity_gb      = int(os.environ.get("GARAGE_CAPACITY_GB", "100"))
CAPACITY_BYTES    = _capacity_gb * 1024 ** 3


def api(method, path, body=None):
    url = f"{ADMIN_URL}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {ADMIN_TOKEN}")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="replace")
        # 409 = already exists → treat as OK
        if e.code == 409:
            return None
        raise RuntimeError(f"{method} {path} → HTTP {e.code}: {body_text}") from None


def wait_for_garage(retries=60, delay=3):
    print("Waiting for Garage admin API...", flush=True)
    for _ in range(retries):
        try:
            api("GET", "/health")
            return
        except Exception:
            time.sleep(delay)
    sys.exit("ERROR: Garage did not become healthy after waiting.")


def configure_layout(node_id):
    # GET /v2/GetClusterLayout — returns {version, roles, stagedRoleChanges}
    layout = api("GET", "/v2/GetClusterLayout")
    current_version = layout.get("version", 0)

    # Idempotent: skip if node is already in layout
    if any(r.get("id") == node_id for r in layout.get("roles", [])):
        print("  ✔  Node already in layout — skipping")
        return

    print(f"  Assigning node {node_id[:12]}… (zone=dc1, capacity={CAPACITY_BYTES // 2**30} GiB)")

    # POST /v2/UpdateClusterLayout — body uses {"roles": [...]} array wrapper (v2 change)
    api("POST", "/v2/UpdateClusterLayout", {
        "roles": [{
            "id":       node_id,
            "zone":     "dc1",
            "capacity": CAPACITY_BYTES,
            "tags":     [],
        }]
    })

    # POST /v2/ApplyClusterLayout — confirm staged layout as the next version
    try:
        api("POST", "/v2/ApplyClusterLayout", {"version": current_version + 1})
        print("  ✔  Layout applied")
    except RuntimeError as e:
        print(f"  ⚠  Layout apply warning (may already be active): {e}", flush=True)


def ensure_key():
    print(f"  Importing access key {ACCESS_KEY_ID}…")
    result = api("POST", "/v2/ImportKey", {
        "accessKeyId":     ACCESS_KEY_ID,
        "secretAccessKey": SECRET_ACCESS_KEY,
        "name":            "monitoring-stack",
    })
    if result is None:
        print("  ✔  Key already exists — skipping import")
    else:
        print("  ✔  Access key imported")


def ensure_bucket(name):
    print(f"  Bucket '{name}'…")
    # Create bucket — returns None on 409/conflict, so always proceed to GET
    try:
        api("POST", "/v2/CreateBucket", {"globalAlias": name})
    except RuntimeError:
        pass  # may already exist with a non-409 error code

    # GET /v2/GetBucketInfo?globalAlias=name
    info = api("GET", f"/v2/GetBucketInfo?globalAlias={name}")
    if not info:
        raise RuntimeError(f"Could not retrieve info for bucket '{name}'")
    bucket_id = info["id"]

    # POST /v2/AllowBucketKey — idempotent (existing perms are not downgraded)
    api("POST", "/v2/AllowBucketKey", {
        "bucketId":    bucket_id,
        "accessKeyId": ACCESS_KEY_ID,
        "permissions": {"read": True, "write": True, "owner": True},
    })
    print(f"  ✔  Bucket '{name}' ready (id={bucket_id[:8]}…)")


def main():
    wait_for_garage()
    print("✔  Garage is healthy\n", flush=True)

    # GET /v2/GetClusterStatus — node ID is at nodes[0].id (v2 response structure)
    status = api("GET", "/v2/GetClusterStatus")
    nodes = status.get("nodes", [])
    node_id = nodes[0].get("id") if nodes else None
    if not node_id:
        print(f"  WARN: Could not extract node ID from status: {status}", flush=True)
        print("  Skipping layout assignment (may already be configured)", flush=True)
    else:
        configure_layout(node_id)

    print("\nConfiguring access key…", flush=True)
    ensure_key()

    print("\nConfiguring buckets…", flush=True)
    for b in BUCKETS:
        ensure_bucket(b)

    print("\n✔  Garage initialization complete\n", flush=True)


if __name__ == "__main__":
    main()
