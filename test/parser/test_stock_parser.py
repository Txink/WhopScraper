"""
正股解析器测试
测试正股交易信号的解析准确性
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from parser.stock_parser import StockParser


def test_buy_patterns():
    """测试买入指令解析"""
    test_cases = [
        ("AAPL 买入 $150", "AAPL", 150.0),
        ("买入 TSLA 在 $250", "TSLA", 250.0),
        ("NVDA $900 买", "NVDA", 900.0),
    ]
    
    passed = 0
    failed = 0
    
    for msg, expected_ticker, expected_price in test_cases:
        result = StockParser.parse(msg)
        if result:
            if (result.ticker == expected_ticker and 
                result.price == expected_price and
                result.option_type == 'STOCK' and
                result.instruction_type == "OPEN"):
                print(f"✅ PASS: {msg}")
                passed += 1
            else:
                print(f"❌ FAIL: {msg}")
                print(f"   Expected: {expected_ticker} {expected_price}")
                print(f"   Got: {result.ticker} {result.price} {result.option_type} {result.instruction_type}")
                failed += 1
        else:
            print(f"❌ FAIL: {msg} - 未能解析")
            failed += 1
    
    return passed, failed


def test_sell_patterns():
    """测试卖出指令解析"""
    test_cases = [
        ("AAPL 卖出 $180", "AAPL", 180.0),
        ("卖出 TSLA 在 $300", "TSLA", 300.0),
        ("NVDA $950 出", "NVDA", 950.0),
    ]
    
    passed = 0
    failed = 0
    
    for msg, expected_ticker, expected_price in test_cases:
        result = StockParser.parse(msg)
        if result:
            if (result.ticker == expected_ticker and 
                result.price == expected_price and
                result.option_type == 'STOCK' and
                result.instruction_type == "TAKE_PROFIT"):
                print(f"✅ PASS: {msg}")
                passed += 1
            else:
                print(f"❌ FAIL: {msg}")
                failed += 1
        else:
            print(f"❌ FAIL: {msg} - 未能解析")
            failed += 1
    
    return passed, failed


def test_stop_loss_patterns():
    """测试止损指令解析"""
    test_cases = [
        ("AAPL 止损 $145", "AAPL", 145.0),
        ("止损 TSLA 在 $240", "TSLA", 240.0),
    ]
    
    passed = 0
    failed = 0
    
    for msg, expected_ticker, expected_price in test_cases:
        result = StockParser.parse(msg)
        if result and result.instruction_type == "STOP_LOSS":
            if result.ticker == expected_ticker and result.price == expected_price:
                print(f"✅ PASS: {msg}")
                passed += 1
            else:
                print(f"❌ FAIL: {msg}")
                failed += 1
        else:
            print(f"❌ FAIL: {msg} - 未能解析或类型错误")
            failed += 1
    
    return passed, failed


def main():
    """运行所有测试"""
    print("=" * 60)
    print("正股解析器测试")
    print("=" * 60)
    
    total_passed = 0
    total_failed = 0
    
    print("\n【买入指令测试】")
    p, f = test_buy_patterns()
    total_passed += p
    total_failed += f
    
    print("\n【卖出指令测试】")
    p, f = test_sell_patterns()
    total_passed += p
    total_failed += f
    
    print("\n【止损指令测试】")
    p, f = test_stop_loss_patterns()
    total_passed += p
    total_failed += f
    
    print("\n" + "=" * 60)
    print(f"测试完成: {total_passed} 通过, {total_failed} 失败")
    print("=" * 60)
    
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
