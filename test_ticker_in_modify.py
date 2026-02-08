#!/usr/bin/env python3
"""
测试MODIFY指令中提取ticker并使用积极策略补全
"""
from parser.message_context_resolver import MessageContextResolver
from models.instruction import InstructionType


def test_modify_with_ticker():
    """测试MODIFY指令提取ticker并从上下文补全"""
    print("\n" + "=" * 80)
    print("测试MODIFY指令提取ticker并使用积极策略补全")
    print("=" * 80)
    
    messages = [
        {
            "domID": "post_001",
            "content": "BA - $240 CALLS EXPIRATION 2月13 $2.8",
            "timestamp": "Jan 23, 2026 12:50 AM",
            "refer": None,
            "position": "single",
            "history": []
        },
        {
            "domID": "post_002",
            "content": "TSLA 440c 2/9 3.1",
            "timestamp": "Jan 23, 2026 12:51 AM",
            "refer": None,
            "position": "single",
            "history": []
        },
        {
            "domID": "post_003",
            "content": "止损提高到3.2 tsla期权今天也是日内的",
            "timestamp": "Jan 23, 2026 12:51 AM",
            "refer": None,
            "position": "single",
            "history": []
        }
    ]
    
    resolver = MessageContextResolver(all_messages=messages)
    
    # 解析第3条消息
    result = resolver.resolve_instruction(messages[2])
    
    if result:
        instruction, context_source, context_message = result
        print(f"\n✅ 解析成功")
        print(f"   指令类型: {instruction.instruction_type}")
        print(f"   股票代码: {instruction.ticker}")
        print(f"   行权价: ${instruction.strike}")
        print(f"   期权类型: {instruction.option_type}")
        print(f"   到期日: {instruction.expiry}")
        print(f"   止损价格: ${instruction.stop_loss_price}")
        print(f"   上下文来源: {context_source}")
        print(f"   上下文消息: {context_message}")
        
        # 验证
        assert instruction.instruction_type == InstructionType.MODIFY.value
        assert instruction.ticker == "TSLA", f"期望 TSLA，得到 {instruction.ticker}"
        assert instruction.strike == 440, f"期望 440，得到 {instruction.strike}"
        assert instruction.expiry == "2/9", f"期望 2/9，得到 {instruction.expiry}"
        assert instruction.stop_loss_price == 3.2
        assert context_source == "前5条", f"期望 前5条，得到 {context_source}"
        print("\n✓ 所有断言通过 - 正确提取ticker并从前5条补全TSLA的信息")
    else:
        print("\n❌ 解析失败")
        raise AssertionError("解析失败")


def test_modify_wrong_ticker():
    """测试当消息明确指定ticker时，不会被错误的历史消息覆盖"""
    print("\n" + "=" * 80)
    print("测试ticker不匹配时正确忽略")
    print("=" * 80)
    
    messages = [
        {
            "domID": "post_004",
            "content": "BA - $240 CALLS EXPIRATION 2月13 $2.8",
            "timestamp": "Jan 23, 2026 12:50 AM",
            "refer": None,
            "position": "single",
            "history": []
        },
        {
            "domID": "post_005",
            "content": "TSLA 440c 2/9 3.1",
            "timestamp": "Jan 23, 2026 12:51 AM",
            "refer": None,
            "position": "single",
            "history": []
        },
        {
            "domID": "post_006",
            "content": "止损提高到3.2 tsla期权今天也是日内的",  # TSLA ticker，应该跳过BA
            "timestamp": "Jan 23, 2026 12:52 AM",
            "refer": None,
            "position": "single",
            "history": []
        }
    ]
    
    resolver = MessageContextResolver(all_messages=messages)
    
    # 解析第3条消息（有tsla ticker）
    result = resolver.resolve_instruction(messages[2])
    
    if result:
        instruction, context_source, context_message = result
        print(f"\n✅ 解析成功")
        print(f"   股票代码: {instruction.ticker}")
        print(f"   行权价: ${instruction.strike}")
        print(f"   上下文来源: {context_source}")
        print(f"   上下文消息: {context_message}")
        
        # 验证：应该找到TSLA而不是BA
        assert instruction.ticker == "TSLA", f"期望 TSLA，得到 {instruction.ticker}"
        assert instruction.strike == 440, f"期望 440（TSLA），得到 {instruction.strike}"
        # 应该从前5条找到TSLA，跳过BA
        assert context_source == "前5条"
        print("\n✓ 正确跳过BA，找到TSLA")
    else:
        print("\n❌ 解析失败")
        raise AssertionError("解析失败")


def main():
    """运行所有测试"""
    print("\n" + "=" * 80)
    print("MODIFY指令ticker提取和匹配测试")
    print("=" * 80)
    
    try:
        test_modify_with_ticker()
        test_modify_wrong_ticker()
        
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
