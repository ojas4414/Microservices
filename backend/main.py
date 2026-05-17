from backend.forecaster import train, predict, needs_scaling
from backend.scale import scaling, scale_down, scale_down_all, get_active
from backend.database import init_db, insert_call, snapshot_window, get_last_windows
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlite3
import time
import redis
import json
import httpx
import asyncio
import random

SERVICE_URLS = {
    "user-profile": "http://user-profile:8001/health",
    "recommend":    "http://recommend:8002/health",
    "order":        "http://order:8003/health",
    "payment":      "http://payment:8004/health",
    "notification": "http://notification:8005/health",
}

import os
_REDIS_HOST = os.environ.get("REDIS_HOST", "127.0.0.1")
cache = redis.Redis(host=_REDIS_HOST, port=6379, db=0)
app = FastAPI()
forecaster_model = None

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

connected_clients: list[WebSocket] = []


class Callrequest(BaseModel):
    from_service: str
    to_service: str
    latency_ms: float


init_db()

import threading

def bg_forecaster_loop():
    global forecaster_model
    time.sleep(3)
    while True:
        try:
            forecaster_model = train()
        except Exception as e:
            print(f"[forecaster] train error: {e}")
        time.sleep(20)

def bg_window_loop():
    while True:
        window_start = time.time()
        time.sleep(5)
        try:
            snapshot_window(window_start)
        except Exception as e:
            print(f"[snapshot] error: {e}")

threading.Thread(target=bg_forecaster_loop, daemon=True).start()
threading.Thread(target=bg_window_loop, daemon=True).start()


@app.websocket("/ws/calls")
async def websocket_calls(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        while True:
            await asyncio.sleep(1)
    except (WebSocketDisconnect, Exception):
        if websocket in connected_clients:
            connected_clients.remove(websocket)


async def broadcast_call(call_data: dict):
    for client in connected_clients[:]:
        try:
            await client.send_json(call_data)
        except Exception:
            if client in connected_clients:
                connected_clients.remove(client)


@app.post("/call")
async def Call_request(request: Callrequest):
    cache_key = f"{request.from_service}:{request.to_service}"
    cached = cache.get(cache_key)
    if cached:
        result = json.loads(cached)
        result["cache"] = "hit"
        try:
            cache.incr("nexusguard:cache_hits")
        except Exception:
            pass
        asyncio.create_task(broadcast_call({
            "from_service": request.from_service,
            "to_service": request.to_service,
            "latency_ms": request.latency_ms,
            "simulated_cost": 0.0,
            "cache": "hit",
            "id": result.get("id"),
            "timestamp": time.time(),
        }))
        conn = sqlite3.connect("nexusguard.db")
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO call_logs (from_service, to_service, timestamp, latency_ms, simulated_cost, cache_status) VALUES (?,?,?,?,?,?)",
            (request.from_service, request.to_service, time.time(), request.latency_ms, 0.0, 'hit')
        )
        conn.commit()
        conn.close()
        return result

    conn = sqlite3.connect("nexusguard.db")
    cursor = conn.cursor()
    simulated_cost = request.latency_ms * 0.000002
    cursor.execute(
        "INSERT INTO call_logs (from_service, to_service, timestamp, latency_ms, simulated_cost, cache_status) VALUES (?,?,?,?,?,?)",
        (request.from_service, request.to_service, time.time(), request.latency_ms, simulated_cost, 'miss'),
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    result = {"status": "logged", "id": new_id, "cache": "miss"}
    cache.setex(cache_key, 15, json.dumps(result))
    asyncio.create_task(broadcast_call({
        "from_service": request.from_service,
        "to_service": request.to_service,
        "latency_ms": request.latency_ms,
        "simulated_cost": simulated_cost,
        "cache": "miss",
        "id": new_id,
        "timestamp": time.time(),
    }))
    return result


@app.get("/logs")
def logs():
    conn = sqlite3.connect("nexusguard.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM call_logs ORDER BY timestamp DESC LIMIT 100")
    rows = cursor.fetchall()
    conn.close()
    return [{
        "id": row[0], "from_service": row[1], "to_service": row[2],
        "timestamp": row[3], "latency_ms": row[4], "simulated_cost": row[5], "cache": row[6] if len(row) > 6 else "miss"
    } for row in rows]


@app.get("/stats")
def stats():
    conn = sqlite3.connect("nexusguard.db")
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*), SUM(simulated_cost), AVG(latency_ms) FROM call_logs")
    row = cursor.fetchone()
    db_calls   = row[0] or 0
    total_cost = round(row[1] or 0.0, 6)
    avg_latency = round(row[2] or 0.0, 2)

    cursor.execute("""
        SELECT from_service, to_service, SUM(simulated_cost), COUNT(*) as cnt
        FROM call_logs GROUP BY from_service, to_service ORDER BY cnt DESC LIMIT 1
    """)
    expensive = cursor.fetchone()

    cursor.execute("""
        SELECT from_service, to_service, COUNT(*) as cnt, SUM(simulated_cost) as cost
        FROM call_logs GROUP BY from_service, to_service
    """)
    route_rows = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) FROM pre_baked_logs")
    pre_warms = cursor.fetchone()[0] or 0

    conn.close()

    try:
        cache_hits = int(cache.get("nexusguard:cache_hits") or 0)
    except Exception:
        cache_hits = 0

    total_calls = db_calls + cache_hits
    hit_rate = round(cache_hits / total_calls * 100, 1) if total_calls > 0 else 0.0

    return {
        "total_calls": total_calls,
        "cache_hits": cache_hits,
        "cache_misses": db_calls,
        "hit_rate": hit_rate,
        "total_cost": total_cost,
        "avg_latency": avg_latency,
        "pre_warms": pre_warms,
        "most_expensive_route": {
            "from": expensive[0] if expensive else "—",
            "to":   expensive[1] if expensive else "—",
            "cost": round(expensive[2], 6) if expensive else 0,
            "calls": expensive[3] if expensive else 0,
        },
        "routes": [
            {"from": r[0], "to": r[1], "calls": r[2], "cost": round(r[3], 6)}
            for r in route_rows
        ],
    }


