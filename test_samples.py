#!/usr/bin/env python3
"""
测试样本管理功能
验证样本收集、分类和解析器的准确性
"""
from parser.option_parser import OptionParser
from samples.sample_manager import SampleManager, SampleCategory


def test_parser_with_samples():
    """使用样本测试解析器"""
    print("=" * 60)
    print("测试解析器准确性")
    print("=" * 60)
    
    # 测试消息
    test_cases = [
        ("INTC - $48 CALLS 本周 $1.2", True, SampleCategory.OPEN.value),
        ("小仓位  止损 0.95", True, SampleCategory.STOP_LOSS.value),
        ("1.75出三分之一", True, SampleCategory.TAKE_PROFIT.value),
        ("止损提高到1.5", True, SampleCategory.ADJUST.value),
        ("1.65附近出剩下三分之二", True, SampleCategory.TAKE_PROFIT.value),
        ("AAPL $150 PUTS 1/31 $2.5", True, SampleCategory.OPEN.value),
        ("TSLA - 250 CALL $3.0 小仓位", True, SampleCategory.OPEN.value),
        ("2.0 出一半", True, SampleCategory.TAKE_PROFIT.value),
        ("止损调整到 1.8", True, SampleCategory.ADJUST.value),
        ("全部出", False, SampleCategory.UNKNOWN.value),  # 当前不支持
        ("NVDA 800/810 call debit spread 本周 $3.5", False, SampleCategory.UNKNOWN.value),  # 价差策略
    ]
    
    total = len(test_cases)
    passed = 0
    failed = []
    
    for message, should_parse, expected_category in test_cases:
        instruction = OptionParser.parse(message)
        
        if should_parse:
            if instruction:
                passed += 1
                print(f"✓ 解析成功: {message[:40]}...")
                print(f"  结果: {instruction}")
            else:
                failed.append((message, "应该解析但失败"))
                print(f"✗ 解析失败: {message[:40]}...")
        else:
            if not instruction:
                passed += 1
                print(f"✓ 正确识别为无法解析: {message[:40]}...")
            else:
                failed.append((message, "不应该解析但成功了"))
                print(f"✗ 错误解析: {message[:40]}...")
        
        print()
    
    print("=" * 60)
    print(f"测试结果: {passed}/{total} 通过 ({passed/total*100:.1f}%)")
    
    if failed:
        print(f"\n失败的测试用例 ({len(failed)}):")
        for msg, reason in failed:
            print(f"  - {msg}")
            print(f"    原因: {reason}")
    
    print("=" * 60)


def test_sample_manager():
    """测试样本管理器功能"""
    print("\n" + "=" * 60)
    print("测试样本管理器")
    print("=" * 60)
    
    manager = SampleManager("samples/test_samples.json")
    
    # 添加测试样本
    print("\n1. 添加样本...")
    manager.add_parsed_sample(
        message="测试 - $100 CALLS $1.0",
        category=SampleCategory.OPEN.value,
        parsed_result={"ticker": "测试", "price": 1.0},
        notes="测试样本"
    )
    
    manager.add_unparsed_sample(
        message="无法解析的消息",
        notes="测试未解析样本"
    )
    
    # 查询样本
    print("\n2. 查询样本...")
    print(f"   总样本数: {len(manager.samples)}")
    print(f"   已解析: {len(manager.get_parsed_samples())}")
    print(f"   未解析: {len(manager.get_unparsed_samples())}")
    
    # 生成报告
    print("\n3. 生成报告...")
    print(manager.generate_report())
    
    # 清理测试文件
    import os
    if os.path.exists("samples/test_samples.json"):
        os.remove("samples/test_samples.json")
        print("\n✓ 测试完成，已清理测试文件")
    
    print("=" * 60)


if __name__ == "__main__":
    test_parser_with_samples()
    test_sample_manager()
    
    print("\n" + "=" * 60)
    print("所有测试完成")
    print("=" * 60)
    print("\n提示：")
    print("- 如果发现解析失败的用例，可以在 parser/option_parser.py 中改进正则")
    print("- 运行 'python3 setup_samples.py' 初始化样本数据库")
    print("- 运行 'python3 -m samples.sample_manager list' 查看所有样本")
