#!/usr/bin/env python3
"""
测试反向止损模式（价格在前）
"""
from parser.option_parser import OptionParser
from models.instruction import InstructionType


def test_reverse_stop_loss():
    """测试反向止损模式识别"""
    print("\n" + "=" * 80)
    print("测试反向止损模式（价格在前）")
    print("=" * 80)
    
    test_cases = [
        {
            "message": "2.5止损剩下的ba 横盘有磨损了",
            "expected_ticker": "BA",
            "expected_stop_loss": 2.5
        },
        {
            "message": "2.5止损",
            "expected_ticker": None,
            "expected_stop_loss": 2.5
        },
        {
            "message": "3.0止损剩下的tsla",
            "expected_ticker": "TSLA",
            "expected_stop_loss": 3.0
        },
        {
            "message": "1.8SL剩下的nvda",
            "expected_ticker": "NVDA",
            "expected_stop_loss": 1.8
        },
    ]
    
    for idx, test_case in enumerate(test_cases, 1):
        message = test_case["message"]
        expected_ticker = test_case["expected_ticker"]
        expected_stop_loss = test_case["expected_stop_loss"]
        
        print(f"\n测试用例 {idx}:")
        print(f"  消息: {message}")
        
        result = OptionParser.parse(message)
        
        if result:
            print(f"  ✅ 解析成功")
            print(f"     ticker: {result.ticker}")
            print(f"     stop_loss: {result.stop_loss_price}")
            print(f"     instruction_type: {result.instruction_type}")
            
            # 验证
            assert result.instruction_type == InstructionType.MODIFY.value, \
                f"期望 MODIFY，得到 {result.instruction_type}"
            assert result.ticker == expected_ticker, \
                f"期望 ticker {expected_ticker}，得到 {result.ticker}"
            assert result.stop_loss_price == expected_stop_loss, \
                f"期望 stop_loss {expected_stop_loss}，得到 {result.stop_loss_price}"
            
            print(f"  ✓ 所有断言通过")
        else:
            print(f"  ❌ 解析失败")
            raise AssertionError(f"解析失败: {message}")


def test_normal_stop_loss_still_works():
    """测试原有的止损格式仍然有效"""
    print("\n" + "=" * 80)
    print("测试原有止损格式兼容性")
    print("=" * 80)
    
    test_cases = [
        {
            "message": "止损在2.9",
            "expected_stop_loss": 2.9
        },
        {
            "message": "SL 1.5",
            "expected_stop_loss": 1.5
        },
        {
            "message": "止损提高到3.2",
            "expected_stop_loss": 3.2
        },
    ]
    
    for idx, test_case in enumerate(test_cases, 1):
        message = test_case["message"]
        expected_stop_loss = test_case["expected_stop_loss"]
        
        print(f"\n测试用例 {idx}:")
        print(f"  消息: {message}")
        
        result = OptionParser.parse(message)
        
        if result:
            print(f"  ✅ 解析成功")
            print(f"     stop_loss: {result.stop_loss_price}")
            
            assert result.instruction_type == InstructionType.MODIFY.value
            assert result.stop_loss_price == expected_stop_loss
            
            print(f"  ✓ 断言通过")
        else:
            print(f"  ❌ 解析失败")
            raise AssertionError(f"解析失败: {message}")


def main():
    """运行所有测试"""
    print("\n" + "=" * 80)
    print("反向止损模式测试")
    print("=" * 80)
    
    try:
        test_reverse_stop_loss()
        test_normal_stop_loss_still_works()
        
        print("\n" + "=" * 80)
        print("✅ 所有测试通过！")
        print("=" * 80 + "\n")
    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}\n")
    except Exception as e:
        print(f"\n❌ 测试出错: {e}\n")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
