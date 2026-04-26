"""parser_v2 — placeholder during B1.

Re-exports stock_parser.parse so harness code can import from a stable name.
B2 will replace this module's content with a token-based slot-filling parser.
The validate_parser harness uses `parser_v2.parse is stock_parser.parse` as
an identity check to detect the placeholder state and skip the recovery_rate
constraint until a real v2 lands.
"""

from app.parser.stock_parser import parse  # noqa: F401  — re-export

__all__ = ["parse"]
