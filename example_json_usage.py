#!/usr/bin/env python3
"""
JSON导出文件使用示例
演示如何读取和处理导出的JSON消息文件
"""
import json
import sys
from datetime import datetime


def analyze_json_messages(json_file: str):
    """分析JSON消息文件"""
    
    # 读取JSON文件
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"❌ 文件不存在: {json_file}")
        return
    except json.JSONDecodeError as e:
        print(f"❌ JSON格式错误: {e}")
        return
    
    print("\n" + "=" * 80)
    print("JSON消息文件分析")
    print("=" * 80 + "\n")
    
    # 显示元数据
    metadata = data.get('metadata', {})
    print("📊 文件元数据:")
    print(f"  源文件: {metadata.get('source_file')}")
    print(f"  导出时间: {metadata.get('export_time')}")
    print(f"  总消息数: {metadata.get('total_messages')}")
    print(f"  提取器版本: {metadata.get('extractor_version')}")
    print()
    
    # 获取消息列表
    messages = data.get('messages', [])
    
    # 1. 按position统计
    print("📈 按position统计:")
    position_stats = {}
    for msg in messages:
        pos = msg.get('position', 'unknown')
        position_stats[pos] = position_stats.get(pos, 0) + 1
    
    for pos in ['single', 'first', 'middle', 'last']:
        count = position_stats.get(pos, 0)
        print(f"  {pos:8s}: {count:3d} 条")
    print()
    
    # 2. history统计
    print("📋 history字段统计:")
    with_history = [msg for msg in messages if msg.get('history')]
    total_history_items = sum(len(msg.get('history', [])) for msg in messages)
    
    print(f"  有history的消息: {len(with_history)} 条 ({len(with_history)/len(messages)*100:.1f}%)")
    if with_history:
        avg_history = total_history_items / len(with_history)
        print(f"  平均history长度: {avg_history:.1f} 条")
    print()
    
    # 3. 引用消息统计
    print("🔗 引用消息统计:")
    with_refer = [msg for msg in messages if msg.get('refer')]
    print(f"  有引用的消息: {len(with_refer)} 条 ({len(with_refer)/len(messages)*100:.1f}%)")
    print()
    
    # 4. 时间分布分析
    print("⏰ 时间分布分析:")
    date_stats = {}
    for msg in messages:
        ts = msg.get('timestamp', '')
        if ts:
            try:
                # 解析时间戳
                dt = datetime.strptime(ts, '%b %d, %Y %I:%M %p')
                date_key = dt.strftime('%Y-%m-%d')
                date_stats[date_key] = date_stats.get(date_key, 0) + 1
            except:
                pass
    
    for date in sorted(date_stats.keys())[:10]:  # 显示前10天
        count = date_stats[date]
        print(f"  {date}: {count:3d} 条消息")
    
    if len(date_stats) > 10:
        print(f"  ... 还有 {len(date_stats) - 10} 天的数据")
    print()
    
    # 5. 示例消息展示
    print("💬 示例消息展示:")
    print("-" * 80)
    
    # 显示前3条消息
    for i, msg in enumerate(messages[:3], 1):
        print(f"\n{i}. {msg.get('position'):8s} | domID: {msg.get('domID', 'N/A')[:30]}...")
        print(f"   时间: {msg.get('timestamp', 'N/A')}")
        print(f"   内容: {msg.get('content', '')[:60]}...")
        
        if msg.get('refer'):
            print(f"   引用: {msg.get('refer')[:60]}...")
        
        history = msg.get('history', [])
        if history:
            print(f"   history: {len(history)} 条")
            for j, h in enumerate(history[:2], 1):
                print(f"     {j}. {h[:50]}...")
    
    print("\n" + "-" * 80)
    
    # 6. 搜索功能示例
    print("\n🔍 搜索功能示例:")
    search_term = "SPY"
    matching = [msg for msg in messages if search_term in msg.get('content', '')]
    print(f"  包含 '{search_term}' 的消息: {len(matching)} 条")
    
    if matching:
        print(f"\n  示例匹配:")
        for msg in matching[:2]:
            print(f"    - {msg.get('content')[:60]}...")
    print()
    
    # 7. 数据导出示例
    print("📤 数据导出示例:")
    print("  # 导出为CSV")
    print("  import pandas as pd")
    print("  df = pd.DataFrame(messages)")
    print("  df.to_csv('messages.csv', index=False)")
    print()
    print("  # 过滤特定消息")
    print("  spy_messages = [m for m in messages if 'SPY' in m['content']]")
    print("  print(f'SPY消息: {len(spy_messages)} 条')")
    print()


def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("\n使用方法:")
        print(f"  python3 {sys.argv[0]} <JSON文件路径>")
        print("\n示例:")
        print(f"  python3 {sys.argv[0]} debug/page_20260202_000748_messages_20260202_220944.json")
        print()
        return
    
    json_file = sys.argv[1]
    analyze_json_messages(json_file)


if __name__ == "__main__":
    main()
