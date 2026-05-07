# Copilot Instructions — Mission Control Monitoring Stack

**Repository:** https://github.com/aburaihan-dev/monitoring-stack  
**Owner:** aburaihan-dev (m.arsrabon@gmail.com)  
**Last updated:** 2026-05-07  

This is a **production-grade Docker Compose observability stack** — a "Mission Control Centre"
combining infrastructure monitoring, container metrics, structured logs, distributed traces,
and application-level OpenTelemetry into a single Grafana dashboarding experience.

See [`MONITORING-STACK-ANALYSIS.md`](../MONITORING-STACK-ANALYSIS.md) for the original
architecture analysis, feasibility study, and design decisions.

---

## Architecture

```
Sources → Alloy (collector) → Storage backends → Grafana (UI) → Alertmanager
```

**Alloy is the single entry point for all telemetry.** Nothing writes directly to Loki,
Tempo, or Mimir — everything routes through `configs/alloy/config.alloy`.

| Signal | Flow |
|---|---|
| Host metrics | `node-exporter` → `prometheus.scrape` → `prometheus.remote_write` → Mimir |
| Container metrics | `cadvisor` → `prometheus.scrape` → `prometheus.remote_write` → Mimir |
| Synthetic probes | `blackbox-exporter` → `prometheus.scrape` → `prometheus.remote_write` → Mimir |
| Garage metrics | `garage:3903/metrics` → Bearer auth scrape → Mimir |
| App metrics (OTel) | SDK → `otelcol.receiver.otlp` → `otelcol.exporter.prometheus` → Mimir |
| App traces (OTel) | SDK → `otelcol.receiver.otlp` → `otelcol.exporter.otlp` → Tempo |
| App logs (OTel) | SDK → `otelcol.receiver.otlp` → `otelcol.exporter.loki` → Loki |
| Docker container logs | Docker socket → `loki.source.docker` → `loki.write` → Loki |
| App log push | App → `loki.source.api` (`:3500`) → `loki.write` → Loki |

**Mimir is the metrics store** (not Prometheus). Alloy scrapes and remote_writes to Mimir.
Prometheus-compatible query API: `http://mimir:9009/prometheus`.

**Garage is the S3-compatible object storage** (replaced MinIO). Loki, Tempo, and Mimir
write to Garage buckets. `scripts/garage-init.py` creates buckets on first boot.

**Nginx is the reverse proxy.** All external access goes through Nginx (port 80/443).
Internal service ports are not exposed; only Nginx ports are published.

---

## Services (14 total)

| Service | Image | Version | Role |
|---|---|---|---|
| `nginx` | `nginx:alpine` | 1.30-alpine | Reverse proxy + TLS termination |
| `grafana` | `grafana/grafana` | 13.0.1 | Dashboards, alerting UI |
| `alloy` | `grafana/alloy` | v1.16.1 | Unified telemetry collector |
| `mimir` | `grafana/mimir` | 3.0.6 | Long-term metrics (TSDB) |
| `loki` | `grafana/loki` | 3.7.1 | Log storage + querying |
| `tempo` | `grafana/tempo` | 2.10.5 | Distributed trace storage |
| `alertmanager` | `prom/alertmanager` | v0.32.1 | Alert routing, dedup, silencing |
| `node-exporter` | `prom/node-exporter` | v1.11.1 | Host hardware + OS metrics |
| `cadvisor` | `gcr.io/cadvisor/cadvisor` | v0.56.2 | Container resource metrics |
| `blackbox-exporter` | `prom/blackbox-exporter` | v0.28.0 | Synthetic URL/TCP/ICMP probes |
| `garage` | `dxflrs/garage` | v2.3.0 | S3-compatible object storage |
| `garage-init` | `python:3-alpine` | — | One-shot bucket + key setup |
| `redis` | `redis:alpine` | 8-alpine | Query cache for Loki/Mimir |

Versions are pinned in `.env` / `.env.example`. Bump versions there, then run
`./stack pull && ./stack recreate <svc>`.

---

## Repository Structure

