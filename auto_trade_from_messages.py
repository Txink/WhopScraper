#!/usr/bin/env python3
"""
从消息文件自动交易脚本
读取HTML消息文件 → 解析指令 → 自动执行交易
"""
import asyncio
import os
import sys
from datetime import datetime
from glob import glob

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.async_api import async_playwright
from broker import LongPortBroker, load_longport_config, AutoTrader
from scraper.message_extractor import EnhancedMessageExtractor
from parser.message_context_resolver import MessageContextResolver
from broker.order_formatter import print_info_message, print_success_message, print_warning_message


async def auto_trade_from_html(html_file: str, dry_run: bool = True, require_confirm: bool = True):
    """
    从HTML文件自动交易
    
    Args:
        html_file: HTML文件路径
        dry_run: 是否仅模拟（不实际下单）
        require_confirm: 是否需要确认
    """
    print("\n" + "=" * 80)
    print("从消息文件自动交易")
    print("=" * 80 + "\n")
    
    # 检查文件是否存在
    if not os.path.exists(html_file):
        print(f"❌ 文件不存在: {html_file}")
        return
    
    print(f"📄 源文件: {html_file}")
    file_size = os.path.getsize(html_file) / 1024 / 1024
    print(f"📊 文件大小: {file_size:.2f} MB")
    print(f"🧪 Dry Run: {dry_run}")
    print(f"✋ 需要确认: {require_confirm}\n")
    
    # ========================================
    # 第1步：提取消息
    # ========================================
    print_info_message("第1步：提取消息")
    print("-" * 80)
    
    try:
        with open(html_file, 'r', encoding='utf-8') as f:
            html_content = f.read()
        print(f"✅ 已读取 {len(html_content):,} 字符")
    except Exception as e:
        print(f"❌ 读取文件失败: {e}")
        return
    
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.set_content(html_content)
            
            extractor = EnhancedMessageExtractor(page)
            raw_groups = await extractor.extract_message_groups()
            
            print(f"✅ 成功提取 {len(raw_groups)} 条原始消息\n")
            
            await browser.close()
            
            if not raw_groups:
                print("⚠️  未提取到任何消息")
                return
            
        except Exception as e:
            print(f"❌ 消息提取失败: {e}")
            if 'browser' in locals():
                await browser.close()
            return
    
    # ========================================
    # 第2步：解析指令
    # ========================================
    print_info_message("第2步：解析指令")
    print("-" * 80)
    
    # 转换为简化格式
    import re
    all_messages_simple = []
    for group in raw_groups:
        simple_dict = group.to_simple_dict()
        content = simple_dict['content'].strip()
        
        # 清理消息内容
        content_clean = content
        content_clean = re.sub(r'^\[引用\]\s*', '', content_clean)
        content_clean = re.sub(r'^[\w]+•[A-Z][a-z]{2,9}\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2}\s+[AP]M\s*', '', content_clean)
        content_clean = re.sub(r'^[XxＸｘ]+', '', content_clean)
        content_clean = re.sub(r'^•?\s*[A-Z][a-z]+\s+\d{1,2}:\d{2}\s+[AP]M\s*', '', content_clean)
        content_clean = content_clean.strip()
        
        simple_dict['content'] = content_clean
        all_messages_simple.append(simple_dict)
    
    # 创建上下文解析器
    resolver = MessageContextResolver(all_messages_simple)
    
    # 解析所有消息
    instructions = []
    for simple_dict in all_messages_simple:
        content = simple_dict['content']
        
        # 过滤纯元数据消息
        if not content or len(content) < 5:
            continue
        
        # 使用上下文解析器
        result = resolver.resolve_instruction(simple_dict)
        
        if result:
            instruction, context_source, context_message = result
            if instruction:
                instructions.append(instruction)
    
    print(f"✅ 成功解析 {len(instructions)} 条有效指令")
    
    # 按指令类型统计
    from collections import Counter
    type_counts = Counter(inst.instruction_type for inst in instructions)
    print(f"\n指令类型分布:")
    for inst_type, count in type_counts.items():
        print(f"  {inst_type}: {count} 条")
    print()
    
    if not instructions:
        print("⚠️  未解析到任何有效指令")
        return
    
    # ========================================
    # 第3步：初始化交易器
    # ========================================
    print_info_message("第3步：初始化交易器")
    print("-" * 80)
    
    try:
        # 设置环境变量
        if dry_run:
            os.environ['LONGPORT_DRY_RUN'] = 'true'
        if require_confirm:
            os.environ['REQUIRE_CONFIRMATION'] = 'true'
        else:
            os.environ['REQUIRE_CONFIRMATION'] = 'false'
        
        config = load_longport_config()
        broker = LongPortBroker(config)
        trader = AutoTrader(broker)
        
        mode = "模拟" if broker.is_paper else "真实"
        print(f"✅ 交易器初始化完成")
        print(f"   账户模式: {mode}")
        print(f"   Dry Run: {broker.dry_run}")
        print(f"   自动交易: {broker.auto_trade}")
        print()
        
    except Exception as e:
        print(f"❌ 交易器初始化失败: {e}")
        return
    
    # ========================================
    # 第4步：执行交易
    # ========================================
    print_info_message("第4步：执行交易")
    print("-" * 80)
    print(f"共 {len(instructions)} 条指令待执行\n")
    
    # 如果需要全局确认
    if not dry_run and require_confirm:
        print_warning_message("⚠️  即将执行真实交易！")
        print_warning_message(f"   指令数量: {len(instructions)}")
        print_warning_message(f"   账户模式: {mode}")
        print_warning_message("-" * 80)
        
        confirm = input("确认开始执行? (yes/no): ").strip().lower()
        if confirm not in ('yes', 'y'):
            print_info_message("已取消执行")
            return
        print()
    
    # 批量执行
    try:
        results = trader.execute_batch_instructions(instructions)
    except Exception as e:
        print(f"❌ 批量执行失败: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # ========================================
    # 第5步：统计结果
    # ========================================
    print("\n" + "=" * 80)
    print_info_message("第5步：执行统计")
    print("=" * 80 + "\n")
    
    success_count = sum(1 for r in results if r is not None)
    failed_count = len(results) - success_count
    
    print(f"总指令数: {len(results)}")
    print(f"成功执行: {success_count}")
    print(f"执行失败: {failed_count}")
    print(f"成功率: {success_count/len(results)*100:.1f}%")
    
    # 按类型统计成功率
    type_stats = {}
    for i, inst in enumerate(instructions):
        inst_type = inst.instruction_type
        if inst_type not in type_stats:
            type_stats[inst_type] = {'total': 0, 'success': 0}
        type_stats[inst_type]['total'] += 1
        if results[i] is not None:
            type_stats[inst_type]['success'] += 1
    
    print(f"\n按类型统计:")
    for inst_type, stats in type_stats.items():
        success_rate = stats['success'] / stats['total'] * 100 if stats['total'] > 0 else 0
        print(f"  {inst_type}: {stats['success']}/{stats['total']} ({success_rate:.1f}%)")
    
    print("\n" + "=" * 80)
    print_success_message("执行完成！")
    print("=" * 80 + "\n")


def select_html_file():
    """选择要处理的HTML文件"""
    html_files = glob("debug/page_*.html")
    
    if not html_files:
        print("❌ 未找到HTML文件")
        print("\n💡 提示: 请先运行以下命令导出HTML:")
        print("   python3 main.py --test export-dom\n")
        return None
    
    # 按修改时间排序，最新的在前
    html_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    
    print(f"\n📁 找到 {len(html_files)} 个HTML文件:\n")
    for i, file in enumerate(html_files[:10], 1):
        mtime = os.path.getmtime(file)
        time_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        size_mb = os.path.getsize(file) / 1024 / 1024
        print(f"   {i}. {os.path.basename(file)}")
        print(f"      时间: {time_str}, 大小: {size_mb:.2f} MB")
    
    if len(html_files) > 10:
        print(f"\n   ... 还有 {len(html_files) - 10} 个文件")
    
    # 选择文件
    print("\n请选择要分析的文件 (输入序号，默认=1): ", end='')
    choice = input().strip()
    
    if not choice:
        choice = "1"
    
    try:
        index = int(choice) - 1
        if index < 0 or index >= len(html_files):
            print("❌ 无效的选择")
            return None
        return html_files[index]
    except ValueError:
        print("❌ 无效的输入")
        return None


def main():
    """主函数"""
    print("\n" + "=" * 80)
    print("从消息文件自动交易工具")
    print("=" * 80)
    
    # 解析命令行参数
    import argparse
    parser = argparse.ArgumentParser(description='从HTML消息文件自动交易')
    parser.add_argument('html_file', nargs='?', help='HTML文件路径（可选，不指定则交互选择）')
    parser.add_argument('--real', action='store_true', help='真实执行（默认为dry_run）')
    parser.add_argument('--no-confirm', action='store_true', help='跳过确认（谨慎使用！）')
    
    args = parser.parse_args()
    
    # 选择文件
    if args.html_file:
        html_file = args.html_file
        if not os.path.exists(html_file):
            print(f"❌ 文件不存在: {html_file}")
            return
    else:
        html_file = select_html_file()
        if not html_file:
            return
    
    # 确定运行模式
    dry_run = not args.real
    require_confirm = not args.no_confirm
    
    # 安全提示
    if not dry_run:
        print("\n" + "⚠️ " * 20)
        print("⚠️  警告：您正在使用真实交易模式！")
        print("⚠️  所有订单将提交到交易所！")
        print("⚠️ " * 20)
        
        confirm = input("\n确认继续? (输入 YES 继续): ").strip()
        if confirm != "YES":
            print("已取消")
            return
    
    # 执行自动交易
    asyncio.run(auto_trade_from_html(html_file, dry_run=dry_run, require_confirm=require_confirm))


if __name__ == "__main__":
    main()
