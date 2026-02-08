#!/usr/bin/env python3
"""
测试 CONTEXT_SEARCH_LIMIT 环境变量配置
"""
import os
from parser.message_context_resolver import MessageContextResolver
from models.instruction import InstructionType


def test_default_limit():
    """测试默认配置（5条）"""
    print("\n" + "=" * 80)
    print("测试默认配置（未设置环境变量）")
    print("=" * 80)
    
    # 确保环境变量未设置
    if 'CONTEXT_SEARCH_LIMIT' in os.environ:
        del os.environ['CONTEXT_SEARCH_LIMIT']
    
    messages = [{"domID": "test_1", "content": "test", "timestamp": None, "refer": None, "position": "single", "history": []}]
    resolver = MessageContextResolver(all_messages=messages)
    
    print(f"默认 context_search_limit: {resolver.context_search_limit}")
    assert resolver.context_search_limit == 5, f"期望默认值为5，得到 {resolver.context_search_limit}"
    print("✓ 默认值测试通过")


def test_custom_limit():
    """测试自定义配置"""
    print("\n" + "=" * 80)
    print("测试自定义配置（设置为10）")
    print("=" * 80)
    
    # 设置环境变量
    os.environ['CONTEXT_SEARCH_LIMIT'] = '10'
    
    messages = [{"domID": "test_1", "content": "test", "timestamp": None, "refer": None, "position": "single", "history": []}]
    resolver = MessageContextResolver(all_messages=messages)
    
    print(f"自定义 context_search_limit: {resolver.context_search_limit}")
    assert resolver.context_search_limit == 10, f"期望配置值为10，得到 {resolver.context_search_limit}"
    print("✓ 自定义配置测试通过")


def test_context_source_display():
    """测试上下文来源显示"""
    print("\n" + "=" * 80)
    print("测试上下文来源动态显示")
    print("=" * 80)
    
    # 设置为3条
    os.environ['CONTEXT_SEARCH_LIMIT'] = '3'
    
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
            "content": "止损在2.5",
            "timestamp": "Jan 23, 2026 12:51 AM",
            "refer": None,
            "position": "single",
            "history": []
        }
    ]
    
    resolver = MessageContextResolver(all_messages=messages)
    
    print(f"配置 context_search_limit: {resolver.context_search_limit}")
    
    # 解析第2条消息
    result = resolver.resolve_instruction(messages[1])
    
    if result:
        instruction, context_source, context_message = result
        print(f"解析成功:")
        print(f"  ticker: {instruction.ticker}")
        print(f"  stop_loss: {instruction.stop_loss_price}")
        print(f"  上下文来源: {context_source}")
        
        # 验证上下文来源应该显示"前3条"
        assert context_source == "前3条", f"期望 '前3条'，得到 '{context_source}'"
        print("✓ 上下文来源显示正确")
    else:
        print("解析失败")


def test_different_limits():
    """测试不同的limit值"""
    print("\n" + "=" * 80)
    print("测试不同的limit配置值")
    print("=" * 80)
    
    test_cases = [
        ("1", 1),
        ("3", 3),
        ("5", 5),
        ("10", 10),
        ("20", 20),
    ]
    
    for env_value, expected_value in test_cases:
        os.environ['CONTEXT_SEARCH_LIMIT'] = env_value
        messages = [{"domID": "test_1", "content": "test", "timestamp": None, "refer": None, "position": "single", "history": []}]
        resolver = MessageContextResolver(all_messages=messages)
        
        print(f"CONTEXT_SEARCH_LIMIT={env_value} -> context_search_limit={resolver.context_search_limit}")
        assert resolver.context_search_limit == expected_value
    
    print("✓ 所有配置值测试通过")


def main():
    """运行所有测试"""
    print("\n" + "=" * 80)
    print("CONTEXT_SEARCH_LIMIT 配置测试")
    print("=" * 80)
    
    try:
        test_default_limit()
        test_custom_limit()
        test_context_source_display()
        test_different_limits()
        
        print("\n" + "=" * 80)
        print("✅ 所有测试通过！")
        print("=" * 80 + "\n")
    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}\n")
    except Exception as e:
        print(f"\n❌ 测试出错: {e}\n")
        import traceback
        traceback.print_exc()
    finally:
        # 清理环境变量
        if 'CONTEXT_SEARCH_LIMIT' in os.environ:
            del os.environ['CONTEXT_SEARCH_LIMIT']


if __name__ == "__main__":
    main()
