"""
数据集管理器
管理期权和正股信号数据集，用于测试解析器准确率
"""
import os
import json
from typing import List, Dict, Optional
from pathlib import Path

from parser.option_parser import OptionParser
from parser.stock_parser import StockParser


class DatasetManager:
    """数据集管理器"""
    
    def __init__(self, data_dir: str = "samples/data"):
        """
        初始化数据集管理器
        
        Args:
            data_dir: 数据集根目录
        """
        self.data_dir = Path(data_dir)
        
        # 数据集路径
        self.option_dir = self.data_dir / "option_signals"
        self.stock_dir = self.data_dir / "stock_signals"
        
        # 确保目录存在
        self.option_dir.mkdir(parents=True, exist_ok=True)
        self.stock_dir.mkdir(parents=True, exist_ok=True)
    
    def load_dataset(self, dataset_type: str, category: str) -> List[Dict]:
        """
        加载数据集文件
        
        Args:
            dataset_type: 数据集类型 ('option' 或 'stock')
            category: 类别 (如 'open_position', 'stop_loss', 'buy', 'sell')
            
        Returns:
            数据集列表
        """
        if dataset_type == 'option':
            file_path = self.option_dir / f"{category}.json"
        elif dataset_type == 'stock':
            file_path = self.stock_dir / f"{category}.json"
        else:
            raise ValueError(f"不支持的数据集类型: {dataset_type}")
        
        if not file_path.exists():
            print(f"⚠️  数据集文件不存在: {file_path}")
            return []
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return data if isinstance(data, list) else []
    
    def save_dataset(self, dataset_type: str, category: str, data: List[Dict]):
        """
        保存数据集文件
        
        Args:
            dataset_type: 数据集类型
            category: 类别
            data: 数据列表
        """
        if dataset_type == 'option':
            file_path = self.option_dir / f"{category}.json"
        elif dataset_type == 'stock':
            file_path = self.stock_dir / f"{category}.json"
        else:
            raise ValueError(f"不支持的数据集类型: {dataset_type}")
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"✅ 已保存数据集: {file_path} ({len(data)} 条)")
    
    def add_sample(
        self,
        dataset_type: str,
        category: str,
        message: str,
        expected_result: Optional[Dict] = None,
        notes: str = ""
    ):
        """
        添加新样本到数据集
        
        Args:
            dataset_type: 数据集类型
            category: 类别
            message: 消息文本
            expected_result: 期望的解析结果
            notes: 备注
        """
        dataset = self.load_dataset(dataset_type, category)
        
        # 检查是否已存在
        for item in dataset:
            if item.get('message') == message:
                print(f"⚠️  样本已存在: {message}")
                return
        
        sample = {
            'message': message,
            'expected': expected_result,
            'notes': notes
        }
        
        dataset.append(sample)
        self.save_dataset(dataset_type, category, dataset)
        print(f"✅ 已添加样本到 {dataset_type}/{category}")
    
    def test_parser(self, dataset_type: str, category: str) -> Dict:
        """
        测试解析器对指定数据集的覆盖率
        
        Args:
            dataset_type: 数据集类型
            category: 类别
            
        Returns:
            测试结果统计
        """
        dataset = self.load_dataset(dataset_type, category)
        
        if not dataset:
            return {
                'total': 0,
                'parsed': 0,
                'unparsed': 0,
                'coverage': 0.0,
                'unparsed_samples': []
            }
        
        # 选择解析器
        if dataset_type == 'option':
            parser = OptionParser
        else:
            parser = StockParser
        
        parsed_count = 0
        unparsed_samples = []
        
        for item in dataset:
            message = item.get('message', '')
            instruction = parser.parse(message)
            
            if instruction:
                parsed_count += 1
            else:
                unparsed_samples.append({
                    'message': message,
                    'expected': item.get('expected'),
                    'notes': item.get('notes', '')
                })
        
        total = len(dataset)
        coverage = (parsed_count / total * 100) if total > 0 else 0.0
        
        return {
            'total': total,
            'parsed': parsed_count,
            'unparsed': total - parsed_count,
            'coverage': coverage,
            'unparsed_samples': unparsed_samples
        }
    
    def test_all(self, dataset_type: str) -> Dict:
        """
        测试指定类型的所有数据集
        
        Args:
            dataset_type: 数据集类型 ('option' 或 'stock')
            
        Returns:
            所有类别的测试结果
        """
        if dataset_type == 'option':
            categories = ['open_position', 'stop_loss', 'take_profit']
        else:
            categories = ['buy', 'sell']
        
        results = {}
        total_samples = 0
        total_parsed = 0
        
        for category in categories:
            result = self.test_parser(dataset_type, category)
            results[category] = result
            total_samples += result['total']
            total_parsed += result['parsed']
        
        # 计算总体覆盖率
        overall_coverage = (total_parsed / total_samples * 100) if total_samples > 0 else 0.0
        
        results['overall'] = {
            'total': total_samples,
            'parsed': total_parsed,
            'unparsed': total_samples - total_parsed,
            'coverage': overall_coverage
        }
        
        return results
    
    def generate_report(self, dataset_type: str) -> str:
        """
        生成解析覆盖率报告
        
        Args:
            dataset_type: 数据集类型
            
        Returns:
            报告文本
        """
        results = self.test_all(dataset_type)
        
        report = []
        report.append("=" * 70)
        report.append(f"{dataset_type.upper()} 解析器覆盖率报告")
        report.append("=" * 70)
        report.append("")
        
        # 按类别显示结果
        for category, result in results.items():
            if category == 'overall':
                continue
            
            report.append(f"【{category}】")
            report.append(f"  总样本数: {result['total']}")
            report.append(f"  成功解析: {result['parsed']}")
            report.append(f"  未能解析: {result['unparsed']}")
            report.append(f"  覆盖率: {result['coverage']:.1f}%")
            
            if result['unparsed_samples']:
                report.append(f"  未解析样本:")
                for sample in result['unparsed_samples'][:5]:  # 只显示前5个
                    report.append(f"    - {sample['message']}")
                if len(result['unparsed_samples']) > 5:
                    report.append(f"    ... 还有 {len(result['unparsed_samples']) - 5} 条")
            
            report.append("")
        
        # 总体统计
        overall = results.get('overall', {})
        report.append("【总体统计】")
        report.append(f"  总样本数: {overall.get('total', 0)}")
        report.append(f"  成功解析: {overall.get('parsed', 0)}")
        report.append(f"  未能解析: {overall.get('unparsed', 0)}")
        report.append(f"  覆盖率: {overall.get('coverage', 0):.1f}%")
        report.append("")
        report.append("=" * 70)
        
        return "\n".join(report)
    
    def export_unparsed(self, dataset_type: str, output_file: str):
        """
        导出所有未能解析的样本
        
        Args:
            dataset_type: 数据集类型
            output_file: 输出文件路径
        """
        results = self.test_all(dataset_type)
        
        all_unparsed = []
        for category, result in results.items():
            if category == 'overall':
                continue
            
            for sample in result.get('unparsed_samples', []):
                all_unparsed.append({
                    'category': category,
                    'message': sample['message'],
                    'expected': sample.get('expected'),
                    'notes': sample.get('notes', '')
                })
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(all_unparsed, f, ensure_ascii=False, indent=2)
        
        print(f"✅ 已导出 {len(all_unparsed)} 条未解析样本到: {output_file}")
    
    def list_datasets(self) -> Dict[str, List[str]]:
        """
        列出所有可用的数据集
        
        Returns:
            数据集列表字典
        """
        datasets = {
            'option': [],
            'stock': []
        }
        
        # 扫描期权数据集
        if self.option_dir.exists():
            for file_path in self.option_dir.glob("*.json"):
                datasets['option'].append(file_path.stem)
        
        # 扫描正股数据集
        if self.stock_dir.exists():
            for file_path in self.stock_dir.glob("*.json"):
                datasets['stock'].append(file_path.stem)
        
        return datasets


