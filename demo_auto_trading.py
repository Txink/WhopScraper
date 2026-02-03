#!/usr/bin/env python3
"""
自动交易功能演示脚本
展示如何使用AutoTrader执行parser处理后的指令
"""
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from broker import LongPortBroker, load_longport_config, AutoTrader
from models.instruction import OptionInstruction, InstructionType


def demo_buy_instruction():
    """演示买入指令"""
    print("\n" + "=" * 80)
    print("演示1: 买入指令")
    print("=" * 80 + "\n")
    
    # 创建买入指令
    instruction = OptionInstruction(
        instruction_type=InstructionType.BUY.value,
        ticker="AAPL",
        option_type="CALL",
        strike=250.0,
        expiry="2/7",
        price=5.0,
        position_size="小仓位",
        raw_message="AAPL 250c 2/7 5.0 小仓位"
    )
    
    print(f"指令: {instruction}")
    print()
    
    # 初始化broker和trader
    config = load_longport_config()
    broker = LongPortBroker(config)
    trader = AutoTrader(broker)
    
    # 执行指令
    result = trader.execute_instruction(instruction)
    
    if result:
        print(f"\n执行结果: {result}")
    else:
        print("\n执行失败")


def demo_sell_instruction():
    """演示卖出指令"""
    print("\n" + "=" * 80)
    print("演示2: 卖出指令（卖出1/3）")
    print("=" * 80 + "\n")
    
    # 创建卖出指令
    instruction = OptionInstruction(
        instruction_type=InstructionType.SELL.value,
        ticker="AAPL",
        option_type="CALL",
        strike=250.0,
        expiry="2/7",
        price=6.0,
        sell_quantity="1/3",
        raw_message="AAPL 250c 2/7 6.0出1/3"
    )
    
    print(f"指令: {instruction}")
    print()
    
    # 初始化broker和trader
    config = load_longport_config()
    broker = LongPortBroker(config)
    trader = AutoTrader(broker)
    
    # 执行指令
    result = trader.execute_instruction(instruction)
    
    if result:
        print(f"\n执行结果: {result}")
    else:
        print("\n执行失败")


def demo_close_instruction():
    """演示清仓指令"""
    print("\n" + "=" * 80)
    print("演示3: 清仓指令")
    print("=" * 80 + "\n")
    
    # 创建清仓指令
    instruction = OptionInstruction(
        instruction_type=InstructionType.CLOSE.value,
        ticker="AAPL",
        option_type="CALL",
        strike=250.0,
        expiry="2/7",
        price=7.0,
        raw_message="AAPL 250c 2/7 7.0清仓"
    )
    
    print(f"指令: {instruction}")
    print()
    
    # 初始化broker和trader
    config = load_longport_config()
    broker = LongPortBroker(config)
    trader = AutoTrader(broker)
    
    # 执行指令
    result = trader.execute_instruction(instruction)
    
    if result:
        print(f"\n执行结果: {result}")
    else:
        print("\n执行失败")


def demo_modify_instruction():
    """演示修改指令（止盈止损）"""
    print("\n" + "=" * 80)
    print("演示4: 修改指令（止盈止损）")
    print("=" * 80 + "\n")
    
    # 创建修改指令
    instruction = OptionInstruction(
        instruction_type=InstructionType.MODIFY.value,
        ticker="AAPL",
        option_type="CALL",
        strike=250.0,
        expiry="2/7",
        stop_loss_price=3.0,
        take_profit_price=10.0,
        raw_message="AAPL 250c 2/7 止损3.0 止盈10.0"
    )
    
    print(f"指令: {instruction}")
    print()
    
    # 初始化broker和trader
    config = load_longport_config()
    broker = LongPortBroker(config)
    trader = AutoTrader(broker)
    
    # 执行指令
    result = trader.execute_instruction(instruction)
    
    if result:
        print(f"\n执行结果: {result}")
    else:
        print("\n执行失败")


def demo_batch_instructions():
    """演示批量执行指令"""
    print("\n" + "=" * 80)
    print("演示5: 批量执行指令")
    print("=" * 80 + "\n")
    
    # 创建多个指令
    instructions = [
        OptionInstruction(
            instruction_type=InstructionType.BUY.value,
            ticker="AAPL",
            option_type="CALL",
            strike=250.0,
            expiry="2/7",
            price=5.0,
            position_size="小仓位",
            raw_message="AAPL 250c 2/7 5.0 小仓位"
        ),
        OptionInstruction(
            instruction_type=InstructionType.BUY.value,
            ticker="TSLA",
            option_type="CALL",
            strike=440.0,
            expiry="2/9",
            price=3.1,
            position_size="中仓位",
            raw_message="TSLA 440c 2/9 3.1 中仓位"
        ),
        OptionInstruction(
            instruction_type=InstructionType.MODIFY.value,
            ticker="AAPL",
            option_type="CALL",
            strike=250.0,
            expiry="2/7",
            stop_loss_price=3.0,
            raw_message="AAPL 250c 2/7 止损3.0"
        ),
    ]
    
    print(f"共 {len(instructions)} 条指令:")
    for i, inst in enumerate(instructions, 1):
        print(f"{i}. {inst}")
    print()
    
    # 初始化broker和trader
    config = load_longport_config()
    broker = LongPortBroker(config)
    trader = AutoTrader(broker)
    
    # 批量执行
    results = trader.execute_batch_instructions(instructions)
    
    # 统计结果
    success_count = sum(1 for r in results if r is not None)
    print(f"\n执行完成: 成功 {success_count}/{len(instructions)}")


def main():
    """主函数"""
    print("\n" + "=" * 80)
    print("自动交易功能演示")
    print("=" * 80)
    print("\n请选择演示场景:")
    print("  1. 买入指令")
    print("  2. 卖出指令")
    print("  3. 清仓指令")
    print("  4. 修改指令（止盈止损）")
    print("  5. 批量执行指令")
    print("  6. 全部演示")
    print("  0. 退出")
    
    choice = input("\n请输入选项 (0-6): ").strip()
    
    if choice == "1":
        demo_buy_instruction()
    elif choice == "2":
        demo_sell_instruction()
    elif choice == "3":
        demo_close_instruction()
    elif choice == "4":
        demo_modify_instruction()
    elif choice == "5":
        demo_batch_instructions()
    elif choice == "6":
        demo_buy_instruction()
        demo_sell_instruction()
        demo_close_instruction()
        demo_modify_instruction()
        demo_batch_instructions()
    elif choice == "0":
        print("退出")
    else:
        print("无效选项")


if __name__ == "__main__":
    main()
