# llm_agent.py
import json, time, re, urllib.parse
from typing import Optional, List, Dict

import pandas as pd
import numpy as np
import yfinance as yf
import feedparser

from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_groq import ChatGroq
from langchain.tools import tool

from finance_agent import run_query as fa_run_query, pick_valid_ticker
from predictor import predict_one
from brokers import price_now

# ============ 모델 빌더 ============
def build_model():
    import os
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    model = os.getenv("GROQ_MODEL", "llama3-8b-8192")
    if not key:
        return None
    return ChatGroq(model=model, temperature=0.2, api_key=key)

model = build_model()

# ============ 안전 폴백 예측 ============
def _predict_fallback(symbol: str) -> dict:
    df = yf.download(symbol, period="6mo", interval="1d", auto_adjust=True, progress=False)
    if not isinstance(df, pd.DataFrame) or df.empty or "Close" not in df:
        raise RuntimeError("fallback: no price data")
    close = pd.to_numeric(df["Close"], errors="coerce").dropna()
    if len(close) < 20:
        raise RuntimeError("fallback: not enough data")
    # 간단 EWMA 수익률 → 1일 예측
    ret = close.pct_change().ewm(span=10, adjust=False).mean().iloc[-1]
    last = float(close.iloc[-1])
    pred_close = last * (1.0 + float(ret))
    signal = "BUY" if ret > 0.01 else ("SELL" if ret < -0.01 else "HOLD")
    return {
        "symbol": symbol,
        "last_close": round(last, 4),
        "pred_ret_1d": round(float(ret), 6),
        "pred_close_1d": round(float(pred_close), 4),
        "signal": signal,
        "ts": int(time.time()),
    }

# ============ 뉴스: yfinance + Google News RSS, 클린업 ============
def _news_enriched(symbol: str, language: str, company_name: Optional[str] = None, k: int = 10) -> List[Dict]:
    items: List[Dict] = []
    # 1) yfinance
    try:
        arr = getattr(yf.Ticker(symbol), "news", []) or []
        for n in arr[:k]:
            items.append({
                "title": n.get("title"),
                "link": n.get("link"),
                "providerPublishTime": n.get("providerPublishTime") or n.get("pubTime"),
            })
    except Exception:
        pass

    def _google(q: str):
        is_ko = str(language).lower().startswith("ko")
        hl = "ko" if is_ko else "en-US"
        gl = "KR" if is_ko else "US"
        url = ("https://news.google.com/rss/search?q="
               + urllib.parse.quote_plus(q)
               + f"&hl={hl}&gl={gl}&ceid={gl}:{hl}")
        feed = feedparser.parse(url)
        out = []
        for e in feed.entries[:k]:
            link = e.get("link") or (e.get("links", [{}])[0].get("href"))
            ts = int(time.mktime(e.published_parsed)) if getattr(e, "published_parsed", None) else None
            out.append({"title": e.get("title"), "link": link, "providerPublishTime": ts})
        return out

    # 2) 부족하면 보강
    if len(items) < 3:
        q = f"{symbol} stock" if language[:2] != "ko" else f"{symbol} 주가 OR {symbol} 실적 OR {symbol} 주식"
        try: items.extend(_google(q))
        except Exception: pass

    if len(items) < 3 and company_name:
        q2 = f"{company_name} stock" if language[:2] != "ko" else f"{company_name} 주가 OR {company_name} 실적 OR {company_name} 주식"
        try: items.extend(_google(q2))
        except Exception: pass

    # 3) 제목 없는 항목 제거 & 링크 중복 제거
    clean, seen = [], set()
    for it in items:
        t = (it or {}).get("title") or ""
        lk = (it or {}).get("link")
        if not t.strip():
            continue
        if lk and lk in seen:
            continue
        if lk:
            seen.add(lk)
        clean.append(it)
    return clean[:k]

