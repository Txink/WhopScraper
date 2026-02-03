#!/usr/bin/env python3
"""
测试消息上下文解析器
使用计划中的测试用例验证功能
"""
from parser.message_context_resolver import MessageContextResolver
from models.instruction import InstructionType


def test_case_1():
    """测试用例1：有股票名但缺细节"""
    print("\n" + "=" * 80)
    print("测试用例1：有股票名但缺细节")
    print("=" * 80)
    
    messages = [
        {
            "domID": "post_001",
            "content": "TSLA 440c 2/9 3.1",
            "timestamp": "Jan 23, 2026 12:51 AM",
            "refer": None,
            "position": "first",
            "history": []
        },
        {
            "domID": "post_002",
            "content": "3.1出三分之一tsla",  # 明确指定tsla
            "timestamp": "Jan 23, 2026 12:51 AM",
            "refer": None,
            "position": "last",
            "history": ["TSLA 440c 2/9 3.1"]
        }
    ]
    
    resolver = MessageContextResolver(messages)
    
    # 解析第二条消息（应该从 history 补全）
    result = resolver.resolve_instruction(messages[1])
    
    if result:
        instruction, context_source, context_message = result
        print(f"\n✅ 解析成功")
        print(f"   指令类型: {instruction.instruction_type}")
        print(f"   股票代码: {instruction.ticker}")
        print(f"   行权价: ${instruction.strike}")
        print(f"   到期日: {instruction.expiry}")
        print(f"   价格: ${instruction.price}")
        print(f"   卖出数量: {instruction.sell_quantity}")
        print(f"   上下文来源: {context_source}")
        print(f"   上下文消息: {context_message}")
        
        # 验证
        assert instruction.ticker == "TSLA", f"期望 TSLA，得到 {instruction.ticker}"
        assert instruction.strike == 440, f"期望 440，得到 {instruction.strike}"
        assert instruction.expiry == "2/9", f"期望 2/9，得到 {instruction.expiry}"
        assert context_source == "history", f"期望 history，得到 {context_source}"
        print("\n✓ 所有断言通过")
    else:
        print("\n❌ 解析失败")


def test_case_2():
    """测试用例2：无股票名"""
    print("\n" + "=" * 80)
    print("测试用例2：无股票名")
    print("=" * 80)
    
    messages = [
        {
            "domID": "post_003",
            "content": "TSLA 440c 2/9 3.1",
            "timestamp": "Jan 23, 2026 12:51 AM",
            "refer": None,
            "position": "first",
            "history": []
        },
        {
            "domID": "post_004",
            "content": "止损在2.9",
            "timestamp": "Jan 23, 2026 12:51 AM",
            "refer": None,
            "position": "last",
            "history": ["TSLA 440c 2/9 3.1", "慢速 小仓位"]
        }
    ]
    
    resolver = MessageContextResolver(messages)
    
    # 解析第二条消息（应该从 history 补全）
    result = resolver.resolve_instruction(messages[1])
    
    if result:
        instruction, context_source, context_message = result
        print(f"\n✅ 解析成功")
        print(f"   指令类型: {instruction.instruction_type}")
        print(f"   股票代码: {instruction.ticker}")
        print(f"   行权价: ${instruction.strike}")
        print(f"   到期日: {instruction.expiry}")
        print(f"   止损价格: ${instruction.stop_loss_price}")
        print(f"   上下文来源: {context_source}")
        print(f"   上下文消息: {context_message}")
        
        # 验证
        assert instruction.instruction_type == InstructionType.MODIFY.value
        assert instruction.ticker == "TSLA", f"期望 TSLA，得到 {instruction.ticker}"
        assert instruction.strike == 440, f"期望 440，得到 {instruction.strike}"
        assert instruction.stop_loss_price == 2.9, f"期望 2.9，得到 {instruction.stop_loss_price}"
        assert context_source == "history", f"期望 history，得到 {context_source}"
        print("\n✓ 所有断言通过")
    else:
        print("\n❌ 解析失败")


def test_case_3():
    """测试用例3：通过 refer 补全"""
    print("\n" + "=" * 80)
    print("测试用例3：通过 refer 补全")
    print("=" * 80)
    
    messages = [
        {
            "domID": "post_005",
            "content": "小仓位 止损 在 1.3",
            "timestamp": "Jan 22, 2026 10:41 PM",
            "refer": "GILD - $130 CALLS 这周 1.5-1.60",
            "position": "first",
            "history": []
        }
    ]
    
    resolver = MessageContextResolver(messages)
    
    # 解析消息（应该从 refer 补全）
    result = resolver.resolve_instruction(messages[0])
    
    if result:
        instruction, context_source, context_message = result
        print(f"\n✅ 解析成功")
        print(f"   指令类型: {instruction.instruction_type}")
        print(f"   股票代码: {instruction.ticker}")
        print(f"   行权价: ${instruction.strike}")
        print(f"   期权类型: {instruction.option_type}")
        print(f"   止损价格: ${instruction.stop_loss_price}")
        print(f"   上下文来源: {context_source}")
        print(f"   上下文消息: {context_message}")
        
        # 验证
        assert instruction.instruction_type == InstructionType.MODIFY.value
        assert instruction.ticker == "GILD", f"期望 GILD，得到 {instruction.ticker}"
        assert instruction.strike == 130, f"期望 130，得到 {instruction.strike}"
        assert instruction.option_type == "CALL", f"期望 CALL，得到 {instruction.option_type}"
        assert instruction.stop_loss_price == 1.3, f"期望 1.3，得到 {instruction.stop_loss_price}"
        assert context_source == "refer", f"期望 refer，得到 {context_source}"
        print("\n✓ 所有断言通过")
    else:
        print("\n❌ 解析失败")


