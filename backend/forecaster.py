import os
import random

import torch
import torch.nn as nn

from backend.database import get_last_windows

SERVICES = ["user-profile", "recommend", "order", "payment", "notification"]
N = len(SERVICES)
SEQ_LEN = 12
THRESHOLD = int(os.environ.get("FORECAST_THRESHOLD", "9"))


class VolumeForecaster(nn.Module):
    def __init__(self):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=N,
            hidden_size=64,
            num_layers=2,
            batch_first=True
        )
        self.ffn = nn.Linear(64, N)

    def forward(self, x):
        out, _ = self.lstm(x)
        last = out[:, -1, :] if out.dim() == 3 else out[-1, :]
        return self.ffn(last)


def generate_synthetic_data(n_samples=500):
    X, Y = [], []
    for _ in range(n_samples):
        pattern = random.choice(["normal", "spike", "cooldown"])
        windows = []
        for i in range(SEQ_LEN + 1):
            if pattern == "normal":
                row = [random.randint(2, 12) for _ in range(N)]
            elif pattern == "spike":
                row = [random.randint(2, 12) for _ in range(N)]
                if i >= SEQ_LEN - 3:
                    spike_svc = random.randint(0, N - 1)
                    row[spike_svc] = random.randint(40, 90)
            elif pattern == "cooldown":
                row = [random.randint(2, 12) for _ in range(N)]
                if i < 4:
                    row = [random.randint(30, 70) for _ in range(N)]
            windows.append(row)
        X.append(windows[:SEQ_LEN])
        Y.append(windows[SEQ_LEN])
    X = torch.tensor(X, dtype=torch.float32)
    Y = torch.tensor(Y, dtype=torch.float32)
    return X, Y


def build_real_training_data(history_size=60):
    windows = get_last_windows(history_size)
    if len(windows) <= SEQ_LEN:
        return None, None

    X, Y = [], []
    for idx in range(len(windows) - SEQ_LEN):
        X.append(windows[idx:idx + SEQ_LEN])
        Y.append(windows[idx + SEQ_LEN])

    if not X:
        return None, None

    return (
        torch.tensor(X, dtype=torch.float32),
        torch.tensor(Y, dtype=torch.float32),
    )


def train():
    model = VolumeForecaster()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
    criterion = nn.MSELoss()
    X, Y = build_real_training_data()
    epochs = 120
    if X is None or Y is None:
        X, Y = generate_synthetic_data(500)
        epochs = 150

    for epoch in range(epochs):
        optimizer.zero_grad()
        output = model(X)
        loss = criterion(output, Y)
        loss.backward()
        optimizer.step()
    return model


def predict(model, windows):
    if model is None or len(windows) < SEQ_LEN:
        return None
    x = torch.tensor(windows, dtype=torch.float32).unsqueeze(0)
    with torch.no_grad():
        output = model(x)
        counts = output[0].tolist()
    return {
        SERVICES[i]: max(0, round(counts[i]))
        for i in range(N)
    }


def needs_scaling(predictions: dict):
    if predictions is None:
        return []
    return [svc for svc, count in predictions.items() if count > THRESHOLD]
