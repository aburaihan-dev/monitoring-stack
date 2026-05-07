# 🛰 Monitoring Stack — Mission Control Centre

> **Full-stack observability for production.**
> Infrastructure metrics, container metrics, application traces & logs, synthetic probes, and alerting —
> unified in a single Grafana-based stack with Nginx reverse proxy and S3-compatible object storage.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Architecture](#architecture)
3. [Signal Flow](#signal-flow)
4. [Services & Ports](#services--ports)
5. [Configuration Reference](#configuration-reference)
6. [Instrumenting Your Application](#instrumenting-your-application)
7. [Alert Rules & Notifications](#alert-rules--notifications)
8. [TLS / SSL Setup](#tls--ssl-setup)
9. [CLI Reference](#cli-reference)
10. [Retention & Storage](#retention--storage)
11. [Directory Structure](#directory-structure)
12. [Production Hardening](#production-hardening)
13. [Troubleshooting](#troubleshooting)

---

## Quick Start

### Prerequisites

| Tool | Minimum version | Purpose |
|------|----------------|---------|
| Docker Engine | 24+ | Container runtime |
| Docker Compose | v2 (plugin) | Orchestration |
| `openssl` | any | TLS cert generation |
| `apache2-utils` / `httpd-tools` | any | `htpasswd` for nginx auth |
| RAM | **8 GB** | Stack peak ~5.2 GB |

### 1 — Clone

```bash
git clone <this-repo>
cd monitoring-stack
chmod +x stack
```

### 2 — Add DNS entries

Point all subdomains at your host IP. For local dev, add to `/etc/hosts`:

```
127.0.0.1  grafana.monitoring.local
127.0.0.1  alertmanager.monitoring.local
127.0.0.1  uar.monitoring.local
127.0.0.1  alloy.monitoring.local
127.0.0.1  ingest.monitoring.local
127.0.0.1  s3.monitoring.local
```

### 3 — Run the init wizard

```bash
./stack init
```

The wizard walks through every step interactively:

| Step | What happens |
|------|-------------|
| **Domain** | Enter your `BASE_DOMAIN` (default: `monitoring.local`) |
| **Admin user** | Enter Grafana admin username (default: `admin`) |
| **Auto-generate secrets** | Generates and writes all passwords/keys to `.env`, then displays them once |
| **Notifications** | Optionally configure Slack webhook and/or email (SMTP) |
| **SSL cert** | Choose: self-signed / existing cert / Let's Encrypt / ZeroSSL |
| **htpasswd** | Set nginx basic-auth credentials |
| **Stack up** | Pulls images and starts all 14 services |

> 💡 **Save the generated secrets** — they are displayed once during init and written to `.env`.
> Back up `.env` to a password manager; it is gitignored and never committed.

### 4 — Verify

```bash
./stack status     # colour-coded health for all containers
./stack urls       # print all service URLs
```

Open `https://grafana.<BASE_DOMAIN>` → log in with your `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD`.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         NGINX  (80 → 443)                               │
│   grafana.*  alertmanager.*  alloy.*  ingest.*  uar.*  s3.*             │
└──────┬───────────┬──────────────┬──────────┬──────────┬─────────────────┘
       │           │              │          │          │
   Grafana   Alertmanager      Alloy UI     UAR        Garage S3
   (3000)    (9093)            (12345)    (8080)       (3900)
                  ┌──────────────────────────────────────────┐
                  │               Grafana Alloy               │
                  │  OTLP gRPC :4317   OTLP HTTP :4318       │
                  │  Loki push  :3500  Prom rw   :9090       │
                  │  Scrapes: node-exporter, cAdvisor,       │
                  │           blackbox, Garage, self         │
                  │  Docker log auto-discovery               │
                  └────┬──────────────┬──────────────┬───────┘
                       │              │              │
                     Mimir           Loki          Tempo
                    (9009)          (3100)         (3200)
                       └──────────────┴──────────────┘
                                      │
                                   Garage
                          loki-data / tempo-data / mimir-data
                          (S3-compatible — MIT licensed)
```

---

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

| Service | Internal port | External URL | Auth |
|---------|--------------|--------------|------|
| Grafana | 3000 | `https://grafana.<BASE_DOMAIN>` | Grafana login |
| Alertmanager | 9093 | `https://alertmanager.<BASE_DOMAIN>` | nginx basic auth |
| Alloy UI | 12345 | `https://alloy.<BASE_DOMAIN>` | nginx basic auth |
| OTLP HTTP ingest | 4318 | `https://ingest.<BASE_DOMAIN>/v1/` | — |
| Loki push | 3500 | `https://ingest.<BASE_DOMAIN>/loki/` | — |
| UAR | 8080 | `https://uar.<BASE_DOMAIN>` | nginx basic auth |
| Garage S3 | 3900 | `https://s3.<BASE_DOMAIN>` | Garage key/secret |
| Mimir | 9009 | internal only | — |
| Loki | 3100 | internal only | — |
| Tempo | 3200 | internal only | — |
| Node Exporter | 9100 | internal only | — |
| cAdvisor | 8080 | internal only | — |
| Blackbox Exporter | 9115 | internal only | — |
| Redis | 6379 | internal only | — |

All internal services are **Docker-network-only** — no host ports exposed.

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

## TLS / SSL Setup

Run at any time (also called automatically by `./stack init`):

```bash
./stack cert
```

You will be prompted to choose from four options:

```
  1) Self-signed         (dev/testing — browser security warning)
  2) Existing cert       (paste paths to your cert + key files)
  3) Let's Encrypt       (free, browser-trusted, auto-renew — requires public domain)
  4) ZeroSSL             (free, ACME v2 alternative CA — requires public domain + EAB)
```

### Option 1 — Self-signed

Generates a 10-year RSA-2048 cert covering `*.BASE_DOMAIN` + `localhost` instantly via `openssl`. Browsers will show a security warning — acceptable for local/dev use only.

### Option 2 — Existing cert (Let's Encrypt obtained separately)

The script prompts for paths to your cert and key files, copies them to `configs/nginx/ssl/`, verifies the pair match, and prints the expiry date.

```bash
./stack cert
# → Choose 2
# → Cert:  /etc/letsencrypt/live/example.com/fullchain.pem
# → Key:   /etc/letsencrypt/live/example.com/privkey.pem
```

### Option 3 — Let's Encrypt (automated)

Requires `certbot` installed on the host and a **publicly reachable domain**.

```bash
# Install certbot first if needed
sudo apt install certbot          # Ubuntu/Debian
sudo dnf install certbot          # RHEL/Fedora
brew install certbot              # macOS

./stack cert   # → Choose 3
```

Then choose the challenge type:

| Challenge | When to use |
|-----------|-------------|
| **HTTP-01 standalone** | Port 80 reachable from internet; nginx is paused ~30 s |
| **DNS-01 manual** | Behind firewall / wildcard cert; you add one DNS TXT record |

HTTP-01 issues individual certs per subdomain. DNS-01 issues a wildcard `*.BASE_DOMAIN`.

### Option 4 — ZeroSSL (automated)

Same flow as Let's Encrypt but uses the ZeroSSL CA. Requires free EAB credentials:

1. Sign up at [app.zerossl.com](https://app.zerossl.com)
2. Go to **Developer** → **EAB Credentials** → generate a key pair
3. Run `./stack cert` → choose **4** → paste the EAB Key ID and HMAC Key when prompted

### Auto-renewal (options 3 & 4)

After ACME cert generation, the script prints a ready-to-paste cron job:

```bash
# Add with: sudo crontab -e
0 3 * * 1  cd /opt/monitoring-stack && ./stack cert-renew >> /var/log/stack-cert-renew.log 2>&1
```

`cert-renew` stops nginx, calls `certbot renew`, copies the new cert, and reloads nginx — all in one command.

### Swapping a cert on a running stack

```bash
./stack cert          # choose any option
./stack nginx-test    # verify config is valid
./stack nginx-reload  # zero-downtime reload
```

---

## CLI Reference

```bash
./stack <command> [service]
```

### Setup

| Command | Description |
|---------|-------------|
| `./stack init` | Full wizard: domain → secrets → SSL → htpasswd → up |
| `./stack secrets` | Rotate all auto-generated secrets in `.env` |
| `./stack cert` | Set up TLS (4 options: self-signed / existing / Let's Encrypt / ZeroSSL) |
| `./stack cert-renew` | Renew ACME cert and reload nginx (run via cron weekly) |
| `./stack auth` | (Re)create nginx `htpasswd` credentials |
| `./stack pull` | Pull latest images for all services |

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

### Nginx

| Command | Description |
|---------|-------------|
| `./stack nginx-reload` | Reload config without downtime |
| `./stack nginx-test` | Test nginx config for syntax errors |

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

### Resource limits

Resource limits are already set per service in `docker-compose.yml`.
Review and tune `mem_limit` / `cpus` to match your host capacity.

### Backup

```bash
# Backup Garage data directory
docker run --rm -v garage-data:/data -v $(pwd):/backup \
  alpine tar czf /backup/garage-backup-$(date +%Y%m%d).tar.gz /data
```

### Let's Encrypt auto-renewal

Add a cron job (or systemd timer) to renew and reload:

```bash
# /etc/cron.d/monitoring-certbot
0 3 * * * root certbot renew --quiet && \
  cd /opt/monitoring-stack && ./stack cert && ./stack nginx-reload
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

### nginx: Bad Gateway

```bash
./stack nginx-test        # syntax errors?
./stack logs nginx        # upstream connection refused?
./stack ps                # is the upstream service actually running?
```

### Cert/key mismatch (nginx won't start)

```bash
./stack cert              # choose option 2 and re-paste the correct files
./stack nginx-test && ./stack nginx-reload
```

### Grafana datasource "No data"

1. Check Alloy is scraping: `./stack logs alloy`
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

