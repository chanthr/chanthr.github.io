# predict_agent.py
import time
from typing import Optional, Dict
import numpy as np
import pandas as pd
import yfinance as yf

# price_now (옵션)
try:
    from brokers import price_now  # 프로젝트에 있으면 사용
except Exception:
    def price_now(symbol: str) -> Optional[float]:
        try:
            fi = (yf.Ticker(symbol).fast_info or {})
            lp = fi.get("last_price")
            return float(lp) if lp is not None else None
        except Exception:
            return None

def _predict_fallback(symbol: str) -> Dict:
    df = yf.download(symbol, period="1y", interval="1d", auto_adjust=True, progress=False)
    if not isinstance(df, pd.DataFrame) or df.empty or "Close" not in df:
        raise RuntimeError("fallback: no price data")
    close = pd.to_numeric(df["Close"], errors="coerce").astype(float).dropna().values
    if close.size < 20:
        raise RuntimeError("fallback: not enough data")
    rets = np.diff(close) / close[:-1]
    tail = rets[-10:] if rets.size >= 10 else rets
    pred_ret = float(np.nanmean(tail))
    last = float(close[-1])
    pred_close = last * (1.0 + pred_ret)
    signal = "BUY" if pred_ret > 0.01 else ("SELL" if pred_ret < -0.01 else "HOLD")
    return {
        "symbol": symbol,
        "last_close": round(last, 4),
        "pred_ret_1d": round(pred_ret, 6),
        "pred_close_1d": round(pred_close, 4),
        "signal": signal,
        "ts": int(time.time()),
    }

def predict(symbol: str) -> Dict:
    """우선 외부 predictor.predict_one 사용, 실패 시 폴백."""
    try:
        from predictor import predict_one
        try:
            p = predict_one(symbol, force=False)
        except Exception:
            p = _predict_fallback(symbol)
    except Exception:
        p = _predict_fallback(symbol)

    # 라이브 가격(있으면)
    try:
        live = price_now(symbol)
        if live is not None:
            p["live_price"] = round(float(live), 4)
    except Exception:
        pass
    return p

__all__ = ["predict", "price_now"]
