#!/usr/bin/env python3
"""
测试原始消息解析效果
读取 data/origin_message.json，使用 MessageContextResolver 解析所有消息
并生成包含原始消息和解析结果的 JSON 文件

输出格式：
{
  "origin": {...},           # 原始消息
  "parsed": {...},           # 解析结果（包含 symbol 字段）
  "status": "✅/⚠️/❌",       # ✅完整 ⚠️不完整 ❌失败
  "context_source": "...",   # 上下文来源
  "context_message": "..."   # 上下文消息
}

运行: python test/test_parse_origin_messages.py  或  python -m test.test_parse_origin_messages
"""
import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parser.message_context_resolver import MessageContextResolver


def clean_message_content(content: str) -> str:
    """
    清理消息内容（参考 monitor.py 的清理逻辑）
    
    Args:
        content: 原始消息内容
        
    Returns:
        清理后的内容
    """
    content_clean = content.strip()
    
    # 去除 [引用] 标记
    content_clean = re.sub(r'^\[引用\]\s*', '', content_clean)
    
    # 去除时间戳前缀
    content_clean = re.sub(r'^[\w]+•[A-Z][a-z]{2,9}\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2}\s+[AP]M\s*', '', content_clean)
    
    # 去除 X 标记
    content_clean = re.sub(r'^[XxＸｘ]+', '', content_clean)
    
    # 再次去除时间戳（可能在 X 后面）
    content_clean = re.sub(r'^[\w]+•[A-Z][a-z]{2,9}\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2}\s+[AP]M\s*', '', content_clean)
    
    # 去除相对时间戳前缀
    content_clean = re.sub(r'^•?\s*[A-Z][a-z]+\s+\d{1,2}:\d{2}\s+[AP]M\s*', '', content_clean)
    
    return content_clean.strip()


def check_instruction_completeness(instruction_dict: Dict) -> bool:
    """
    检查指令信息是否完整
    
    Args:
        instruction_dict: 指令字典
        
    Returns:
        是否完整
    """
    if not instruction_dict:
        return False
    
    inst_type = instruction_dict.get('instruction_type', '')
    
    # 对于需要完整期权信息的指令类型
    if inst_type in ['OPEN', 'BUY', 'CLOSE', 'TAKE_PROFIT', 'STOP_LOSS', 'MODIFY']:
        # 检查关键字段
        has_ticker = bool(instruction_dict.get('ticker'))
        has_strike = instruction_dict.get('strike') is not None
        has_expiry = bool(instruction_dict.get('expiry'))
        has_option_type = bool(instruction_dict.get('option_type'))
        
        # 有 symbol 表示信息完整
        if instruction_dict.get('symbol'):
            return True
        
        # 或者关键字段都存在
        if has_ticker and has_strike and has_expiry and has_option_type:
            return True
        
        return False
    
    # 其他类型的指令，只要能解析出来就算完整
    return True


