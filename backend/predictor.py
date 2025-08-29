# predictor.py
import os, json, time
from typing import Dict, List, Optional
import pandas as pd
import numpy as np
import yfinance as yf

# sklearn 있으면 사용, 없으면 폴백
try:
    from sklearn.linear_model import Ridge
    _HAVE_SK = True
except Exception:
    _HAVE_SK = False

CACHE_FILE = os.getenv("PRED_CACHE_FILE", "predictions.json")
_CACHE: Dict[str, dict] = {}
_TTL = int(os.getenv("PRED_TTL_SEC", "900"))  # 15분 캐시

def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    rs = up / (down.replace(0, np.nan))
    return 100 - (100 / (1 + rs))

def _macd(series: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    sig = macd.ewm(span=signal, adjust=False).mean()
    hist = macd - sig
    return macd, sig, hist

def _features(df: pd.DataFrame) -> pd.DataFrame:
    px = df["Close"]
    feat = pd.DataFrame(index=df.index)
    feat["ret1"] = px.pct_change()
    feat["sma5"] = px.rolling(5).mean() / px - 1
    feat["sma20"] = px.rolling(20).mean() / px - 1
    feat["rsi14"] = _rsi(px, 14) / 100.0
    macd, sig, hist = _macd(px)
    feat["macd"] = macd
    feat["macd_sig"] = sig
    feat["macd_hist"] = hist
    feat = feat.replace([np.inf, -np.inf], np.nan).dropna()
    return feat

def _download(symbol: str, period="2y", interval="1d") -> pd.DataFrame:
    df = yf.download(symbol, period=period, interval=interval, auto_adjust=True, progress=False)
    if not isinstance(df, pd.DataFrame) or df.empty:
        raise RuntimeError(f"no price for {symbol}")
    return df

def _predict_core(symbol: str) -> dict:
    df = _download(symbol)
    X = _features(df)
    # 타깃: 다음 날 종가(비율) -> next_close / close - 1
    y = df["Close"].shift(-1).reindex(X.index) / df["Close"].reindex(X.index) - 1
    data = pd.concat([X, y.rename("y")], axis=1).dropna()
    if len(data) < 60:
        raise RuntimeError("not enough data")

    split = int(len(data) * 0.8)
    train, test = data.iloc[:split], data.iloc[split:]
    Xtr, ytr = train.drop(columns=["y"]), train["y"]
    Xte = test.drop(columns=["y"])

    if _HAVE_SK:
        model = Ridge(alpha=1.0)
        model.fit(Xtr.values, ytr.values)
        pred_ret = float(model.predict(Xte.values)[-1])  # 가장 최근 예측 수익률
    else:
        # 폴백: EWMA 수익률
        pred_ret = float(X["ret1"].ewm(span=10, adjust=False).mean().iloc[-1])

    last_close = float(df["Close"].iloc[-1])
    pred_close = last_close * (1.0 + pred_ret)
    signal = "BUY" if pred_ret > 0.01 else ("SELL" if pred_ret < -0.01 else "HOLD")

    return {
        "symbol": symbol,
        "last_close": round(last_close, 4),
        "pred_ret_1d": round(pred_ret, 6),
        "pred_close_1d": round(pred_close, 4),
        "signal": signal,
        "ts": int(time.time())
    }

def predict_one(symbol: str, force: bool = False) -> dict:
    now = time.time()
    if not force and symbol in _CACHE and (now - _CACHE[symbol]["ts"] < _TTL):
        return _CACHE[symbol]
    out = _predict_core(symbol)
    _CACHE[symbol] = out
    try:
        allc = {}
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r") as f:
                allc = json.load(f) or {}
        allc[symbol] = out
        with open(CACHE_FILE, "w") as f:
            json.dump(allc, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return out

def predict_batch(symbols: List[str], force: bool = False) -> Dict[str, dict]:
    return {s: predict_one(s, force=force) for s in symbols}

def read_cached() -> Dict[str, dict]:
    try:
        with open(CACHE_FILE, "r") as f:
            return json.load(f) or {}
    except Exception:
        return {}