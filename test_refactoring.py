#!/usr/bin/env python3
"""
重构功能单元测试
快速验证核心模块是否正常工作
"""
import sys

def test_message_filter():
    """测试消息过滤器"""
    print("\n=== 测试 MessageFilter ===")
    from scraper.message_filter import MessageFilter
    
    # 测试1: 过滤阅读量
    assert MessageFilter.should_filter_text("由 268阅读") == True
    assert MessageFilter.should_filter_text("268阅读") == True
    print("✅ 阅读量过滤正常")
    
    # 测试2: 过滤编辑标记
    assert MessageFilter.should_filter_text("已编辑") == True
    assert MessageFilter.should_filter_text("Edited") == True
    print("✅ 编辑标记过滤正常")
    
    # 测试3: 过滤时间戳行
    assert MessageFilter.should_filter_text("•Wednesday 11:04 PM") == True
    print("✅ 时间戳行过滤正常")
    
    # 测试4: 保留有效内容
    assert MessageFilter.should_filter_text("小仓位 止损 在 1.3") == False
    assert MessageFilter.should_filter_text("GILD - $130 CALLS") == False
    print("✅ 有效内容保留正常")
    
    # 测试5: 作者名验证
    assert MessageFilter.is_valid_author_text("xiaozhaolucky") == True
    assert MessageFilter.is_valid_author_text("Jan 22, 2026 10:41 PM") == False
    assert MessageFilter.is_valid_author_text("Tail") == False
    print("✅ 作者名验证正常")
    
    # 测试6: 文本清理
    cleaned = MessageFilter.clean_text("小仓位 止损 在 1.3Tail")
    assert cleaned == "小仓位 止损 在 1.3"
    print("✅ 文本清理正常")
    
    print("✅✅✅ MessageFilter 所有测试通过！\n")


def test_quote_matcher():
    """测试引用匹配器"""
    print("=== 测试 QuoteMatcher ===")
    from scraper.quote_matcher import QuoteMatcher
    
    # 测试1: 清理引用文本
    quote1 = "xiaozhaoluckyGILD - $130 CALLS 这周 1.5-1.60"
    clean1 = QuoteMatcher.clean_quote_text(quote1)
    assert "GILD" in clean1
    assert "xiaozhaolucky" not in clean1
    print(f"✅ 引用清理: {quote1[:30]}... -> {clean1[:30]}...")
    
    # 测试2: 提取关键信息
    text = "GILD - $130 CALLS 这周 1.5-1.60"
    info = QuoteMatcher.extract_key_info(text)
    assert 'GILD' in info['symbols']
    assert '130' in info['prices'] or '$130' in info['prices']
    assert 'BUY' in info['actions']
    print(f"✅ 关键信息提取: symbols={info['symbols']}, prices={info['prices'][:3]}")
    
    # 测试3: 相似度计算
    quote = "GILD - $130 CALLS 这周 1.5-1.60"
    candidate1 = "GILD - $130 CALLS 这周 1.5-1.60"
    candidate2 = "小仓位 止损 在 1.3"
    candidate3 = "NVDA 190c 本周"
    
    sim1 = QuoteMatcher.calculate_similarity(quote, candidate1)
    sim2 = QuoteMatcher.calculate_similarity(quote, candidate2)
    sim3 = QuoteMatcher.calculate_similarity(quote, candidate3)
    
    assert sim1 > 0.8  # 完全匹配应该很高
    assert sim1 > sim2  # 相关性应该更高
    assert sim1 > sim3  # 不同股票应该更低
    print(f"✅ 相似度计算: 完全匹配={sim1:.2f}, 部分相关={sim2:.2f}, 不同股票={sim3:.2f}")
    
    # 测试4: 最佳匹配
    candidates = [
        {'content': "GILD - $130 CALLS 这周 1.5-1.60", 'id': '1'},
        {'content': "小仓位 止损 在 1.3", 'id': '2'},
        {'content': "NVDA 190c 本周", 'id': '3'},
    ]
    best = QuoteMatcher.find_best_match("GILD - $130 CALLS", candidates, min_score=0.3)
    assert best is not None
    assert best['id'] == '1'
    print(f"✅ 最佳匹配: 找到ID={best['id']}")
    
    print("✅✅✅ QuoteMatcher 所有测试通过！\n")


