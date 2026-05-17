import docker
import time
import socket

_client = None

def get_client():
    global _client
    if _client is None:
        _client = docker.from_env()
    return _client

SERVICE_CONFIG = {
    "user-profile": {
        "image":   "nexusguard-user-profile",
        "command": "uvicorn backend.user_profile:app --host 0.0.0.0 --port 8001 --reload",
        "container_port": 8001,
    },
    "recommend": {
        "image":   "nexusguard-recommend",
        "command": "uvicorn backend.recommend:app --host 0.0.0.0 --port 8002 --reload",
        "container_port": 8002,
    },
    "order": {
        "image":   "nexusguard-order",
        "command": "uvicorn backend.order:app --host 0.0.0.0 --port 8003 --reload",
        "container_port": 8003,
    },
    "payment": {
        "image":   "nexusguard-payment",
        "command": "uvicorn backend.payment:app --host 0.0.0.0 --port 8004 --reload",
        "container_port": 8004,
    },
    "notification": {
        "image":   "nexusguard-notification",
        "command": "uvicorn backend.notification:app --host 0.0.0.0 --port 8005 --reload",
        "container_port": 8005,
    },
}

extras: dict[str, list] = {}


def _is_port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) != 0


# Each service gets its own port range so they never collide
SERVICE_PORT_BASE = {
    "user-profile": 9100,
    "recommend":    9200,
    "order":        9300,
    "payment":      9400,
    "notification": 9500,
}

def _alive(containers: list):
    live = []
    for container in containers:
        try:
            container.reload()
            if container.status == "running":
                live.append(container)
        except Exception:
            continue
    return live


def scaling(service: str, number: int = 1):
    config = SERVICE_CONFIG.get(service)
    if not config:
        return []

    spun = []
    base = SERVICE_PORT_BASE.get(service, 9000)
    extras[service] = _alive(extras.get(service, []))
    existing = len(extras[service])
    missing = max(0, number - existing)

    if missing == 0:
        return []

    for i in range(missing):
        port = base + existing + i

        try:
            container = get_client().containers.run(
                image=config["image"],
                command=config["command"],
                detach=True,
                network="nexusguard_default",
                ports={f"{config['container_port']}/tcp": port},
                name=f"nexusguard-{service}-extra-{port}",
                remove=True,
            )
            extras[service].append(container)
            spun.append(port)
            print(f"[scaler] scaled up {service} on port {port}")

        except Exception as e:
            print(f"[scaler] failed to spin {service}: {e}")

    return spun


def scale_down(service: str):
    containers = _alive(extras.get(service, []))
    killed = []

    for container in containers:
        try:
            container.stop(timeout=3)
            killed.append(container.name)
            print(f"[scaler] killed {container.name}")
        except Exception as e:
            print(f"[scaler] failed to kill {container.name}: {e}")

    extras[service] = []
    return killed


def scale_down_all():
    all_killed = []
    for s in list(extras.keys()):
        all_killed.extend(scale_down(s))
    return all_killed


def get_active():
    result = {}
    for s in SERVICE_CONFIG:
        extras[s] = _alive(extras.get(s, []))
        extra_count = len(extras[s])
        result[s] = {
            "base": 1,
            "extra": extra_count,
            "total": 1 + extra_count,
        }
    return result
