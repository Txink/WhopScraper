#!/usr/bin/env python3
"""
演示取消订单的浅灰色边框表格
运行此脚本查看取消订单的新样式
"""
from broker.order_formatter import print_order_cancel_table, print_info_message

print("\n" + "="*60)
print("取消订单表格样式演示（浅灰色边框）")
print("="*60 + "\n")

print_info_message("演示 1: 取消正股订单")

# 示例 1: 取消正股订单
cancel_order_1 = {
    'order_id': '1202611904946647040',
    'symbol': 'AAPL.US',
    'side': 'BUY',
    'quantity': 100,
    'price': 250.00,
    'cancelled_at': '2026-02-01 21:50:00',
    'mode': 'paper'
}
print_order_cancel_table(cancel_order_1, "订单撤销")

print("\n" + "-"*60 + "\n")
print_info_message("演示 2: 取消期权订单")

# 示例 2: 取消期权订单
cancel_order_2 = {
    'order_id': '1202611234567890123',
    'symbol': 'AAPL260207C00250000.US',
    'side': 'BUY',
    'quantity': 5,
    'price': 3.50,
    'cancelled_at': '2026-02-01 21:51:30',
    'mode': 'real'
}
print_order_cancel_table(cancel_order_2, "订单撤销")

print("\n" + "-"*60 + "\n")
print_info_message("演示 3: 取消市价单")

# 示例 3: 取消市价单
cancel_order_3 = {
    'order_id': '1202611345678901234',
    'symbol': 'TSLA.US',
    'side': 'SELL',
    'quantity': 50,
    'price': None,  # 市价单
    'cancelled_at': '2026-02-01 21:52:15',
    'mode': 'paper'
}
print_order_cancel_table(cancel_order_3, "订单撤销")

print("\n" + "="*60)
print("✅ 演示完成！注意观察浅灰色边框")
print("="*60 + "\n")