def test_dom_structure_helper():
    """测试DOM结构辅助类"""
    print("=== 测试 DOMStructureHelper ===")
    from scraper.message_filter import DOMStructureHelper
    
    # 验证选择器配置
    assert '.group\\/message' in DOMStructureHelper.MESSAGE_CONTAINER_SELECTORS
    assert '.fui-AvatarRoot' in DOMStructureHelper.AVATAR_SELECTORS
    assert '.peer\\/reply' in DOMStructureHelper.QUOTE_SELECTORS[0]
    print("✅ 选择器配置正确")
    
    # 验证新增的DOM位置判断方法存在
    methods = [
        'is_single_message_group',
        'is_first_in_group', 
        'is_middle_in_group',
        'is_last_in_group',
        'is_message_group_start',
        'is_in_same_group'
    ]
    
    existing_methods = [m for m in methods if hasattr(DOMStructureHelper, m)]
    print(f"✅ 消息组位置判断方法: {len(existing_methods)}/{len(methods)} 个")
    
    # 验证引用选择器包含精确路径
    quote_selectors_str = ' '.join(DOMStructureHelper.QUOTE_SELECTORS)
    assert 'peer/reply' in quote_selectors_str
    print("✅ 引用消息选择器配置正确")
    
    print("✅✅✅ DOMStructureHelper 配置验证通过！\n")


def test_message_group_output():
    """测试MessageGroup输出格式"""
    print("=== 测试 MessageGroup 输出格式 ===")
    from scraper.message_extractor import MessageGroup
    
    # 测试1: 单条消息
    msg = MessageGroup(
        group_id="post_123",
        timestamp="Jan 22, 2026 10:41 PM",
        primary_message="测试消息",
        has_message_above=False,
        has_message_below=False
    )
    assert msg.get_position() == "single"
    print("✅ 单条消息位置判断正确: single")
    
    # 测试2: 第一条消息
    msg.has_message_above = False
    msg.has_message_below = True
    assert msg.get_position() == "first"
    print("✅ 第一条消息位置判断正确: first")
    
    # 测试3: 中间消息
    msg.has_message_above = True
    msg.has_message_below = True
    assert msg.get_position() == "middle"
    print("✅ 中间消息位置判断正确: middle")
    
    # 测试4: 最后一条消息
    msg.has_message_above = True
    msg.has_message_below = False
    assert msg.get_position() == "last"
    print("✅ 最后一条消息位置判断正确: last")
    
    # 测试5: 简化格式输出
    msg_with_refer = MessageGroup(
        group_id="post_456",
        timestamp="Jan 22, 2026 10:41 PM",
        primary_message="小仓位 止损 在 1.3",
        quoted_context="GILD - $130 CALLS 这周 1.5-1.60",
        has_message_above=False,
        has_message_below=True,
        history=[]
    )
    simple = msg_with_refer.to_simple_dict()
    assert simple['domID'] == "post_456"
    assert simple['content'] == "小仓位 止损 在 1.3"
    assert simple['timestamp'] == "Jan 22, 2026 10:41 PM"
    assert simple['refer'] == "GILD - $130 CALLS 这周 1.5-1.60"
    assert simple['position'] == "first"
    assert simple['history'] == []
    print("✅ 简化格式输出正确")
    
    # 测试6: 无引用时refer为None
    simple_no_refer = msg.to_simple_dict()
    assert simple_no_refer['refer'] is None
    print("✅ 无引用时refer为None")
    
    # 测试7: history字段
    msg_with_history = MessageGroup(
        group_id="post_789",
        timestamp="Jan 22, 2026 10:41 PM",
        primary_message="第三条消息",
        has_message_above=True,
        has_message_below=False,
        history=["第一条消息", "第二条消息"]
    )
    simple_with_history = msg_with_history.to_simple_dict()
    assert simple_with_history['history'] == ["第一条消息", "第二条消息"]
    assert simple_with_history['position'] == "last"
    print("✅ history字段正确")
    
    print("✅✅✅ MessageGroup 输出格式测试通过！\n")


def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("🧪 重构功能单元测试")
    print("=" * 60)
    
    try:
        test_message_filter()
        test_quote_matcher()
        test_dom_structure_helper()
        test_message_group_output()
        
        print("\n" + "=" * 60)
        print("🎉 所有测试通过！重构功能正常工作")
        print("=" * 60 + "\n")
        return 0
        
    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"\n❌ 测试错误: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
