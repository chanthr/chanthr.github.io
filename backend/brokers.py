# brokers.py
import os, time
from typing import Optional
import yfinance as yf

# ===== 기본 폴백: yfinance =====
def price_yf(symbol: str) -> Optional[float]:
    try:
        t = yf.Ticker(symbol)
        fast = getattr(t, "fast_info", {}) or {}
        p = fast.get("last_price")
        return float(p) if p is not None else None
    except Exception:
        return None

# ===== 예시: KIS 어댑터 (채워 넣어 사용) =====
# 필요 ENV:
#   KIS_APP_KEY, KIS_APP_SECRET, KIS_ACCOUNT, KIS_IS_PAPER=1/0
# 토큰 발급 후 /quotations API 호출
import requests

_KIS_TOKEN = None
_KIS_EXP = 0

def _kis_base() -> str:
    is_paper = os.getenv("KIS_IS_PAPER", "1") == "1"
    return "https://openapivts.koreainvestment.com:29443" if is_paper else "https://openapi.koreainvestment.com:9443"

def _kis_token() -> Optional[str]:
    global _KIS_TOKEN, _KIS_EXP
    if _KIS_TOKEN and time.time() < _KIS_EXP - 60:
        return _KIS_TOKEN
    app = os.getenv("KIS_APP_KEY", "")
    sec = os.getenv("KIS_APP_SECRET", "")
    if not app or not sec:
        return None
    try:
        url = _kis_base() + "/oauth2/tokenP"
        r = requests.post(url, json={
            "grant_type": "client_credentials",
            "appkey": app,
            "appsecret": sec
        }, timeout=10)
        r.raise_for_status()
        data = r.json()
        _KIS_TOKEN = data.get("access_token")
        _KIS_EXP = time.time() + int(data.get("expires_in", 0))
        return _KIS_TOKEN
    except Exception:
        return None

def price_kis(symbol: str) -> Optional[float]:
    tok = _kis_token()
    app = os.getenv("KIS_APP_KEY", "")
    sec = os.getenv("KIS_APP_SECRET", "")
    if not tok or not app or not sec:
        return None
    try:
        # ※ 주의: 아래 엔드포인트/헤더의 TR_ID는 계좌/시장에 따라 다를 수 있음. KIS 문서를 참고해 조정하세요.
        url = _kis_base() + "/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = {
            "authorization": f"Bearer {tok}",
            "appkey": app,
            "appsecret": sec,
            "tr_id": "FHKST01010100",  # 예시: 주식 현재가 조회
        }
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol}
        r = requests.get(url, headers=headers, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        # 예시 응답에서 현재가 필드명은 계정/TR에 따라 다름. 아래는 관례적 키들:
        for k in ("stck_prpr", "output", "output1", "close"):
            v = data.get(k)
            if isinstance(v, dict):
                v = v.get("stck_prpr") or v.get("close")
            try:
                return float(v)
            except Exception:
                continue
        return None
    except Exception:
        return None

def price_now(symbol: str) -> Optional[float]:
    # KIS가 설정돼 있으면 우선 사용, 아니면 yfinance
    p = price_kis(symbol)
    return p if p is not None else price_yf(symbol)