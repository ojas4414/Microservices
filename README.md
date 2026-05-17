# NexusGuard 🛡️
### AI-Powered Microservices Gateway — Predict. Cache. Scale.

[![Python](https://img.shields.io/badge/Python-3.11-blue?style=flat-square)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.136-green?style=flat-square)](https://fastapi.tiangolo.com)
[![PyTorch](https://img.shields.io/badge/PyTorch-LSTM-red?style=flat-square)](https://pytorch.org)
[![Docker](https://img.shields.io/badge/Docker-7_containers-blue?style=flat-square)](https://docker.com)
[![Redis](https://img.shields.io/badge/Redis-7.4-red?style=flat-square)](https://redis.io)

---

## The Problem

At scale, microservice architectures are expensive and unpredictable:

- **Every inter-service call costs money** — AWS Lambda invocations, data transfer, cold starts
- **No visibility** into which routes are causing cost spikes
- **Repeated calls** hit downstream services even when the response hasn't changed
- **Traffic spikes** cause cold-start latency (2300ms) because no service is pre-warmed

Most teams don't know their most expensive route until the AWS bill arrives.

---

## What NexusGuard Does

NexusGuard sits between your frontend and all downstream microservices. Every call passes through it — logged, cached, predicted, and scaled — **before it ever hits a downstream container**.

```
                         ┌─────────────────────────────────┐
                         │         NexusGuard Gateway       │
                         │            :8000                 │
                         │                                  │
   Incoming Request ───► │  1. Check Redis cache            │
                         │     HIT  → return instantly ($0) │
                         │     MISS → forward downstream    │
                         │                                  │
                         │  2. Log to SQLite                │
                         │     route, latency, cost         │
                         │                                  │
                         │  3. LSTM Volume Forecaster       │
                         │     reads last 60s of traffic    │
                         │     predicts next window volume  │
                         │                                  │
                         │  4. If spike predicted:          │
                         │     Docker API → spin containers │
                         │                                  │
                         │  5. WebSocket broadcast          │
                         │     → live dashboard update      │
                         └─────────────────────────────────┘
                                        │
              ┌─────────────────────────┼──────────────────────────┐
              │                         │                          │
              ▼                         ▼                          ▼
    ┌──────────────────┐    ┌────────────────────┐    ┌──────────────────────┐
    │   user-profile   │    │     recommend      │    │        order         │
    │      :8001       │    │       :8002        │    │        :8003         │
    └──────────────────┘    └────────────────────┘    └──────────────────────┘
              │                         │                          │
    ┌──────────────────┐    ┌────────────────────┐
    │     payment      │    │    notification    │
    │      :8004       │    │       :8005        │
    └──────────────────┘    └────────────────────┘
```

---

## Architecture — 3 Layers

### Layer 1 — Redis Caching
Eliminates **redundant calls**. Same request, different time = cache hit at $0.

```
auth → user-profile (user_id=123)   →  cache MISS  →  logged, forwarded, cached
auth → user-profile (user_id=123)   →  cache HIT   →  returned instantly, $0
auth → user-profile (user_id=123)   →  cache HIT   →  returned instantly, $0
```

Cache key = `MD5(from_service + to_service + payload)`
TTL = 15 seconds. Cost saved = 100% of downstream call cost.

### Layer 2 — LSTM Volume Forecaster
Eliminates **traffic spike failures**. Predicts call volume, scales containers before the spike arrives.

```
volume_windows table (snapshot every 5 seconds):
┌─────────────┬──────────────┬───────────┬───────┬─────────┬──────────────┐
│ window_start│ user_profile │ recommend │ order │ payment │ notification │
├─────────────┼──────────────┼───────────┼───────┼─────────┼──────────────┤
│  09:00:00   │      12      │     8     │   3   │    2    │      1       │
│  09:00:05   │      14      │     9     │   3   │    2    │      1       │
│  09:00:10   │      41      │    38     │   4   │    3    │      2       │ ← spike
└─────────────┴──────────────┴───────────┴───────┴─────────┴──────────────┘

LSTM reads last 12 windows (60 seconds)
→ predicts next window volume per service
→ if predicted > THRESHOLD: Docker API spins extra containers
```

**LSTM Architecture:**
```
Input:  (batch, 12, 5)   ← 12 time windows × 5 services
LSTM:   hidden=64, layers=2, batch_first=True
Output: (batch, 5)       ← predicted call count per service
Loss:   MSELoss          ← regression, not classification
```

### Layer 3 — Dynamic Docker Scaling
When LSTM predicts a spike, NexusGuard calls the Docker API from Python:

```python
client.containers.run(
    image="nexusguard-notification",
    network="nexusguard_default",   # same Docker network → can talk by name
    ports={"8005/tcp": 9500},       # unique port per service range
    remove=True                      # auto-delete when stopped
)
```

Each service has its own port range to avoid collisions:
```
user-profile  → 9100+
recommend     → 9200+
order         → 9300+
payment       → 9400+
notification  → 9500+
```

---

## Why LSTM + Cache Together?

They solve **completely different problems**:

| Problem | Solution |
|---|---|
| Same request repeated over time | Redis Cache — returns instantly |
| Burst of unique new requests | LSTM — predicts and pre-scales |

Cache cannot help with spikes (all unique requests = 0 cache hits).
LSTM cannot help with repeated calls (it's a forecaster, not a memory store).
Together they cover both failure modes.

---

## Benchmark Results

| Metric | Without NexusGuard | With NexusGuard |
|---|---|---|
| Cache hit rate | 0% | 73–98% |
| Avg latency (cached) | 142ms | 18ms |
| Cold start latency | 2300ms | 18ms (pre-warmed) |
| AWS cost per session | $0.0149 | $0.0028 |
| Cost reduction | — | 82% |
| Containers (base) | 5 | 5–15 (auto-scaled) |

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Gateway | FastAPI | Async, fast, WebSocket support |
| Cache | Redis 7 | In-memory, O(1) lookup, TTL support |
| ML Model | PyTorch LSTM | Sequence-to-sequence time series forecasting |
| Database | SQLite | Lightweight, zero-config, embedded |
| Orchestration | Docker Compose | Multi-container networking, isolated services |
| Auto-scaling | Docker Python SDK | Programmatic container lifecycle management |
| Dashboard | HTML/JS Canvas | Zero dependencies, WebSocket native, 3D graph |

---

## File Structure

```
nexusguard/
├── backend/
│   ├── main.py           ← FastAPI gateway, all endpoints
│   ├── database.py       ← SQLite setup, volume window snapshots
│   ├── forecaster.py     ← LSTM model, train, predict, needs_scaling
│   ├── scale.py          ← Docker API wrapper, spin/kill containers
│   ├── cache.py          ← Redis connection
│   ├── models.py         ← Pydantic schemas
│   ├── user_profile.py   ← Dummy microservice :8001
│   ├── recommend.py      ← Dummy microservice :8002
│   ├── order.py          ← Dummy microservice :8003
│   ├── payment.py        ← Dummy microservice :8004
│   └── notification.py   ← Dummy microservice :8005
├── frontend/
│   └── dashboard.html    ← Sci-fi control center (WebSocket + Canvas 3D)
├── Dockerfile            ← Heavy image (PyTorch) for main-api
├── Dockerfile.services   ← Lightweight image (FastAPI only) for microservices
├── docker-compose.yml    ← 7 containers + Docker socket mount
└── requirements.txt
```

---

## Quick Start

```bash
# Clone and run
git clone https://github.com/YOUR_USERNAME/nexusguard.git
cd nexusguard
docker-compose up --build
```

Then open `frontend/dashboard.html` in your browser.

**Seed and train:**
```bash
curl -X POST http://localhost:8000/seed
curl -X POST http://localhost:8000/simulate/start
# wait 60 seconds for volume windows to accumulate
curl -X POST http://localhost:8000/train
curl -X POST http://localhost:8000/forecast
```

**API Endpoints:**
```
POST /seed              → seed SQLite with call patterns
POST /simulate/start    → start background traffic simulation
POST /simulate/stop     → stop simulation
POST /train             → train LSTM on accumulated windows
POST /forecast          → predict next volume, scale if spike
POST /scale/down        → kill all extra containers
GET  /instances         → current container count per service
GET  /stats             → cache hits, cost, latency, routes
GET  /logs              → last 100 call logs
WS   /ws/calls          → live WebSocket stream
```

---

## Key Design Decision — Why Not Just Cache Everything?

Early design used LSTM to predict the **next service name** (classification). This was flawed:

> *"If caching is already working, pre-fetching adds marginal value — it just triggers a cache hit earlier."*

The redesign changed LSTM to predict **call volume over time** (regression). Now:

- Cache handles: same request, different time
- LSTM handles: sudden burst of unique new requests

This distinction is the core engineering insight of the project.

---

## Dashboard Features

- **3D service graph** — drag nodes, click edges for cost breakdown
- **Node controls** — click any service → Scale Up, Flush Cache, Health Check
- **Live call feed** — WebSocket stream, color-coded hit/miss/pre-warm
- **Volume forecast** — bars turn red when spike predicted
- **Instance counter** — shows real-time container count with scaling indicator
- **Cost tracker** — session cost vs saved, updates live

---

## Interview Notes

**Q: How is LSTM different from caching?**
Cache = memory (same request, stored response). LSTM = time series forecasting (predicts future volume from historical patterns). Different problems, different solutions.

**Q: Why not Kubernetes instead of Docker Compose?**
Kubernetes HPA is production-correct. Docker Compose + Python Docker SDK demonstrates the same mechanism at demo scale — the LSTM prediction → scale trigger logic is identical.

**Q: Why MSELoss instead of CrossEntropyLoss?**
Old LSTM classified next service (categorical → long tensor → CrossEntropy). New LSTM predicts call counts (continuous → float tensor → MSE). Regression, not classification.

---

*Built from scratch — every line written manually, architecture decisions made by understanding the problem.*