def main():
    """命令行入口"""
    import sys
    
    if len(sys.argv) < 2:
        print("用法:")
        print("  python -m samples.dataset_manager list              # 列出所有数据集")
        print("  python -m samples.dataset_manager test <type>       # 测试解析器覆盖率")
        print("  python -m samples.dataset_manager report <type>     # 生成覆盖率报告")
        print("  python -m samples.dataset_manager export <type> <file>  # 导出未解析样本")
        print("")
        print("参数:")
        print("  <type>: option 或 stock")
        return
    
    manager = DatasetManager()
    command = sys.argv[1]
    
    if command == "list":
        datasets = manager.list_datasets()
        print("\n可用数据集:")
        print("\n期权数据集:")
        for name in datasets['option']:
            dataset = manager.load_dataset('option', name)
            print(f"  - {name}: {len(dataset)} 条样本")
        
        print("\n正股数据集:")
        for name in datasets['stock']:
            dataset = manager.load_dataset('stock', name)
            print(f"  - {name}: {len(dataset)} 条样本")
    
    elif command == "test":
        if len(sys.argv) < 3:
            print("错误: 请指定数据集类型 (option 或 stock)")
            return
        
        dataset_type = sys.argv[2]
        results = manager.test_all(dataset_type)
        
        print(f"\n{dataset_type.upper()} 解析器测试结果:")
        for category, result in results.items():
            if category == 'overall':
                continue
            print(f"\n{category}:")
            print(f"  覆盖率: {result['coverage']:.1f}% ({result['parsed']}/{result['total']})")
        
        overall = results['overall']
        print(f"\n总体覆盖率: {overall['coverage']:.1f}% ({overall['parsed']}/{overall['total']})")
    
    elif command == "report":
        if len(sys.argv) < 3:
            print("错误: 请指定数据集类型 (option 或 stock)")
            return
        
        dataset_type = sys.argv[2]
        report = manager.generate_report(dataset_type)
        print(report)
    
    elif command == "export":
        if len(sys.argv) < 4:
            print("错误: 请指定数据集类型和输出文件")
            print("示例: python -m samples.dataset_manager export option unparsed.json")
            return
        
        dataset_type = sys.argv[2]
        output_file = sys.argv[3]
        manager.export_unparsed(dataset_type, output_file)
    
    else:
        print(f"未知命令: {command}")


if __name__ == "__main__":
    main()
