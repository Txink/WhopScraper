#!/usr/bin/env python3
"""
订单格式化输出演示
展示彩色表格的各种场景
"""
from broker.order_formatter import (
    print_order_table,
    print_order_search_table,
    print_order_modify_table,
    print_order_cancel_table,
    print_orders_summary_table,
    print_success_message,
    print_error_message,
    print_warning_message,
    print_info_message
)

print("\n" + "="*60)
print("订单格式化输出演示")
print("="*60 + "\n")

# 1. 买入订单（绿色 BUY）
print_info_message("场景 1: 买入订单 (BUY - 绿色)")
print()
buy_order = {
    'order_id': '1202580174474850304',
    'symbol': 'AAPL260207C250000.US',
    'side': 'BUY',
    'quantity': 2,
    'price': 5.0,
    'trigger_price': 3.0,
    'trailing_percent': None,
    'status': 'submitted',
    'mode': 'paper',
    'remark': '带止损的买入订单'
}
print_success_message("订单提交成功")
print_order_table(buy_order, "买入订单详情")

print("\n" + "-"*60 + "\n")

# 2. 卖出订单（红色 SELL）
print_info_message("场景 2: 卖出订单 (SELL - 红色)")
print()
sell_order = {
    'order_id': '1202580174474850305',
    'symbol': 'TSLA260214P250000.US',
    'side': 'SELL',
    'quantity': 1,
    'price': 4.5,
    'trigger_price': None,
    'trailing_percent': 5.0,
    'status': 'submitted',
    'mode': 'paper',
    'remark': '带跟踪止损的卖出订单'
}
print_success_message("订单提交成功")
print_order_table(sell_order, "卖出订单详情")

print("\n" + "-"*60 + "\n")

# 3. 订单查询（蓝色 SEARCH）
print_info_message("场景 3: 订单查询 (SEARCH - 蓝色)")
print()
search_order = {
    'order_id': '1202580174474850308',
    'symbol': 'MSFT260228C450000.US',
    'side': 'BUY',
    'quantity': 3,
    'executed_quantity': 2,
    'price': 6.5,
    'trigger_price': 5.0,
    'status': 'PartiallyFilled',
    'submitted_at': '2026-02-01T10:30:45',
    'mode': 'paper',
    'remark': '部分成交的买入订单'
}
print_success_message("找到订单")
print_order_search_table(search_order, "订单查询")

print("\n" + "-"*60 + "\n")

# 4. 订单修改（只显示修改项，黄色高亮）
print_info_message("场景 4: 订单修改 (只显示修改项，黄色高亮)")
print()
old_order = {
    'order_id': '1202580174474850304',
    'symbol': 'AAPL260207C250000.US',
    'side': 'BUY',
    'quantity': 1,
    'price': 5.0,
    'trigger_price': 3.0,
}

new_values = {
    'quantity': 3,           # 修改了
    'price': 4.5,            # 修改了
    'trigger_price': 2.5,    # 修改了
}

print_success_message("订单修改成功")
print_order_modify_table('1202580174474850304', old_order, new_values, "订单修改详情")

print("\n" + "-"*60 + "\n")

# 4.2 订单修改（部分修改）
print_info_message("场景 4.2: 部分修改 (只改价格)")
print()
old_order2 = {
    'order_id': '1202580174474850307',
    'symbol': 'TSLA260214P250000.US',
    'side': 'SELL',
    'quantity': 2,
    'price': 6.0,
    'trailing_percent': 5.0,
}

new_values2 = {
    'quantity': 2,           # 未修改
    'price': 5.5,            # 修改了
    'trailing_percent': 5.0, # 未修改
}

print_success_message("订单修改成功")
print_order_modify_table('1202580174474850307', old_order2, new_values2, "订单修改详情")

print("\n" + "-"*60 + "\n")

# 5. 订单撤销（黄色 CANCEL）
print_info_message("场景 5: 订单撤销 (CANCEL - 黄色)")
print()
cancel_order = {
    'order_id': '1202580174474850306',
    'symbol': 'NVDA260221C900000.US',
    'side': 'BUY',
    'quantity': 2,
    'price': 3.0,
    'status': 'cancelled',
    'cancelled_at': '2026-02-01T19:44:33.977'
}
print_success_message("订单撤销成功")
print_order_cancel_table(cancel_order, "撤销订单详情")

print("\n" + "-"*60 + "\n")

# 6. 订单列表汇总
print_info_message("场景 6: 订单列表汇总")
print()
orders = [
    {
        'order_id': '1202580174474850304',
        'symbol': 'AAPL260207C250000.US',
        'side': 'BUY',
        'quantity': 2,
        'price': 5.0,
        'trigger_price': 3.0,
        'status': 'filled'
    },
    {
        'order_id': '1202580174474850305',
        'symbol': 'TSLA260214P250000.US',
        'side': 'SELL',
        'quantity': 1,
        'price': 4.5,
        'trailing_percent': 5.0,
        'status': 'pending'
    },
    {
        'order_id': '1202580174474850306',
        'symbol': 'NVDA260221C900000.US',
        'side': 'BUY',
        'quantity': 3,
        'price': 3.0,
        'status': 'cancelled'
    },
]

print_orders_summary_table(orders, "当日订单列表")

print("\n" + "-"*60 + "\n")

# 7. 消息类型演示
print_info_message("场景 7: 各种消息类型")
print()
print_success_message("成功消息 - 绿色")
print_error_message("错误消息 - 红色")
print_warning_message("警告消息 - 黄色")
print_info_message("信息消息 - 青色")

print("\n" + "="*60)
print("演示完成！")
print("="*60 + "\n")

print("📖 说明:")
print("  • BUY (买入) - 绿色粗体")
print("  • SELL (卖出) - 红色粗体")
print("  • SEARCH (查询) - 蓝色粗体")
print("  • CANCEL (撤销) - 黄色粗体")
print("  • 修改项 (如 1 → 2) - 黄色粗体高亮")
print("  • 止盈止损策略 - 自动格式化显示")
print()
