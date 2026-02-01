#!/usr/bin/env python3
"""
演示失败订单的红色边框表格展示
运行此脚本可以看到彩色的失败订单表格
"""
from broker.order_formatter import print_order_failed_table, print_success_message, print_info_message

print("\n" + "="*60)
print("失败订单红色边框表格演示")
print("="*60 + "\n")

print_info_message("演示 1: 无持仓卖出失败")

# 示例 1: 无持仓卖出失败
failed_order_1 = {
    'symbol': 'AMZN.US',
    'side': 'SELL',
    'quantity': 10,
    'price': 180.50,
    'mode': 'paper',
    'remark': '测试卖出订单 - 无持仓'
}
print_order_failed_table(failed_order_1, '持仓不足: 无法卖出 10 股 AMZN.US')

print("\n" + "-"*60 + "\n")
print_info_message("演示 2: 超过持仓数量卖出失败")

# 示例 2: 超过持仓数量
failed_order_2 = {
    'symbol': 'AAPL.US',
    'side': 'SELL',
    'quantity': 1000,
    'price': 250.00,
    'mode': 'paper',
    'remark': '测试卖出订单 - 超量卖出'
}
print_order_failed_table(failed_order_2, '持仓数量不足: AAPL.US 可用 500 < 卖出 1000')

print("\n" + "-"*60 + "\n")
print_info_message("演示 3: 期权卖出失败")

# 示例 3: 期权卖出失败
failed_order_3 = {
    'symbol': 'AAPL260207C00250000.US',
    'side': 'SELL',
    'quantity': 5,
    'price': 3.50,
    'mode': 'real',
    'remark': '测试期权卖出 - 无持仓'
}
print_order_failed_table(failed_order_3, '持仓不足: 无法卖出 5 张 AAPL260207C00250000.US')

print("\n" + "="*60)
print_success_message("演示完成！注意观察红色边框和红色失败原因")
print("="*60 + "\n")