```
monitoring-stack/
├── stack                        # CLI tool — all user-facing operations
├── docker-compose.yml           # 14 services, YAML anchors, health checks, resource limits
├── .env                         # Secrets + tunables (gitignored — never commit)
├── .env.example                 # Template; ./stack init copies and populates this
├── .gitignore
├── README.md                    # User-facing docs (Quick Start → Troubleshooting)
├── MONITORING-STACK-ANALYSIS.md # Architecture analysis + Excalidraw + ASCII diagrams
├── configs/
│   ├── alloy/
│   │   └── config.alloy         # Full pipeline: scrape + OTLP + log discovery + Garage
│   ├── loki/
│   │   └── config.yml           # Garage S3 backend, TSDB schema v13, 30d retention
│   ├── tempo/
│   │   └── config.yml           # Garage S3 backend, OTLP receiver, 14d retention
│   ├── mimir/
│   │   └── config.yml           # Garage S3 backend, filesystem ruler, 90d retention
│   ├── alertmanager/
│   │   └── config.yml           # Routes: Slack + Email; inhibition rules
│   ├── grafana/
│   │   ├── provisioning/
│   │   │   ├── datasources/
│   │   │   │   └── datasources.yml  # Fixed UIDs, cross-signal correlation links
│   │   │   └── dashboards/
│   │   │       └── dashboards.yml   # Auto-provision from configs/grafana/dashboards/
│   │   └── dashboards/
│   │       └── garage-object-storage.json  # 18-panel Garage S3 dashboard (UID: garage-storage)
│   ├── blackbox/
│   │   └── config.yml           # Probe modules: http_2xx, tcp_connect, icmp
│   ├── nginx/
│   │   ├── nginx.conf           # Main Nginx config (events, http, include templates)
│   │   ├── snippets/
│   │   │   ├── ssl-params.conf      # TLS 1.2/1.3, ciphers, HSTS, OCSP
│   │   │   ├── security-headers.conf # CSP, X-Frame-Options, etc.
│   │   │   ├── proxy-headers.conf   # X-Real-IP, X-Forwarded-For, Host
│   │   │   └── basic-auth.conf      # auth_basic include
│   │   ├── templates/               # envsubst-processed at container start
│   │   │   ├── default.conf.template    # Redirect HTTP → HTTPS
│   │   │   ├── grafana.conf.template    # grafana.<domain>
│   │   │   ├── alertmanager.conf.template  # alertmanager.<domain> + basic auth
│   │   │   ├── alloy.conf.template      # alloy.<domain> + basic auth
│   │   │   ├── minio.conf.template      # s3.<domain> (Garage S3 API)
│   │   │   └── uar.conf.template        # uar.<domain>
│   │   └── ssl/                     # cert.pem + key.pem (gitignored)
│   └── rules/
│       ├── node-rules.yml           # 8 host-level PromQL alert rules
│       ├── container-rules.yml      # 6 container-level alert rules
│       ├── blackbox-rules.yml       # 4 endpoint probe alert rules
│       └── garage-rules.yml         # 9 Garage S3 alert + recording rules
└── scripts/
    ├── garage-entrypoint.sh     # Generates garage.toml from env vars
    ├── garage-init.py           # Garage v2 API: creates buckets + access keys (idempotent)
    ├── gen-htpasswd.sh          # Generates configs/nginx/.htpasswd
    └── gen-selfsigned-cert.sh   # Generates self-signed cert for configs/nginx/ssl/
```

---

## `./stack` CLI Reference

The `stack` bash script is the only interface for managing this project. Never run
raw `docker compose` commands directly — always use `./stack`.

```bash
# First-time setup wizard (copies .env, generates secrets, sets domain, picks SSL, starts)
./stack init

# Certificate management (4 options)
./stack cert            # interactive: self-signed / existing / Let's Encrypt / ZeroSSL
./stack cert-renew      # renew ACME cert and reload nginx (add to cron)

# Rotate all auto-generated secrets in .env
./stack secrets

# Create/update nginx basic-auth password file
./stack auth

# Lifecycle
./stack up              # docker compose up -d
./stack down            # docker compose down (keeps volumes)
./stack restart <svc>   # restart one service
./stack recreate <svc>  # force-recreate (picks up config/image changes)
./stack pull            # pull latest images
./stack clean           # stop + remove ALL containers AND volumes (data loss!)

# Observability
./stack status          # container names, health, uptime
./stack logs [svc]      # tail logs (all or one service)
./stack urls            # print all service URLs
./stack open            # open Grafana in browser

# Nginx
./stack nginx-reload    # reload nginx config without downtime
./stack nginx-test      # test nginx config syntax

# Validation
./stack validate        # docker compose config + rule YAML lint
./stack rules-check     # lint alert rule files only
```

