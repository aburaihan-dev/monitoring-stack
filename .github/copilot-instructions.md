# Copilot Instructions — Mission Control Monitoring Stack

This repository is a **production-grade Docker Compose observability stack** combining
infrastructure monitoring, container metrics, structured logs, distributed traces, and
application-level telemetry into a single unified Grafana dashboarding experience.

See [`MONITORING-STACK-ANALYSIS.md`](../MONITORING-STACK-ANALYSIS.md) for the full
architecture analysis, feasibility study, and implementation plan that this codebase
was designed from.

---

## Architecture

The stack is organized into five layers:

```
Sources → Alloy (collector) → Storage backends → Grafana (UI) → Alertmanager
```

**Alloy is the single entry point for all telemetry.** Nothing writes directly to Loki,
Tempo, or Mimir — everything is routed through `configs/alloy/config.alloy`.

| Signal | Source → Alloy pipeline → Backend |
|---|---|
| Host metrics | `node-exporter` → `prometheus.scrape` → `prometheus.remote_write` → Mimir |
| Container metrics | `cadvisor` → `prometheus.scrape` → `prometheus.remote_write` → Mimir |
| Synthetic probes | `blackbox-exporter` → `prometheus.scrape` → `prometheus.remote_write` → Mimir |
| App metrics (OTel) | SDK → `otelcol.receiver.otlp` → `otelcol.exporter.prometheus` → Mimir |
| App traces (OTel) | SDK → `otelcol.receiver.otlp` → `otelcol.exporter.otlp` → Tempo |
| App logs (OTel) | SDK → `otelcol.receiver.otlp` → `otelcol.exporter.loki` → Loki |
| Docker container logs | Docker socket → `loki.source.docker` → `loki.write` → Loki |
| App log push | App → `loki.source.api` (`:3500`) → `loki.write` → Loki |

**Mimir is the metrics store, not Prometheus.** Prometheus is not used as a long-term
store — Alloy scrapes and remote_writes to Mimir. Mimir exposes a Prometheus-compatible
API at `http://mimir:9009/prometheus`.

**MinIO backs all three storage services.** Loki, Tempo, and Mimir all write to MinIO
buckets (`loki/`, `tempo/`, `mimir/`) instead of local filesystem. The MinIO init
container/script creates these buckets on first boot.

---

## Repository Structure

```
monitoring-stack/
├── docker-compose.yml          # All 12 services, resource limits, health checks
├── .env                        # Secrets and tunables (gitignored, see .env.example)
├── .env.example                # Template for all required environment variables
├── Makefile                    # Convenience targets: up, down, logs, restart <svc>
├── configs/
│   ├── alloy/
│   │   └── config.alloy        # Alloy pipeline: scrape + OTLP + log discovery + fan-out
│   ├── loki/
│   │   └── config.yml          # Loki: MinIO S3 backend, schema, compactor, 30d retention
│   ├── tempo/
│   │   └── config.yml          # Tempo: MinIO S3 backend, OTLP receiver, 14d retention
│   ├── mimir/
│   │   └── config.yml          # Mimir: MinIO S3 backend, ruler, 90d retention
│   ├── alertmanager/
│   │   └── config.yml          # Routes: Slack + Email + PagerDuty + UAR
│   ├── grafana/
│   │   ├── provisioning/
│   │   │   ├── datasources/
│   │   │   │   └── datasources.yml   # Mimir, Loki, Tempo, Alertmanager with correlation
│   │   │   └── dashboards/
│   │   │       └── dashboards.yml    # Dashboard provider config
│   │   └── dashboards/               # Pre-built JSON dashboard files
│   ├── blackbox/
│   │   └── config.yml          # Probe modules: http_2xx, tcp_connect, icmp
│   └── rules/
│       ├── node-alerts.yml     # Host-level PromQL alert rules
│       ├── container-alerts.yml # Container PromQL alert rules
│       └── slo-alerts.yml      # Application SLO alert rules
└── scripts/
    └── minio-init.sh           # Creates MinIO buckets on first boot
```

---

## Key Conventions

### Environment Variables (`.env`)

All secrets, image versions, and tunable retention periods live in `.env`. Never
hardcode credentials in config files. The pattern throughout `docker-compose.yml`:

```yaml
environment:
  - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD}
```

Retention values are passed via env to config files using Docker's variable substitution
or as direct container environment variables that configs read via Alloy/Loki/etc.

### Alloy Config Syntax

`configs/alloy/config.alloy` uses **Alloy's River syntax** (HCL-like, not YAML).
The key pattern is chained components:

