import time
import random
from fastapi import FastAPI

app = FastAPI()

def simulate_latency():
    time.sleep(random.uniform(0.05, 0.2))

@app.get("/health")
def health():
    return {"service": "payment", "status": "warm"}

@app.get("/payment/{payment_id}")
def get_payment(payment_id: str):
    simulate_latency()
    return {
        "payment_id": payment_id,
        "status": random.choice(["pending", "success", "failed"]),
        "method": random.choice(["card", "upi", "wallet", "netbanking"]),
        "amount_usd": round(random.uniform(5.0, 500.0), 2),
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)
