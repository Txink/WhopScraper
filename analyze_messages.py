"""
分析历史消息并测试更新后的正则规则
"""
import json
import sys
from parser.option_parser import OptionParser

def load_messages(filepath):
    """加载历史消息"""
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)

def analyze_and_parse():
    """分析并解析历史消息"""
    messages = load_messages('/Users/txink/Documents/code/playwright/20260130.message.json')
    
    results = {
        'total': len(messages),
        'parsed': 0,
        'unparsed': 0,
        'open_positions': [],
        'stop_losses': [],
        'take_profits': [],
        'adjustments': [],
        'unparsed_messages': []
    }
    
    for msg_obj in messages:
        text = msg_obj.get('text', '')
        msg_id = msg_obj.get('id', '')
        
        # 跳过太短的消息
        if len(text) < 10:
            continue
        
        # 解析指令
        instruction = OptionParser.parse(text, msg_id)
        
        if instruction:
            results['parsed'] += 1
            
            # 分类统计
            if instruction.instruction_type == 'OPEN':
                results['open_positions'].append({
                    'text': text,
                    'ticker': instruction.ticker,
                    'strike': instruction.strike,
                    'option_type': instruction.option_type,
                    'expiry': instruction.expiry,
                    'price': instruction.price,
                    'position_size': instruction.position_size
                })
            elif instruction.instruction_type == 'STOP_LOSS':
                results['stop_losses'].append({
                    'text': text,
                    'price': instruction.price
                })
            elif instruction.instruction_type == 'TAKE_PROFIT':
                results['take_profits'].append({
                    'text': text,
                    'price': instruction.price,
                    'portion': instruction.portion
                })
            elif instruction.instruction_type == 'ADJUST':
                results['adjustments'].append({
                    'text': text,
                    'price': instruction.price
                })
        else:
            results['unparsed'] += 1
            # 只保存可能是交易指令的消息（包含数字和关键字）
            if any(keyword in text for keyword in ['call', 'put', 'CALL', 'PUT', '出', '止损']):
                results['unparsed_messages'].append(text)
    
    return results

def print_results(results):
    """打印分析结果"""
    print("\n" + "="*80)
    print("期权交易消息分析报告")
    print("="*80)
    
    print(f"\n总消息数: {results['total']}")
    print(f"成功解析: {results['parsed']}")
    print(f"未能解析: {results['unparsed']}")
    print(f"解析率: {results['parsed']/(results['parsed']+results['unparsed'])*100:.1f}%")
    
    print("\n" + "-"*80)
    print(f"开仓指令 ({len(results['open_positions'])} 条)")
    print("-"*80)
    for i, item in enumerate(results['open_positions'][:20], 1):  # 只显示前20条
        print(f"\n{i}. {item['ticker']} {item['strike']} {item['option_type']} @ ${item['price']}")
        print(f"   到期: {item['expiry'] or '未指定'} | 仓位: {item['position_size'] or '未指定'}")
        print(f"   原文: {item['text'][:100]}")
    
    if len(results['open_positions']) > 20:
        print(f"\n   ... 还有 {len(results['open_positions'])-20} 条开仓指令")
    
    print("\n" + "-"*80)
    print(f"止损指令 ({len(results['stop_losses'])} 条)")
    print("-"*80)
    for i, item in enumerate(results['stop_losses'][:10], 1):
        print(f"{i}. 止损价: ${item['price']}")
        print(f"   原文: {item['text'][:80]}")
    
    print("\n" + "-"*80)
    print(f"止盈指令 ({len(results['take_profits'])} 条)")
    print("-"*80)
    for i, item in enumerate(results['take_profits'][:10], 1):
        print(f"{i}. 价格: ${item['price']} | 比例: {item['portion']}")
        print(f"   原文: {item['text'][:80]}")
    
    print("\n" + "-"*80)
    print(f"止损调整 ({len(results['adjustments'])} 条)")
    print("-"*80)
    for i, item in enumerate(results['adjustments'], 1):
        print(f"{i}. 新止损价: ${item['price']}")
        print(f"   原文: {item['text'][:80]}")
    
    print("\n" + "-"*80)
    print(f"未能解析的交易相关消息 ({len(results['unparsed_messages'])} 条)")
    print("-"*80)
    for i, text in enumerate(results['unparsed_messages'][:20], 1):
        print(f"{i}. {text[:120]}")
    
    if len(results['unparsed_messages']) > 20:
        print(f"\n   ... 还有 {len(results['unparsed_messages'])-20} 条未解析消息")
    
    print("\n" + "="*80)

if __name__ == "__main__":
    results = analyze_and_parse()
    print_results(results)
    
    # 保存详细结果到JSON
    output_file = '/Users/txink/Documents/code/playwright/analysis_results.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"\n详细结果已保存到: {output_file}")
