# llm_agent.py
import json
from typing import Optional, List, Dict

from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_groq import ChatGroq
from langchain.tools import tool

from finance_agent import run_query as fa_run_query, pick_valid_ticker
from predictor import predict_one
from brokers import price_now
import yfinance as yf

# ============ 모델 빌더 ============
def build_model():
    import os
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    model = os.getenv("GROQ_MODEL", "llama3-8b-8192")
    if not key:
        # 키가 없어도 동작은 하되, LLM 요약 없이 툴 결괏값만 합쳐서 반환
        return None
    return ChatGroq(model=model, temperature=0.2, api_key=key)

model = build_model()

# ============ (선택) 뉴스 툴 ============
def _news_top(symbol: str, k: int = 3) -> List[Dict]:
    try:
        t = yf.Ticker(symbol)
        news = t.news or []
        out = []
        for item in news[:k]:
            out.append({
                "title": item.get("title"),
                "link": item.get("link"),
                "pubTime": item.get("providerPublishTime")
            })
        return out
    except Exception:
        return []

# ============ LangChain Tools ============
class PredictArgs(BaseModel):
    symbol: str = Field(..., description="Ticker symbol like AAPL or 005930.KS")
    force: bool = Field(False, description="If true, bypass cache")

@tool("predict_one_day", args_schema=PredictArgs)
def predict_one_day_tool(symbol: str, force: bool = False) -> str:
    """Return 1-day ahead prediction (return, target close, signal) and last close; may include live_price."""
    out = predict_one(symbol, force=force)
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
    return json.dumps({"symbol": symbol, "news": _news_top(symbol, k)}, ensure_ascii=False)

TOOLS = [predict_one_day_tool, compute_financials_tool, get_live_price_tool, get_news_tool]

# ============ 출력 스키마 (최종 JSON) ============
class AgentOutput(BaseModel):
    ticker: str
    company: Optional[str] = None
    price: Optional[float] = None
    analysis: Optional[dict] = None      # finance_agent.run_query() 전체
    prediction: Optional[dict] = None    # predictor.predict_one() 결과(+ live_price)
    news: Optional[List[dict]] = None
    summary: Optional[str] = None        # LLM 한줄 요약(키 없으면 None)

# ============ 에이전트 실행기 ============
def _deterministic_aggregate(query: str, language: str = "ko") -> AgentOutput:
    """LLM이 없어도 안전하게 동작하는 폴백: 비율 분석 + 예측 + 실시간가 + 뉴스(최대 3)."""
    # 라우팅용 티커 감지
    sym = pick_valid_ticker(query)
    ana = fa_run_query(query, language=language)
    pred = predict_one(sym, force=False)
    live = price_now(sym)
    if live is not None:
        pred["live_price"] = round(float(live), 4)
    news = _news_top(sym, 3)

    return AgentOutput(
        ticker=ana["core"]["ticker"],
        company=ana["core"]["company"],
        price=ana["core"]["price"],
        analysis=ana,
        prediction=pred,
        news=news,
        summary=None,   # 아래에서 LLM이 있으면 요약 추가
    )

def run_manager(query: str, language: str = "ko", include_news: bool = True) -> dict:
    """
    자연어 질의 하나로 분석/예측/실시간가/뉴스를 묶어 반환.
    - LLM이 가능하면 툴을 선택/호출해 최종 JSON을 만들고,
    - 불가능하면 결정론적 집계로 폴백.
    """
    base = _deterministic_aggregate(query, language=language)

    if model is None:
        return json.loads(base.model_dump_json())

    # LLM 요약만 붙이는 간단 전략 (툴콜은 이미 폴백에서 수행됨)
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
    except Exception:
        text = None

    base.summary = text
    return json.loads(base.model_dump_json())

# (선택) “진짜” 툴콜 에이전트로 실행하고 싶다면:
def run_manager_with_tools(query: str, language: str = "ko", want_news: bool = True) -> dict:
    """LLM이 각 툴을 직접 호출(create_tool_calling_agent 방식). 사용 환경에 따라 주석 해제."""
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
        # 모델이 JSON 텍스트를 반환한다고 가정
        txt = resp["output"]
        return json.loads(txt)
    except Exception:
        # 실패 시 폴백
        return run_manager(query, language=language, include_news=want_news)