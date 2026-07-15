#!/usr/bin/env python3
"""
Object-storage initialization script — runs once on every `stack up`.
Branches on OBJECT_STORAGE (garage | seaweedfs) and prepares the loki/
tempo/mimir buckets so those services can start writing immediately.
"""
import urllib.request
import urllib.error
import json
import os
import sys
import time

BUCKETS = ["loki", "tempo", "mimir"]
BACKEND = os.environ.get("OBJECT_STORAGE", "garage")


def wait_for(url, name, retries=60, delay=3):
    print(f"Waiting for {name}...", flush=True)
    for _ in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=5):
                return  # any 2xx → daemon is up
        except Exception:
            time.sleep(delay)
    sys.exit(f"ERROR: {name} did not become healthy after waiting.")


# ── Garage ────────────────────────────────────────────────────────────────
def init_garage():
    admin_url = "http://garage:3903"
    admin_token = os.environ["GARAGE_ADMIN_TOKEN"]
    access_key_id = os.environ["GARAGE_ACCESS_KEY_ID"]
    secret_access_key = os.environ["GARAGE_SECRET_ACCESS_KEY"]
    capacity_bytes = int(os.environ.get("GARAGE_CAPACITY_GB", "100")) * 1024 ** 3

    def api(method, path, body=None):
        url = f"{admin_url}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {admin_token}")
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

    # Uses /metrics (unauthenticated, returns 200 immediately on startup)
    # instead of /health, which returns 503 until the cluster layout is
    # configured — creating a chicken-and-egg deadlock.
    wait_for(f"{admin_url}/metrics", "Garage")
    print("✔  Garage is healthy\n", flush=True)

    # GET /v2/GetClusterStatus — node ID is at nodes[0].id (v2 response structure)
    status = api("GET", "/v2/GetClusterStatus")
    nodes = status.get("nodes", [])
    node_id = nodes[0].get("id") if nodes else None
    if not node_id:
        print(f"  WARN: Could not extract node ID from status: {status}", flush=True)
        print("  Skipping layout assignment (may already be configured)", flush=True)
    else:
        # GET /v2/GetClusterLayout — returns {version, roles, stagedRoleChanges}
        layout = api("GET", "/v2/GetClusterLayout")
        current_version = layout.get("version", 0)
        if any(r.get("id") == node_id for r in layout.get("roles", [])):
            print("  ✔  Node already in layout — skipping")
        else:
            print(f"  Assigning node {node_id[:12]}… (zone=dc1, capacity={capacity_bytes // 2**30} GiB)")
            # POST /v2/UpdateClusterLayout — body uses {"roles": [...]} array wrapper (v2 change)
            api("POST", "/v2/UpdateClusterLayout", {
                "roles": [{"id": node_id, "zone": "dc1", "capacity": capacity_bytes, "tags": []}]
            })
            try:
                api("POST", "/v2/ApplyClusterLayout", {"version": current_version + 1})
                print("  ✔  Layout applied")
            except RuntimeError as e:
                print(f"  ⚠  Layout apply warning (may already be active): {e}", flush=True)

    print("\nConfiguring access key…", flush=True)
    print(f"  Importing access key {access_key_id}…")
    result = api("POST", "/v2/ImportKey", {
        "accessKeyId": access_key_id,
        "secretAccessKey": secret_access_key,
        "name": "monitoring-stack",
    })
    print("  ✔  Key already exists — skipping import" if result is None else "  ✔  Access key imported")

    print("\nConfiguring buckets…", flush=True)
    for name in BUCKETS:
        print(f"  Bucket '{name}'…")
        try:
            api("POST", "/v2/CreateBucket", {"globalAlias": name})
        except RuntimeError:
            pass  # may already exist with a non-409 error code

        info = api("GET", f"/v2/GetBucketInfo?globalAlias={name}")
        if not info:
            raise RuntimeError(f"Could not retrieve info for bucket '{name}'")
        bucket_id = info["id"]

        # POST /v2/AllowBucketKey — idempotent (existing perms are not downgraded)
        api("POST", "/v2/AllowBucketKey", {
            "bucketId": bucket_id,
            "accessKeyId": access_key_id,
            "permissions": {"read": True, "write": True, "owner": True},
        })
        print(f"  ✔  Bucket '{name}' ready (id={bucket_id[:8]}…)")

    print("\n✔  Garage initialization complete\n", flush=True)


# ── SeaweedFS ─────────────────────────────────────────────────────────────
def init_seaweedfs():
    filer_url = "http://seaweedfs:8888"
    wait_for(filer_url, "SeaweedFS filer")
    print("✔  SeaweedFS is healthy\n", flush=True)

    print("Configuring buckets…", flush=True)
    for name in BUCKETS:
        # The filer creates a directory on POST with a trailing slash — the
        # embedded S3 gateway treats /buckets/<name>/ as the bucket root, so
        # no S3-signed request (and no extra library) is needed to "create"
        # a bucket, just a plain filer mkdir.
        req = urllib.request.Request(f"{filer_url}/buckets/{name}/", method="POST")
        try:
            urllib.request.urlopen(req, timeout=10)
        except urllib.error.HTTPError as e:
            if e.code not in (200, 201, 204, 409):
                raise RuntimeError(f"POST /buckets/{name}/ → HTTP {e.code}") from None
        print(f"  ✔  Bucket '{name}' ready")

    print("\n✔  SeaweedFS initialization complete\n", flush=True)


def main():
    print(f"Object storage backend: {BACKEND}\n", flush=True)
    if BACKEND == "seaweedfs":
        init_seaweedfs()
    else:
        init_garage()


if __name__ == "__main__":
    main()
