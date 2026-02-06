"""
测试本地 LLM (Qwen2.5 1.5B) 在交易指令解析中的表现

测试场景：
1. 简单指令（完整信息）
2. 复杂指令（一条消息包含多个操作）
3. 上下文依赖指令（需要历史消息）
4. 边界情况
"""
import time
import json
import sys
import os
import argparse

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

try:
    import ollama
except ImportError:
    print("❌ 请先安装 ollama-python: pip install ollama")
    sys.exit(1)


class LLMParserTester:
    """LLM 解析器测试器"""
    
    def __init__(self, model='qwen2.5:1.5b'):
        self.model = model
        self.test_results = []
        
        # 定义输出结构
        self.schema = {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "instructions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "instruction_type": {
                                "type": "string",
                                "enum": ["BUY", "SELL", "CLOSE", "MODIFY"]
                            },
                            "ticker": {"type": "string"},
                            "price": {"type": ["number", "null"]},
                            "option_type": {"type": ["string", "null"]},
                            "strike": {"type": ["number", "null"]},
                            "expiry": {"type": ["string", "null"]},
                            "sell_quantity": {"type": ["string", "null"]},
                            "stop_loss_price": {"type": ["number", "null"]},
                            "position_size": {"type": ["string", "null"]}
                        },
                        "required": ["instruction_type"]
                    }
                }
            },
            "required": ["success", "instructions"]
        }
    
    def check_model(self):
        """检查模型是否已下载"""
        print(f"🔍 检查模型 {self.model} ...")
        try:
            models = ollama.list()
            # ollama-python 返回 ListResponse，每项为 Model，字段为 model（不是 name）
            models_list = getattr(models, 'models', []) or []
            model_names = []
            for m in models_list:
                name = getattr(m, 'model', None) or getattr(m, 'name', None)
                if name:
                    model_names.append(str(name))
            
            if self.model not in model_names and f"{self.model}:latest" not in model_names:
                print(f"❌ 模型 {self.model} 未找到")
                print(f"请运行: ollama pull {self.model}")
                return False
            
            print(f"✅ 模型已就绪")
            return True
        except Exception as e:
            print(f"❌ 无法连接到 Ollama: {e}")
            print("请确保 Ollama 服务已启动: ollama serve")
            return False
    
    def parse_with_llm(self, message: str, history: list = None, timeout: float = 5.0) -> dict:
        """
        使用 LLM 解析指令
        
        Args:
            message: 当前消息
            history: 历史消息列表（可选）
            timeout: 超时时间（秒）
            
        Returns:
            {
                'result': 解析结果,
                'time': 耗时（秒）,
                'success': 是否成功
            }
        """
        # 构建提示词（优化版：Few-shot + 清晰结构）
        system_prompt = """你是期权交易指令解析器。严格按规则将指令转为 JSON。

【核心规则】
1. 指令类型识别（按优先级判断）：
   - BUY: 买入期权 → 标准格式：TICKER 行权价+类型 日期 价格 [仓位]
     * 示例格式："BA 240c 2/13 1.25 小仓位"
     * 字段顺序：ticker(BA) → strike+type(240c) → expiry(2/13) → price(1.25) → position_size(小仓位)
     * price 是倒数第2或第1个数字（position_size前的数字）
   - SELL: 卖出部分 → 必须有分数/比例（1/3、三分之一、1/2、一半）
     * 关键特征：有明确的数量比例
   - CLOSE: 清仓全部 → 没有分数 + 全部性关键词（都出、全部出、剩下的出、清仓）
     * 关键特征：没有分数，全部卖出
   - MODIFY: 修改止损 → 关键词：止损、SL + 价格

2. 字段映射规则（按指令类型）：
   【BUY】必需字段：ticker, option_type, strike, expiry, price
         可选字段：position_size（如：小仓位、大仓位）
   【SELL】必需字段：price, sell_quantity（如："1/3", "1/2"）
          可选字段：ticker
   【CLOSE】必需字段：price
           可选字段：ticker
   【MODIFY】必需字段：stop_loss_price
            可选字段：ticker

3. 通用字段格式：
   - ticker: 全大写（TSLA, BA, AMD）
   - strike: 从 "240c" 提取 240.0
   - option_type: "CALL"（c结尾）或 "PUT"（p结尾）
   - expiry: "2/13", "本周"

3. 上下文处理（关键）：
   如果当前消息缺 ticker，从历史消息中找【最后一条】的 ticker

【示例学习】

例1 - 买入期权（price 字段必须包含！1.25是买入价格）：
输入: "BA 240c 2/13 1.25 小仓位"
输出: {"success": true, "instructions": [{"instruction_type": "BUY", "ticker": "BA", "option_type": "CALL", "strike": 240.0, "expiry": "2/13", "price": 1.25, "position_size": "小仓位"}]}

注意：price 字段在 BUY 指令中是必需的！不能省略！

例2 - 买入期权（带美元符号）：
输入: "GOOG - $345 CALLS本周 $1.70"
输出: {"success": true, "instructions": [{"instruction_type": "BUY", "ticker": "GOOG", "option_type": "CALL", "strike": 345.0, "expiry": "本周", "price": 1.7}]}

例3 - 卖出部分（有分数 → SELL）：
输入: "1.9出三分之一"
输出: {"success": true, "instructions": [{"instruction_type": "SELL", "price": 1.9, "sell_quantity": "1/3"}]}

例4 - 卖出部分（中文分数 → SELL）：
输入: "一点七五出三分之一"
输出: {"success": true, "instructions": [{"instruction_type": "SELL", "price": 1.75, "sell_quantity": "1/3"}]}

例5 - 清仓全部（关键词：都出，无分数 → CLOSE）：
输入: "2.3都出 msft"
输出: {"success": true, "instructions": [{"instruction_type": "CLOSE", "ticker": "MSFT", "price": 2.3}]}

例6 - 清仓全部（关键词：剩下的出，无分数 → CLOSE）：
输入: "1.75出剩下的goog"
输出: {"success": true, "instructions": [{"instruction_type": "CLOSE", "ticker": "GOOG", "price": 1.75}]}

例7 - 复杂指令（SELL + MODIFY）：
输入: "2.53出三分之一 hon 止损剩下提高到2.3"
输出: {"success": true, "instructions": [{"instruction_type": "SELL", "ticker": "HON", "price": 2.53, "sell_quantity": "1/3"}, {"instruction_type": "MODIFY", "ticker": "HON", "stop_loss_price": 2.3}]}

例8 - 修改止损：
输入: "止损上移到2.25"
输出: {"success": true, "instructions": [{"instruction_type": "MODIFY", "stop_loss_price": 2.25}]}

例9 - 上下文依赖（从【最后一条】历史取ticker）：
历史: ["TSLA 240c 2/13 0.45", "NVDA 150c 2/20 2.5"]
输入: "0.17 卖出 1/3"
输出: {"success": true, "instructions": [{"instruction_type": "SELL", "ticker": "NVDA", "price": 0.17, "sell_quantity": "1/3"}]}

【输出要求】
- 仅输出 JSON，不要额外文字
- 必须包含 "success" 和 "instructions" 字段
- instructions 是数组，可包含多个指令
- 【重要】每个指令必须包含该类型的所有必需字段：
  * BUY 必须有: instruction_type, ticker, option_type, strike, expiry, price
  * SELL 必须有: instruction_type, price, sell_quantity
  * CLOSE 必须有: instruction_type, price
  * MODIFY 必须有: instruction_type, stop_loss_price
"""
        
        # 构建用户消息
        user_content = f"当前指令: {message}"
        
        if history:
            history_text = "\n".join([f"- {h}" for h in history[-5:]])  # 最近5条
            user_content = f"历史消息:\n{history_text}\n\n{user_content}"
        
        start_time = time.time()
        
        try:
            response = ollama.chat(
                model=self.model,
                messages=[
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_content}
                ],
                format=self.schema,  # schema 约束保证输出结构稳定
                options={
                    'temperature': 0.1,  # 低温度保证一致性
                    'num_predict': 500   # 限制输出长度
                }
            )
            
            elapsed = time.time() - start_time
            
            # 解析响应
            content = response['message']['content']
            result = json.loads(content)
            
            return {
                'result': result,
                'time': elapsed,
                'success': True,
                'raw': content
            }
            
        except Exception as e:
            elapsed = time.time() - start_time
            return {
                'result': None,
                'time': elapsed,
                'success': False,
                'error': str(e)
            }
    
    def run_test(self, name: str, message: str, history: list, expected: dict):
        """
        运行单个测试用例
        
        Args:
            name: 测试名称
            message: 当前消息
            history: 历史消息
            expected: 期望结果
        """
        print(f"\n{'='*60}")
        print(f"测试: {name}")
        print(f"{'='*60}")
        print(f"消息: {message}")
        if history:
            print(f"历史: {history}")
        
        # 执行解析
        result = self.parse_with_llm(message, history)
        
        # 显示结果
        print(f"\n耗时: {result['time']:.2f}秒")
        print(f"状态: {'✅ 成功' if result['success'] else '❌ 失败'}")
        
        if result['success']:
            print(f"\n解析结果:")
            print(json.dumps(result['result'], ensure_ascii=False, indent=2))
            
            # 验证结果
            is_correct = self.verify_result(result['result'], expected)
            print(f"\n准确性: {'✅ 正确' if is_correct else '❌ 错误'}")
            
            if not is_correct:
                print(f"\n期望结果:")
                print(json.dumps(expected, ensure_ascii=False, indent=2))
        else:
            print(f"错误: {result.get('error', 'Unknown')}")
            is_correct = False
        
        # 记录测试结果
        self.test_results.append({
            'name': name,
            'success': result['success'],
            'correct': is_correct,
            'time': result['time'],
            'message': message
        })
        
        return is_correct
    
    def verify_result(self, actual: dict, expected: dict) -> bool:
        """验证结果是否符合预期"""
        if not actual.get('success'):
            return False
        
        actual_instructions = actual.get('instructions', [])
        expected_instructions = expected.get('instructions', [])
        
        if len(actual_instructions) != len(expected_instructions):
            return False
        
        for actual_inst, expected_inst in zip(actual_instructions, expected_instructions):
            # 检查关键字段
            for key in ['instruction_type', 'ticker']:
                if actual_inst.get(key) != expected_inst.get(key):
                    return False
            
            # 检查价格（允许小误差）
            if expected_inst.get('price') is not None:
                actual_price = actual_inst.get('price')
                expected_price = expected_inst.get('price')
                if actual_price is None or abs(actual_price - expected_price) > 0.01:
                    return False
        
        return True
    
    def run_all_tests(self):
        """运行所有测试用例"""
        print(f"\n{'#'*60}")
        print(f"# LLM 交易指令解析能力测试 ({self.model})")
        print(f"{'#'*60}")
        
        if not self.check_model():
            return
        
        # 预热模型
        print("\n🔥 预热模型...")
        self.parse_with_llm("test", timeout=10)
        print("✅ 预热完成\n")
        
        # 测试用例
        test_cases = [
            # 1. 简单指令
            {
                'name': '简单卖出指令（完整信息）',
                'message': 'tsla 0.17 卖出 1/3',
                'history': [],
                'expected': {
                    'success': True,
                    'instructions': [{
                        'instruction_type': 'SELL',
                        'ticker': 'TSLA',
                        'price': 0.17,
                        'sell_quantity': '1/3'
                    }]
                }
            },
            
            # 2. 复杂指令（多操作）
            {
                'name': '复杂指令（卖出+止损）',
                'message': '2.53出三分之一 hon 止损剩下提高到2.3',
                'history': [],
                'expected': {
                    'success': True,
                    'instructions': [
                        {
                            'instruction_type': 'SELL',
                            'ticker': 'HON',
                            'price': 2.53,
                            'sell_quantity': '1/3'
                        },
                        {
                            'instruction_type': 'MODIFY',
                            'ticker': 'HON',
                            'stop_loss_price': 2.3
                        }
                    ]
                }
            },
            
            # 3. 上下文依赖（无ticker）
            {
                'name': '上下文依赖（缺少ticker）',
                'message': '0.17 卖出 1/3',
                'history': [
                    'TSLA 240c 2/13 0.45',
                    'NVDA 150c 2/20 2.5'
                ],
                'expected': {
                    'success': True,
                    'instructions': [{
                        'instruction_type': 'SELL',
                        'ticker': 'NVDA',  # 应该从最近的历史消息获取
                        'price': 0.17,
                        'sell_quantity': '1/3'
                    }]
                }
            },
            
            # 4. 止损指令
            {
                'name': '止损指令',
                'message': '止损提高到1.5',
                'history': ['AAPL 180c 2/28 2.0'],
                'expected': {
                    'success': True,
                    'instructions': [{
                        'instruction_type': 'MODIFY',
                        'ticker': 'AAPL',
                        'stop_loss_price': 1.5
                    }]
                }
            },
            
            # 5. 清仓指令
            {
                'name': '清仓指令',
                'message': '2.3都出 msft',
                'history': [],
                'expected': {
                    'success': True,
                    'instructions': [{
                        'instruction_type': 'CLOSE',
                        'ticker': 'MSFT',
                        'price': 2.3
                    }]
                }
            },
            
            # 6. 买入指令
            {
                'name': '买入指令',
                'message': 'BA 240c 2/13 1.25 小仓位',
                'history': [],
                'expected': {
                    'success': True,
                    'instructions': [{
                        'instruction_type': 'BUY',
                        'ticker': 'BA',
                        'option_type': 'CALL',
                        'strike': 240,
                        'expiry': '2/13',
                        'price': 1.25,
                        'position_size': '小仓位'
                    }]
                }
            },
            
            # 7. 中文数字
            {
                'name': '中文表达',
                'message': '一点七五出三分之一',
                'history': ['NVDA 150c 2/20 2.5'],
                'expected': {
                    'success': True,
                    'instructions': [{
                        'instruction_type': 'SELL',
                        'ticker': 'NVDA',
                        'price': 1.75,
                        'sell_quantity': '1/3'
                    }]
                }
            },
            
            # 8. 反向止损
            {
                'name': '反向止损（价格在前）',
                'message': '2.5止损',
                'history': ['AMD 170c 3/15 3.0'],
                'expected': {
                    'success': True,
                    'instructions': [{
                        'instruction_type': 'MODIFY',
                        'ticker': 'AMD',
                        'stop_loss_price': 2.5
                    }]
                }
            }
        ]
        
        # 执行所有测试
        for test_case in test_cases:
            self.run_test(
                test_case['name'],
                test_case['message'],
                test_case['history'],
                test_case['expected']
            )
        
        # 显示总结
        self.print_summary()
    
    def print_summary(self):
        """打印测试总结"""
        print(f"\n\n{'='*60}")
        print(f"测试总结")
        print(f"{'='*60}")
        
        total = len(self.test_results)
        success = sum(1 for r in self.test_results if r['success'])
        correct = sum(1 for r in self.test_results if r['correct'])
        avg_time = sum(r['time'] for r in self.test_results) / total if total > 0 else 0
        
        print(f"\n总测试数: {total}")
        print(f"成功解析: {success} ({success/total*100:.1f}%)")
        print(f"结果正确: {correct} ({correct/total*100:.1f}%)")
        print(f"平均耗时: {avg_time:.2f}秒")
        print(f"速度评级: {self.get_speed_rating(avg_time)}")
        
        # 失败的测试
        failed = [r for r in self.test_results if not r['correct']]
        if failed:
            print(f"\n❌ 失败的测试:")
            for r in failed:
                print(f"  - {r['name']}: {r['message']}")
        
        # 性能分级
        print(f"\n性能评估:")
        if avg_time < 1.0:
            print(f"  ✅ 响应速度: 优秀 (< 1秒)")
        elif avg_time < 2.0:
            print(f"  ⚠️  响应速度: 良好 (1-2秒)")
        else:
            print(f"  ❌ 响应速度: 较慢 (> 2秒)")
        
        if correct / total > 0.9:
            print(f"  ✅ 准确率: 优秀 (> 90%)")
        elif correct / total > 0.7:
            print(f"  ⚠️  准确率: 良好 (70-90%)")
        else:
            print(f"  ❌ 准确率: 需改进 (< 70%)")
        
        # 建议
        print(f"\n建议:")
        if avg_time >= 1.0 and correct / total >= 0.8:
            print(f"  📌 准确率较高但速度慢，建议混合方案：正则优先 + LLM兜底")
        elif avg_time < 1.0 and correct / total < 0.8:
            print(f"  📌 速度快但准确率低，建议优化提示词或使用更大模型")
        elif avg_time >= 1.0 and correct / total < 0.8:
            print(f"  📌 速度和准确率都不理想，建议使用正则解析器")
        else:
            print(f"  ✅ 性能优秀，可以考虑使用 LLM 解析方案")
    
    def get_speed_rating(self, avg_time: float) -> str:
        """获取速度评级"""
        if avg_time < 0.5:
            return "⚡ 极快"
        elif avg_time < 1.0:
            return "✅ 快"
        elif avg_time < 2.0:
            return "⚠️ 中等"
        else:
            return "❌ 慢"


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="LLM 交易指令解析能力测试")
    parser.add_argument(
        "--model", "-m",
        default="qwen2.5:1.5b",
        help="Ollama 模型名，如 qwen2.5:1.5b、qwen2.5:3b（默认: qwen2.5:1.5b）",
    )
    args = parser.parse_args()
    tester = LLMParserTester(model=args.model)
    tester.run_all_tests()


if __name__ == "__main__":
    main()
