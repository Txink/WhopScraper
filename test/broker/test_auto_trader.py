#!/usr/bin/env python3
"""
AutoTrader 测试脚本
测试自动交易模块的各种功能
"""
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from broker import LongPortBroker, load_longport_config, AutoTrader
from models.instruction import OptionInstruction, InstructionType


def test_generate_option_symbol():
    """测试期权代码生成"""
    print("\n" + "=" * 80)
    print("测试1: 期权代码生成")
    print("=" * 80 + "\n")
    
    config = load_longport_config()
    broker = LongPortBroker(config)
    trader = AutoTrader(broker)
    
    test_cases = [
        {
            'ticker': 'AAPL',
            'option_type': 'CALL',
            'strike': 250.0,
            'expiry': '2/7',
            'expected': 'AAPL260207C250000.US'
        },
        {
            'ticker': 'TSLA',
            'option_type': 'PUT',
            'strike': 440.5,
            'expiry': '2月9日',
            'expected': 'TSLA260209P440500.US'
        },
        {
            'ticker': 'NVDA',
            'option_type': 'CALL',
            'strike': 145.0,
            'expiry': '3/14',
            'expected': 'NVDA260314C145000.US'
        }
    ]
    
    for i, case in enumerate(test_cases, 1):
        instruction = OptionInstruction(
            ticker=case['ticker'],
            option_type=case['option_type'],
            strike=case['strike'],
            expiry=case['expiry']
        )
        
        result = trader._generate_option_symbol(instruction)
        success = result == case['expected']
        
        print(f"用例 {i}: {'✅ 通过' if success else '❌ 失败'}")
        print(f"  输入: {case['ticker']} {case['strike']} {case['option_type']} {case['expiry']}")
        print(f"  期望: {case['expected']}")
        print(f"  实际: {result}")
        print()
    
    print("=" * 80 + "\n")


def test_buy_instruction_dry_run():
    """测试买入指令（Dry Run模式）"""
    print("\n" + "=" * 80)
    print("测试2: 买入指令（Dry Run）")
    print("=" * 80 + "\n")
    
    # 设置Dry Run模式
    os.environ['LONGPORT_DRY_RUN'] = 'true'
    os.environ['REQUIRE_CONFIRMATION'] = 'false'
    
    config = load_longport_config()
    broker = LongPortBroker(config)
    trader = AutoTrader(broker)
    
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
    
    print(f"指令: {instruction}\n")
    
    # 执行指令
    result = trader.execute_instruction(instruction)
    
    if result:
        print(f"\n✅ 执行成功")
        print(f"结果: {result}")
    else:
        print(f"\n❌ 执行失败")
    
    print("\n" + "=" * 80 + "\n")


def test_sell_instruction_dry_run():
    """测试卖出指令（Dry Run模式）"""
    print("\n" + "=" * 80)
    print("测试3: 卖出指令（Dry Run）")
    print("=" * 80 + "\n")
    
    # 设置Dry Run模式
    os.environ['LONGPORT_DRY_RUN'] = 'true'
    os.environ['REQUIRE_CONFIRMATION'] = 'false'
    
    config = load_longport_config()
    broker = LongPortBroker(config)
    trader = AutoTrader(broker)
    
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
    
    print(f"指令: {instruction}\n")
    
    # 执行指令（预期会跳过，因为没有持仓）
    result = trader.execute_instruction(instruction)
    
    if result:
        print(f"\n✅ 执行成功")
        print(f"结果: {result}")
    else:
        print(f"\n⚠️  跳过执行（预期行为：无持仓）")
    
    print("\n" + "=" * 80 + "\n")


def test_modify_instruction_dry_run():
    """测试修改指令（Dry Run模式）"""
    print("\n" + "=" * 80)
    print("测试4: 修改指令（Dry Run）")
    print("=" * 80 + "\n")
    
    # 设置Dry Run模式
    os.environ['LONGPORT_DRY_RUN'] = 'true'
    os.environ['REQUIRE_CONFIRMATION'] = 'false'
    
    config = load_longport_config()
    broker = LongPortBroker(config)
    trader = AutoTrader(broker)
    
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
    
    print(f"指令: {instruction}\n")
    
    # 执行指令（预期会跳过，因为没有持仓）
    result = trader.execute_instruction(instruction)
    
    if result:
        print(f"\n✅ 执行成功")
        print(f"结果: {result}")
    else:
        print(f"\n⚠️  跳过执行（预期行为：无持仓）")
    
    print("\n" + "=" * 80 + "\n")


def test_batch_instructions():
    """测试批量执行指令"""
    print("\n" + "=" * 80)
    print("测试5: 批量执行指令（Dry Run）")
    print("=" * 80 + "\n")
    
    # 设置Dry Run模式
    os.environ['LONGPORT_DRY_RUN'] = 'true'
    os.environ['REQUIRE_CONFIRMATION'] = 'false'
    
    config = load_longport_config()
    broker = LongPortBroker(config)
    trader = AutoTrader(broker)
    
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
            raw_message="AAPL 250c 2/7 5.0"
        ),
        OptionInstruction(
            instruction_type=InstructionType.BUY.value,
            ticker="TSLA",
            option_type="CALL",
            strike=440.0,
            expiry="2/9",
            price=3.1,
            position_size="中仓位",
            raw_message="TSLA 440c 2/9 3.1"
        ),
        OptionInstruction(
            instruction_type=InstructionType.SELL.value,
            ticker="AAPL",
            option_type="CALL",
            strike=250.0,
            expiry="2/7",
            price=6.0,
            sell_quantity="1/2",
            raw_message="AAPL 250c 2/7 6.0出一半"
        ),
    ]
    
    print(f"共 {len(instructions)} 条指令:")
    for i, inst in enumerate(instructions, 1):
        print(f"{i}. {inst}")
    print()
    
    # 批量执行
    results = trader.execute_batch_instructions(instructions)
    
    # 统计结果
    success_count = sum(1 for r in results if r is not None)
    print(f"\n执行完成: 成功 {success_count}/{len(instructions)}")
    
    print("\n" + "=" * 80 + "\n")


def main():
    """主函数"""
    print("\n" + "=" * 80)
    print("AutoTrader 测试套件")
    print("=" * 80)
    print("\n所有测试运行在 Dry Run 模式，不会实际下单\n")
    
    # 运行所有测试
    test_generate_option_symbol()
    test_buy_instruction_dry_run()
    test_sell_instruction_dry_run()
    test_modify_instruction_dry_run()
    test_batch_instructions()
    
    print("\n" + "=" * 80)
    print("所有测试完成")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
