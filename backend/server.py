# server.py
import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# 기존 파일을 같은 폴더에 둔다고 가정
import finance_agent as fa

app = FastAPI(title="LSA Tool API", version="0.1.0")

# --- CORS (프론트 도메인 허용: github.io) ---
FRONT_ORIGINS = os.getenv("FRONT_ORIGINS", "*").split(",")  # ex) "https://username.github.io"
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONT_ORIGINS if FRONT_ORIGINS != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AnalyseReq(BaseModel):
    query: str
    language: str = "ko"  # "ko" or "en"

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/analyse")
def analyse(req: AnalyseReq):
    try:
        out = fa.run_query(req.query, language=req.language)
        return out
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)
