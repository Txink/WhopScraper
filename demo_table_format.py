"""
演示新的表格格式化输出
展示账户信息、持仓信息、当日订单的表格格式
"""
from broker.order_formatter import (
    print_order_table,
    print_orders_summary_table,
    print_account_info_table,
    print_positions_table,
    parse_option_symbol
)

# 演示期权名称解析
print("\n=== 期权名称解析演示 ===")
test_symbols = [
    "AAPL250202C00252500.US",
    "TSLA260131P00300000.US",
    "GOOGL250214C01500000.US",
    "MSFT260228C00420500.US"
]

for symbol in test_symbols:
    parsed = parse_option_symbol(symbol)
    print(f"{symbol} -> {parsed}")

# 演示订单表格（横向一行）
print("\n=== 单个订单表格演示 ===")
order = {
    "order_id": "12345678-1234-1234-1234-123456789012",
    "symbol": "AAPL250202C00252500.US",
    "side": "BUY",
    "quantity": 10,
    "price": 5.50,
    "trigger_price": None,
    "trailing_percent": None,
    "trailing_amount": None,
    "status": "待成交",
    "mode": "paper",
    "remark": "测试订单"
}
print_order_table(order)

# 演示订单列表表格
print("\n=== 订单列表表格演示 ===")
orders = [
    {
        "symbol": "AAPL250202C00252500.US",
        "side": "BUY",
        "quantity": 10,
        "executed_quantity": 5,
        "price": 5.50,
        "status": "部分成交",
        "trigger_price": None,
        "trailing_percent": None,
        "trailing_amount": None
    },
    {
        "symbol": "TSLA260131P00300000.US",
        "side": "SELL",
        "quantity": 5,
        "executed_quantity": 0,
        "price": None,  # 市价单
        "status": "待成交",
        "trigger_price": None,
        "trailing_percent": None,
        "trailing_amount": None
    },
    {
        "symbol": "GOOGL250214C01500000.US",
        "side": "BUY",
        "quantity": 20,
        "executed_quantity": 20,
        "price": 12.75,
        "status": "已成交",
        "trigger_price": 1450.00,
        "trailing_percent": None,
        "trailing_amount": None
    }
]
print_orders_summary_table(orders, title="当日订单")

# 演示账户信息表格
print("\n=== 账户信息表格演示 ===")
account_info = {
    "total_cash": 100000.50,
    "available_cash": 75000.25,
    "position_value": 30000.00,
    "currency": "USD"
}
print_account_info_table(account_info)

# 演示持仓信息表格
print("\n=== 持仓信息表格演示 ===")
positions = [
    {
        "symbol": "AAPL250202C00252500.US",
        "quantity": 10,
        "available_quantity": 10,
        "cost_price": 5.50,
        "current_price": 6.20,
        "currency": "USD"
    },
    {
        "symbol": "TSLA260131P00300000.US",
        "quantity": 5,
        "available_quantity": 5,
        "cost_price": 8.00,
        "current_price": 7.20,
        "currency": "USD"
    },
    {
        "symbol": "GOOGL250214C01500000.US",
        "quantity": 20,
        "available_quantity": 15,
        "cost_price": 12.75,
        "current_price": 14.50,
        "currency": "USD"
    }
]
print_positions_table(positions)

print("\n=== 演示完成 ===")
