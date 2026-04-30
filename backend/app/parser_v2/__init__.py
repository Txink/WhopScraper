"""parser_v2 — independent token-based stock parser.

See docs/superpowers/specs/2026-04-27-parser-v2-token-based-design.md.
Entry point: parse(content, *, message_id) -> StockInstruction | None.
"""

from app.parser_v2.parse import parse  # noqa: F401

__all__ = ["parse"]
