#!/usr/bin/env python3
"""
初始化样本数据库
从 initial_samples.json 导入初始样本
"""
import json
import os
from samples.sample_manager import SampleManager


def setup_initial_samples():
    """设置初始样本"""
    print("=" * 60)
    print("初始化样本数据库")
    print("=" * 60)
    
    # 检查是否已有样本
    if os.path.exists("samples/samples.json"):
        response = input("\n样本数据库已存在，是否覆盖？(y/N): ")
        if response.lower() != 'y':
            print("已取消")
            return
        os.remove("samples/samples.json")
    
    # 加载初始样本
    initial_samples_path = "samples/initial_samples.json"
    if not os.path.exists(initial_samples_path):
        print(f"错误: 找不到 {initial_samples_path}")
        return
    
    with open(initial_samples_path, "r", encoding="utf-8") as f:
        initial_data = json.load(f)
    
    # 创建样本管理器并导入
    manager = SampleManager()
    
    print(f"\n正在导入 {len(initial_data)} 个初始样本...")
    
    for item in initial_data:
        manager.add_sample(
            message=item["message"],
            category=item["category"],
            notes=item["notes"],
            parsed_successfully=item["parsed_successfully"],
            parsed_result=item.get("parsed_result")
        )
    
    print(f"\n✓ 成功导入 {len(initial_data)} 个样本")
    
    # 显示统计
    print(manager.generate_report())
    
    print("\n可以使用以下命令管理样本：")
    print("  python3 -m samples.sample_manager list")
    print("  python3 -m samples.sample_manager report")
    print("  python3 -m samples.sample_manager list --unparsed")


if __name__ == "__main__":
    setup_initial_samples()
