# Changelog — 2026-07-15 Session

This document summarizes all changes made to the monitoring stack during the
2026-07-15 troubleshooting and enhancement session. It covers object storage
fixes, SeaweedFS exposure, Alloy pipeline changes, and new Grafana dashboards.

---

## 1. Tempo — fixed config parse failure (restart loop)

**File:** [`configs/tempo/config.yml`](configs/tempo/config.yml)

- Removed obsolete top-level `ingester` and `compactor` blocks.
- Grafana Tempo `3.0.2` no longer accepts these fields at the top level and
  was rejecting the config on startup with:
  ```
  field ingester not found in type app.Config
  field compactor not found in type app.Config
  ```
- Tempo now starts cleanly under `grafana/tempo:3.0.2`.

---

## 2. SeaweedFS — fixed object storage write failures

**File:** [`docker-compose.yml`](docker-compose.yml)

- **Writable volumes:** Added startup flags to the `seaweedfs` service command
  so it allocates writable volumes automatically in single-node mode:
  ```
  -volume.max=0 -master.volumeSizeLimitMB=1024 -volume.preStopSeconds=1
  ```
  Previously, Tempo/Loki/Mimir writes to SeaweedFS failed with
  `No writable volumes and no free volumes left`.
- **Healthcheck fix:** Changed the healthcheck endpoint from
  `http://localhost:8888/` (404) to `http://localhost:8888/metrics` (also 404
  on this image) and finally to **`http://localhost:8888/buckets/`**, which
  reliably returns `200` and reports the container as `healthy`.

---

## 3. SeaweedFS — exposed admin UIs to the host

**File:** [`docker-compose.yml`](docker-compose.yml)

Published SeaweedFS's web UIs on `127.0.0.1` only (not open to the network):

| UI | Host binding | Container port |
|---|---|---|
| Filer UI / admin API | `127.0.0.1:8888` | `8888` |
| Master UI / cluster status | `127.0.0.1:9333` | `9333` |
| Volume server UI / node status | `127.0.0.1:${SEAWEEDFS_VOLUME_UI_PORT:-18080}` | `8080` |

- The volume UI's host port defaults to `18080` (configurable via
  `SEAWEEDFS_VOLUME_UI_PORT`) because host port `8080` was already in use by
  another service (Jenkins) on the shared server.

---

## 4. Alloy — object storage probe is now backend-aware

**Files:** [`configs/alloy/config.alloy`](configs/alloy/config.alloy),
[`docker-compose.yml`](docker-compose.yml)

- The blackbox object-storage probe was hardcoded to
  `http://garage:3903/health`, which caused constant DNS failures
  (`lookup garage on 127.0.0.11:53: server misbehaving`) once the stack was
  switched to SeaweedFS.
- Replaced with an env-driven target:
  ```alloy
  "__param_target" = env("OBJECT_STORAGE_ENDPOINT"),
  "__param_module" = "tcp_connect",
  "instance"       = "object-storage",
  ```
- Added `OBJECT_STORAGE_ENDPOINT=${OBJECT_STORAGE_ENDPOINT}` to the `alloy`
  service environment in `docker-compose.yml` so the probe target follows
  whichever backend (`garage` or `seaweedfs`) is active via `./stack storage`.

---

## 5. Alloy — automatic `machine_name` label for pushed application logs

**File:** [`configs/alloy/config.alloy`](configs/alloy/config.alloy)

- Loki's push API has no mechanism to capture a client's source IP as a
  label — this is a protocol limitation, not a config gap.
- As a practical alternative, added a `loki.process "app_push"` stage in
  front of the existing `loki.source.api "push"` (port `3500`) receiver that:
  1. Extracts the JSON body from lines shaped like
     `2026-07-15 15:47:53.737 warn {"Message":...}` (timestamp + level prefix
     followed by a JSON object) using `stage.regex`.
  2. Parses the `MachineName` field from that JSON body using `stage.json`.
  3. Promotes it to a `machine_name` label using `stage.labels`.
