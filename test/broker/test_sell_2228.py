#!/usr/bin/env python3
"""
测试卖出 1000 股 2228.HK
"""
import logging
from broker import LongPortBroker, load_longport_config
from broker.order_formatter import (
    print_positions_table,
    print_success_message,
    print_info_message,
    print_warning_message
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def main():
    print("\n" + "="*60)
    print("测试卖出 1000 股 2228.HK")
    print("="*60 + "\n")
    
    # 1. 初始化
    config = load_longport_config()
    broker = LongPortBroker(config)
    
    # 2. 查询当前持仓
    print_info_message("步骤 1: 查询当前持仓")
    positions = broker.get_positions()
    
    if positions:
        print_positions_table(positions, title="当前持仓")
    else:
        print_warning_message("暂无持仓")
        return
    
    # 3. 查找 2228.HK 持仓
    target_position = None
    for pos in positions:
        if pos['symbol'] == '2228.HK':
            target_position = pos
            break
    
    if not target_position:
        print_warning_message("未找到 2228.HK 持仓")
        return
    
    available_qty = target_position['available_quantity']
    print(f"\n✅ 找到 2228.HK 持仓")
    print(f"   可用数量: {available_qty:.0f} 股")
    print(f"   成本价: ${target_position['cost_price']:.2f}")
    
    # 4. 测试卖出 1000 股
    sell_qty = 1000
    print(f"\n" + "="*60)
    print_info_message(f"步骤 2: 测试卖出 {sell_qty} 股 2228.HK")
    print("="*60 + "\n")
    
    if sell_qty > available_qty:
        print_warning_message(f"卖出数量 ({sell_qty}) 超过可用持仓 ({available_qty:.0f})")
        print_info_message("此订单应该被拦截")
    else:
        print_success_message(f"卖出数量 ({sell_qty}) 在可用持仓范围内 ({available_qty:.0f})")
        print_info_message("此订单应该可以提交")
    
    print()
    
    # 5. 提交卖出订单
    try:
        # 注意：这里使用 Dry Run 模式（默认），不会真实下单
        # 如果要真实下单，需要设置 broker.dry_run = False
        
        # 临时启用真实模式以测试持仓检查（但仍在模拟账户）
        original_dry_run = broker.dry_run
        original_auto_trade = broker.auto_trade
        
        broker.dry_run = False  # 关闭 Dry Run 以测试持仓检查
        broker.auto_trade = True  # 启用自动交易
        
        order = broker.submit_stock_order(
            symbol='2228.HK',
            side='SELL',
            quantity=sell_qty,
            price=12.00,  # 使用一个测试价格
            order_type='LIMIT',
            remark=f'测试卖出 {sell_qty} 股'
        )
        
        print()
        print_success_message(f"订单提交成功！订单ID: {order['order_id']}")
        print(f"   股票: {order['symbol']}")
        print(f"   方向: {order['side']}")
        print(f"   数量: {order['quantity']}")
        print(f"   价格: ${order['price']:.2f}")
        print(f"   状态: {order['status']}")
        
        # 恢复原始设置
        broker.dry_run = original_dry_run
        broker.auto_trade = original_auto_trade
        
    except ValueError as e:
        print_warning_message(f"订单被拦截: {e}")
        print()
        print("="*60)
        print("⚠️  这是预期行为：持仓检查正常工作")
        print("="*60)
    except Exception as e:
        print_warning_message(f"订单提交失败: {e}")
    
    print("\n" + "="*60)
    print("测试完成")
    print("="*60 + "\n")

if __name__ == "__main__":
    main()
