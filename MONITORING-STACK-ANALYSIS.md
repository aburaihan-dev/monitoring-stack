# 🎛️ Mission Control Centre — Monitoring Stack Analysis & Plan

> **Objective:** Combine two reference GitHub repos into a single, production-grade observability
> stack covering infrastructure hardware, containers, logs, distributed traces, and application
> metrics — all in one unified dashboard.

---

## 📦 Source Repositories

| | Repo 1 | Repo 2 |
|---|---|---|
| **Name** | `ruanbekker/docker-monitoring-stack-gpnc` | `quochuydev/dokploy-grafana-compose` |
| **Focus** | Infra metrics + logs + alerting | Modern LGTM stack + tracing + OTel |
| **Collector** | Promtail (deprecated) | Grafana Alloy (modern) |
| **Metrics Store** | Prometheus TSDB (7-day local) | Mimir (long-term, scalable) |
| **Log Store** | Loki | Loki |
| **Trace Store** | ❌ None | Tempo |
| **OTel Ingest** | ❌ None | ✅ OTLP gRPC + HTTP |
| **Alerting** | ✅ Alertmanager + alert rules + UAR | ❌ None |
| **Container Metrics** | ✅ cAdvisor | ❌ None |
| **Docker Log Discovery** | ✅ Promtail socket | ❌ Push-only |
| **Cross-Signal Correlation** | ❌ | ✅ Traces ↔ Logs ↔ Metrics |
| **Object Storage** | ❌ Filesystem only | ❌ Filesystem only |
| **Grafana Auth** | ❌ Anonymous (dev-grade) | ✅ Admin credentials |
| **Health Checks** | ❌ Partial | ✅ All services |
| **Config Management** | ✅ Volume-mounted files | ⚠️ Baked into Dockerfiles |

---

## 🔍 Deep Analysis

### Repo 1 — GPNC Stack

**What it does well:**
- End-to-end alerting: Prometheus alert rules → Alertmanager → UAR alert inbox
- cAdvisor provides per-container CPU / RAM / network / disk metrics
- Promtail auto-discovers Docker container logs via the Docker socket (label-based)
- Recording rules for pre-aggregated metrics
- Redis, resource limits, JSON log rotation all configured

**Critical production gaps:**
- **No distributed tracing** — you cannot trace a slow request across services
- **No OpenTelemetry** — cannot receive app-level metrics/traces/logs from SDKs
- **Short-term metrics only** — Prometheus TSDB with 7-day retention is unsuitable for trends
- **Promtail is deprecated** — Grafana replaced it with Alloy; no future investment
- **Anonymous Grafana auth** — anyone on the network is an admin
- **Filesystem-only storage** — a disk failure destroys all observability history

---

### Repo 2 — Dokploy Grafana Compose

**What it does well:**
- **Grafana Alloy** is the modern unified collector (replaces Promtail, Prometheus Agent,
  OpenTelemetry Collector — all in one)
- **Tempo** provides full distributed trace storage + OTLP gRPC/HTTP ingest
- **Mimir** offers Prometheus-compatible, horizontally scalable long-term metrics
- **Cross-datasource linking** in Grafana: click a trace ID in logs → jump to Tempo;
  click a service in Tempo → jump to Mimir metrics for that service
- Proper health checks, resource reservations, and admin credentials

**Critical production gaps:**
- **Zero alerting** — no Alertmanager, no alert rules, no notification routing
- **No container metrics** — cAdvisor is absent, so you can't see per-container usage
- **No Docker log auto-discovery** — only push-based; running containers are invisible
- **Config baked into Docker images** — every config change requires a rebuild
- **No synthetic monitoring** — no URL/endpoint probing (Blackbox Exporter)
- **Filesystem-only storage** — same durability risk as Repo 1

---

## ✅ Feasibility Assessment

### Verdict: **Fully Feasible on a single Linux Docker host**

All services run as Docker containers; the combined stack is a single `docker-compose up -d`.
No Kubernetes required. For production durability, MinIO provides S3-compatible object storage
so Loki, Tempo, and Mimir write to durable block storage instead of ephemeral local disk.

### Host Requirements

| Resource | Minimum | Recommended |
|---|---|---|
| **CPU** | 4 vCPU | 8 vCPU |
| **RAM** | 8 GB | 16 GB |
| **Disk** | 80 GB | 200 GB |
| **OS** | Ubuntu 22.04 LTS | Ubuntu 24.04 LTS |
| **Docker** | Engine 24+ with Compose Plugin | Engine 26+ |

### Memory Budget (peak estimates)