---

## Key Conventions

### Environment Variables (`.env`)

All secrets, versions, and tunables live in `.env`. The file is gitignored. Template is
`.env.example`. `./stack init` copies the template and runs the interactive setup wizard.

Safe in-place key replacement uses `_env_set()` (awk-based, portable):
```bash
_env_set GRAFANA_ADMIN_PASSWORD "newvalue"
```
This only replaces lines starting with `KEY=`, never commented lines.

Auto-generated secrets (via `./stack init` or `./stack secrets`):
| Variable | Generator |
|---|---|
| `GRAFANA_ADMIN_PASSWORD` | `openssl rand -base64 18 \| tr -d '=+/\\' \| head -c 24` |
| `GARAGE_RPC_SECRET` | `openssl rand -hex 32` |
| `GARAGE_ADMIN_TOKEN` | `openssl rand -hex 16` |
| `GARAGE_ACCESS_KEY_ID` | `GK$(openssl rand -hex 14)` |
| `GARAGE_SECRET_ACCESS_KEY` | `openssl rand -hex 32` |

### Nginx Template System

Nginx uses `*.template` files processed by `envsubst` at container start.
- Only `${BASE_DOMAIN}` and explicit vars use single `$`
- Nginx runtime vars (`$host`, `$uri`, `$request_uri`) **must** be written as `$$host`, `$$uri`, `$$request_uri` in templates to prevent envsubst from expanding them
- SSL cert is always at `configs/nginx/ssl/cert.pem` + `key.pem` (regardless of how it was generated)
- Basic auth reads from `configs/nginx/.htpasswd` (gitignored)

SSL options (all managed via `./stack cert`):
1. **Self-signed** — generates with `openssl req -x509`; for dev/LAN
2. **Existing** — copies cert + key from user-provided paths, verifies pair match
3. **Let's Encrypt** — certbot standalone (HTTP-01) or DNS-01 for wildcards; stores domain in `.certbot-domain`
4. **ZeroSSL** — same certbot flow but with EAB credentials (Key ID + HMAC from app.zerossl.com)

Renewal: `./stack cert-renew` (reads `.certbot-domain`, tries standalone then generic renew).
Add to cron: `0 3 * * * /path/to/stack cert-renew >> /var/log/cert-renew.log 2>&1`

### Alloy Config (River Syntax)

`configs/alloy/config.alloy` uses **River syntax** (HCL-like, not YAML).

```hcl
// Chain components with forward_to / output — never leave a pipeline unconnected
prometheus.scrape "node_exporter" {
  targets    = [{ __address__ = "node-exporter:9100" }]
  forward_to = [prometheus.remote_write.mimir.receiver]
}
prometheus.remote_write "mimir" {
  endpoint { url = "http://mimir:9009/api/v1/push" }
}
```

Garage metrics use Bearer token auth:
```hcl
prometheus.scrape "garage" {
  targets    = [{ __address__ = "garage:3903" }]
  bearer_token = env("GARAGE_ADMIN_TOKEN")
  forward_to = [prometheus.remote_write.mimir.receiver]
}
```

Component IDs: `type.label` — lowercase snake_case labels.

### Garage v2 API (scripts/garage-init.py)

All Garage API paths use `/v2/` prefix. Key patterns:
- Health: `GET /health` (no auth, no version prefix)
- Node ID: `GET /v2/status` → `status["nodes"][0]["id"]`
- Layout update: `POST /v2/layout` body `{"roles": [{id, zone, capacity, tags}]}`
- Apply layout: `POST /v2/layout/apply` body `{"version": N}`
- Create bucket: `POST /v2/bucket`
- Create key: `POST /v2/key`
- `GARAGE_ACCESS_KEY_ID` must start with `GK` followed by hex chars

