"""
测试 GOLD 期权合约是否能在 LongPort 上找到
"""
from broker import load_longport_config, LongPortBroker

def test_gold_symbol():
    print("=" * 80)
    print("测试 GOLD 期权合约查询")
    print("=" * 80)
    
    # 加载配置并初始化 broker
    config = load_longport_config()
    broker = LongPortBroker(config)
    
    # 测试1：查询 GOLD 的期权到期日列表
    print("\n1. 查询 GOLD 的期权到期日列表...")
    try:
        expiry_dates = broker.get_option_expiry_dates("GOLD")
        print(f"   ✅ 找到 {len(expiry_dates)} 个到期日:")
        for date in expiry_dates[:5]:
            print(f"      - {date}")
    except Exception as e:
        print(f"   ❌ 查询失败: {e}")
    
    # 测试2：查询 2026-02-20 的期权链
    print("\n2. 查询 GOLD 2026-02-20 的期权链...")
    try:
        option_chain = broker.get_option_chain_info("GOLD", "260220")
        print(f"   ✅ 找到期权链信息")
        
        # 提取 strike prices
        strikes = option_chain.get('strike_prices', [])
        print(f"   找到 {len(strikes)} 个行权价")
        print(f"   前10个行权价: {strikes[:10]}")
        
        # 检查是否有 60 这个行权价
        if 60.0 in strikes:
            print(f"   ✅ 找到行权价 $60")
            
            # 尝试查询这个行权价的 call 合约
            calls = option_chain.get('call_symbols', [])
            puts = option_chain.get('put_symbols', [])
            print(f"   Call 合约数: {len(calls)}")
            print(f"   Put 合约数: {len(puts)}")
            
            # 查找包含 60 的合约
            call_60 = [s for s in calls if '060' in s or '60' in s]
            print(f"   包含60的Call合约: {call_60}")
        else:
            print(f"   ⚠️  没有找到行权价 $60")
            print(f"   最接近的行权价: {[s for s in strikes if 55 <= s <= 65]}")
    except Exception as e:
        print(f"   ❌ 查询失败: {e}")
    
    # 测试3：直接查询 GOLD260220C060000.US 的报价
    print("\n3. 查询 GOLD260220C060000.US 的报价...")
    try:
        symbol = "GOLD260220C060000.US"
        quotes = broker.get_option_quote([symbol])
        if quotes and len(quotes) > 0:
            print(f"   ✅ 找到报价:")
            quote = quotes[0]
            print(f"      - 最新价: ${quote.get('last_done', 0):.2f}")
            print(f"      - 行权价: ${quote.get('strike_price', 0):.2f}")
        else:
            print(f"   ❌ 无法获取报价（返回空列表）")
    except Exception as e:
        print(f"   ❌ 查询失败: {e}")
    
    # 测试4：尝试查询 GLD（如果 GOLD 不对）
    print("\n4. 对比：查询 GLD (SPDR Gold Trust) 的期权...")
    try:
        expiry_dates = broker.get_option_expiry_dates("GLD")
        print(f"   ✅ GLD 找到 {len(expiry_dates)} 个到期日")
    except Exception as e:
        print(f"   ❌ GLD 查询失败: {e}")
    
    print("\n" + "=" * 80)

if __name__ == "__main__":
    test_gold_symbol()
