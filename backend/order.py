import time
import random
from fastapi import FastAPI

app = FastAPI()

def simulate_latency():
    time.sleep(random.uniform(0.05, 0.2))

@app.get("/health")
def health():
    return {"service": "order", "status": "warm"}

@app.get("/order/{order_id}")
def get_order(order_id: str):
    simulate_latency()
    return {
        "order_id": order_id,
        "status": random.choice(["pending", "confirmed", "shipped", "delivered"]),
        "items": random.randint(1, 10),
        "total_usd": round(random.uniform(5.0, 500.0), 2),
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