def test_case_4():
    """测试用例4：前5条消息查找"""
    print("\n" + "=" * 80)
    print("测试用例4：前5条消息查找（积极策略）")
    print("=" * 80)
    
    messages = [
        {
            "domID": "post_006",
            "content": "NVDA 145c 2/7 2.5",
            "timestamp": "Jan 23, 2026 12:40 AM",
            "refer": None,
            "position": "single",
            "history": []
        },
        {
            "domID": "post_007",
            "content": "AMD 180c 2/14 3.0",
            "timestamp": "Jan 23, 2026 12:42 AM",
            "refer": None,
            "position": "single",
            "history": []
        },
        {
            "domID": "post_008",
            "content": "市场反弹",
            "timestamp": "Jan 23, 2026 12:43 AM",
            "refer": None,
            "position": "single",
            "history": []
        },
        {
            "domID": "post_009",
            "content": "2.8出一半nvda",
            "timestamp": "Jan 23, 2026 12:45 AM",
            "refer": None,
            "position": "single",
            "history": []
        }
    ]
    
    resolver = MessageContextResolver(messages)
    
    # 解析第4条消息（应该从前5条找到 NVDA）
    result = resolver.resolve_instruction(messages[3])
    
    if result:
        instruction, context_source, context_message = result
        print(f"\n✅ 解析成功")
        print(f"   指令类型: {instruction.instruction_type}")
        print(f"   股票代码: {instruction.ticker}")
        print(f"   行权价: ${instruction.strike}")
        print(f"   到期日: {instruction.expiry}")
        print(f"   价格: ${instruction.price}")
        print(f"   卖出数量: {instruction.sell_quantity}")
        print(f"   上下文来源: {context_source}")
        print(f"   上下文消息: {context_message}")
        
        # 验证
        assert instruction.ticker == "NVDA", f"期望 NVDA，得到 {instruction.ticker}"
        assert instruction.strike == 145, f"期望 145，得到 {instruction.strike}"
        assert instruction.expiry == "2/7", f"期望 2/7，得到 {instruction.expiry}"
        assert context_source == "前5条", f"期望 前5条，得到 {context_source}"
        print("\n✓ 所有断言通过")
    else:
        print("\n❌ 解析失败")


def test_case_5():
    """测试用例5：实际消息场景"""
    print("\n" + "=" * 80)
    print("测试用例5：实际消息场景（来自用户提供的数据）")
    print("=" * 80)
    
    messages = [
        {
            "domID": "post_1CXjRw4evzFxZ1Mg98rH15",
            "content": "TSLA 440c 2/9 3.1",
            "timestamp": "Jan 23, 2026 12:51 AM",
            "refer": None,
            "position": "first",
            "history": []
        },
        {
            "domID": "post_1CXjRx8kHbRZgNmmzAFimV",
            "content": "止损在2.9",
            "timestamp": "Jan 23, 2026 12:51 AM",
            "refer": None,
            "position": "last",
            "history": ["TSLA 440c 2/9 3.1", "慢速 小仓位"]
        },
        {
            "domID": "post_1CXjYG8qtgGgDKkFCsV9p8",
            "content": "BA - $240 CALLS EXPIRATION 2月13 $2.8",
            "timestamp": "Jan 23, 2026 12:51 AM",
            "refer": None,
            "position": "first",
            "history": []
        },
        {
            "domID": "post_1CXjYTNh5zdtNhQRanz2BM",
            "content": "3.1出三分之一ba",
            "timestamp": "Jan 23, 2026 12:51 AM",
            "refer": None,
            "position": "single",
            "history": []
        }
    ]
    
    resolver = MessageContextResolver(messages)
    
    # 测试第2条消息（止损在2.9）
    print("\n--- 测试消息2：止损在2.9 ---")
    result = resolver.resolve_instruction(messages[1])
    if result:
        instruction, context_source, context_message = result
        print(f"✅ 补全成功: {instruction.ticker} ${instruction.strike} {instruction.option_type}")
        print(f"   上下文来源: {context_source}")
        assert instruction.ticker == "TSLA"
        assert instruction.strike == 440
    
    # 测试第4条消息（3.1出三分之一ba）
    print("\n--- 测试消息4：3.1出三分之一ba ---")
    result = resolver.resolve_instruction(messages[3])
    if result:
        instruction, context_source, context_message = result
        print(f"✅ 补全成功: {instruction.ticker} ${instruction.strike} {instruction.option_type}")
        print(f"   上下文来源: {context_source}")
        # 这条消息应该从前5条找到 BA
        assert instruction.ticker == "BA"
        assert instruction.strike == 240


def main():
    """运行所有测试"""
    print("\n" + "=" * 80)
    print("消息上下文解析器测试")
    print("=" * 80)
    
    try:
        test_case_1()
        test_case_2()
        test_case_3()
        test_case_4()
        test_case_5()
        
        print("\n" + "=" * 80)
        print("✅ 所有测试通过！")
        print("=" * 80 + "\n")
    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}\n")
    except Exception as e:
        print(f"\n❌ 测试出错: {e}\n")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
