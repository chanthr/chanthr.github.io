# api.py
import os
from typing import List
from fastapi import FastAPI
from pydantic import BaseModel
from finance_agent import run_query
from predictor import predict_one, predict_batch, read_cached
from brokers import price_now

app = FastAPI(title="FIN Agent + Predictions", version="1.0")

class AnalyseIn(BaseModel):
    query: str
    language: str = "ko"

class PredictIn(BaseModel):
    symbol: str
    force: bool = False

class PredictBatchIn(BaseModel):
    symbols: List[str]
    force: bool = False

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/analyse")
def analyse(body: AnalyseIn):
    return run_query(body.query, language=body.language)

@app.post("/predict")
def predict(body: PredictIn):
    out = predict_one(body.symbol, force=body.force)
    # 증권사/폴백 현재가 같이 반환
    live = price_now(body.symbol)
    if live is not None:
        out["live_price"] = round(live, 4)
    return out

@app.post("/predict/batch")
def predict_batch_ep(body: PredictBatchIn):
    out = predict_batch(body.symbols, force=body.force)
    # 옵션: 실시간가 병합
    for s in body.symbols:
        live = price_now(s)
        if live is not None:
            out[s]["live_price"] = round(live, 4)
    return out

@app.get("/predict/cached")
def cached():
    return read_cached()