### Docker Compose Conventions

Every service must have:
```yaml
restart: unless-stopped
mem_limit: <value>
mem_reservation: <value>
logging:
  driver: json-file
  options: { max-size: "5m", max-file: "3" }
networks: [monitoring]
labels:
  logging: "alloy"   # enables Docker log autodiscovery in Alloy
```

`x-logging` and `x-monitoring-labels` YAML anchors are defined **before** the `services:`
block. This is required — YAML anchors cannot forward-reference.

Internal services use `expose:` (not `ports:`). Only Nginx uses `ports: ["80:80", "443:443"]`.

### Grafana Datasource UIDs (fixed — never change)

| Datasource | UID | Notes |
|---|---|---|
| Mimir | `mimir` | prometheusVersion: 3.0.0 |
| Loki | `loki` | |
| Tempo | `tempo` | tracesToLogsV2 → loki UID |
| Alertmanager | `alertmanager` | |

Cross-signal drill-down: Tempo → Loki (via `tracesToLogsV2`) and Tempo → Mimir (via `tracesToMetrics`).

### Mimir 3.0 Breaking Changes (already applied)

- `target: all` (NOT `all,alertmanager`)
- No `alertmanager.sharding_enabled: false`
- `ruler_storage.backend: filesystem` with `dir: /rules`
- Rules bind-mounted at `./configs/rules:/rules/anonymous:ro`
- Tenant = `anonymous` (multitenancy disabled)
- Never mount rules inside the `mimir-data` volume path (`/data/mimir`)

### Grafana 13 Removed Env Vars (do not add back)

```
GF_UNIFIED_ALERTING_ENABLED   ← removed in v13
GF_ALERTING_ENABLED           ← removed in v13
GF_FEATURE_TOGGLES_ENABLE     ← removed in v13
```

### Alert Rules