| Service | Limit | Reserve |
|---|---|---|
| Grafana | 512 MB | 256 MB |
| Mimir | 1 GB | 512 MB |
| Loki | 1 GB | 512 MB |
| Tempo | 1 GB | 512 MB |
| Alloy | 512 MB | 256 MB |
| Alertmanager | 256 MB | 128 MB |
| cAdvisor | 256 MB | 128 MB |
| node-exporter | 128 MB | 32 MB |
| Blackbox Exporter | 64 MB | 32 MB |
| MinIO | 512 MB | 256 MB |
| Redis | 256 MB | 128 MB |
| UAR | 64 MB | 32 MB |
| **TOTAL** | **~5.4 GB** | **~2.8 GB** |

---

## 🏗️ Combined Architecture

> 🎨 **Interactive Excalidraw Diagram:**
> [Open Architecture Diagram →](https://excalidraw.com/#json=tI1miA0rxEX0BuE5K8Sq7,dJvMJTVRNZwEmKXe16gomg)

### ASCII Diagram — Layer Overview

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                       🎛️  MISSION CONTROL CENTRE                            ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  ┌─────────────────── VISUALIZATION LAYER ────────────────────────────────┐ ║
║  │                                                                         │ ║
║  │                    ┌────────────────────┐                               │ ║
║  │                    │      GRAFANA        │                               │ ║
║  │                    │   Dashboards /      │                               │ ║
║  │                    │   Alerts / Explore  │                               │ ║
║  │                    └────────────────────┘                               │ ║
║  └─────────────────────────────────────────────────────────────────────────┘ ║
║          │           │           │           │           │                   ║
║     (metrics)     (logs)      (traces)    (alerts)   (alert UI)              ║
║          ↓           ↓           ↓           ↓           ↓                   ║
║  ┌─────────────────── STORAGE & ALERTING LAYER ────────────────────────────┐ ║
║  │                                                                         │ ║
║  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌──────────────┐  ┌────────┐ │ ║
║  │  │  MIMIR  │  │  LOKI   │  │  TEMPO  │  │ ALERTMANAGER │  │  UAR   │ │ ║
║  │  │ :9009   │  │ :3100   │  │ :3200   │  │    :9093     │  │ :9094  │ │ ║
║  │  │ metrics │  │  logs   │  │ traces  │  │  routing /   │  │ alert  │ │ ║
║  │  │  90d    │  │  30d    │  │  14d    │  │  silencing   │  │  UI    │ │ ║
║  │  └─────────┘  └─────────┘  └─────────┘  └──────────────┘  └────────┘ │ ║
║  └─────────────────────────────────────────────────────────────────────────┘ ║
║          ↑           ↑           ↑                                           ║
║  ┌─────────────────── COLLECTION LAYER ────────────────────────────────────┐ ║
║  │                                                                         │ ║
║  │  ╔═══════════════════════════════════════════════════════════════════╗  │ ║
║  │  ║                    GRAFANA ALLOY                                  ║  │ ║
║  │  ║   OTLP gRPC :4317  │  OTLP HTTP :4318  │  Prom write :9090      ║  │ ║
║  │  ║   Loki push :3500  │  Scrape engine    │  Docker log discovery  ║  │ ║
║  │  ╚═══════════════════════════════════════════════════════════════════╝  │ ║
║  └─────────────────────────────────────────────────────────────────────────┘ ║
║          ↑           ↑           ↑           ↑           ↑                   ║
║  ┌─────────────────── SOURCES LAYER ───────────────────────────────────────┐ ║
║  │                                                                         │ ║
║  │  ┌────────────┐  ┌─────────┐  ┌──────────┐  ┌────────────┐  ┌──────┐ │ ║
║  │  │   NODE     │  │cADVISOR │  │BLACKBOX  │  │ APP / SDK  │  │DOCKER│ │ ║
║  │  │ EXPORTER   │  │:8080    │  │EXPORTER  │  │ OTel OTLP  │  │ LOGS │ │ ║
║  │  │ host/OS    │  │container│  │synthetic │  │traces+mtrc │  │      │ │ ║
║  │  └────────────┘  └─────────┘  └──────────┘  └────────────┘  └──────┘ │ ║
║  └─────────────────────────────────────────────────────────────────────────┘ ║
║                                                                              ║
║  ┌─────────────────── INFRASTRUCTURE LAYER ────────────────────────────────┐ ║
║  │                                                                         │ ║
║  │     ┌─────────────────────────┐       ┌──────────────────────┐         │ ║
║  │     │  MINIO  (S3-compatible) │       │  REDIS (query cache) │         │ ║
║  │     │  loki/ tempo/ mimir/    │       │  Loki + Mimir cache  │         │ ║
║  │     └─────────────────────────┘       └──────────────────────┘         │ ║
║  └─────────────────────────────────────────────────────────────────────────┘ ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

---

## 🔀 Data Flow

> 🎨 **Interactive Excalidraw Diagram:**
> [Open Data Flow Diagram →](https://excalidraw.com/#json=F8ADgFm7oQpTMjzuCKYeZ,H7AUCz1RpaUK1DPrzv7B_g)

### ASCII Diagram — Signal Routing

```
┌─ INFRASTRUCTURE SIGNALS ──────────────────────────────────────────────────┐
│                                                                             │
│  /proc, /sys, /              /var/lib/docker          Docker socket        │
│       │                            │                        │              │
│  node-exporter             cAdvisor :8080           Alloy log discovery    │
│       │                            │                        │              │
│       └──────────────scrape────────┘                        │              │
│                            │                                │              │
│                     Alloy scrape                    Alloy docker.logs      │
│                            │                                │              │
│              ┌─── remote_write ──────┐                      │              │
│              ↓                       │               ┌──loki.write──┐      │
│           MIMIR                      │               ↓              │      │
│                                      └────────→    LOKI             │      │
└─────────────────────────────────────────────────────────────────────┘      │
                                                                              │
┌─ APPLICATION SIGNALS ─────────────────────────────────────────────────────┐ │
│                                                                             │ │
│  App (Go / Java / Python / .NET / Node.js)                                  │ │
│       │                                                                     │ │
│       ├── OTLP gRPC :4317  ──→  Alloy otelcol.receiver.otlp                │ │
│       └── OTLP HTTP :4318  ──→       │                                     │ │
│                                      ├── traces  ──→  TEMPO               │ │
│                                      ├── metrics ──→  MIMIR               │ │
│                                      └── logs    ──→  LOKI ←──────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                                                              │
┌─ SYNTHETIC SIGNALS ───────────────────────────────────────────────────────┐  │
│                                                                             │  │
│  Blackbox Exporter :9115                                                    │  │
│       │  probes: HTTP/HTTPS/TCP/ICMP endpoints                             │  │
│       └── Alloy scrape ──→ MIMIR                                            │  │
└─────────────────────────────────────────────────────────────────────────────┘  │
                                                                                  │
┌─ ALERTING FLOW ──────────────────────────────────────────────────────────────┐ │
│                                                                               │ │
│  MIMIR / LOKI (ruler)                                                         │ │
│       │  alert rules (PromQL / LogQL)                                         │ │
│       ↓                                                                       │ │
│  GRAFANA ALERTING ENGINE                                                      │ │
│       │  evaluates rules against all datasources                              │ │
│       ↓                                                                       │ │
│  ALERTMANAGER :9093                                                           │ │
│       │  dedup │ group │ route │ silence                                      │ │
│       ├──→  Slack webhook                                                     │ │
│       ├──→  Email SMTP                                                        │ │
│       ├──→  PagerDuty / Opsgenie API                                          │ │
│       └──→  UAR :9094  (alert inbox UI)                                       │ │
└───────────────────────────────────────────────────────────────────────────────┘
```

---

## 📊 What You Can Monitor

| Signal | Tool Chain | Coverage |
|---|---|---|
| **CPU / RAM / Disk / Network** | node-exporter → Alloy → Mimir → Grafana | ✅ Host OS |
| **Container CPU / RAM / Net** | cAdvisor → Alloy → Mimir → Grafana | ✅ Per container |
| **Application Metrics** | OTel SDK → Alloy → Mimir → Grafana | ✅ Custom metrics |
| **Application Logs** | OTel SDK or Docker → Alloy → Loki → Grafana | ✅ Structured + plain |
| **Distributed Traces** | OTel SDK → Alloy → Tempo → Grafana | ✅ End-to-end request flow |
| **URL / API Probes** | Blackbox → Alloy → Mimir → Grafana | ✅ Uptime + latency |
| **Alerts (infra)** | Mimir ruler → Alertmanager | ✅ CPU/disk/memory thresholds |
| **Alerts (app SLO)** | Mimir/Loki → Grafana Alerts | ✅ Error rate / p99 latency |
| **Cross-signal drill-down** | Grafana correlation | ✅ Log → Trace → Metric |

---

## 🔐 Production Hardening

```
┌─ SECURITY ────────────────────────────────────────────────────────────────┐
│                                                                             │
│  Auth      Grafana admin credentials via .env (not anonymous)              │
│  Secrets   All passwords in .env file (gitignored)                         │
│  TLS       Reverse proxy (Traefik / Nginx) terminates HTTPS                │
│  Alloy     Protected with Traefik basicAuth middleware                      │
│  Network   Internal services NOT exposed on host ports                     │
│  MinIO     Root credentials via env vars, bucket policies per service      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─ RELIABILITY ─────────────────────────────────────────────────────────────┐
│                                                                             │
│  Restart   unless-stopped on all services                                  │
│  Health    health checks on Grafana, Loki, Tempo, Mimir, MinIO             │
│  Retention Loki 30d │ Mimir 90d │ Tempo 14d (configurable via env)         │
│  Backups   MinIO buckets: loki/ tempo/ mimir/ (S3-compatible)              │
│  Limits    mem_limit + mem_reservation on every container                  │
│  Logs      json-file driver: max-size=5m max-file=3 on all containers      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 📋 Full Service Inventory

| Service | Image | Role | Internal Port | Exposed |
|---|---|---|---|---|
| `grafana` | `grafana/grafana:11.x` | Dashboards, alerting UI | 3000 | ✅ :3000 |
| `alloy` | `grafana/alloy:latest` | Unified collector pipeline | 4317, 4318, 3500, 9090, 12345 | 🔒 via proxy |
| `loki` | `grafana/loki:3.x` | Log storage & querying | 3100 | 🔒 internal |
| `tempo` | `grafana/tempo:2.x` | Trace storage & querying | 3200, 4317 | 🔒 internal |
| `mimir` | `grafana/mimir:2.x` | Long-term scalable metrics | 9009 | 🔒 internal |
| `alertmanager` | `prom/alertmanager:latest` | Alert routing, dedup, silencing | 9093 | ✅ :9093 |
| `node-exporter` | `prom/node-exporter:latest` | Host hardware & OS metrics | 9100 | 🔒 internal |
| `cadvisor` | `gcr.io/cadvisor/cadvisor` | Docker container metrics | 8080 | 🔒 internal |
| `blackbox-exporter` | `prom/blackbox-exporter` | HTTP/TCP/ICMP synthetic probes | 9115 | 🔒 internal |
| `minio` | `minio/minio:latest` | S3-compatible object storage | 9000, 9001 | ✅ :9001 (UI) |
| `redis` | `redis:7-alpine` | Query result cache | 6379 | 🔒 internal |
| `uar` | `ghcr.io/jamesread/uncomplicated-alert-receiver` | Alert inbox UI | 8080 | ✅ :9094 |

---

## 🗺️ Implementation Plan

### Phase 1 — Foundation
| # | Task | Description |
|---|---|---|
| 1 | `scaffold` | Create `configs/` directory tree for all 12 services |
| 2 | `.env.example` | All secrets, versions, retention settings as env vars |
| 3 | `docker-compose.yml` | Full compose with resource limits, health checks, networks |
| 4 | `minio-init.sh` | Create buckets: `loki`, `tempo`, `mimir` on first boot |

### Phase 2 — Storage Backends
| # | Task | Description |
|---|---|---|
| 5 | `loki/config.yml` | MinIO S3 backend, compactor, 30-day retention |
| 6 | `tempo/config.yml` | MinIO S3 backend, 14-day retention, OTLP receiver |
| 7 | `mimir/config.yml` | MinIO S3 backend, 90-day retention, ruler enabled |

### Phase 3 — Collection Pipeline
| # | Task | Description |
|---|---|---|
| 8 | `alloy/config.alloy` | Scraping (node, cAdvisor, blackbox), OTLP ingest, Docker log discovery, fan-out |
| 9 | `blackbox/config.yml` | HTTP/TCP probe modules |

### Phase 4 — Alerting
| # | Task | Description |
|---|---|---|
| 10 | `alertmanager/config.yml` | Slack + email routing, grouping, inhibition rules |
| 11 | `prometheus/rules/` | Node-level, container-level, application SLO alert rules |

### Phase 5 — Visualization
| # | Task | Description |
|---|---|---|
| 12 | `grafana/datasources.yml` | Mimir + Loki + Tempo + Alertmanager with correlation links |
| 13 | `grafana/dashboards/` | Node Metrics, Container Metrics, APM, Logs, Traces dashboards |

### Phase 6 — Documentation
| # | Task | Description |
|---|---|---|
| 14 | `README.md` | Setup guide, OTel SDK integration examples, alert configuration |

---

## 🧩 OpenTelemetry Application Integration

```
Your App (any language)
     │
     ├── go get go.opentelemetry.io/otel   (Go)
     ├── pip install opentelemetry-sdk      (Python)
     ├── npm install @opentelemetry/sdk-node (Node.js)
     └── ... (Java, .NET, Ruby, PHP, Rust all supported)
     │
     └──→  OTLP exporter → http://alloy:4318   (HTTP)
                         → alloy:4317           (gRPC)
                              │
                              ├── traces  → Tempo
                              ├── metrics → Mimir
                              └── logs    → Loki
```

---

> **Next Step:** Run `make up` (or `docker compose up -d`) to launch all 12 services.
> Grafana will be available at `http://localhost:3000` with all datasources pre-provisioned.
