"""Signal Station FastAPI 入口 —— Phase 0 占位版本。"""
from fastapi import FastAPI

app = FastAPI(title="Signal Station", version="0.1.0")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "phase": "0"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