def parse_origin_messages(input_file: str = "data/origin_message.json", 
                         output_file: str = "data/parsed_messages.json") -> Dict:
    """
    解析原始消息并生成结果文件
    
    Args:
        input_file: 输入的原始消息 JSON 文件
        output_file: 输出的解析结果 JSON 文件
        
    Returns:
        统计信息字典
    """
    print("\n" + "=" * 80)
    print("测试原始消息解析效果")
    print("=" * 80 + "\n")
    
    # 1. 读取原始消息
    print(f"📖 正在读取原始消息: {input_file}")
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            messages = json.load(f)
        print(f"✅ 成功读取 {len(messages)} 条消息\n")
    except Exception as e:
        print(f"❌ 读取失败: {e}")
        return {}
    
    # 2. 清理消息内容
    print("🧹 正在清理消息内容...")
    cleaned_messages = []
    for msg in messages:
        msg_copy = msg.copy()
        original_content = msg_copy.get('content', '')
        cleaned_content = clean_message_content(original_content)
        msg_copy['content'] = cleaned_content
        msg_copy['original_content'] = original_content  # 保留原始内容用于对比
        cleaned_messages.append(msg_copy)
    print(f"✅ 清理完成\n")
    
    # 3. 创建上下文解析器并解析所有消息
    print("🔍 正在解析消息...")
    resolver = MessageContextResolver(cleaned_messages)
    
    parse_results = []
    success_count = 0
    failed_count = 0
    complete_count = 0  # 信息完整的数量
    incomplete_count = 0  # 信息不完整的数量
    
    for msg in cleaned_messages:
        result = resolver.resolve_instruction(msg)
        
        parse_result = {
            "origin": {
                "domID": msg.get('domID'),
                "content": msg.get('content'),
                "original_content": msg.get('original_content'),
                "timestamp": msg.get('timestamp'),
                "refer": msg.get('refer'),
                "position": msg.get('position'),
                "history": msg.get('history', [])
            },
            "parsed": None,
            "status": "❌"
        }
        
        if result:
            instruction, context_source, context_message = result
            parsed_dict = instruction.to_dict()
            
            # 移除 parsed 中的 origin 字段（避免重复，外层已有 origin）
            if "origin" in parsed_dict:
                del parsed_dict["origin"]
            
            # 检查信息是否完整
            is_complete = check_instruction_completeness(parsed_dict)
            
            parse_result["parsed"] = parsed_dict
            parse_result["context_source"] = context_source
            parse_result["context_message"] = context_message
            parse_result["status"] = "✅" if is_complete else "⚠️"
            
            success_count += 1
            if is_complete:
                complete_count += 1
            else:
                incomplete_count += 1
        else:
            failed_count += 1
        
        parse_results.append(parse_result)
    
    print(f"✅ 解析完成\n")
    
    # 4. 导出结果
    print(f"💾 正在导出结果到: {output_file}")
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(parse_results, f, ensure_ascii=False, indent=2)
        print(f"✅ 结果已保存\n")
    except Exception as e:
        print(f"❌ 保存失败: {e}")
        return {}
    
    # 5. 统计信息
    stats = {
        "total": len(messages),
        "success": success_count,
        "failed": failed_count,
        "complete": complete_count,
        "incomplete": incomplete_count,
        "success_rate": f"{success_count / len(messages) * 100:.2f}%",
        "complete_rate": f"{complete_count / len(messages) * 100:.2f}%" if success_count > 0 else "0.00%"
    }
    
    # 统计状态分布
    status_count = {"✅": complete_count, "⚠️": incomplete_count, "❌": failed_count}
    stats["status_distribution"] = status_count
    
    # 统计指令类型分布
    instruction_types = {}
    for result in parse_results:
        if result["parsed"]:
            inst_type = result["parsed"].get("instruction_type", "UNKNOWN")
            instruction_types[inst_type] = instruction_types.get(inst_type, 0) + 1
    
    stats["instruction_types"] = instruction_types
    
    # 统计上下文来源分布
    context_sources = {}
    for result in parse_results:
        if result.get("context_source"):
            source = result["context_source"]
            context_sources[source] = context_sources.get(source, 0) + 1
    
    stats["context_sources"] = context_sources
    
    # 统计有 symbol 的指令数量
    symbol_count = sum(1 for result in parse_results if (result.get("parsed") or {}).get("symbol"))
    stats["with_symbol"] = symbol_count
    
    # 6. 显示统计信息
    print("=" * 80)
    print("📊 解析统计")
    print("=" * 80)
    print(f"\n总消息数: {stats['total']}")
    print(f"解析成功: {stats['success']} ({stats['success_rate']})")
    print(f"  - ✅ 信息完整: {stats['complete']} ({stats['complete_rate']})")
    print(f"  - ⚠️  信息不完整: {stats['incomplete']}")
    print(f"  - 生成 symbol: {stats['with_symbol']}")
    print(f"解析失败: {stats['failed']} (❌)")
    
    if instruction_types:
        print(f"\n指令类型分布:")
        for inst_type, count in sorted(instruction_types.items(), key=lambda x: x[1], reverse=True):
            print(f"  - {inst_type}: {count}")
    
    if context_sources:
        print(f"\n上下文来源分布:")
        for source, count in sorted(context_sources.items(), key=lambda x: x[1], reverse=True):
            print(f"  - {source}: {count}")
    
    print("\n" + "=" * 80)
    print("✅ 完成！")
    print("=" * 80)
    print(f"\n📁 输出文件: {output_file}")
    print(f"💡 提示: 可以打开该文件查看详细的解析结果\n")
    
    return stats


if __name__ == "__main__":
    parse_origin_messages()
