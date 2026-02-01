#!/usr/bin/env python3
"""
对比不同订单类型的边框颜色
"""
from broker.order_formatter import (
    print_order_table,
    print_order_cancel_table,
    print_order_failed_table,
    print_info_message
)

print("\n" + "="*60)
print("订单表格边框颜色对比")
print("="*60 + "\n")

# 1. 成功的买入订单（蓝色边框）
print_info_message("1. 成功的买入订单（蓝色边框）")
success_buy_order = {
    'order_id': '1202611111111111111',
    'symbol': 'AAPL.US',
    'side': 'BUY',
    'quantity': 100,
    'price': 250.00,
    'status': 'submitted',
    'mode': 'paper',
    'remark': '成功买入订单'
}
print_order_table(success_buy_order)

print("\n" + "-"*60 + "\n")

# 2. 成功的卖出订单（绿色边框）
print_info_message("2. 成功的卖出订单（绿色边框）")
success_sell_order = {
    'order_id': '1202612222222222222',
    'symbol': 'TSLA.US',
    'side': 'SELL',
    'quantity': 50,
    'price': 400.00,
    'status': 'submitted',
    'mode': 'paper',
    'remark': '成功卖出订单'
}
print_order_table(success_sell_order)

print("\n" + "-"*60 + "\n")

# 3. 取消的订单（极浅灰色边框）
print_info_message("3. 取消的订单（极浅灰色边框 - dim white）")
cancel_order = {
    'order_id': '1202613333333333333',
    'symbol': 'NVDA.US',
    'side': 'BUY',
    'quantity': 20,
    'price': 190.00,
    'cancelled_at': '2026-02-01 22:00:00',
    'mode': 'paper'
}
print_order_cancel_table(cancel_order)

print("\n" + "-"*60 + "\n")

# 4. 失败的订单（红色边框）
print_info_message("4. 失败的订单（红色边框）")
failed_order = {
    'symbol': 'AMZN.US',
    'side': 'SELL',
    'quantity': 100,
    'price': 180.00,
    'mode': 'paper',
    'remark': '失败的卖出订单'
}
print_order_failed_table(failed_order, '持仓不足: 无法卖出 100 股 AMZN.US')

print("\n" + "="*60)
print("✅ 对比完成")
print("\n边框颜色层次:")
print("  🔵 蓝色 - 买入成功")
print("  🟢 绿色 - 卖出成功")
print("  ⚪ 极浅灰 - 取消订单")
print("  🔴 红色 - 失败订单")
print("="*60 + "\n")
