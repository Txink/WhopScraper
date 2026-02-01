#!/usr/bin/env python3
"""
交互式测试运行器
提供菜单选择，自动运行指定的测试项
"""
import sys
import subprocess
import os
from typing import List, Dict

# 定义所有测试项
TEST_ITEMS = {
    "1": {
        "name": "配置加载测试",
        "description": "测试 .env 配置文件加载和验证",
        "module": "test.test_config",
        "tags": ["config", "快速"]
    },
    "2": {
        "name": "LongPort 接口集成测试",
        "description": "测试 LongPort API 连接、账户信息、下单功能",
        "module": "test.broker.test_longport_integration",
        "tags": ["broker", "api", "中等"]
    },
    "3": {
        "name": "持仓管理测试",
        "description": "测试持仓的增删改查和持久化",
        "module": "test.broker.test_position_management",
        "tags": ["broker", "快速"]
    },
    "4": {
        "name": "期权解析器测试",
        "description": "测试期权消息解析功能",
        "module": "test.parser.test_option_parser",
        "tags": ["parser", "快速"]
    },
    "5": {
        "name": "正股解析器测试",
        "description": "测试正股消息解析功能",
        "module": "test.parser.test_stock_parser",
        "tags": ["parser", "快速"]
    },
    "6": {
        "name": "期权过期检查测试",
        "description": "测试期权到期日期校验",
        "module": "test.parser.test_option_expiry",
        "tags": ["parser", "快速"]
    },
    "7": {
        "name": "期权过期集成测试",
        "description": "测试期权过期检查的完整流程",
        "module": "test.parser.test_expiry_integration",
        "tags": ["parser", "integration", "快速"]
    },
    "8": {
        "name": "解析器覆盖率测试",
        "description": "测试所有解析器的样本覆盖率",
        "module": "test.parser.test_parser_coverage",
        "tags": ["parser", "快速"]
    },
    "9": {
        "name": "样本管理测试",
        "description": "测试样本收集和管理功能",
        "module": "test.test_samples",
        "tags": ["samples", "快速"]
    },
}


def print_header():
    """打印欢迎标题"""
    print("\n" + "="*70)
    print("🧪 交易系统测试运行器")
    print("="*70)


def print_menu():
    """打印测试菜单"""
    print("\n可用测试项：\n")
    
    # 按类别分组
    categories = {
        "配置测试": [],
        "Broker 测试": [],
        "解析器测试": [],
        "其他测试": []
    }
    
    for key, test in TEST_ITEMS.items():
        if "config" in test["tags"]:
            categories["配置测试"].append((key, test))
        elif "broker" in test["tags"]:
            categories["Broker 测试"].append((key, test))
        elif "parser" in test["tags"]:
            categories["解析器测试"].append((key, test))
        else:
            categories["其他测试"].append((key, test))
    
    for category, items in categories.items():
        if items:
            print(f"  📁 {category}")
            for key, test in items:
                duration = "⚡" if "快速" in test["tags"] else "🕐"
                print(f"    [{key}] {duration} {test['name']}")
                print(f"        └─ {test['description']}")
            print()
    
    print("  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  [a] 🚀 运行所有测试")
    print("  [b] 🎯 按类别运行")
    print("  [q] 👋 退出")
    print("  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")


def print_category_menu():
    """打印类别菜单"""
    print("\n选择测试类别：\n")
    print("  [1] 配置测试")
    print("  [2] Broker 测试")
    print("  [3] 解析器测试")
    print("  [4] 其他测试")
    print("  [b] 返回主菜单")


def run_test(module: str, name: str) -> bool:
    """运行单个测试"""
    print(f"\n{'='*70}")
    print(f"🧪 运行测试: {name}")
    print(f"{'='*70}\n")
    
    try:
        # 确保在项目根目录运行
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        # 运行测试
        result = subprocess.run(
            [sys.executable, "-m", module],
            cwd=project_root,
            capture_output=False,
            text=True
        )
        
        if result.returncode == 0:
            print(f"\n✅ {name} - 通过")
            return True
        else:
            print(f"\n❌ {name} - 失败 (退出码: {result.returncode})")
            return False
            
    except Exception as e:
        print(f"\n❌ {name} - 错误: {e}")
        return False


def run_tests_by_keys(keys: List[str]):
    """运行指定的测试"""
    results = []
    for key in keys:
        if key in TEST_ITEMS:
            test = TEST_ITEMS[key]
            success = run_test(test["module"], test["name"])
            results.append((test["name"], success))
    
    # 打印总结
    print("\n" + "="*70)
    print("📊 测试结果总结")
    print("="*70)
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for name, success in results:
        status = "✅ 通过" if success else "❌ 失败"
        print(f"  {status} - {name}")
    
    print(f"\n总计: {passed}/{total} 通过")
    print("="*70 + "\n")


def run_all_tests():
    """运行所有测试"""
    keys = sorted(TEST_ITEMS.keys())
    run_tests_by_keys(keys)


def run_tests_by_category(category: str):
    """按类别运行测试"""
    category_map = {
        "1": "config",
        "2": "broker",
        "3": "parser",
        "4": "samples"
    }
    
    tag = category_map.get(category)
    if not tag:
        return
    
    keys = [key for key, test in TEST_ITEMS.items() if tag in test["tags"]]
    
    if keys:
        run_tests_by_keys(keys)
    else:
        print(f"\n❌ 未找到该类别的测试")


def run_multiple_tests():
    """运行多个选定的测试"""
    print("\n输入要运行的测试编号，用空格或逗号分隔（例如: 1 2 3 或 1,2,3）")
    choice = input("请选择: ").strip()
    
    # 解析输入
    if not choice:
        return
    
    # 支持空格或逗号分隔
    keys = choice.replace(",", " ").split()
    
    # 验证输入
    valid_keys = [k for k in keys if k in TEST_ITEMS]
    invalid_keys = [k for k in keys if k not in TEST_ITEMS]
    
    if invalid_keys:
        print(f"\n⚠️  忽略无效选项: {', '.join(invalid_keys)}")
    
    if valid_keys:
        run_tests_by_keys(valid_keys)
    else:
        print("\n❌ 未选择有效的测试项")


def main():
    """主函数"""
    print_header()
    
    while True:
        print_menu()
        choice = input("\n请选择测试项 (输入编号或选项): ").strip().lower()
        
        if choice == "q":
            print("\n👋 再见！\n")
            break
        elif choice == "a":
            run_all_tests()
        elif choice == "b":
            print_category_menu()
            cat_choice = input("\n请选择类别: ").strip()
            if cat_choice == "b":
                continue
            run_tests_by_category(cat_choice)
        elif choice == "m":
            run_multiple_tests()
        elif choice in TEST_ITEMS:
            test = TEST_ITEMS[choice]
            run_test(test["module"], test["name"])
        elif " " in choice or "," in choice:
            # 直接输入多个编号
            keys = choice.replace(",", " ").split()
            valid_keys = [k for k in keys if k in TEST_ITEMS]
            if valid_keys:
                run_tests_by_keys(valid_keys)
            else:
                print("\n❌ 无效的选项，请重新选择")
        else:
            print("\n❌ 无效的选项，请重新选择")
        
        # 询问是否继续
        continue_choice = input("\n按 Enter 继续，或输入 q 退出: ").strip().lower()
        if continue_choice == "q":
            print("\n👋 再见！\n")
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 测试已取消\n")
        sys.exit(0)
