# batch_job.py (선택)
import os
from predictor import predict_batch
WATCHLIST = os.getenv("WATCHLIST", "AAPL,MSFT,GOOGL,005930.KS").split(",")

if __name__ == "__main__":
    out = predict_batch([s.strip() for s in WATCHLIST if s.strip()], force=True)
    print("batch done:", list(out.keys()))