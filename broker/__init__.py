"""
长桥证券交易模块
支持模拟账户和真实账户，可通过环境变量切换
"""

# ⚠️ DEAD CODE — pre-refactor-v2 legacy.
# The active codebase is backend/app/. This module references utils.watched_stocks,
# which was removed in commit c9ad06b. These files are kept only for archive purposes.

from .config_loader import LongPortConfigLoader, load_longport_config
from .longport_broker import (
    LongPortBroker,
    convert_to_longport_symbol,
    validate_option_expiry,
    calculate_quantity
)
from .position_manager import (
    PositionManager,
    Position,
    create_position_from_order
)
from .auto_trader import AutoTrader

__all__ = [
    'LongPortConfigLoader',
    'load_longport_config',
    'LongPortBroker',
    'convert_to_longport_symbol',
    'validate_option_expiry',
    'calculate_quantity',
    'PositionManager',
    'Position',
    'create_position_from_order',
    'AutoTrader'
]
