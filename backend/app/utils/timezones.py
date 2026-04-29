"""Project-wide timezone constants.

The system runs in a single business timezone (Beijing). Storage is
real UTC; presentation and calendar arithmetic that mirrors what a
Beijing-based user sees on Whop happens in ``BEIJING``.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

BEIJING: ZoneInfo = ZoneInfo("Asia/Shanghai")
"""Asia/Shanghai (UTC+8, no DST). Use for any 'what the trader's wall clock says' computation."""
