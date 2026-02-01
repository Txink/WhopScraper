"""
解析器覆盖率测试
基于数据集测试解析器的覆盖率
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from samples.dataset_manager import DatasetManager


def test_option_parser_coverage():
    """测试期权解析器覆盖率"""
    print("\n" + "=" * 70)
    print("期权解析器覆盖率测试")
    print("=" * 70)
    
    manager = DatasetManager()
    report = manager.generate_report('option')
    print(report)
    
    # 导出未解析样本
    results = manager.test_all('option')
    overall = results.get('overall', {})
    
    if overall.get('unparsed', 0) > 0:
        print("\n发现未解析样本，导出到 test_option_unparsed.json")
        manager.export_unparsed('option', 'test_option_unparsed.json')
    
    return overall.get('coverage', 0)


def test_stock_parser_coverage():
    """测试正股解析器覆盖率"""
    print("\n" + "=" * 70)
    print("正股解析器覆盖率测试")
    print("=" * 70)
    
    manager = DatasetManager()
    report = manager.generate_report('stock')
    print(report)
    
    # 导出未解析样本
    results = manager.test_all('stock')
    overall = results.get('overall', {})
    
    if overall.get('unparsed', 0) > 0:
        print("\n发现未解析样本，导出到 test_stock_unparsed.json")
        manager.export_unparsed('stock', 'test_stock_unparsed.json')
    
    return overall.get('coverage', 0)


def main():
    """运行所有覆盖率测试"""
    option_coverage = test_option_parser_coverage()
    stock_coverage = test_stock_parser_coverage()
    
    print("\n" + "=" * 70)
    print("覆盖率汇总")
    print("=" * 70)
    print(f"期权解析器覆盖率: {option_coverage:.1f}%")
    print(f"正股解析器覆盖率: {stock_coverage:.1f}%")
    print("=" * 70)
    
    # 如果覆盖率低于80%，返回失败
    if option_coverage < 80.0 or stock_coverage < 80.0:
        print("\n⚠️  警告: 覆盖率低于 80%，建议完善解析规则")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