# ============ 헤더 제거 & 1~2문장 요약 ============
def _short_summary(text: str, language: str) -> str:
    if not text:
        return ""
    s = re.sub(r"```.*?```", " ", text, flags=re.S)
    s = re.sub(r"`[^`]*`", " ", s)
    s = re.sub(r"^#{1,6} .*$", " ", s, flags=re.M)  # 헤더 라인 제거
    s = re.sub(r"[*_\[\]()>-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return ""
    parts = (re.split(r"(?:다\.|요\.|\.|\?|!)\s", s, maxsplit=2)
             if language.lower().startswith("ko")
             else re.split(r"(?<=[\.\?!])\s", s, maxsplit=2))
    out = " ".join([p for p in parts[:2] if p]).strip()
    return out[:280]

# ============ LangChain Tools ============
class PredictArgs(BaseModel):
    symbol: str = Field(..., description="Ticker symbol like AAPL or 005930.KS")
    force: bool = Field(False, description="If true, bypass cache")

@tool("predict_one_day", args_schema=PredictArgs)
def predict_one_day_tool(symbol: str, force: bool = False) -> str:
    """Return 1-day ahead prediction (return, target close, signal) and last close; may include live_price."""
    try:
        out = predict_one(symbol, force=force)
    except Exception:
        out = _predict_fallback(symbol)
    live = price_now(symbol)
    if live is not None:
        out["live_price"] = round(float(live), 4)
    return json.dumps(out, ensure_ascii=False)

class AnalyseArgs(BaseModel):
    query: str = Field(..., description="User query that contains a ticker or company name")
    language: str = Field("ko", description="ko or en")

@tool("compute_financials", args_schema=AnalyseArgs)
def compute_financials_tool(query: str, language: str = "ko") -> str:
    """Return liquidity/solvency JSON (company, ticker, price, ratios, explanation)."""
    data = fa_run_query(query, language=language)
    return json.dumps(data, ensure_ascii=False)

class PriceArgs(BaseModel):
    symbol: str

@tool("get_live_price", args_schema=PriceArgs)
def get_live_price_tool(symbol: str) -> str:
    """Return best-effort live price via broker adapter with yfinance fallback."""
    p = price_now(symbol)
    return json.dumps({"symbol": symbol, "live_price": p}, ensure_ascii=False)

class NewsArgs(BaseModel):
    symbol: str
    k: int = 3

@tool("get_news", args_schema=NewsArgs)
def get_news_tool(symbol: str, k: int = 3) -> str:
    """Return up to k recent headlines for the symbol (best-effort)."""
    news = _news_enriched(symbol, language="en", company_name=None, k=k)
    return json.dumps({"symbol": symbol, "news": news}, ensure_ascii=False)

TOOLS = [predict_one_day_tool, compute_financials_tool, get_live_price_tool, get_news_tool]

# ============ 출력 스키마 (최종 JSON) ============
class AgentOutput(BaseModel):
    ticker: str
    company: Optional[str] = None
    price: Optional[float] = None
    analysis: Optional[dict] = None      # finance_agent.run_query() 전체
    prediction: Optional[dict] = None    # predictor.predict_one() 결과(+ live_price)
    news: Optional[List[dict]] = None
    summary: Optional[str] = None        # 요약(키 없으면 None)

# ============ 에이전트 실행기 ============
def _deterministic_aggregate(query: str, language: str = "ko") -> AgentOutput:
    sym = pick_valid_ticker(query)
    ana = fa_run_query(query, language=language)

    # 예측: 원 함수 실패 시 폴백
    try:
        pred = predict_one(sym, force=False)
    except Exception:
        pred = _predict_fallback(sym)

    live = price_now(sym)
    if live is not None:
        pred["live_price"] = round(float(live), 4)

    news = _news_enriched(sym, language, company_name=ana["core"].get("company"), k=10)
    summary = _short_summary(ana.get("explanation", ""), language)

    return AgentOutput(
        ticker=ana["core"]["ticker"],
        company=ana["core"]["company"],
        price=ana["core"]["price"],
        analysis=ana,
        prediction=pred,
        news=news,
        summary=summary,
    )

def run_manager(query: str, language: str = "ko", include_news: bool = True) -> dict:
    """
    하나의 질의로 분석/예측/실시간가/뉴스를 묶어 반환.
    LLM 키가 있으면 요약을 더 깔끔하게 다듬고, 없으면 폴백 요약 사용.
    """
    base = _deterministic_aggregate(query, language=language)
    if not include_news:
        base.news = []

    if model is None:
        return json.loads(base.model_dump_json())

    # (선택) LLM으로 한 줄 요약 다듬기
    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are a finance orchestrator. Write in {ask_lang}. "
         "Summarize liquidity/solvency and the 1-day prediction in 2–3 concise sentences. "
         "Do not reveal internal reasoning. Be concrete, mention key ratios if notable."),
        ("human", "DATA (JSON):\n{blob}\n\nReturn only the summary text.")
    ])
    chain = prompt | model | StrOutputParser()
    ask_lang = "Korean" if language.lower().startswith("ko") else "English"
    try:
        text = chain.invoke({"ask_lang": ask_lang, "blob": base.model_dump_json()})
        if text:
            base.summary = _short_summary(text, language)
    except Exception:
        pass

    return json.loads(base.model_dump_json())

# (선택) “진짜” 툴콜 에이전트:
def run_manager_with_tools(query: str, language: str = "ko", want_news: bool = True) -> dict:
    try:
        from langchain.agents import create_tool_calling_agent, AgentExecutor
        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are a finance orchestrator. When unsure, call both compute_financials and predict_one_day. "
             "Always determine the ticker with context. "
             "At the end, return a single JSON following this schema keys: "
             "ticker, company, price, analysis, prediction, news(optional), summary."),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder("agent_scratchpad"),
        ])
        agent = create_tool_calling_agent(model, TOOLS, prompt)
        executor = AgentExecutor(agent=agent, tools=TOOLS, verbose=False)
        resp = executor.invoke({"input": f"{query}\nLanguage:{language}\nInclude news: {want_news}"})
        txt = resp["output"]
        return json.loads(txt)
    except Exception:
        return run_manager(query, language=language, include_news=want_news)
