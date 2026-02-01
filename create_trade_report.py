"""
创建期权交易动作报告，供用户校对
"""
import json
from datetime import datetime
from parser.option_parser import OptionParser

def load_messages(filepath):
    """加载历史消息"""
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)

def extract_date_from_text(text):
    """从消息文本中提取日期"""
    import re
    # 尝试匹配各种日期格式
    date_patterns = [
        r'(\w+ \d+, \d{4} \d+:\d+ [AP]M)',  # Jan 30, 2026 10:30 PM
        r'(Yesterday at \d+:\d+ [AP]M)',
        r'(\d+:\d+ [AP]M)',
    ]
    
    for pattern in date_patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return "Unknown"

def create_trade_report():
    """创建交易动作报告"""
    messages = load_messages('/Users/txink/Documents/code/playwright/20260130.message.json')
    
    # 按类型分类
    trades = {
        'open': [],
        'stop_loss': [],
        'adjust': [],
        'take_profit': []
    }
    
    for msg_obj in messages:
        text = msg_obj.get('text', '')
        msg_id = msg_obj.get('id', '')
        
        if len(text) < 10:
            continue
        
        # 提取日期
        date = extract_date_from_text(text)
        
        # 解析指令
        instruction = OptionParser.parse(text, msg_id)
        
        if instruction:
            # 添加日期信息
            trade_info = {
                'date': date,
                'raw_text': text[:200],  # 截取前200字符
                'instruction': instruction.to_dict()
            }
            
            if instruction.instruction_type == 'OPEN':
                trades['open'].append(trade_info)
            elif instruction.instruction_type == 'STOP_LOSS':
                trades['stop_loss'].append(trade_info)
            elif instruction.instruction_type == 'ADJUST':
                trades['adjust'].append(trade_info)
            elif instruction.instruction_type == 'TAKE_PROFIT':
                trades['take_profit'].append(trade_info)
    
    return trades

