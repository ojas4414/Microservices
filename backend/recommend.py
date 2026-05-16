import time
import random
from fastapi import FastAPI

app = FastAPI()

def simulate_latency():
    time.sleep(random.uniform(0.05, 0.2))

@app.get("/health")
def health():
    return {"service": "recommend", "status": "warm"}

@app.get("/recommend/{user_id}")
def get_recommendations(user_id: str):
    simulate_latency()
    return {
        "user_id": user_id,
        "recommendations": [
            {"item_id": f"item_{random.randint(100, 999)}", "score": round(random.uniform(0.6, 1.0), 3)}
            for _ in range(5)
        ],
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
