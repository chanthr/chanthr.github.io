# news_agent.py
import os, re, time, json, sqlite3, urllib.parse
from typing import Optional, List, Dict
import yfinance as yf
from llm_core import summarize_media

# ---------- Google News RSS ----------
def _unwrap_gnews_link(link: Optional[str]) -> Optional[str]:
    if not link:
        return link
    try:
        if "news.google.com" not in link:
            return link
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(link)
        qs = parse_qs(parsed.query)
        u = (qs.get("url") or qs.get("u") or [None])[0]
        return u or link
    except Exception:
        return link

def _fetch_google_news_rss(query: str, language: str, k: int = 12) -> List[Dict]:
    is_ko = str(language).lower().startswith("ko")
    hl = "ko" if is_ko else "en-US"
    gl = "KR" if is_ko else "US"
    url = "https://news.google.com/rss/search?q=" + urllib.parse.quote_plus(query) + f"&hl={hl}&gl={gl}&ceid={gl}:{hl}"
    try:
        import feedparser as _fp
    except Exception:
        return []
    feed = _fp.parse(url)
    out: List[Dict] = []
    for e in getattr(feed, "entries", [])[:k]:
        title = e.get("title")
        link = e.get("link") or (e.get("links", [{}])[0].get("href"))
        link = _unwrap_gnews_link(link)
        ts = None
        try:
            pp = getattr(e, "published_parsed", None)
            up = getattr(e, "updated_parsed", None)
            if pp: ts = int(time.mktime(pp))
            elif up: ts = int(time.mktime(up))
        except Exception:
            ts = None
        if title and link:
            out.append({"title": title, "link": link, "providerPublishTime": ts})
    return out

# ---------- Query helpers ----------
_CORP_SUFFIX_RE = re.compile(
    r"\b(Inc\.?|Incorporated|Corp\.?|Corporation|Co\.?|Ltd\.?|Limited|PLC|S\.?A\.?|N\.?V\.?|SE|AG|KK|GmbH|LLC|LP|Holdings?|Group|Company)\b\.?",
    flags=re.I,
)
def _clean_company_name(name: str) -> str:
    s = re.sub(r"[\(\)（）]", " ", name or "")
    s = _CORP_SUFFIX_RE.sub(" ", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s or name

def _make_company_queries(company_name: str, symbol: str, language: str) -> List[str]:
    q: List[str] = []
    base = (company_name or "").strip()
    clean = _clean_company_name(base)
    if base: q.append(f"\"{base}\"")
    if clean and clean.lower() != base.lower(): q.append(f"\"{clean}\"")
    if language.lower().startswith("ko"):
        topics = "발표 OR 출시 OR 인수 OR 합병 OR 제휴 OR 투자 OR 규제 OR 소송 OR 공급망 OR 실적발표"
    else:
        topics = "announcement OR launch OR acquisition OR merger OR partnership OR investment OR regulatory OR lawsuit OR supply chain OR earnings call"
    if base:  q.append(f"\"{base}\" ({topics})")
    if clean and clean.lower() != base.lower(): q.append(f"\"{clean}\" ({topics})")
    if symbol: q.append(symbol)
    seen, uniq = set(), []
    for s in q:
        key = s.lower()
        if key not in seen:
            seen.add(key); uniq.append(s)
    return uniq

def _news_enriched(symbol: str, language: str, company_name: Optional[str] = None, k: int = 40) -> List[Dict]:
    items: List[Dict] = []
    if company_name:
        for q in _make_company_queries(company_name, symbol, language):
            try:
                items.extend(_fetch_google_news_rss(q, language, k=max(20, k * 2)))
            except Exception:
                continue
            if len(items) >= k: break
    else:
        try:
            items.extend(_fetch_google_news_rss(symbol, language, k=max(20, k * 2)))
        except Exception:
            pass
    # yfinance 보강
    try:
        arr = getattr(yf.Ticker(symbol), "news", []) or []
        for n in arr[: max(10, k)]:
            title = n.get("title")
            link = _unwrap_gnews_link(n.get("link"))
            ts = n.get("providerPublishTime") or n.get("pubTime")
            try: ts = int(ts) if ts is not None else None
            except Exception: ts = None
            if title and link:
                items.append({"title": title, "link": link, "providerPublishTime": ts})
    except Exception:
        pass
    # 정리
    clean, seen = [], set()
    for it in items:
        title = (it.get("title") or "").strip()
        link  = _unwrap_gnews_link(it.get("link"))
        ts    = it.get("providerPublishTime")
        if not title or not link: continue
        key = (title.lower(), link)
        if key in seen: continue
        seen.add(key)
        if ts is not None and not isinstance(ts, (int, float)):
            try: ts = int(ts)
            except Exception: ts = None
        clean.append({"title": title, "link": link, "providerPublishTime": ts})
    clean.sort(key=lambda x: x.get("providerPublishTime") or 0, reverse=True)
    return clean[:k]

# ---------- keyword/sentiment ----------
_STOP_EN = {"the","a","an","and","or","for","of","to","in","on","with","at","by","from","company","inc","corp","co","ltd","plc","group","shares","stock","reports","earnings","news","today","update"}
_STOP_KO = {"및","그리고","또","더","관련","회사","기업","주가","증권","속보","뉴스","발표","오늘","보고"}

_POS_TERMS_EN = {"beat":1.0,"beats":1.0,"surge":1.0,"surges":1.0,"jump":0.9,"jumps":0.9,"record":0.8,"upgrade":0.8,"r_
