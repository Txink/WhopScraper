"""CI gate for parser quality.

Calls the validate_parser harness against the production
data/parser_golden.json and asserts result.summary.passed. While
parser_v2 is still aliased to stock_parser the recovery_rate constraint
is exempt; once B2 lands the constraint becomes load-bearing.

Skips with a clear marker when golden hasn't been built yet (pre-B1
generation pass).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.validate_parser import (
    GOLDEN_PATH_DEFAULT,
    format_console_summary,
    run_validation,
)


def test_v2_meets_quality_bar() -> None:
    if not Path(GOLDEN_PATH_DEFAULT).exists():
        pytest.skip(
            f"golden missing at {GOLDEN_PATH_DEFAULT} — run "
            "`scripts/build_golden.py` to generate before enabling this test"
        )

    result = run_validation()
    assert result.summary.passed, (
        "parser_v2 quality bar failed:\n"
        + format_console_summary(result)
    )
