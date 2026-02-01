#!/usr/bin/env python3
"""
订单表格边框颜色演示
展示不同订单类型的彩色边框效果
"""
from broker.order_formatter import (
    print_order_table,
    print_order_search_table,
    print_order_modify_table,
    print_order_cancel_table,
    print_success_message
)

print("\n" + "="*60)
print("订单表格边框颜色演示")
print("="*60)

# 1. 购买订单 - 蓝色边框
print("\n📘 场景 1: 购买订单（BUY - 蓝色粗体边框）\n")
buy_order = {
    'order_id': '1234567890',
    'symbol': 'AAPL260207C250000.US',
    'side': 'BUY',
    'quantity': 2,
    'price': 5.00,
    'trigger_price': 3.00,
    'status': 'submitted',
    'mode': 'paper',
    'remark': '购买订单 - 蓝色边框示例'
}
print_order_table(buy_order)

# 2. 售卖订单 - 绿色边框
print("\n" + "-"*60)
print("\n📗 场景 2: 售卖订单（SELL - 绿色粗体边框）\n")
sell_order = {
    'order_id': '9876543210',
    'symbol': 'TSLA260214P250000.US',
    'side': 'SELL',
    'quantity': 1,
    'price': 4.50,
    'trailing_percent': 5.0,
    'status': 'submitted',
    'mode': 'paper',
    'remark': '售卖订单 - 绿色边框示例'
}
print_order_table(sell_order)

# 3. 修改订单 - 黄色边框
print("\n" + "-"*60)
print("\n📙 场景 3: 订单修改（MODIFY - 黄色粗体边框）\n")
old_order = {
    'symbol': 'AAPL260207C250000.US',
    'side': 'BUY',
    'quantity': 1,
    'price': 5.00,
    'trigger_price': 3.00
}
new_values = {
    'quantity': 3,
    'price': 4.50
}
print_order_modify_table('1234567890', old_order, new_values)

# 4. 撤销订单 - 红色边框
print("\n" + "-"*60)
print("\n📕 场景 4: 撤销订单（CANCEL - 红色粗体边框）\n")
cancel_order = {
    'order_id': '5555666677',
    'symbol': 'NVDA260221C900000.US',
    'side': 'BUY',
    'quantity': 2,
    'price': 3.00,
    'status': 'cancelled',
    'cancelled_at': '2026-02-01T20:00:00.000'
}
print_order_cancel_table(cancel_order)

# 5. 查询订单（根据side显示边框）
print("\n" + "-"*60)
print("\n🔍 场景 5: 订单查询（边框颜色跟随订单类型）\n")
print("查询购买订单 - 蓝色边框：")
search_buy_order = {
    'order_id': '1111222233',
    'symbol': 'MSFT260228C450000.US',
    'side': 'BUY',
    'quantity': 3,
    'executed_quantity': 2,
    'price': 6.50,
    'trigger_price': 5.00,
    'status': 'PartiallyFilled',
    'submitted_at': '2026-02-01T10:30:45',
    'remark': '部分成交的购买订单'
}
print_order_search_table(search_buy_order)

print("\n" + "="*60)
print("演示完成！")
print("="*60)
print("\n📖 边框颜色说明:")
print("  🔵 蓝色边框 - 购买订单（BUY）")
print("  🟢 绿色边框 - 售卖订单（SELL）")
print("  🟡 黄色边框 - 修改订单（MODIFY）")
print("  🔴 红色边框 - 撤销订单（CANCEL）")
print("\n💡 提示：粗边框 + 彩色边框帮助快速识别订单类型，降低误操作风险！\n")
