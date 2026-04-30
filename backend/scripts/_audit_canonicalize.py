"""One-off: rewrite sell_quantity / position_size in golden to content
original form when content contains a verbatim QUANTIFIER / POSITION_SIZE
phrase that v2 would output.

Heuristic: for each trade_signal entry, run parser_v2.parse; if v2's
sell_quantity / position_size string differs from golden but is a literal
substring of content, replace golden's value with v2's.

Per spec § 13 / Q6=A: golden should match content original form, not the
curator's canonical fraction.
"""

import json
from pathlib import Path

from app.parser_v2.parse import parse

PATH = Path(__file__).parent.parent.parent / "data" / "parser_golden.json"


def main() -> None:
    data = json.loads(PATH.read_text())
    patched = 0
    for entry in data:
        if entry.get("classification") != "trade_signal":
            continue
        exp = entry.get("expected")
        if exp is None:
            continue
        inst = parse(entry["content"], message_id=entry["domID"])
        if inst is None:
            continue
        for field in ("sell_quantity", "position_size"):
            v2_val = getattr(inst, field, None)
            gold_val = exp.get(field)
            if v2_val is None or gold_val == v2_val:
                continue
            if v2_val and v2_val in entry["content"]:
                exp[field] = v2_val
                patched += 1
    PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"patched {patched} entries")


if __name__ == "__main__":
    main()
