"""Pin parser_v2 → stock_parser alias. Once B2 lands and parser_v2 has its
own implementation, this test fails — that's the signal to flip the harness's
exemption clause."""

from app.parser import stock_parser
from app.parser_v2 import parse as parser_v2_parse


def test_parser_v2_is_alias_of_stock_parser_parse() -> None:
    """Identity check: parser_v2.parse must be the EXACT SAME function object
    as stock_parser.parse during B1.  Use `is` not `==`. The harness's
    exemption clause depends on this identity."""
    assert parser_v2_parse is stock_parser.parse
