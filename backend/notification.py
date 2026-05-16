import time
import random
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class NotifyRequest(BaseModel):
    user_id: str
    message: str
    channel: str = "email"

def simulate_latency():
    time.sleep(random.uniform(0.05, 0.2))

@app.get("/health")
def health():
    return {"service": "notification", "status": "warm"}

@app.post("/notify")
def notify(request: NotifyRequest):
    simulate_latency()
    return {
        "user_id": request.user_id,
        "channel": request.channel,
        "status": "sent",
        "notification_id": f"notif_{random.randint(10000, 99999)}",
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8005)
