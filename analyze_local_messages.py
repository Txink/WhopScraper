#!/usr/bin/env python3
"""
本地HTML消息分析脚本
直接分析本地HTML文件，使用EnhancedMessageExtractor提取消息并分组
无需启动浏览器连接网页
"""
import asyncio
import os
import sys
import json
from glob import glob
from datetime import datetime
from playwright.async_api import async_playwright


def generate_option_symbol(ticker: str, option_type: str, strike: float, expiry: str, timestamp: str = None) -> str:
    """
    生成完整的期权代码
    
    Args:
        ticker: 股票代码（如 "BA"）
        option_type: 期权类型（"CALL" 或 "PUT"）
        strike: 行权价（如 240.0）
        expiry: 到期日（如 "2/13", "2月13"）
        timestamp: 消息时间戳（如 "Jan 23, 2026 12:51 AM"），用于推断年份
        
    Returns:
        完整期权代码（如 "BA260213C240000.US"）
    """
    from datetime import datetime
    import re
    
    if not all([ticker, option_type, strike, expiry]):
        return ticker or "未知"
    
    # 从timestamp提取年份
    year = 26  # 默认2026年
    if timestamp:
        try:
            # 尝试解析 "Jan 23, 2026 12:51 AM" 格式
            ts_match = re.search(r', (\d{4})', timestamp)
            if ts_match:
                year = int(ts_match.group(1)) % 100  # 取后两位
        except:
            pass
    
    # 解析到期日
    month = None
    day = None
    
    # 尝试匹配 "2/13" 格式
    match = re.match(r'(\d{1,2})/(\d{1,2})', expiry)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
    else:
        # 尝试匹配 "2月13" 格式
        match = re.match(r'(\d{1,2})月(\d{1,2})', expiry)
        if match:
            month = int(match.group(1))
            day = int(match.group(2))
    
    if not month or not day:
        return ticker
    
    # 格式化日期为 YYMMDD
    date_str = f"{year:02d}{month:02d}{day:02d}"
    
    # 期权类型代码
    option_code = 'C' if option_type == 'CALL' else 'P'
    
    # 行权价（乘以1000并格式化为8位）
    strike_code = f"{int(strike * 1000):08d}"
    
    # 组合完整代码
    return f"{ticker}{date_str}{option_code}{strike_code}.US"


def export_messages_to_json(raw_groups, html_file: str) -> str:
    """
    导出消息到JSON文件
    
    Args:
        raw_groups: 消息组列表
        html_file: 源HTML文件路径
        
    Returns:
        导出的JSON文件路径
    """
    # 生成输出文件名
    base_name = os.path.splitext(os.path.basename(html_file))[0]
    output_dir = os.path.dirname(html_file) or 'debug'
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    json_file = os.path.join(output_dir, f"{base_name}_messages_{timestamp}.json")
    
    # 转换为简化格式
    messages_data = []
    for group in raw_groups:
        simple_dict = group.to_simple_dict()
        messages_data.append(simple_dict)
    
    # 构建完整的JSON数据结构
    output_data = {
        "metadata": {
            "source_file": html_file,
            "export_time": datetime.now().isoformat(),
            "total_messages": len(messages_data),
            "extractor_version": "3.9"
        },
        "messages": messages_data
    }
    
    # 写入JSON文件
    try:
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        return json_file
    except Exception as e:
        print(f"❌ JSON导出失败: {e}")
        return None