@app.get("/status")
def status():
    return stats()


@app.get("/health")
def health_self():
    return {"status": "healthy"}

@app.get("/health/{service}")
def check_service_health(service: str):
    """Proxy health checks so frontend doesn't need to deal with CORS on 5 different ports."""
    url = SERVICE_URLS.get(service)
    if not url:
        return {"status": "offline"}
    try:
        r = httpx.get(url, timeout=2.0)
        return {"status": "warm" if r.status_code == 200 else "offline"}
    except Exception:
        return {"status": "offline"}


# Semi-structured workflows so the LSTM can learn patterns, but varied enough for cache simulation.
CALL_CHAINS = [
    # Standard Login & Checkout
    [("auth", "user-profile"), ("user-profile", "order"), ("order", "payment")],
    [("auth", "order"), ("order", "payment"), ("payment", "notification")],
    # Content Browsing
    [("auth", "user-profile"), ("user-profile", "recommend"), ("recommend", "notification")],
    [("auth", "recommend"), ("recommend", "user-profile"), ("user-profile", "notification")],
    # Admin / Background
    [("order", "notification"), ("notification", "user-profile")],
    [("user-profile", "payment"), ("payment", "recommend")],
] * 2  # duplicate array to avoid modifying single array logic

def _is_prewarmed(cursor, to_svc):
    cursor.execute("SELECT timestamp FROM pre_baked_logs WHERE service=? ORDER BY timestamp DESC LIMIT 1", (to_svc,))
    row = cursor.fetchone()
    # Consider it pre-warmed if the prediction happened within the last 6 seconds
    if row and time.time() - row[0] < 6.0:
        return True
    return False

def _insert_call(cursor, from_svc, to_svc, latency_ms, cache_status='miss'):
    cost = latency_ms * 0.000002 if cache_status == 'miss' else 0.0
    cursor.execute(
        "INSERT INTO call_logs (from_service, to_service, timestamp, latency_ms, simulated_cost, cache_status) VALUES (?,?,?,?,?,?)",
        (from_svc, to_svc, time.time(), latency_ms, cost, cache_status),
    )

@app.post("/seed")
def seed_data():
    """Insert a randomized burst of traffic — different every call."""
    conn = sqlite3.connect("nexusguard.db")
    cursor = conn.cursor()
    rows = 0
    # Pick 4-6 random chains and add random latency noise so training data is always fresh
    chosen = random.choices(CALL_CHAINS, k=random.randint(4, 6))
    for chain in chosen:
        for from_svc, to_svc in chain:
            latency = random.uniform(40, 280)
            _insert_call(cursor, from_svc, to_svc, latency)
            rows += 1
    conn.commit()
    conn.close()
    return {"status": "seeded", "rows": rows}