def print_report(trades):
    """打印格式化的交易报告"""
    
    print("\n" + "="*100)
    print("期权交易动作整理报告 - 供用户校对")
    print("="*100)
    print(f"报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"数据来源: 20260130.message.json")
    print("="*100)
    
    # 开仓指令
    print(f"\n{'─'*100}")
    print(f"📈 开仓指令 (共 {len(trades['open'])} 条)")
    print(f"{'─'*100}\n")
    
    for i, trade in enumerate(trades['open'], 1):
        ins = trade['instruction']
        print(f"[{i}] {trade['date']}")
        print(f"    股票: {ins.get('ticker', 'N/A')}")
        print(f"    类型: {ins.get('option_type', 'N/A')} | 行权价: ${ins.get('strike', 'N/A')}")
        print(f"    到期: {ins.get('expiry') or '未指定'}")
        print(f"    入场价: ${ins.get('price', 'N/A')}")
        print(f"    仓位: {ins.get('position_size') or '未指定'}")
        print(f"    原文: {trade['raw_text'][:100]}...")
        print()
    
    # 止损指令
    print(f"\n{'─'*100}")
    print(f"🛑 止损指令 (共 {len(trades['stop_loss'])} 条)")
    print(f"{'─'*100}\n")
    
    for i, trade in enumerate(trades['stop_loss'], 1):
        ins = trade['instruction']
        print(f"[{i}] {trade['date']}")
        print(f"    止损价: ${ins.get('price', 'N/A')}")
        print(f"    原文: {trade['raw_text'][:100]}...")
        print()
    
    # 止损调整
    print(f"\n{'─'*100}")
    print(f"📊 止损调整 (共 {len(trades['adjust'])} 条)")
    print(f"{'─'*100}\n")
    
    for i, trade in enumerate(trades['adjust'], 1):
        ins = trade['instruction']
        print(f"[{i}] {trade['date']}")
        print(f"    新止损价: ${ins.get('price', 'N/A')}")
        print(f"    原文: {trade['raw_text'][:100]}...")
        print()
    
    # 止盈/出货指令
    print(f"\n{'─'*100}")
    print(f"💰 止盈/出货指令 (共 {len(trades['take_profit'])} 条)")
    print(f"{'─'*100}\n")
    
    for i, trade in enumerate(trades['take_profit'], 1):
        ins = trade['instruction']
        print(f"[{i}] {trade['date']}")
        print(f"    出货价: ${ins.get('price', 'N/A')} | 比例: {ins.get('portion', 'N/A')}")
        print(f"    原文: {trade['raw_text'][:100]}...")
        print()
    
    # 统计汇总
    print(f"\n{'='*100}")
    print("📊 统计汇总")
    print(f"{'='*100}")
    print(f"开仓指令: {len(trades['open'])} 条")
    print(f"止损指令: {len(trades['stop_loss'])} 条")
    print(f"止损调整: {len(trades['adjust'])} 条")
    print(f"止盈指令: {len(trades['take_profit'])} 条")
    print(f"总计: {sum(len(v) for v in trades.values())} 条交易指令")
    print(f"{'='*100}\n")

def save_report(trades):
    """保存报告到文件"""
    output_file = '/Users/txink/Documents/code/playwright/trade_report.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(trades, f, ensure_ascii=False, indent=2)
    
    # 也保存一份markdown格式
    md_file = '/Users/txink/Documents/code/playwright/trade_report.md'
    with open(md_file, 'w', encoding='utf-8') as f:
        f.write("# 期权交易动作整理报告\n\n")
        f.write(f"报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        # 开仓指令
        f.write(f"## 📈 开仓指令 ({len(trades['open'])} 条)\n\n")
        for i, trade in enumerate(trades['open'], 1):
            ins = trade['instruction']
            f.write(f"### [{i}] {trade['date']}\n\n")
            f.write(f"- **股票**: {ins.get('ticker', 'N/A')}\n")
            f.write(f"- **类型**: {ins.get('option_type', 'N/A')}\n")
            f.write(f"- **行权价**: ${ins.get('strike', 'N/A')}\n")
            f.write(f"- **到期**: {ins.get('expiry') or '未指定'}\n")
            f.write(f"- **入场价**: ${ins.get('price', 'N/A')}\n")
            f.write(f"- **仓位**: {ins.get('position_size') or '未指定'}\n")
            f.write(f"- **原文**: {trade['raw_text'][:150]}...\n\n")
        
        # 止损指令
        f.write(f"## 🛑 止损指令 ({len(trades['stop_loss'])} 条)\n\n")
        for i, trade in enumerate(trades['stop_loss'], 1):
            ins = trade['instruction']
            f.write(f"### [{i}] {trade['date']}\n\n")
            f.write(f"- **止损价**: ${ins.get('price', 'N/A')}\n")
            f.write(f"- **原文**: {trade['raw_text'][:150]}...\n\n")
        
        # 止损调整
        f.write(f"## 📊 止损调整 ({len(trades['adjust'])} 条)\n\n")
        for i, trade in enumerate(trades['adjust'], 1):
            ins = trade['instruction']
            f.write(f"### [{i}] {trade['date']}\n\n")
            f.write(f"- **新止损价**: ${ins.get('price', 'N/A')}\n")
            f.write(f"- **原文**: {trade['raw_text'][:150]}...\n\n")
        
        # 止盈指令
        f.write(f"## 💰 止盈/出货指令 ({len(trades['take_profit'])} 条)\n\n")
        for i, trade in enumerate(trades['take_profit'], 1):
            ins = trade['instruction']
            f.write(f"### [{i}] {trade['date']}\n\n")
            f.write(f"- **出货价**: ${ins.get('price', 'N/A')}\n")
            f.write(f"- **比例**: {ins.get('portion', 'N/A')}\n")
            f.write(f"- **原文**: {trade['raw_text'][:150]}...\n\n")
        
        # 统计
        f.write(f"## 📊 统计汇总\n\n")
        f.write(f"- 开仓指令: {len(trades['open'])} 条\n")
        f.write(f"- 止损指令: {len(trades['stop_loss'])} 条\n")
        f.write(f"- 止损调整: {len(trades['adjust'])} 条\n")
        f.write(f"- 止盈指令: {len(trades['take_profit'])} 条\n")
        f.write(f"- **总计**: {sum(len(v) for v in trades.values())} 条交易指令\n")
    
    return output_file, md_file

if __name__ == "__main__":
    trades = create_trade_report()
    print_report(trades)
    json_file, md_file = save_report(trades)
    print(f"✅ JSON报告已保存: {json_file}")
    print(f"✅ Markdown报告已保存: {md_file}")