```hcl
// 1. Define a source (scrape / receiver / discovery)
prometheus.scrape "node_exporter" {
  targets    = [{ __address__ = "node-exporter:9100" }]
  forward_to = [prometheus.remote_write.mimir.receiver]  // pipe to next component
}

// 2. Define the sink
prometheus.remote_write "mimir" {
  endpoint { url = "http://mimir:9009/api/v1/push" }
}
```

Component IDs follow `type.label` — use lowercase snake_case for labels. Always chain
with `forward_to` / `output` — never leave a pipeline endpoint unconnected.

### Docker Compose Service Conventions

Every service in `docker-compose.yml` must have:
- `restart: unless-stopped`
- `mem_limit` and `mem_reservation`
- `logging` with `json-file` driver, `max-size: "5m"`, `max-file: "3"`
- A `monitoring` network membership
- The `logging: "promtail"` label (for Alloy Docker log discovery)

Services that are internal (not accessed by users) use `expose:` not `ports:`. Only
Grafana (`:3000`), Alertmanager (`:9093`), MinIO UI (`:9001`), and UAR (`:9094`) use `ports:`.

### Grafana Datasource UIDs

The datasource UIDs are fixed and cross-referenced between datasources for correlation.
Do not change these UIDs when editing `configs/grafana/provisioning/datasources/datasources.yml`:

| Datasource | UID |
|---|---|
| Mimir | `mimir` |
| Loki | `loki` |
| Tempo | `tempo` |
| Alertmanager | `alertmanager` |

Tempo's datasource config includes `tracesToLogsV2` pointing to `loki` UID, and
`tracesToMetrics` pointing to `mimir` UID — this enables one-click cross-signal
drill-down in Grafana.

### Alert Rules

Alert rules in `configs/rules/` are **PromQL** (evaluated by Mimir's ruler) or
**LogQL** (evaluated by Loki's ruler). They are provisioned via Mimir's `ruler` API
or mounted directly.

Rule files use Prometheus rule format:
```yaml
groups:
  - name: node.rules
    rules:
      - alert: HighCPU
        expr: 100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High CPU on {{ $labels.instance }}"
```

### MinIO Bucket Layout

Each backend service writes to its own isolated bucket. The MinIO init script must
create these before any backend starts:

| Bucket | Used by |
|---|---|
| `loki` | Loki chunks and index |
| `tempo` | Tempo trace blocks |
| `mimir` | Mimir TSDB blocks and ruler |

### Service Health Check Pattern

Health checks poll each service's `/ready` or `/health` HTTP endpoint:
```yaml
healthcheck:
  test: ["CMD", "wget", "-q", "--spider", "http://localhost:3100/ready"]
  interval: 30s
  timeout: 10s
  retries: 5
  start_period: 30s
```
Use `start_period: 30s` for storage backends (Loki, Tempo, Mimir) since they take
longer to initialize against MinIO.

---

## Common Operations

```bash
# Start the full stack
docker compose up -d

# Start a single service (e.g., after config change)
docker compose up -d --no-deps alloy

# Tail logs for a specific service
docker compose logs -f alloy

# Reload Alloy config without restart (if --stability.level=public-preview enabled)
docker compose exec alloy alloy reload /etc/alloy/config.alloy

# Check Alloy pipeline graph (UI)
open http://localhost:12345

# Validate an Alloy config file locally (requires alloy binary)
alloy fmt configs/alloy/config.alloy
alloy run --dry-run configs/alloy/config.alloy

# Force recreate a service after docker-compose.yml change
docker compose up -d --force-recreate grafana

# MinIO bucket inspection
docker compose exec minio mc ls local/
```

---

## OTel SDK Integration

Applications send telemetry to **Alloy**, not directly to Tempo/Loki/Mimir.

```
OTLP endpoint (traces + metrics + logs):
  gRPC:  alloy:4317   (from within Docker network)
  HTTP:  alloy:4318   (from within Docker network)
  HTTP:  http://<host>:4318  (from outside, if exposed via proxy)
```

The OTLP receiver in Alloy routes:
- `traces`  → Tempo via `otelcol.exporter.otlp`
- `metrics` → Mimir via `otelcol.exporter.prometheus` + `prometheus.remote_write`
- `logs`    → Loki via `otelcol.exporter.loki`

---

## Ports Reference

| Port | Service | Access |
|---|---|---|
| 3000 | Grafana UI | Public |
| 9093 | Alertmanager UI | Internal / restricted |
| 9094 | UAR (Uncomplicated Alert Receiver) | Internal |
| 9001 | MinIO Console UI | Internal |
| 12345 | Alloy UI + self-metrics | Internal |
| 4317 | Alloy OTLP gRPC ingest | Apps |
| 4318 | Alloy OTLP HTTP ingest | Apps |
| 3500 | Alloy Loki push ingest | Apps |
| 9090 | Alloy Prometheus remote_write ingest | Apps |
