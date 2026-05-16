import time
import random
from fastapi import FastAPI

app = FastAPI()

def simulate_latency():
    time.sleep(random.uniform(0.05, 0.2))

@app.get("/health")
def health():
    return {"service": "user-profile", "status": "warm"}

@app.get("/user/{user_id}")
def get_user(user_id: str):
    simulate_latency()
    return {
        "user_id": user_id,
        "name": f"User {user_id}",
        "email": f"user{user_id}@example.com",
        "tier": random.choice(["free", "pro", "enterprise"]),
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
