#!/usr/bin/env python3
"""longport_push_recorder.py — 独立脚本，录制 LongPort 订单推送原始数据。

用途
----
1. 监听 LongPort 实盘/模拟盘的 ``PushOrderChanged`` 推送
2. 每条推送：
   - stdout 打印一行简表（status / order_id / exec_qty / submitted_price）
   - 追加一条 JSON 到 ``--output`` 文件（默认 data/pushes.jsonl）
3. JSONL 字段保留**完整类型信息**（Decimal / SDK 枚举变体名 / datetime ISO），
   后续 ``longport_push_simulator.py``（待写）可以读这个文件，构造 mock 对象
   喂给 ``PushListener._handle_raw_push`` 做离线回放。

读取凭证
--------
优先读 ``data/longport_settings.json``（前端 Settings 弹窗写入的运行期凭证），
不存在则回退到 ``LONGPORT_*`` 环境变量。``--mode`` 可强制覆盖 paper/real。

用法
----
    python scripts/longport_push_recorder.py
    python scripts/longport_push_recorder.py --output data/pushes_demo.jsonl
    python scripts/longport_push_recorder.py --mode real
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = ROOT / "data" / "longport_settings.json"

# Lazy import — keep import errors human-readable if SDK isn't installed.
try:
    from longport.openapi import Config as LPConfig
    from longport.openapi import TopicType, TradeContext
except ImportError as exc:  # noqa: BLE001
    sys.exit(
        f"longport SDK not installed ({exc}).\n"
        "Run from the backend venv:\n"
        "    source backend/.venv/bin/activate && python scripts/longport_push_recorder.py"
    )


def _load_creds(mode_override: str | None) -> tuple[str, str, str, str]:
    """Return ``(app_key, app_secret, access_token, mode)``.

    Settings JSON wins; env vars are the fallback so the script still works
    on a fresh checkout where the user hasn't opened the Settings dialog.
    """
    if SETTINGS_PATH.exists():
        s = json.loads(SETTINGS_PATH.read_text())
        mode = (mode_override or s.get("mode") or "paper").lower()
        creds = s.get(mode) or {}
        if creds.get("app_key") and creds.get("app_secret") and creds.get("access_token"):
            return creds["app_key"], creds["app_secret"], creds["access_token"], mode

    mode = (mode_override or os.environ.get("LONGPORT_MODE") or "paper").lower()
    prefix = "LONGPORT_PAPER" if mode == "paper" else "LONGPORT_REAL"
    app_key = os.environ.get(f"{prefix}_APP_KEY", "")
    app_secret = os.environ.get(f"{prefix}_APP_SECRET", "")
    access_token = os.environ.get(f"{prefix}_ACCESS_TOKEN", "")
    if not (app_key and app_secret and access_token):
        sys.exit(
            f"No usable credentials for mode={mode}. Either:\n"
            f"  1. Configure them via the UI Settings dialog (writes {SETTINGS_PATH})\n"
            f"  2. Or export {prefix}_APP_KEY / _APP_SECRET / _ACCESS_TOKEN in env"
        )
    return app_key, app_secret, access_token, mode


def _serialise(v: Any) -> Any:
    """JSON-safe value with Decimal / SDK enum-like fidelity preserved.

    Mirrors ``app.broker.push_listener._serialise_value`` post-fix:
    Decimals stringify faithfully, SDK enum-likes (``OrderStatus.New``) reduce
    to their variant name, datetimes go to ISO. Anything else falls back to
    ``str(v)``.
    """
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, datetime):
        return v.isoformat()
    raw = repr(v)
    # SDK enum-like has the shape ``ClassName.VariantName`` (no quotes/parens).
    if "." in raw and not any(c in raw for c in "'(\" "):
        return raw.split(".")[-1]
    return str(v)


def _attrs_of(obj: Any) -> dict[str, Any]:
    """Enumerate every public, non-callable attribute of an SDK push object.

    The SDK delivers ``PushOrderChanged`` as a Rust-backed C extension whose
    ``vars(obj)`` returns a non-dict (a builtin method); ``dir()`` is the
    only reliable enumeration path.
    """
    out: dict[str, Any] = {}
    for name in dir(obj):
        if name.startswith("_"):
            continue
        try:
            val = getattr(obj, name)
        except Exception:  # noqa: BLE001
            continue
        if callable(val):
            continue
        out[name] = val
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--output", "-o",
        default=str(ROOT / "data" / "pushes.jsonl"),
        type=Path,
        help="Output JSONL path (default: data/pushes.jsonl, append mode).",
    )
    parser.add_argument(
        "--mode", choices=("paper", "real"),
        help="Force mode (otherwise reads from settings JSON / env).",
    )
    parser.add_argument(
        "--label", "-l",
        help="Tag every record with a label (use to mark scenarios — e.g. "
             "'manual_modify_price', 'normal_fill', 'rejected').",
    )
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)

    app_key, app_secret, access_token, mode = _load_creds(args.mode)
    print(f"[recorder] mode={mode}  output={args.output}", file=sys.stderr)
    if args.label:
        print(f"[recorder] label={args.label!r}", file=sys.stderr)
    print("[recorder] connecting to LongPort TradeContext…", file=sys.stderr)

    ctx = TradeContext(LPConfig(
        app_key=app_key,
        app_secret=app_secret,
        access_token=access_token,
    ))

    counter = {"n": 0}
    fp = args.output.open("a", buffering=1)  # line-buffered → safe to tail -f

    def on_push(evt: Any) -> None:
        counter["n"] += 1
        seq = counter["n"]
        recv_iso = datetime.now(UTC).isoformat()
        attrs = _attrs_of(evt)

        record: dict[str, Any] = {
            "_seq": seq,
            "_recv_at": recv_iso,
            "_class": type(evt).__name__,
            "_repr": repr(evt),
            # type names per attribute let the simulator reconstruct Decimal /
            # enum-like values that JSON would otherwise flatten to strings.
            "_types": {k: type(v).__name__ for k, v in attrs.items()},
            "fields": {k: _serialise(v) for k, v in attrs.items()},
        }
        if args.label:
            record["_label"] = args.label

        fp.write(json.dumps(record, ensure_ascii=False) + "\n")

        f = record["fields"]
        print(
            f"[#{seq:>3}] {recv_iso}  "
            f"status={f.get('status')!r:<22}  "
            f"order_id={f.get('order_id')!r:<22}  "
            f"exec_qty={f.get('executed_quantity')!r:<6}  "
            f"submitted_price={f.get('submitted_price')!r}",
            flush=True,
        )

    ctx.set_on_order_changed(on_push)
    ctx.subscribe([TopicType.Private])

    print(
        f"[recorder] subscribed to TopicType.Private; Ctrl+C to stop\n"
        f"[recorder] tip: tail -f {args.output}",
        file=sys.stderr,
    )

    # SDK runs callbacks on its own thread — our main thread just sleeps until
    # interrupted. signal.pause() is more responsive than time.sleep(very_long)
    # but isn't available on Windows; sleep loop is fine cross-platform.
    stop = False

    def _handle_sigterm(_signum: int, _frame: Any) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _handle_sigterm)
    signal.signal(signal.SIGTERM, _handle_sigterm)

    try:
        while not stop:
            time.sleep(1)
    finally:
        fp.close()
        print(
            f"\n[recorder] stopped — captured {counter['n']} push(es) → {args.output}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
