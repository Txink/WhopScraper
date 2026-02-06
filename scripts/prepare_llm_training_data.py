#!/usr/bin/env python3
"""
将 samples.json 转换为 LLM 微调训练数据

输出格式: JSONL (每行一个训练样本)
适用于: Unsloth, llama.cpp, Ollama Modelfile
"""

import json
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def convert_to_training_format(
    input_file='samples/samples.json',
    output_file='training_data/trading_parser.jsonl',
    min_confidence=True
):
    """
    将 samples.json 转换为训练格式
    
    Args:
        input_file: 输入文件路径
        output_file: 输出文件路径  
        min_confidence: 是否只使用成功解析的样本
    """
    
    # 读取样本数据
    input_path = project_root / input_file
    with open(input_path, 'r', encoding='utf-8') as f:
        samples = json.load(f)
    
    print(f"📖 读取 {len(samples)} 条样本...")
    
    # 转换为训练格式
    training_data = []
    skipped = 0
    
    for sample in samples:
        # 过滤条件
        if min_confidence and not sample.get('parsed_successfully'):
            skipped += 1
            continue
        
        # 构建训练样本
        instruction = sample['message']
        parsed_result = sample.get('parsed_result', {})
        
        # 简化输出（只保留关键字段）
        output_fields = {}
        key_fields = [
            'instruction_type', 'ticker', 'price', 'sell_quantity',
            'stop_loss_price', 'option_type', 'strike', 'expiry', 'position_size'
        ]
        for field in key_fields:
            if field in parsed_result:
                output_fields[field] = parsed_result[field]
        
        # 构造标准输出格式
        output = {
            "success": True,
            "instructions": [output_fields] if output_fields else []
        }
        
        # Alpaca 格式（适用于大多数微调框架）
        training_sample = {
            "instruction": "将以下交易指令解析为标准JSON格式",
            "input": instruction,
            "output": json.dumps(output, ensure_ascii=False)
        }
        
        training_data.append(training_sample)
    
    print(f"✅ 转换 {len(training_data)} 条训练样本")
    if skipped > 0:
        print(f"⚠️  跳过 {skipped} 条未成功解析的样本")
    
    # 创建输出目录
    output_path = project_root / output_file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 保存为 JSONL
    with open(output_path, 'w', encoding='utf-8') as f:
        for sample in training_data:
            f.write(json.dumps(sample, ensure_ascii=False) + '\n')
    
    print(f"\n💾 训练数据已保存到: {output_path}")
    
    # 显示统计
    print(f"\n📊 数据统计:")
    print(f"  - 总样本数: {len(training_data)}")
    print(f"  - 平均输入长度: {sum(len(s['input']) for s in training_data) / len(training_data):.1f} 字符")
    print(f"  - 平均输出长度: {sum(len(s['output']) for s in training_data) / len(training_data):.1f} 字符")
    
    # 显示前3个示例
    print(f"\n📝 示例（前3条）:")
    for i, sample in enumerate(training_data[:3], 1):
        print(f"\n  [{i}] 输入: {sample['input']}")
        print(f"      输出: {sample['output'][:100]}...")
    
    return output_path


def create_ollama_modelfile(training_data_path):
    """创建 Ollama Modelfile 用于创建自定义模型"""
    
    modelfile_path = project_root / "training_data" / "Modelfile"
    
    content = f"""# Trading Parser - 基于 Qwen2.5 的交易指令解析模型
FROM qwen2.5:3b

# 系统提示词
SYSTEM \"\"\"你是专业的期权交易指令解析器。
你的任务是将自然语言描述的交易指令解析为标准JSON格式。

支持的指令类型:
- BUY: 买入期权
- SELL: 卖出部分持仓
- CLOSE: 清仓全部
- MODIFY: 修改止损/止盈

输出格式必须为:
{{
  "success": true,
  "instructions": [...]
}}
\"\"\"

# 参数优化（针对交易指令解析）
PARAMETER temperature 0.1
PARAMETER top_p 0.9
PARAMETER num_predict 500

# 停止词
PARAMETER stop "```"
PARAMETER stop "###"
"""
    
    with open(modelfile_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"\n📄 Modelfile 已创建: {modelfile_path}")
    print(f"\n使用方法:")
    print(f"  ollama create trading-parser -f {modelfile_path}")
    print(f"  python3 test/parser/test_llm_parser.py --model trading-parser")


def main():
    """主函数"""
    print("="*60)
    print("LLM 微调数据准备工具")
    print("="*60)
    
    # 转换训练数据
    output_path = convert_to_training_format()
    
    # 创建 Ollama Modelfile
    create_ollama_modelfile(output_path)
    
    print(f"\n{'='*60}")
    print("✅ 完成！")
    print(f"{'='*60}\n")
    
    print("下一步:")
    print("  1. 使用 Ollama 创建自定义模型:")
    print("     ollama create trading-parser -f training_data/Modelfile")
    print("")
    print("  2. 或使用训练数据进行 LoRA 微调:")
    print("     (需要 GPU 和微调框架如 Unsloth)")
    print("")
    print("  3. 测试微调后的模型:")
    print("     python3 test/parser/test_llm_parser.py --model trading-parser")


if __name__ == "__main__":
    main()