@app.post("/simulate")
async def simulate_traffic(n: int = 20):
    """Generate n random realistic service calls right now, broadcast each via WS."""
    inserted = 0
    for _ in range(n):
        chain = random.choice(CALL_CHAINS)
        from_svc, to_svc = random.choice(chain)
        latency = random.uniform(35, 300)
        cache_key = f"{from_svc}:{to_svc}"
        
        conn = sqlite3.connect("nexusguard.db")
        cursor = conn.cursor()
        
        hit = cache.exists(cache_key)
        is_pw = not hit and _is_prewarmed(cursor, to_svc)
        
        if hit:
            cache.incr("nexusguard:cache_hits")
            c_status = "hit"
            latency = random.uniform(2, 5) # cache hit latency
            simulated_cost = 0.0
        elif is_pw:
            c_status = "prewarmed"
            latency = random.uniform(8, 25) # pre-warmed latency
            simulated_cost = latency * 0.000002
        else:
            c_status = "miss"
            simulated_cost = latency * 0.000002
            
        cache.setex(cache_key, 15, json.dumps({"id": 0})) # Fake id just to have value
        
        _insert_call(cursor, from_svc, to_svc, latency, cache_status=c_status)
        new_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        asyncio.create_task(broadcast_call({
            "from_service": from_svc,
            "to_service":   to_svc,
            "latency_ms":   round(latency, 1),
            "simulated_cost": round(simulated_cost, 6),
            "cache": c_status,
            "id": new_id,
            "timestamp": time.time(),
        }))
        inserted += 1
        await asyncio.sleep(0.05)  # small gap so WS clients get individual events
    return {"status": "simulated", "calls": inserted}


# Background simulation state
_sim_task: asyncio.Task | None = None

async def _bg_simulate():
    """Continuously generate random calls every 2-4 seconds."""
    while True:
        try:
            chain = random.choice(CALL_CHAINS)
            from_svc, to_svc = random.choice(chain)
            latency = random.uniform(35, 300)
            cache_key = f"{from_svc}:{to_svc}"
            
            conn = sqlite3.connect("nexusguard.db")
            cursor = conn.cursor()
            
            hit = cache.exists(cache_key)
            is_pw = not hit and _is_prewarmed(cursor, to_svc)
            
            if hit:
                cache.incr("nexusguard:cache_hits")
                c_status = "hit"
                latency = random.uniform(2, 5)
                simulated_cost = 0.0
            elif is_pw:
                c_status = "prewarmed"
                latency = random.uniform(8, 25)
                simulated_cost = latency * 0.000002
            else:
                c_status = "miss"
                simulated_cost = latency * 0.000002

            cache.setex(cache_key, 15, json.dumps({"id": 0}))
            
            _insert_call(cursor, from_svc, to_svc, latency, cache_status=c_status)
            conn.commit()
            new_id = cursor.lastrowid
            conn.close()
            
            await broadcast_call({
                "from_service": from_svc,
                "to_service":   to_svc,
                "latency_ms":   round(latency, 1),
                "simulated_cost": round(simulated_cost, 6),
                "cache": c_status,
                "id": new_id,
                "timestamp": time.time(),
            })
        except Exception:
            pass
        await asyncio.sleep(random.uniform(1.5, 3.5))

@app.post("/simulate/start")
async def start_simulation():
    global _sim_task
    if _sim_task and not _sim_task.done():
        return {"status": "already_running"}
    _sim_task = asyncio.create_task(_bg_simulate())
    return {"status": "started"}

@app.post("/simulate/stop")
async def stop_simulation():
    global _sim_task
    if _sim_task and not _sim_task.done():
        _sim_task.cancel()
        _sim_task = None
        return {"status": "stopped"}
    return {"status": "not_running"}


@app.post("/scale/down")
def scale_down_endpoint():
    killed = scale_down_all()
    return {"status": "scaled_down", "killed": killed}


@app.post("/scale/purge")
def scale_purge():
    """Force-kill ALL extra containers by name pattern — handles orphans after restart."""
    import docker as docker_lib
    try:
        client = docker_lib.from_env()
        killed = []
        for container in client.containers.list():
            if "extra" in container.name:
                try:
                    container.stop(timeout=3)
                    killed.append(container.name)
                except Exception:
                    pass  # container already dead, ignore
        scale_down_all()
    except Exception as e:
        return {"killed": [], "error": str(e)}
    return {"killed": killed}


@app.post("/train")
def training():
    global forecaster_model
    forecaster_model = train()
    return {"status": "trained"}


@app.get("/instances")
def instances():
    return get_active()


@app.post("/forecast")
def forecast():
    global forecaster_model
    windows = get_last_windows(12)
    if len(windows) < 12:
        return {"error": "not enough data yet", "windows": len(windows)}
    predictions = predict(forecaster_model, windows)
    spike_services = needs_scaling(predictions)
    scaled = {}
    for svc in spike_services:
        ports = scaling(svc, 2)
        scaled[svc] = ports
    return {
        "predictions": predictions,
        "spike_services": spike_services,
        "scaled_up": scaled,
        "instances": get_active(),
    }
