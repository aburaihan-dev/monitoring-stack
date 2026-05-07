# 🛰 Monitoring Stack — Mission Control Centre

> **Full-stack observability for production.**
> Infrastructure metrics, container metrics, application traces & logs, synthetic probes, and alerting —
> unified in a single Grafana-based stack with Garage S3-compatible object storage.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Architecture](#architecture)
3. [Signal Flow](#signal-flow)
4. [Services & Ports](#services--ports)
5. [Configuration Reference](#configuration-reference)
6. [Instrumenting Your Application](#instrumenting-your-application)
7. [Alert Rules & Notifications](#alert-rules--notifications)
8. [CLI Reference](#cli-reference)
9. [Retention & Storage](#retention--storage)
10. [Directory Structure](#directory-structure)
11. [OpenWrt Router Monitoring](#openwrt-router-monitoring)
12. [Production Hardening](#production-hardening)
13. [Troubleshooting](#troubleshooting)

---

## Quick Start

### Prerequisites

| Tool | Minimum version | Purpose |
|------|----------------|---------|
| Docker Engine | 24+ | Container runtime |
| Docker Compose | v2 (plugin) | Orchestration |
| RAM | **8 GB** | Stack peak ~5.2 GB |

### 1 — Clone

```bash
git clone <this-repo>
cd monitoring-stack
chmod +x stack
```

### 2 — Run the init wizard

```bash
./stack init
```

The wizard walks through every step interactively:

| Step | What happens |
|------|-------------|
| **Domain** | Enter your `BASE_DOMAIN` (used in Grafana root URL and alert links) |
| **Admin user** | Enter Grafana admin username (default: `admin`) |
| **Auto-generate secrets** | Generates and writes all passwords/keys to `.env`, then displays them once |
| **Notifications** | Optionally configure Slack webhook and/or email (SMTP) |
| **Stack up** | Pulls images and starts all 13 services |

> 💡 **Save the generated secrets** — they are displayed once during init and written to `.env`.
> Back up `.env` to a password manager; it is gitignored and never committed.

### 3 — Verify

```bash
./stack status     # colour-coded health for all containers
./stack urls       # print all service URLs
```

Open `http://<HOST_IP>:3000` → log in with your `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD`.

---

## Architecture

```
+-------------------------------------------------------------------------+
|          Direct host ports (no built-in reverse proxy)                   |
|  Grafana :3000   Alertmanager :9093   Alloy UI :12345                   |
|  OTLP gRPC :4317  OTLP HTTP :4318    Loki push :3500                    |
+------------------+---------------------------+----------------------------+
         |                    |                           |
     Grafana           Alertmanager           Grafana Alloy
     (3000)              (9093)               (collector)
                                    +-------------------------------+
                                    |         Grafana Alloy         |
                                    |  OTLP gRPC :4317              |
                                    |  OTLP HTTP :4318              |
                                    |  Loki push :3500              |
                                    |  Scrapes node/cAdvisor/       |
                                    |   blackbox/Garage/self        |
                                    |  Docker log auto-discovery    |
                                    +------+----------+-------+-----+
                                           |          |       |
                                         Mimir      Loki   Tempo
                                         (9009)    (3100)  (3200)
                                           +----------+-------+
                                                    |
                                                 Garage
                                       loki/ tempo/ mimir/ buckets
                                       (Garage v2 — AGPLv3)
```

## Signal Flow

| Signal | Path |
|--------|------|
| Host metrics | `node-exporter` → Alloy scrape → **Mimir** |
| Container metrics | `cAdvisor` → Alloy scrape → **Mimir** |
| Object storage metrics | `Garage /metrics` → Alloy scrape (bearer auth) → **Mimir** |
| App metrics | OTel SDK → Alloy OTLP → **Mimir** |
| App traces | OTel SDK → Alloy OTLP → **Tempo** |
| App logs (push) | OTel SDK → Alloy OTLP → **Loki** |
| Container logs | Docker socket → Alloy auto-discovery → **Loki** |
| Synthetic probes | Blackbox → Alloy scrape → **Mimir** |
| Alert evaluation | Mimir ruler reads `/configs/rules/*.yml` (filesystem, no upload needed) |
| Alert routing | Mimir → **Alertmanager** → Slack / Email / webhook |

---

## Services & Ports

| Service | Image | Version | Host port | Notes |
|---------|-------|---------|-----------|-------|
| Grafana | `grafana/grafana` | 13.0.1 | **:3000** | Admin UI |
| Grafana Alloy | `grafana/alloy` | v1.16.1 | **:12345** UI · **:4317** gRPC · **:4318** HTTP · **:3500** Loki | Unified collector |
| Alertmanager | `prom/alertmanager` | v0.32.1 | **:9093** | Alert routing |
| UAR | `ghcr.io/jamesread/uncomplicated-alert-receiver` | latest | internal | Alert inbox UI |
| Mimir | `grafana/mimir` | 3.0.6 | internal | Metrics storage (90 d) |
| Loki | `grafana/loki` | 3.7.1 | internal | Log storage (30 d) |
| Tempo | `grafana/tempo` | 2.10.5 | internal | Trace storage (14 d) |
| Garage | `dxflrs/garage` | v2.3.0 | internal | S3-compatible object store |
| Valkey | `valkey/valkey` | 9.0.4-alpine3.23 | internal | Query result cache |
| node-exporter | `prom/node-exporter` | v1.11.1 | internal | Host metrics |
| cAdvisor | `ghcr.io/google/cadvisor` | 0.56.2 | internal | Container metrics |
| Blackbox Exporter | `prom/blackbox-exporter` | v0.28.0 | internal | Synthetic probes |

> Alloy, Grafana, and Alertmanager are exposed directly on host ports.
> All storage and source services are **Docker-network-only**.
> To add TLS/auth in front, place your own reverse proxy (Caddy, Traefik, nginx)
> in front and expose only that proxy externally.
---

## Configuration Reference

All tunables live in `.env` (copied from `.env.example` and populated by `./stack init`).

### What init auto-generates

Running `./stack init` and answering **Y** to "Auto-generate secrets?" fills these automatically:

| Variable | Generated as | Example |
|----------|-------------|---------|
| `GRAFANA_ADMIN_PASSWORD` | 24-char base64 | `kH9mRvTpXqLwNjC2sYaZbD` |
| `GARAGE_RPC_SECRET` | `openssl rand -hex 32` | `3f8a1b…` (64 hex chars) |
| `GARAGE_ADMIN_TOKEN` | `openssl rand -hex 16` | `9c4d2e…` (32 hex chars) |
| `GARAGE_ACCESS_KEY_ID` | `GK` + `openssl rand -hex 14` | `GKa3f9c2…` |
| `GARAGE_SECRET_ACCESS_KEY` | `openssl rand -hex 32` | `7b1e4a…` (64 hex chars) |

If you ever need to rotate secrets on a running stack:

```bash
./stack secrets    # generates new values and prints restart instructions
```

> ⚠️ Rotating Garage keys requires re-running `garage-init`. The `secrets` command reminds you of the exact commands.

### What you must set manually

| Variable | Description |
|----------|-------------|
| `BASE_DOMAIN` | Your domain — prompted interactively by `./stack init` |
| `GRAFANA_ADMIN_USER` | Grafana admin username — prompted interactively |
| `SLACK_WEBHOOK_URL` | Slack incoming webhook — prompted optionally during init |
| `ALERT_EMAIL_FROM/TO` | Alert email addresses — prompted optionally during init |
| `SMTP_HOST/USERNAME/PASSWORD` | SMTP settings — prompted optionally during init |

To update notification settings on a running stack, edit `.env` then:

```bash
./stack recreate alertmanager
```

---

## Instrumenting Your Application

### From inside the same Docker Compose project

Add to your app service:

```yaml
services:
  myapp:
    image: myapp:latest
    environment:
      OTEL_EXPORTER_OTLP_ENDPOINT: http://alloy:4317     # gRPC
      OTEL_SERVICE_NAME: myapp
      OTEL_RESOURCE_ATTRIBUTES: deployment.environment=production
    networks:
      - monitoring

networks:
  monitoring:
    external: true
    name: monitoring
```

### From a separate Docker Compose project

```yaml
# In your app's docker-compose.yml
services:
  myapp:
    environment:
      OTEL_EXPORTER_OTLP_ENDPOINT: http://alloy:4317
    networks:
      - mon_monitoring    # join the monitoring stack's network

networks:
  mon_monitoring:         # "mon" = the monitoring-stack compose project name
    external: true
```

### From an external host or application

Use the HTTPS ingest endpoints via Nginx:

```
OTLP gRPC:    (TLS termination at nginx — use HTTP endpoint instead)
OTLP HTTP:    https://ingest.<BASE_DOMAIN>/v1/traces
              https://ingest.<BASE_DOMAIN>/v1/metrics
              https://ingest.<BASE_DOMAIN>/v1/logs
Loki push:    https://ingest.<BASE_DOMAIN>/loki/api/v1/push
```

### SDK quick-reference

<details>
<summary>Python (opentelemetry-sdk)</summary>

```python
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

provider = TracerProvider()
provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(
        endpoint="http://alloy:4318/v1/traces"
    ))
)
trace.set_tracer_provider(provider)
```

</details>

<details>
<summary>Node.js (@opentelemetry/sdk-node)</summary>

```javascript
const { NodeSDK } = require('@opentelemetry/sdk-node');
const { OTLPTraceExporter } = require('@opentelemetry/exporter-trace-otlp-http');

const sdk = new NodeSDK({
  traceExporter: new OTLPTraceExporter({
    url: 'http://alloy:4318/v1/traces',
  }),
  serviceName: 'myapp',
});
sdk.start();
```

</details>

---

## Alert Rules & Notifications

Alert rules are YAML files in `configs/rules/` and are loaded automatically by Mimir on startup — no `mimirtool` upload step required.

| File | Covers |
|------|--------|
| `node-rules.yml` | CPU, memory, disk, load average |
| `container-rules.yml` | Container restarts, OOM kills, CPU throttle |
| `blackbox-rules.yml` | HTTP probe failures, TLS expiry |
| `garage-rules.yml` | Garage cluster health, disk usage, S3 errors |

### Add a new rule

Create or edit any file in `configs/rules/`, then:

```bash
./stack rules-check          # validate YAML
./stack recreate mimir       # hot-reload (Mimir re-reads on startup)
```

### Notification channels

Edit `configs/alertmanager/config.yml` to wire up:
- **Slack** — set `SLACK_WEBHOOK_URL` + `SLACK_CHANNEL` in `.env`
- **Email** — set `SMTP_*` + `ALERT_EMAIL_*` in `.env`
- **PagerDuty / OpsGenie / webhook** — add a new receiver in `alertmanager/config.yml`

---

## Reverse Proxy & TLS (optional)

This stack does **not** include a built-in reverse proxy. Services are accessible
directly on their host ports. To add HTTPS and authentication:

| Option | Quick start |
|--------|-------------|
| **Caddy** (recommended) | `caddy reverse-proxy --from grafana.yourdomain.com --to :3000` |
| **Traefik** | Add a `traefik` service to `docker-compose.yml` with label-based routing |
| **nginx** | Mount a custom `nginx.conf` and map port 443 to the services |

> 🔒 **Firewall tip:** Allow only your reverse proxy port (443) from the internet.
> Block direct access to :3000, :9093, :12345 etc. with `ufw deny <port>`.

---

### Lifecycle

| Command | Description |
|---------|-------------|
| `./stack up` | Start all services (detached) |
| `./stack down` | Stop all (volumes retained) |
| `./stack restart <svc>` | Restart one service |
| `./stack recreate <svc>` | Force-recreate (picks up config file changes) |
| `./stack clean` | **Destructive** — stops stack and removes all volumes |

### Observability

| Command | Description |
|---------|-------------|
| `./stack status` | Colour-coded container health |
| `./stack ps` | Compact service list |
| `./stack logs [svc]` | Tail logs — all or one service |
| `./stack exec <svc> <cmd>` | Exec into a container |
| `./stack open` | Open Grafana in your browser |
| `./stack urls` | Print all service URLs |


| Command | Description |
|---------|-------------|

### Validation

| Command | Description |
|---------|-------------|
| `./stack validate` | Validate `docker-compose.yml` + all rule YAML |
| `./stack rules-check` | Lint alert rule files only |

---

## Retention & Storage

| Backend | Default | Env var |
|---------|---------|---------|
| Mimir (metrics) | 90 days | `MIMIR_RETENTION_PERIOD` |
| Loki (logs) | 30 days | `LOKI_RETENTION_PERIOD` |
| Tempo (traces) | 14 days | `TEMPO_RETENTION_PERIOD` |

All three backends store data in **Garage** (S3-compatible, MIT-licensed). Buckets:

| Bucket | Contents |
|--------|----------|
| `loki-data` | Log chunks + index |
| `tempo-data` | Trace blocks |
| `mimir-data` | Metric blocks, ruler state |

Buckets are created automatically by `garage-init` on first startup.

---

## Directory Structure

```
monitoring-stack/
├── stack                       # CLI tool  (chmod +x, then ./stack help)
├── docker-compose.yml
├── .env.example                # Copy to .env before running
├── configs/
│   ├── nginx/
│   │   ├── nginx.conf
│   │   ├── snippets/           # proxy-headers, ssl-params, security-headers, basic-auth
│   │   ├── templates/          # per-subdomain .conf.template (processed by nginx envsubst)
│   │   ├── ssl/                # cert.pem + key.pem  (gitignored)
│   │   └── .htpasswd           # (gitignored)
│   ├── alloy/config.alloy      # Unified collection pipeline
│   ├── loki/config.yml
│   ├── tempo/config.yml
│   ├── mimir/config.yml
│   ├── alertmanager/config.yml
│   ├── blackbox/config.yml
│   ├── rules/                  # Alert & recording rules — auto-loaded by Mimir
│   │   ├── node-rules.yml
│   │   ├── container-rules.yml
│   │   ├── blackbox-rules.yml
│   │   └── garage-rules.yml
│   └── grafana/
│       ├── provisioning/
│       │   ├── datasources/datasources.yml
│       │   └── dashboards/dashboards.yml
│       └── dashboards/         # Drop .json dashboard files here — auto-provisioned
└── scripts/
    ├── garage-entrypoint.sh    # Generates garage.toml from env vars
    ├── garage-init.py          # Creates buckets + keys via Garage v2 admin API
    ├── gen-htpasswd.sh
    └── gen-selfsigned-cert.sh
```

---

## OpenWrt Router Monitoring

Full observability for your OpenWrt router: CPU, memory, network interfaces, NAT connections, WiFi stations, and syslog forwarding — all visible in Grafana.

### Dashboards provisioned

| Dashboard | UID | Panels | Description |
|---|---|---|---|
| OpenWrt Router | `openwrt-router` | 32 | CPU, memory, filesystem, network, load |
| OpenWrt WiFi & Clients | `openwrt-wifi` | 8 | WiFi stations, signal strength, TX/RX rate, NAT |

### 1 — Configure the router IP

Edit `.env` and set your router's actual IP:

```bash
OPENWRT_IP=192.168.31.31   # change to your router IP
```

Then recreate Alloy to pick up the new env var:

```bash
./stack recreate alloy
```

### 2 — Install packages on OpenWrt

SSH into your router and run:

```bash
opkg update
opkg install \
  prometheus-node-exporter-lua \
  prometheus-node-exporter-lua-nat_traffic \
  prometheus-node-exporter-lua-netstat \
  prometheus-node-exporter-lua-openwrt \
  prometheus-node-exporter-lua-wifi \
  prometheus-node-exporter-lua-wifi_stations \
  prometheus-node-exporter-lua-uci_config \
  prometheus-node-exporter-lua-conntrack
```

Start and enable the exporter:

```bash
/etc/init.d/prometheus-node-exporter-lua enable
/etc/init.d/prometheus-node-exporter-lua start
```

Verify it works:

```bash
curl http://192.168.31.31:9100/metrics | head -20
```

### 3 — Forward syslog to Alloy

Edit `/etc/config/system` on the router (or use LuCI → System → System → Logging):

```uci
config system
    option log_ip    <monitoring-host-ip>
    option log_port  514
    option log_proto udp
```

Apply the change:

```bash
/etc/init.d/log restart
```

> Replace `<monitoring-host-ip>` with the IP of the machine running this stack.
> Port 514 UDP is exposed by the Alloy container.

### 4 — Open the dashboards in Grafana

Navigate to **Dashboards → Monitoring Stack**:

- **OpenWrt Router** — system overview (CPU, memory, interfaces, load)
- **OpenWrt WiFi & Clients** — per-station signal, TX/RX rate, NAT count, syslog

### Firewall note

Allow the monitoring host to reach the router's metrics port, and allow the router to send syslog to the monitoring host:

```bash
# On router (OpenWrt)
uci set firewall.openwrt_metrics=rule
uci set firewall.openwrt_metrics.name='Allow metrics scrape'
uci set firewall.openwrt_metrics.src='lan'
uci set firewall.openwrt_metrics.dest_port='9100'
uci set firewall.openwrt_metrics.target='ACCEPT'
uci commit firewall
/etc/init.d/firewall restart

# On monitoring host — allow syslog UDP inbound on port 514
ufw allow 514/udp
```

---

## Production Hardening

### Firewall

Only expose port 443 (and 80 for ACME redirect) to the internet.
All service ports (3000, 9009, 3100, 3200, etc.) must be **blocked** at the firewall.

```bash
ufw allow 80/tcp
ufw allow 443/tcp
ufw deny 3000/tcp   # Grafana — behind nginx
ufw deny 9009/tcp   # Mimir   — backend only
# … repeat for all internal ports
```

### Secrets

- Never commit `.env` to version control (it is gitignored)
- Rotate `GARAGE_ADMIN_TOKEN` periodically — update `.env` then `./stack recreate garage alloy`
- Use a secrets manager (Vault, AWS SSM) for production deployments
### Firewall

If Grafana and Alertmanager are only for internal access, block their host ports:

```bash
# Allow only from trusted networks
ufw allow from 192.168.0.0/16 to any port 3000  # Grafana
ufw allow from 192.168.0.0/16 to any port 9093  # Alertmanager
ufw allow from 192.168.0.0/16 to any port 12345 # Alloy UI
ufw deny 3000
ufw deny 9093
ufw deny 12345
# Storage backends are internal-only (no host ports)
```

### Let's Encrypt auto-renewal

Add a cron job (or systemd timer) to renew and reload:

```bash
```

---

## Troubleshooting

### Stack won't start — check health

```bash
./stack status            # which containers are unhealthy?
./stack logs garage       # common cause: bad GARAGE_* env vars
./stack logs garage-init  # check bucket creation
./stack logs mimir        # rules loading errors appear here
```
### Grafana "Bad Gateway" or service unreachable

```bash
./stack status            # which container is down?
./stack logs alloy         # pipeline errors?
./stack logs mimir         # rules loading errors?
```

2. Check Mimir is healthy: `./stack logs mimir`
3. Verify datasource UIDs in Grafana → Connections → Data sources:
   - Mimir UID must be `mimir`, Loki → `loki`, Tempo → `tempo`

### Garage metrics not appearing

Alloy uses a Bearer token to scrape Garage. Verify `GARAGE_ADMIN_TOKEN` in `.env` matches
the value used during `garage-init`. Re-run if changed:

```bash
./stack recreate garage
./stack recreate alloy
```

### Rules not firing

```bash
./stack rules-check                  # YAML lint
./stack exec mimir -- /bin/sh        # check /rules/anonymous/ directory
ls /rules/anonymous/
```

Mimir reads rules from `/rules/anonymous/` at startup. If you add a new rule file:

```bash
./stack recreate mimir
```

