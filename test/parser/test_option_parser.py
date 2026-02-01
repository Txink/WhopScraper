"""
期权解析器测试
测试期权信号的解析准确性
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from parser.option_parser import OptionParser


def test_open_position_patterns():
    """测试开仓指令解析"""
    test_cases = [
        ("INTC - $48 CALLS 本周 $1.2", "INTC", 48.0, "CALL", 1.2),
        ("AAPL $150 PUTS 1/31 $2.5", "AAPL", 150.0, "PUT", 2.5),
        ("TSLA - 250 CALL $3.0 小仓位", "TSLA", 250.0, "CALL", 3.0),
    ]
    
    passed = 0
    failed = 0
    
    for msg, expected_ticker, expected_strike, expected_type, expected_price in test_cases:
        result = OptionParser.parse(msg)
        if result:
            if (result.ticker == expected_ticker and 
                result.strike == expected_strike and
                result.option_type == expected_type and
                result.price == expected_price):
                print(f"✅ PASS: {msg}")
                passed += 1
            else:
                print(f"❌ FAIL: {msg}")
                print(f"   Expected: {expected_ticker} {expected_strike} {expected_type} {expected_price}")
                print(f"   Got: {result.ticker} {result.strike} {result.option_type} {result.price}")
                failed += 1
        else:
            print(f"❌ FAIL: {msg} - 未能解析")
            failed += 1
    
    return passed, failed


def test_stop_loss_patterns():
    """测试止损指令解析"""
    test_cases = [
        ("止损 0.95", 0.95),
        ("止损在1.00", 1.00),
        ("SL 1.5", 1.5),
    ]
    
    passed = 0
    failed = 0
    
    for msg, expected_price in test_cases:
        result = OptionParser.parse(msg)
        if result and result.instruction_type == "STOP_LOSS":
            if result.price == expected_price:
                print(f"✅ PASS: {msg}")
                passed += 1
            else:
                print(f"❌ FAIL: {msg}")
                print(f"   Expected price: {expected_price}")
                print(f"   Got price: {result.price}")
                failed += 1
        else:
            print(f"❌ FAIL: {msg} - 未能解析或类型错误")
            failed += 1
    
    return passed, failed


def test_take_profit_patterns():
    """测试止盈指令解析"""
    test_cases = [
        ("1.75出三分之一", 1.75, "1/3"),
        ("2.0 出一半", 2.0, "1/2"),
        ("1.65附近出剩下三分之二", 1.65, "2/3"),
    ]
    
    passed = 0
    failed = 0
    
    for msg, expected_price, expected_portion in test_cases:
        result = OptionParser.parse(msg)
        if result and result.instruction_type == "TAKE_PROFIT":
            if result.price == expected_price and result.portion == expected_portion:
                print(f"✅ PASS: {msg}")
                passed += 1
            else:
                print(f"❌ FAIL: {msg}")
                print(f"   Expected: {expected_price} {expected_portion}")
                print(f"   Got: {result.price} {result.portion}")
                failed += 1
        else:
            print(f"❌ FAIL: {msg} - 未能解析或类型错误")
            failed += 1
    
    return passed, failed


def main():
    """运行所有测试"""
    print("=" * 60)
    print("期权解析器测试")
    print("=" * 60)
    
    total_passed = 0
    total_failed = 0
    
    print("\n【开仓指令测试】")
    p, f = test_open_position_patterns()
    total_passed += p
    total_failed += f
    
    print("\n【止损指令测试】")
    p, f = test_stop_loss_patterns()
    total_passed += p
    total_failed += f
    
    print("\n【止盈指令测试】")
    p, f = test_take_profit_patterns()
    total_passed += p
    total_failed += f
    
    print("\n" + "=" * 60)
    print(f"测试完成: {total_passed} 通过, {total_failed} 失败")
    print("=" * 60)
    
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
