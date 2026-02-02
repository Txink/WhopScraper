#!/usr/bin/env python3
"""
本地HTML消息分析脚本
直接分析本地HTML文件，使用EnhancedMessageExtractor提取消息并分组
无需启动浏览器连接网页
"""
import asyncio
import os
import sys
from glob import glob
from datetime import datetime
from playwright.async_api import async_playwright


async def analyze_html_messages(html_file: str):
    """
    分析本地HTML文件中的消息
    
    Args:
        html_file: HTML文件路径
    """
    print("\n" + "=" * 80)
    print("本地HTML消息提取分析")
    print("=" * 80 + "\n")
    
    # 检查文件是否存在
    if not os.path.exists(html_file):
        print(f"❌ 文件不存在: {html_file}")
        return
    
    print(f"📄 源文件: {html_file}")
    file_size = os.path.getsize(html_file) / 1024 / 1024
    print(f"📊 文件大小: {file_size:.2f} MB\n")
    
    # 读取HTML文件
    print("📖 正在读取HTML文件...")
    try:
        with open(html_file, 'r', encoding='utf-8') as f:
            html_content = f.read()
        print(f"✅ 已读取 {len(html_content):,} 字符\n")
    except Exception as e:
        print(f"❌ 读取文件失败: {e}")
        return
    
    # 使用playwright加载HTML并提取消息
    print("🚀 正在启动Playwright...")
    async with async_playwright() as p:
        try:
            # 启动浏览器
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            print("✅ Playwright已启动\n")
            
            # 加载HTML内容
            print("📝 正在加载HTML内容...")
            await page.set_content(html_content)
            print("✅ HTML内容已加载\n")
            
            # 使用EnhancedMessageExtractor提取消息
            print("🔍 正在提取消息...")
            from scraper.message_extractor import EnhancedMessageExtractor
            from scraper.message_grouper import MessageGrouper, format_as_table, format_as_detailed_table
            
            extractor = EnhancedMessageExtractor(page)
            raw_groups = await extractor.extract_message_groups()
            
            print(f"✅ 成功提取 {len(raw_groups)} 条原始消息\n")
            
            if not raw_groups:
                print("⚠️  未提取到任何消息")
                print("\n💡 可能的原因:")
                print("   1. HTML文件不完整")
                print("   2. 页面结构已变化")
                print("   3. 选择器需要更新")
                await browser.close()
                return
            
            # 转换为字典格式
            messages = []
            for group in raw_groups:
                message_dict = {
                    'id': group.group_id,
                    'author': group.author,
                    'timestamp': group.timestamp,
                    'content': group.get_full_content(),
                    'primary_message': group.primary_message,
                    'related_messages': group.related_messages,
                    'quoted_message': group.quoted_message,
                    'quoted_context': group.quoted_context,
                    'has_message_above': group.has_message_above,
                    'has_message_below': group.has_message_below
                }
                messages.append(message_dict)
            
            # 使用消息分组器进行交易组聚合（流式处理）
            print("🔄 正在按时间顺序流式处理消息...\n")
            grouper = MessageGrouper()
            trade_groups = grouper.group_messages(messages, stream_output=True)
            
            # 注意：消息已在group_messages中流式输出，无需再调用format_as_rich_panels
            
            # 显示原始消息（前10条）
            print("\n" + "=" * 80)
            print("【原始消息详情】（前10条）")
            print("=" * 80)
            for i, group in enumerate(raw_groups[:10], 1):
                print(f"\n{i}. 消息 ID: {group.group_id}")
                print(f"   作者: {group.author or '(未识别)'}")
                print(f"   时间: {group.timestamp or '(未识别)'}")
                print(f"   DOM: has_above={group.has_message_above}, has_below={group.has_message_below}")
                
                if group.primary_message:
                    print(f"   主消息: {group.primary_message[:80]}...")
                
                if group.related_messages:
                    print(f"   关联消息数: {len(group.related_messages)}")
                    for j, related in enumerate(group.related_messages[:2], 1):
                        print(f"      {j}. {related[:60]}...")
                
                if group.quoted_context:
                    print(f"   引用: {group.quoted_context[:60]}...")
                
                print("-" * 80)
            
            if len(raw_groups) > 10:
                print(f"\n... 还有 {len(raw_groups) - 10} 条消息未显示")
            
            # 统计信息
            print("\n" + "=" * 80)
            print("📊 统计信息")
            print("=" * 80)
            print(f"原始消息数: {len(raw_groups)}")
            print(f"交易组数: {len(trade_groups)}")
            
            # 统计有作者的消息
            with_author = sum(1 for g in raw_groups if g.author)
            print(f"有作者信息: {with_author} ({with_author/len(raw_groups)*100:.1f}%)")
            
            # 统计有时间戳的消息
            with_timestamp = sum(1 for g in raw_groups if g.timestamp)
            print(f"有时间戳: {with_timestamp} ({with_timestamp/len(raw_groups)*100:.1f}%)")
            
            # 统计有引用的消息
            with_quote = sum(1 for g in raw_groups if g.quoted_context)
            print(f"有引用内容: {with_quote} ({with_quote/len(raw_groups)*100:.1f}%)")
            
            print("=" * 80)
            
            # 生成分析报告
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_file = f"debug/message_analysis_{timestamp}.txt"
            
            print(f"\n💾 正在保存详细报告...")
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write("=" * 80 + "\n")
                f.write("本地HTML消息提取分析报告\n")
                f.write("=" * 80 + "\n\n")
                f.write(f"源文件: {html_file}\n")
                f.write(f"分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"文件大小: {file_size:.2f} MB\n\n")
                
                f.write("=" * 80 + "\n")
                f.write("统计信息\n")
                f.write("=" * 80 + "\n\n")
                f.write(f"原始消息数: {len(raw_groups)}\n")
                f.write(f"交易组数: {len(trade_groups)}\n")
                f.write(f"有作者信息: {with_author} ({with_author/len(raw_groups)*100:.1f}%)\n")
                f.write(f"有时间戳: {with_timestamp} ({with_timestamp/len(raw_groups)*100:.1f}%)\n")
                f.write(f"有引用内容: {with_quote} ({with_quote/len(raw_groups)*100:.1f}%)\n\n")
                
                f.write("=" * 80 + "\n")
                f.write("详细表格视图\n")
                f.write("=" * 80 + "\n\n")
                f.write(format_as_detailed_table(trade_groups))
                
                f.write("\n\n" + "=" * 80 + "\n")
                f.write("分组摘要视图\n")
                f.write("=" * 80 + "\n\n")
                f.write(format_as_table(trade_groups))
                
                f.write("\n\n" + "=" * 80 + "\n")
                f.write("所有原始消息\n")
                f.write("=" * 80 + "\n\n")
                
                for i, group in enumerate(raw_groups, 1):
                    f.write(f"\n{i}. 消息 ID: {group.group_id}\n")
                    f.write(f"   作者: {group.author or '(未识别)'}\n")
                    f.write(f"   时间: {group.timestamp or '(未识别)'}\n")
                    
                    if group.primary_message:
                        f.write(f"   主消息: {group.primary_message}\n")
                    
                    if group.related_messages:
                        f.write(f"   关联消息:\n")
                        for j, related in enumerate(group.related_messages, 1):
                            f.write(f"      {j}. {related}\n")
                    
                    if group.quoted_context:
                        f.write(f"   引用: {group.quoted_context}\n")
                    
                    full_content = group.get_full_content()
                    f.write(f"\n   完整内容:\n")
                    for line in full_content.split('\n'):
                        f.write(f"      {line}\n")
                    
                    f.write("\n" + "-" * 80 + "\n")
            
            print(f"✅ 详细报告已保存到: {report_file}\n")
            
            print("=" * 80)
            print("分析完成！")
            print("=" * 80)
            print("\n💡 下一步:")
            print(f"   1. 查看详细报告: cat {report_file}")
            print("   2. 如果提取不准确，查看 doc/SELECTOR_OPTIMIZATION.md")
            print("   3. 调整选择器: vim scraper/message_extractor.py")
            print("   4. 重新运行此脚本验证")
            print("=" * 80 + "\n")
            
            # 关闭浏览器
            await browser.close()
            
        except Exception as e:
            print(f"\n❌ 分析失败: {e}")
            import traceback
            traceback.print_exc()
            if 'browser' in locals():
                await browser.close()


def select_html_file():
    """
    让用户选择要分析的HTML文件
    
    Returns:
        选择的文件路径，如果取消则返回None
    """
    # 查找debug目录下的HTML文件
    html_files = glob("debug/page_*.html")
    
    if not html_files:
        print("❌ 未找到HTML文件")
        print("\n💡 提示: 请先运行以下命令导出HTML:")
        print("   python3 main.py --test export-dom\n")
        return None
    
    # 按修改时间排序，最新的在前
    html_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    
    print(f"📁 找到 {len(html_files)} 个HTML文件:\n")
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
    print("本地HTML消息提取分析工具")
    print("=" * 80 + "\n")
    
    # 检查命令行参数
    if len(sys.argv) > 1:
        html_file = sys.argv[1]
        if not os.path.exists(html_file):
            print(f"❌ 文件不存在: {html_file}")
            print("\n使用方法:")
            print(f"   python3 {sys.argv[0]} [HTML文件路径]")
            print(f"   python3 {sys.argv[0]}  # 交互式选择文件\n")
            return
    else:
        # 交互式选择文件
        html_file = select_html_file()
        if not html_file:
            return
    
    # 分析文件
    asyncio.run(analyze_html_messages(html_file))


if __name__ == "__main__":
    main()
