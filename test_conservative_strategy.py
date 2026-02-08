#!/usr/bin/env python3
"""
测试保守策略的前5条消息查找功能
验证无ticker的消息可以从前5条历史消息中找到买入信息
"""
from parser.message_context_resolver import MessageContextResolver
from models.instruction import InstructionType


def test_conservative_with_recent_messages():
    """测试保守策略：无ticker，从前5条消息查找"""
    print("\n" + "=" * 80)
    print("测试保守策略：无ticker，从前5条消息查找")
    print("=" * 80)
    
    messages = [
        {
            "domID": "post_001",
            "content": "AAPL 150c 2/14 5.5",
            "timestamp": "Jan 23, 2026 12:40 AM",
            "refer": None,
            "position": "single",
            "history": []
        },
        {
            "domID": "post_002",
            "content": "TSLA 440c 2/9 3.1",
            "timestamp": "Jan 23, 2026 12:41 AM",
            "refer": None,
            "position": "single",
            "history": []
        },
        {
            "domID": "post_003",
            "content": "市场震荡",
            "timestamp": "Jan 23, 2026 12:42 AM",
            "refer": None,
            "position": "single",
            "history": []
        },
        {
            "domID": "post_004",
            "content": "AMD 180c 2/14 3.0",
            "timestamp": "Jan 23, 2026 12:43 AM",
            "refer": None,
            "position": "single",
            "history": []
        },
        {
            "domID": "post_005",
            "content": "止损在2.5",  # 无ticker，应该从前5条找到最近的AMD
            "timestamp": "Jan 23, 2026 12:44 AM",
            "refer": None,
            "position": "single",
            "history": []
        }
    ]
    
    resolver = MessageContextResolver(all_messages=messages)
    
    # 解析第5条消息（无ticker的止损指令）
    result = resolver.resolve_instruction(messages[4])
    
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
        assert instruction.ticker == "AMD", f"期望 AMD（最近的买入），得到 {instruction.ticker}"
        assert instruction.strike == 180, f"期望 180，得到 {instruction.strike}"
        assert instruction.stop_loss_price == 2.5, f"期望 2.5，得到 {instruction.stop_loss_price}"
        assert context_source == "前5条", f"期望 前5条，得到 {context_source}"
        print("\n✓ 所有断言通过 - 保守策略成功从前5条消息查找到买入信息")
    else:
        print("\n❌ 解析失败")
        raise AssertionError("解析失败")


def test_conservative_priority():
    """测试保守策略的优先级：history > refer > 前5条"""
    print("\n" + "=" * 80)
    print("测试保守策略的查找优先级")
    print("=" * 80)
    
    messages = [
        {
            "domID": "post_006",
            "content": "NVDA 145c 2/7 2.5",
            "timestamp": "Jan 23, 2026 12:40 AM",
            "refer": None,
            "position": "first",
            "history": []
        },
        {
            "domID": "post_007",
            "content": "小仓位",
            "timestamp": "Jan 23, 2026 12:40 AM",
            "refer": None,
            "position": "middle",
            "history": ["NVDA 145c 2/7 2.5"]
        },
        {
            "domID": "post_008",
            "content": "止损在2.0",  # 无ticker，应该从history找到NVDA（优先级高于前5条）
            "timestamp": "Jan 23, 2026 12:40 AM",
            "refer": None,
            "position": "last",
            "history": ["NVDA 145c 2/7 2.5", "小仓位"]
        },
        {
            "domID": "post_009",
            "content": "TSLA 440c 2/9 3.1",
            "timestamp": "Jan 23, 2026 12:41 AM",
            "refer": None,
            "position": "single",
            "history": []
        },
        {
            "domID": "post_010",
            "content": "止损在2.8",  # 无ticker，history为空，应该从前5条找到TSLA
            "timestamp": "Jan 23, 2026 12:42 AM",
            "refer": None,
            "position": "single",
            "history": []
        }
    ]
    
    resolver = MessageContextResolver(all_messages=messages)
    
    # 测试1：从history找到
    print("\n--- 测试1：优先从history查找 ---")
    result = resolver.resolve_instruction(messages[2])
    if result:
        instruction, context_source, context_message = result
        print(f"✅ 找到: {instruction.ticker} 来源: {context_source}")
        assert instruction.ticker == "NVDA"
        assert context_source == "history"
        print("✓ 正确优先使用history")
    
    # 测试2：从前5条找到
    print("\n--- 测试2：history为空时从前5条查找 ---")
    result = resolver.resolve_instruction(messages[4])
    if result:
        instruction, context_source, context_message = result
        print(f"✅ 找到: {instruction.ticker} 来源: {context_source}")
        assert instruction.ticker == "TSLA"
        assert context_source == "前5条"
        print("✓ 正确使用前5条作为后备")
    
    print("\n✓ 优先级测试通过")


def test_conservative_with_refer():
    """测试保守策略：refer优先级高于前5条"""
    print("\n" + "=" * 80)
    print("测试保守策略：refer优先级高于前5条")
    print("=" * 80)
    
    messages = [
        {
            "domID": "post_011",
            "content": "AMD 180c 2/14 3.0",
            "timestamp": "Jan 23, 2026 12:40 AM",
            "refer": None,
            "position": "single",
            "history": []
        },
        {
            "domID": "post_012",
            "content": "止损在2.5",
            "timestamp": "Jan 23, 2026 12:41 AM",
            "refer": "NVDA 145c 2/7 2.5",  # 引用了NVDA，应该优先使用refer而非前5条的AMD
            "position": "single",
            "history": []
        }
    ]
    
    resolver = MessageContextResolver(all_messages=messages)
    
    result = resolver.resolve_instruction(messages[1])
    if result:
        instruction, context_source, context_message = result
        print(f"\n✅ 解析成功")
        print(f"   股票代码: {instruction.ticker}")
        print(f"   上下文来源: {context_source}")
        
        assert instruction.ticker == "NVDA", f"期望 NVDA（从refer），得到 {instruction.ticker}"
        assert context_source == "refer", f"期望 refer，得到 {context_source}"
        print("\n✓ 正确优先使用refer而非前5条")
    else:
        print("\n❌ 解析失败")
        raise AssertionError("解析失败")


def main():
    """运行所有测试"""
    print("\n" + "=" * 80)
    print("保守策略增强测试")
    print("=" * 80)
    
    try:
        test_conservative_with_recent_messages()
        test_conservative_priority()
        test_conservative_with_refer()
        
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
