"""
长桥证券交易模块
支持模拟账户和真实账户，可通过环境变量切换
"""

from .config_loader import LongPortConfigLoader, load_longport_config
from .longport_broker import (
    LongPortBroker,
    convert_to_longport_symbol,
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
    'calculate_quantity',
    'PositionManager',
    'Position',
    'create_position_from_order',
    'AutoTrader'
]
