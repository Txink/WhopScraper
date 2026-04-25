"""Dump OpenAPI schema to a file by running FastAPI app under TestClient.

Usage (from project root):
  uv run --project backend python scripts/dump_openapi.py frontend/openapi.json
"""
import json
import sys
from pathlib import Path

# Ensure backend/ is importable
BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from tests.broker._fakes import FakeBrokerClient  # noqa: E402


def main() -> None:
    out_path = Path(sys.argv[1] if len(sys.argv) > 1 else "frontend/openapi.json")
    settings = Settings(app_token="stub-for-schema", database_url="sqlite+aiosqlite:///:memory:")
    app = create_app(settings=settings, broker_override=FakeBrokerClient())

    with TestClient(app) as client:
        # /openapi.json is the FastAPI default
        resp = client.get("/openapi.json")
        resp.raise_for_status()
        schema = resp.json()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote OpenAPI schema to {out_path}")


if __name__ == "__main__":
    main()
