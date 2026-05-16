import torch
import torch.nn as nn
import numpy as np
import sqlite3

SERVICES = [
    "auth",
    "user-profile", 
    "recommend",
    "order",
    "payment",
    "notification"
]

service_to_idx = {s: i for i, s in enumerate(SERVICES)}
idx_to_service = {i: s for i, s in enumerate(SERVICES)}

class LSTM_predictor(nn.Module):
    def __init__(self,input_size,hidden_size,output_size):
        super(LSTM_predictor,self).__init__()
        self.hidden_size=hidden_size
        self.lstm=nn.LSTM(input_size,hidden_size,batch_first=True)
        self.ffn=nn.Linear(hidden_size,output_size)
    
    def forward(self,x):
        output,_=self.lstm(x)
        output=self.ffn(output[ :,-1,:])
        return output

def sequence_():
        conn=sqlite3.connect("nexusguard.db")
        cursor=conn.cursor()
        cursor.execute("SELECT to_service FROM call_logs ORDER BY timestamp")
        rows=cursor.fetchall()
        conn.close()
        return [row[0] for row in rows]
    
def train():
        sequence=sequence_()
        if len(sequence)<4:
              return None
        x,y=[],[]

        for i in range(len(sequence)-3):
              window=sequence[i:i+3]
              target=sequence[i+3]

              x_encode=[service_to_idx.get(s,0) for s in window] ## since window has 3 items we need to map all 3 to their numbers
              y_encode= service_to_idx.get(target,0)
              x.append(x_encode)
              y.append(y_encode)

        x=torch.tensor(x,dtype=torch.float32).unsqueeze(-1)
        y=torch.tensor(y,dtype=torch.long)

        model=LSTM_predictor(1,32,len(SERVICES))
        optimizer=torch.optim.Adam(model.parameters(), lr=0.01)
        criterion = nn.CrossEntropyLoss()

        for e in range(100):
              optimizer.zero_grad()
              output=model(x)
              loss=criterion(output,y)
              loss.backward()
              optimizer.step()
        return model
def predict(model,bottom_three):
      if model is None:
            return None,0.0
      
      encode=[service_to_idx.get(s,0) for s in bottom_three]
      x=torch.tensor(encode,dtype=torch.float32).unsqueeze(0).unsqueeze(-1)

      with torch.no_grad():
            output=model(x)
            prob=torch.softmax(output,dim=1)
            pred_idx=torch.argmax(prob).item()
            confidence=prob[0][pred_idx].item()
      return idx_to_service[pred_idx], round(confidence, 2)
                 