- This works for **any** client pushing logs in this shape, without requiring
  app-side configuration changes.
- Verified end-to-end: pushed a synthetic log matching the real .NET/Serilog
  sample format and confirmed `machine_name` appeared as a queryable Loki
  label.
- **Note:** the real application already sends its own `MachineName` label
  natively (PascalCase) via the Serilog `GrafanaLoki` sink's
  `propertiesAsLabels: ["Instance", "MachineName"]` setting — confirmed by
  querying live streams. The Alloy-side `machine_name` (lowercase) stage acts
  as a safety net for other log sources that don't set this themselves.

---

## 6. New Grafana dashboards

All dashboards are auto-provisioned from
[`configs/grafana/dashboards/`](configs/grafana/dashboards) into the
**Monitoring Stack** folder — no manual import needed.

### 6.1 `loki-application-logs.json` — general application log dashboard
- Log lines per interval, log volume by level, top hosts, top loggers, full
  log stream.
- Filters: `app`, `environment`.

### 6.2 `loki-warn-error-observability.json` — warning/error focused dashboard
- Warning rate, error rate, error percentage, warning/error trend, top
  `SourceContext`, top error request paths, dedicated error/warning log
  streams.
- Built specifically around the fact that this stack ships **warning and
  error logs only** (no info/debug).

### 6.3 `sre-log-slo-dashboard.json` — SRE/DevOps SLO dashboard
Organized into collapsible rows:
- **SLO Overview** — error rate, warning rate, error % (of warn+error
  volume), non-error ratio (SLI), warn+error volume/interval, long-running
  request count.
- **Trends & Latency** — warning/error trend, request latency percentiles
  (p50/p95/p99) parsed from the `ElapsedSeconds` field in
  `LongRunningRequestMiddleware` logs via LogQL `unwrap`.
- **Top Offenders** — top `SourceContext`, top error request paths, slowest
  request paths by average latency, top hosts.
- **Raw Logs** — error logs, warning logs, long-running request logs.
- **Server Identification** *(added later)* — `machine_name` filter
  variable, top app servers by warn/error volume, log volume by server.

**Panel naming correction:** Since only warning/error logs are shipped (no
info/debug baseline), two panels were renamed to avoid implying a "clean
logs" baseline that doesn't exist:
- `Error Percentage of Total Logs` → `Error % (of Warn+Error Volume)`
- `Clean Log Ratio (SLI)` → `Non-Error Ratio (SLI)`
- `Total Log Volume / Interval` → `Warning + Error Volume / Interval`

---

## 7. Operational guidance provided (no config change)

- **Loki ingest URL for external apps:**
  `http://<monitoring-server-ip>:3500/loki/api/v1/push` (via Alloy, not
  directly to Loki).
- **Firewall checklist:** minimum ports to open for external ingestion
  (`4317`, `4318`, `3500`), UI ports (`3000`, `9093`), and which ports should
  stay internal-only (SeaweedFS `8333`, Loki `3100`, Tempo `3200`, Mimir
  `9009`, etc.).
- Sample client configs provided for Fluent Bit, Promtail, Serilog, NLog, and
  raw `curl` pushes.

---

## Summary of files changed

| File | Change |
|---|---|
| `configs/tempo/config.yml` | Removed obsolete `ingester`/`compactor` blocks |
| `docker-compose.yml` | SeaweedFS writable-volume flags, healthcheck fix, admin UI ports, Alloy `OBJECT_STORAGE_ENDPOINT` env |
| `configs/alloy/config.alloy` | Backend-aware blackbox probe, `loki.process "app_push"` stage for `machine_name` extraction |
| `configs/grafana/dashboards/loki-application-logs.json` | New — general log dashboard |
| `configs/grafana/dashboards/loki-warn-error-observability.json` | New — warning/error dashboard |
| `configs/grafana/dashboards/sre-log-slo-dashboard.json` | New — SRE/SLO dashboard with server identification |
