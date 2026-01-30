"""
测试期权过期校验在实际场景中的集成
"""
from datetime import datetime, timedelta
from parser.option_parser import OptionParser
from broker import convert_to_longport_symbol
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_expired_option_in_real_scenario():
    """测试实际场景中已过期的期权"""
    print("\n" + "="*60)
    print("集成测试: 实际场景 - 已过期期权")
    print("="*60)
    
    # 模拟一个昨天到期的期权指令
    yesterday = datetime.now() - timedelta(days=1)
    expiry_str = yesterday.strftime("%m/%d")
    
    message = f"AAPL - $150 CALLS {expiry_str} $2.5"
    
    logger.info(f"原始消息: {message}")
    
    # 1. 解析指令
    instruction = OptionParser.parse(message)
    
    if not instruction:
        logger.error("❌ 指令解析失败")
        return
    
    logger.info(f"✅ 指令解析成功: {instruction}")
    
    # 2. 尝试转换期权代码（应该抛出异常）
    try:
        symbol = convert_to_longport_symbol(
            ticker=instruction.ticker,
            option_type=instruction.option_type,
            strike=instruction.strike,
            expiry=instruction.expiry
        )
        logger.error(f"❌ 测试失败: 应该抛出异常，但返回了 {symbol}")
    except ValueError as e:
        logger.info(f"✅ 测试通过: 正确拦截过期期权")
        logger.info(f"   错误信息: {e}")
        logger.warning(f"⚠️  跳过开仓指令 - {message}")


def test_valid_option_in_real_scenario():
    """测试实际场景中有效的期权"""
    print("\n" + "="*60)
    print("集成测试: 实际场景 - 有效期权")
    print("="*60)
    
    # 模拟一个未来到期的期权指令
    next_week = datetime.now() + timedelta(days=7)
    expiry_str = next_week.strftime("%m/%d")
    
    message = f"TSLA - $250 PUTS {expiry_str} $3.0 小仓位"
    
    logger.info(f"原始消息: {message}")
    
    # 1. 解析指令
    instruction = OptionParser.parse(message)
    
    if not instruction:
        logger.error("❌ 指令解析失败")
        return
    
    logger.info(f"✅ 指令解析成功: {instruction}")
    
    # 2. 转换期权代码
    try:
        symbol = convert_to_longport_symbol(
            ticker=instruction.ticker,
            option_type=instruction.option_type,
            strike=instruction.strike,
            expiry=instruction.expiry
        )
        logger.info(f"✅ 测试通过: 成功生成期权代码 {symbol}")
        logger.info(f"   期权到期日: {next_week.strftime('%Y-%m-%d')}")
        logger.info(f"   距离到期: {(next_week - datetime.now()).days} 天")
    except ValueError as e:
        logger.error(f"❌ 测试失败: 不应该抛出异常，错误: {e}")


def test_this_week_option():
    """测试"本周"期权（永远有效）"""
    print("\n" + "="*60)
    print("集成测试: 实际场景 - 本周期权")
    print("="*60)
    
    message = "NVDA - $900 CALLS 本周 $5.0"
    
    logger.info(f"原始消息: {message}")
    
    # 1. 解析指令
    instruction = OptionParser.parse(message)
    
    if not instruction:
        logger.error("❌ 指令解析失败")
        return
    
    logger.info(f"✅ 指令解析成功: {instruction}")
    
    # 2. 转换期权代码
    try:
        symbol = convert_to_longport_symbol(
            ticker=instruction.ticker,
            option_type=instruction.option_type,
            strike=instruction.strike,
            expiry=instruction.expiry or "本周"
        )
        logger.info(f"✅ 测试通过: 成功生成'本周'期权代码 {symbol}")
    except ValueError as e:
        logger.error(f"❌ 测试失败: {e}")


if __name__ == "__main__":
    print("\n" + "="*60)
    print("🚀 期权过期校验 - 集成测试")
    print("="*60)
    
    test_expired_option_in_real_scenario()
    test_valid_option_in_real_scenario()
    test_this_week_option()
    
    print("\n" + "="*60)
    print("✅ 所有集成测试完成！")
    print("="*60)
    print("\n💡 说明:")
    print("  - 已过期的期权将被自动拦截，不会执行下单")
    print("  - 有效的期权将正常处理")
    print("  - '本周'期权将自动计算到本周五")
    print("="*60 + "\n")