async def analyze_html_messages(html_file: str, export_json: bool = True):
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
            
            # 使用EnhancedMessageExtractor提取消息（scraper层唯一输出格式）
            print("🔍 正在提取消息...")
            from scraper.message_extractor import EnhancedMessageExtractor
            
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
            
            # 导出JSON文件
            if export_json:
                print("📤 正在导出JSON文件...")
                json_file = export_messages_to_json(raw_groups, html_file)
                if json_file:
                    file_size = os.path.getsize(json_file) / 1024
                    print(f"✅ JSON文件已导出: {json_file}")
                    print(f"   文件大小: {file_size:.2f} KB")
                    print(f"   消息数量: {len(raw_groups)}")
                    print()
            
            # scraper层只负责提取消息，不做分组
            
            # 解析消息并转化为broker指令
            from parser.option_parser import OptionParser
            from parser.message_context_resolver import MessageContextResolver
            
            # 检查是否显示解析输出（可通过环境变量控制）
            show_parser_output = os.getenv('SHOW_PARSER_OUTPUT', 'true').lower() in ('true', '1', 'yes')
            
            if show_parser_output:
                print("\n" + "="*140)
                print("【指令解析 - 转化为Broker可用指令（含上下文补全）】")
                print("="*140)
            
            # 按时间排序所有消息
            from datetime import datetime
            def parse_ts(group):
                ts = group.timestamp
                if not ts:
                    return datetime.max
                try:
                    return datetime.strptime(ts, '%b %d, %Y %I:%M %p')
                except:
                    return datetime.max
            sorted_groups = sorted(raw_groups, key=lambda x: (parse_ts(x), x.group_id))
            
            # 准备所有消息（简化格式）用于上下文解析
            import re
            all_messages_simple = []
            for group in sorted_groups:
                simple_dict = group.to_simple_dict()
                content = simple_dict['content'].strip()
                
                # 清理消息内容
                content_clean = content
                content_clean = re.sub(r'^\[引用\]\s*', '', content_clean)
                content_clean = re.sub(r'^[\w]+•[A-Z][a-z]{2,9}\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2}\s+[AP]M\s*', '', content_clean)
                content_clean = re.sub(r'^[XxＸｘ]+', '', content_clean)
                content_clean = re.sub(r'^[\w]+•[A-Z][a-z]{2,9}\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2}\s+[AP]M\s*', '', content_clean)
                content_clean = re.sub(r'^•?\s*[A-Z][a-z]+\s+\d{1,2}:\d{2}\s+[AP]M\s*', '', content_clean)
                content_clean = content_clean.strip()
                
                # 更新清理后的内容
                simple_dict['content'] = content_clean
                all_messages_simple.append(simple_dict)
            
            # 创建上下文解析器
            resolver = MessageContextResolver(all_messages_simple)
            
            # 统计解析结果
            total_messages = 0
            parsed_success = 0
            parsed_failed = 0
            context_used_count = 0
            
            # 收集解析结果用于表格展示
            parse_results = []
            
            # 逐条解析消息
            for simple_dict in all_messages_simple:
                msg_id = simple_dict['domID']
                timestamp = simple_dict['timestamp']
                content = simple_dict['content']
                
                # 过滤纯元数据消息
                if not content or len(content) < 5:
                    continue
                
                total_messages += 1
                
                # 使用上下文解析器（返回三元组：instruction, context_source, context_message）
                result = resolver.resolve_instruction(simple_dict)
                
                if result:
                    instruction, context_source, context_message = result
                    
                    if instruction:
                        parsed_success += 1
                        
                        # 记录是否使用了上下文
                        if context_source:
                            context_used_count += 1
                        
                        ticker = instruction.ticker if instruction.ticker else "未识别"
                        # 移除换行符并限制长度
                        raw_msg = content.replace('\n', ' ').replace('\r', ' ')[:80]
                        parse_results.append({
                            'timestamp': timestamp,
                            'ticker': ticker,
                            'status': '✅',
                            'type': instruction.instruction_type,
                            'instruction': instruction,
                            'raw_message': raw_msg,
                            'context_source': context_source,
                            'context_message': context_message
                        })
                        continue
                
                # 解析失败
                parsed_failed += 1
                ticker_match = re.search(r'\b([A-Z]{1,5})\b', content)
                ticker = ticker_match.group(1) if ticker_match else "未识别"
                content_display = content.replace('\n', ' ').replace('\r', ' ')[:80]
                if len(content) > 80:
                    content_display += "..."
                parse_results.append({
                    'timestamp': timestamp,
                    'ticker': ticker,
                    'status': '❌',
                    'type': 'FAILED',
                    'instruction': None,
                    'error': f"解析失败",
                    'raw_message': content_display,
                    'context_source': None,
                    'context_message': None
                })
            
            # 表格展示
            if show_parser_output and parse_results:
                from rich.console import Console
                from rich.table import Table
                from rich import box
                
                console = Console()
                print()
                
                # 为每个指令创建独立表格
                for idx, result in enumerate(parse_results, 1):
                    # 构建表格标题
                    if result['status'] == '✅':
                        title = f"#{idx} {result['type']} - {result['ticker']}"
                        title_style = "bold green"
                    else:
                        title = f"#{idx} 解析失败 - {result['ticker']}"
                        title_style = "bold red"
                    
                    # 创建表格
                    table = Table(
                        title=title,
                        title_style=title_style,
                        box=box.ROUNDED,
                        show_header=True,
                        header_style="bold cyan",
                        width=80,
                        padding=(0, 1)
                    )
                    
                    # 添加列
                    table.add_column("字段", style="cyan", width=18, no_wrap=True)
                    table.add_column("值", style="white", width=56, no_wrap=False)
                    
                    # 添加基本信息
                    table.add_row("时间", result['timestamp'])
                    
                    # 生成完整的期权代码
                    if result['status'] == '✅' and result['instruction']:
                        inst = result['instruction']
                        option_symbol = generate_option_symbol(
                            inst.ticker,
                            inst.option_type,
                            inst.strike,
                            inst.expiry,
                            result['timestamp']
                        )
                        table.add_row("期权代码", option_symbol)
                        # 如果完整代码生成失败，显示股票代码
                        if option_symbol == inst.ticker or option_symbol == "未知":
                            table.add_row("股票代码", result['ticker'] or "未识别")
                    else:
                        table.add_row("股票代码", result['ticker'] or "未识别")
                    
                    table.add_row("指令类型", result['type'])
                    table.add_row("状态", result['status'])
                    
                    # 根据指令类型显示详细信息
                    if result['status'] == '✅' and result['instruction']:
                        inst = result['instruction']
                        
                        if result['type'] == 'BUY':
                            # 买入指令
                            if inst.option_type:
                                table.add_row("期权类型", inst.option_type)
                            if inst.strike:
                                table.add_row("行权价", f"${inst.strike}")
                            if inst.expiry:
                                table.add_row("到期日", inst.expiry)
                            if inst.price_range:
                                table.add_row("价格区间", f"${inst.price_range[0]} - ${inst.price_range[1]}")
                                table.add_row("价格(中间值)", f"${inst.price}")
                            elif inst.price:
                                table.add_row("价格", f"${inst.price}")
                            if inst.position_size:
                                table.add_row("仓位大小", inst.position_size)
                        
                        elif result['type'] == 'SELL':
                            # 卖出指令
                            if inst.price_range:
                                table.add_row("价格区间", f"${inst.price_range[0]} - ${inst.price_range[1]}")
                                table.add_row("价格(中间值)", f"${inst.price}")
                            elif inst.price:
                                table.add_row("价格", f"${inst.price}")
                            if inst.sell_quantity:
                                table.add_row("卖出数量", inst.sell_quantity)
                        
                        elif result['type'] == 'CLOSE':
                            # 清仓指令
                            if inst.price_range:
                                table.add_row("价格区间", f"${inst.price_range[0]} - ${inst.price_range[1]}")
                                table.add_row("价格(中间值)", f"${inst.price}")
                            elif inst.price:
                                table.add_row("价格", f"${inst.price}")
                            table.add_row("数量", "全部")
                        
                        elif result['type'] == 'MODIFY':
                            # 修改指令
                            if inst.stop_loss_range:
                                table.add_row("止损区间", f"${inst.stop_loss_range[0]} - ${inst.stop_loss_range[1]}")
                                table.add_row("止损(中间值)", f"${inst.stop_loss_price}")
                            elif inst.stop_loss_price:
                                table.add_row("止损价格", f"${inst.stop_loss_price}")
                            
                            if inst.take_profit_range:
                                table.add_row("止盈区间", f"${inst.take_profit_range[0]} - ${inst.take_profit_range[1]}")
                                table.add_row("止盈(中间值)", f"${inst.take_profit_price}")
                            elif inst.take_profit_price:
                                table.add_row("止盈价格", f"${inst.take_profit_price}")
                        
                        # 显示上下文补全信息
                        if result.get('context_source'):
                            table.add_row("🔗 上下文来源", result['context_source'])
                            if result.get('context_message'):
                                ctx_msg = result['context_message'][:60]
                                if len(result['context_message']) > 60:
                                    ctx_msg += "..."
                                table.add_row("🔗 上下文消息", ctx_msg)
                        
                        # 显示原始消息
                        if result['raw_message']:
                            raw_msg = result['raw_message']
                            if len(raw_msg) > 75:
                                table.add_row("原始消息", raw_msg[:75] + "...")
                            else:
                                table.add_row("原始消息", raw_msg)
                    else:
                        # 失败的解析
                        if 'error' in result:
                            table.add_row("错误", result['error'])
                        raw_msg = result['raw_message']
                        if len(raw_msg) > 75:
                            table.add_row("原始消息", raw_msg[:75] + "...")
                        else:
                            table.add_row("原始消息", raw_msg)
                    
                    # 渲染表格
                    console.print(table)
                    print()
                
                # 统计信息
                stats_table = Table(
                    title="📊 解析统计",
                    title_style="bold yellow",
                    box=box.DOUBLE,
                    show_header=False,
                    width=80
                )
                stats_table.add_column("", style="bold cyan")
                stats_table.add_row(f"总消息数: {total_messages} | 成功: {parsed_success} | 失败: {parsed_failed} | 成功率: {parsed_success/total_messages*100:.1f}%")
                if context_used_count > 0:
                    stats_table.add_row(f"🔗 使用上下文补全: {context_used_count} ({context_used_count/parsed_success*100:.1f}% 的成功解析)")
                console.print(stats_table)
                print()
            
            # 显示原始消息（前200条）- 使用新的简化格式
            print("\n" + "=" * 80)
            print("【原始消息详情】（前200条 - 新格式）")
            print("=" * 80)
            
            import json
            for i, group in enumerate(raw_groups[:200], 1):
                # 使用新的简化格式
                simple_data = group.to_simple_dict()
                
                print(f"\n{i}. 消息 #{i}")
                print("   " + "-" * 76)
                print(f"   domID:     {simple_data['domID']}")
                print(f"   position:  {simple_data['position']}")
                print(f"   timestamp: {simple_data['timestamp'] or '(未识别)'}")
                print(f"   content:   {simple_data['content'][:70]}...")
                
                if simple_data['refer']:
                    print(f"   refer:     {simple_data['refer'][:70]}...")
                
                if simple_data['history']:
                    print(f"   history:   [{len(simple_data['history'])} 条历史消息]")
                    for j, hist_msg in enumerate(simple_data['history'][:3], 1):
                        print(f"     {j}. {hist_msg[:65]}...")
                    if len(simple_data['history']) > 3:
                        print(f"     ... 还有 {len(simple_data['history']) - 3} 条")
                else:
                    print(f"   history:   []")
                
                print("   " + "-" * 76)
                
                # JSON格式预览
                if i <= 3:  # 只展示前3条的完整JSON
                    print(f"\n   📋 JSON格式:")
                    json_str = json.dumps(simple_data, ensure_ascii=False, indent=4)
                    for line in json_str.split('\n'):
                        print(f"   {line}")
                
                print("-" * 80)
            
            if len(raw_groups) > 200:
                print(f"\n... 还有 {len(raw_groups) - 200} 条消息未显示")
            
            # 统计信息 - 增强版
            print("\n" + "=" * 80)
            print("📊 统计信息（基于新格式）")
            print("=" * 80)
            print(f"原始消息数: {len(raw_groups)}")
            
            # 统计有作者的消息
            with_author = sum(1 for g in raw_groups if g.author)
            print(f"有作者信息: {with_author} ({with_author/len(raw_groups)*100:.1f}%)")
            
            # 统计有时间戳的消息
            with_timestamp = sum(1 for g in raw_groups if g.timestamp)
            print(f"有时间戳: {with_timestamp} ({with_timestamp/len(raw_groups)*100:.1f}%)")
            
            # 统计有引用的消息
            with_quote = sum(1 for g in raw_groups if g.quoted_context)
            print(f"有引用内容: {with_quote} ({with_quote/len(raw_groups)*100:.1f}%)")
            
            # 统计消息位置分布
            position_stats = {}
            history_stats = {'with_history': 0, 'total_history_count': 0}
            
            for g in raw_groups:
                simple = g.to_simple_dict()
                pos = simple['position']
                position_stats[pos] = position_stats.get(pos, 0) + 1
                
                if simple['history']:
                    history_stats['with_history'] += 1
                    history_stats['total_history_count'] += len(simple['history'])
            
            print(f"\n消息位置分布:")
            for pos, count in sorted(position_stats.items()):
                print(f"  {pos:8s}: {count:3d} ({count/len(raw_groups)*100:.1f}%)")
            
            print(f"\nhistory字段统计:")
            print(f"  有历史消息: {history_stats['with_history']} ({history_stats['with_history']/len(raw_groups)*100:.1f}%)")
            if history_stats['with_history'] > 0:
                avg_history = history_stats['total_history_count'] / history_stats['with_history']
                print(f"  平均历史条数: {avg_history:.1f}")
            
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
                f.write(f"有作者信息: {with_author} ({with_author/len(raw_groups)*100:.1f}%)\n")
                f.write(f"有时间戳: {with_timestamp} ({with_timestamp/len(raw_groups)*100:.1f}%)\n")
                f.write(f"有引用内容: {with_quote} ({with_quote/len(raw_groups)*100:.1f}%)\n\n")
                
                # 添加新格式统计
                position_stats = {}
                history_stats = {'with_history': 0, 'total_history_count': 0}
                
                for g in raw_groups:
                    simple = g.to_simple_dict()
                    pos = simple['position']
                    position_stats[pos] = position_stats.get(pos, 0) + 1
                    
                    if simple['history']:
                        history_stats['with_history'] += 1
                        history_stats['total_history_count'] += len(simple['history'])
                
                f.write("消息位置分布:\n")
                for pos, count in sorted(position_stats.items()):
                    f.write(f"  {pos:8s}: {count:3d} ({count/len(raw_groups)*100:.1f}%)\n")
                
                f.write(f"\nhistory字段统计:\n")
                f.write(f"  有历史消息: {history_stats['with_history']} ({history_stats['with_history']/len(raw_groups)*100:.1f}%)\n")
                if history_stats['with_history'] > 0:
                    avg_history = history_stats['total_history_count'] / history_stats['with_history']
                    f.write(f"  平均历史条数: {avg_history:.1f}\n")
                f.write("\n")
                
                f.write("\n\n" + "=" * 80 + "\n")
                f.write("所有原始消息（新格式）\n")
                f.write("=" * 80 + "\n\n")
                
                import json
                for i, group in enumerate(raw_groups, 1):
                    # 使用新的简化格式
                    simple_data = group.to_simple_dict()
                    
                    f.write(f"\n{i}. 消息 #{i}\n")
                    f.write("-" * 80 + "\n")
                    f.write(f"domID:     {simple_data['domID']}\n")
                    f.write(f"position:  {simple_data['position']}\n")
                    f.write(f"timestamp: {simple_data['timestamp'] or '(未识别)'}\n")
                    f.write(f"content:   {simple_data['content']}\n")
                    
                    if simple_data['refer']:
                        f.write(f"refer:     {simple_data['refer']}\n")
                    
                    if simple_data['history']:
                        f.write(f"history:   [{len(simple_data['history'])} 条历史消息]\n")
                        for j, hist_msg in enumerate(simple_data['history'], 1):
                            f.write(f"  {j}. {hist_msg}\n")
                    else:
                        f.write(f"history:   []\n")
                    
                    # 完整JSON格式
                    f.write(f"\nJSON格式:\n")
                    json_str = json.dumps(simple_data, ensure_ascii=False, indent=2)
                    for line in json_str.split('\n'):
                        f.write(f"  {line}\n")
                    
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
    
    # 解析命令行参数
    export_json = True  # 默认导出JSON
    html_file = None
    
    # 检查命令行参数
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if arg == '--no-json':
                export_json = False
            elif not arg.startswith('--'):
                html_file = arg
        
        if html_file and not os.path.exists(html_file):
            print(f"❌ 文件不存在: {html_file}")
            print("\n使用方法:")
            print(f"   python3 {sys.argv[0]} [HTML文件路径] [选项]")
            print(f"   python3 {sys.argv[0]}  # 交互式选择文件")
            print("\n选项:")
            print("   --no-json    不导出JSON文件\n")
            return
    
    if not html_file:
        # 交互式选择文件
        html_file = select_html_file()
        if not html_file:
            return
    
    # 分析文件
    asyncio.run(analyze_html_messages(html_file, export_json=export_json))


if __name__ == "__main__":
    main()