Rules in `configs/rules/` are PromQL (evaluated by Mimir's ruler).
Mimir loads them from `/rules/anonymous/` (bind-mounted from `./configs/rules`).

Standard rule format:
```yaml
groups:
  - name: node.rules
    interval: 1m
    rules:
      - alert: HighCPU
        expr: (1 - avg by(instance)(rate(node_cpu_seconds_total{mode="idle"}[5m]))) * 100 > 85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High CPU on {{ $labels.instance }}"
          description: "CPU is {{ printf \"%.1f\" $value }}% on {{ $labels.instance }}"
```

### Garage Object Storage Dashboard

- UID: `garage-storage`
- 18 panels, 4 rows, datasource UID `mimir`
- File: `configs/grafana/dashboards/garage-object-storage.json`
- Auto-provisioned (no manual import needed)

Key Garage v2 metrics:
```
cluster_available, cluster_healthy, cluster_partitions_quorum
block_resync_errored_blocks               # MUST stay 0
garage_local_disk_avail{volume="data"}
garage_local_disk_total{volume="data"}
api_s3_request_counter, api_s3_error_counter
api_s3_request_duration_bucket
block_bytes_read, block_bytes_written
```

### Garage Bucket Layout

| Bucket | Used by | Access Key |
|---|---|---|
| `loki` | Loki chunks + index | `GARAGE_ACCESS_KEY_ID` |
| `tempo` | Tempo trace blocks | `GARAGE_ACCESS_KEY_ID` |
| `mimir` | Mimir TSDB blocks | `GARAGE_ACCESS_KEY_ID` |

All buckets created by `garage-init` one-shot container at first startup. The init
script is idempotent — 409 Conflict responses are treated as success.

### Service Health Check Pattern

```yaml
healthcheck:
  test: ["CMD", "wget", "-q", "--spider", "http://localhost:3100/ready"]
  interval: 30s
  timeout: 10s
  retries: 5
  start_period: 45s   # storage backends (Loki/Tempo/Mimir) need longer start_period
```

---

## Common Operations

```bash
# First-time setup
./stack init

# Daily operations
./stack status
./stack logs alloy
./stack logs grafana

# After changing a config file
./stack recreate alloy          # alloy config.alloy
./stack nginx-reload            # nginx templates (no downtime)
./stack recreate grafana        # grafana provisioning

# After changing docker-compose.yml
./stack recreate <svc>

# Update all images to pinned versions in .env
./stack pull
./stack recreate alloy          # one service at a time for zero-downtime

# Garage: check cluster health
docker compose exec garage /garage status
docker compose exec garage /garage bucket list
docker compose exec garage /garage key list

# Alloy: live config reload
docker compose exec alloy alloy reload /etc/alloy/config.alloy

# Mimir: check ruler loaded rules
curl -s http://localhost:9009/prometheus/api/v1/rules | jq '.data.groups[].name'
```

---

## OTel SDK Integration

Applications send to **Alloy** (not directly to Tempo/Loki/Mimir):

```
OTLP gRPC:  alloy:4317    (from inside Docker network)
OTLP HTTP:  alloy:4318    (from inside Docker network)
            https://ingest.<BASE_DOMAIN>  (from outside, via nginx)
Loki push:  alloy:3500
```

Alloy routes:
- `traces`  → Tempo via `otelcol.exporter.otlp`
- `metrics` → Mimir via `otelcol.exporter.prometheus` + `prometheus.remote_write`
- `logs`    → Loki via `otelcol.exporter.loki`

SDK quickstart (any language):
```python
# Python example
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
exporter = OTLPSpanExporter(endpoint="http://alloy:4317", insecure=True)
```

---

## Ports Reference

| Port | Service | Exposed? | Access via |
|---|---|---|---|
| 80 | Nginx HTTP | ✅ public | redirect → HTTPS |
| 443 | Nginx HTTPS | ✅ public | all subdomains |
| 3000 | Grafana | ❌ internal | `grafana.<domain>` |
| 9009 | Mimir | ❌ internal | direct only |
| 3100 | Loki | ❌ internal | direct only |
| 3200 | Tempo | ❌ internal | direct only |
| 9093 | Alertmanager | ❌ internal | `alertmanager.<domain>` |
| 9094 | UAR | ❌ internal | `uar.<domain>` |
| 3900 | Garage S3 API | ❌ internal | `s3.<domain>` |
| 3903 | Garage metrics | ❌ internal | Alloy scrape only |
| 3901 | Garage admin RPC | ❌ internal | garage-init only |
| 12345 | Alloy UI | ❌ internal | `alloy.<domain>` |
| 4317 | Alloy OTLP gRPC | ❌ internal | `ingest.<domain>` |
| 4318 | Alloy OTLP HTTP | ❌ internal | `ingest.<domain>` |
| 3500 | Alloy Loki push | ❌ internal | `ingest.<domain>` |
| 6379 | Redis | ❌ internal | Loki/Mimir only |
| 8080 | cAdvisor | ❌ internal | Alloy scrape only |
| 9100 | node-exporter | ❌ internal | Alloy scrape only |
| 9115 | blackbox-exporter | ❌ internal | Alloy scrape only |

---

## Subdomain Map

| Subdomain | Service |
|---|---|
| `grafana.<domain>` | Grafana UI |
| `alertmanager.<domain>` | Alertmanager UI (basic auth) |
| `alloy.<domain>` | Alloy pipeline UI (basic auth) |
| `s3.<domain>` | Garage S3 API endpoint |
| `uar.<domain>` | Uncomplicated Alert Receiver |
| `ingest.<domain>` | Alloy OTLP ingest (4317/4318/3500) |

---

## Memory / Retention

| Service | Retention | Backend |
|---|---|---|
| Loki | 30d | Garage S3 `loki` bucket |
| Mimir | 90d | Garage S3 `mimir` bucket |
| Tempo | 14d (336h) | Garage S3 `tempo` bucket |

Change via `.env` (`LOKI_RETENTION_PERIOD`, `MIMIR_RETENTION_PERIOD`, `TEMPO_RETENTION_PERIOD`),
then `./stack recreate loki` / `mimir` / `tempo`.

Memory budget: ~5.2 GB peak, ~2.6 GB reservation. **Minimum 8 GB RAM required.**
