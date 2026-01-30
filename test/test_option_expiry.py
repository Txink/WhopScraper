"""
测试期权过期校验功能
"""
from broker import convert_to_longport_symbol
from datetime import datetime, timedelta


def test_expired_option():
    """测试已过期的期权"""
    print("\n" + "="*60)
    print("测试 1: 已过期的期权")
    print("="*60)
    
    # 测试一个已经过期的日期（昨天）
    yesterday = datetime.now() - timedelta(days=1)
    expiry = yesterday.strftime("%m/%d")
    
    try:
        symbol = convert_to_longport_symbol("AAPL", "CALL", 150.0, expiry)
        print(f"❌ 测试失败: 应该抛出 ValueError，但返回了 {symbol}")
    except ValueError as e:
        print(f"✅ 测试通过: 正确检测到过期期权")
        print(f"   错误信息: {e}")


def test_valid_future_option():
    """测试未来有效的期权"""
    print("\n" + "="*60)
    print("测试 2: 未来有效的期权")
    print("="*60)
    
    # 测试一个未来的日期（下周）
    next_week = datetime.now() + timedelta(days=7)
    expiry = next_week.strftime("%m/%d")
    
    try:
        symbol = convert_to_longport_symbol("AAPL", "CALL", 150.0, expiry)
        print(f"✅ 测试通过: 成功生成期权代码 {symbol}")
    except ValueError as e:
        print(f"❌ 测试失败: 不应该抛出异常，错误: {e}")


def test_today_option():
    """测试今天到期的期权"""
    print("\n" + "="*60)
    print("测试 3: 今天到期的期权")
    print("="*60)
    
    # 测试今天到期的期权（应该仍然有效）
    today = datetime.now()
    expiry = today.strftime("%m/%d")
    
    try:
        symbol = convert_to_longport_symbol("AAPL", "CALL", 150.0, expiry)
        print(f"✅ 测试通过: 今天到期的期权仍然有效 {symbol}")
    except ValueError as e:
        print(f"注意: 今天到期的期权被标记为过期")
        print(f"   错误信息: {e}")


def test_this_week_option():
    """测试"本周"期权"""
    print("\n" + "="*60)
    print("测试 4: '本周'期权")
    print("="*60)
    
    try:
        symbol = convert_to_longport_symbol("NVDA", "CALL", 900.0, "本周")
        print(f"✅ 测试通过: 成功生成'本周'期权代码 {symbol}")
    except ValueError as e:
        print(f"❌ 测试失败: {e}")


def test_full_date_format():
    """测试完整日期格式"""
    print("\n" + "="*60)
    print("测试 5: 完整日期格式 (YYYYMMDD)")
    print("="*60)
    
    # 测试一个过期的完整日期
    expired_date = "20240101"
    try:
        symbol = convert_to_longport_symbol("TSLA", "PUT", 250.0, expired_date)
        print(f"❌ 测试失败: 应该抛出 ValueError，但返回了 {symbol}")
    except ValueError as e:
        print(f"✅ 测试通过: 正确检测到过期期权")
        print(f"   错误信息: {e}")
    
    # 测试一个未来的完整日期
    future_date = "20261231"
    try:
        symbol = convert_to_longport_symbol("TSLA", "PUT", 250.0, future_date)
        print(f"✅ 测试通过: 成功生成期权代码 {symbol}")
    except ValueError as e:
        print(f"❌ 测试失败: 不应该抛出异常，错误: {e}")


if __name__ == "__main__":
    print("\n" + "="*60)
    print("🚀 期权过期校验测试")
    print("="*60)
    
    test_expired_option()
    test_valid_future_option()
    test_today_option()
    test_this_week_option()
    test_full_date_format()
    
    print("\n" + "="*60)
    print("✅ 所有测试完成！")
    print("="*60)
