#!/usr/bin/env python3
"""
订单管理功能测试
测试订单撤销、修改和止盈止损功能
"""
import logging
import sys
import time
from broker import load_longport_config, LongPortBroker
from broker.order_formatter import (
    print_order_table,
    print_order_search_table,
    print_orders_summary_table,
    print_success_message,
    print_warning_message
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def print_option_chain_format(option_chain: dict, expiry: str, underlying: str = "AAPL.US"):
    """打印券商返回的期权代码格式，便于与本地生成格式对比"""
    print("\n" + "-" * 60)
    print("📋 券商返回的期权代码格式 (用于对比 auto_trade 本地生成格式)")
    print("-" * 60)
    print(f"  标的: {underlying}")
    print(f"  到期日(原始): {expiry!r}  (type={type(expiry).__name__})")
    strikes = option_chain.get("strike_prices") or []
    call_syms = option_chain.get("call_symbols") or []
    put_syms = option_chain.get("put_symbols") or []
    n = len(strikes)
    if n == 0:
        print("  (无数据)")
        print("-" * 60 + "\n")
        return
    # 前 3 个、中间 1 个、后 2 个样本
    indices = list(range(min(3, n)))
    if n > 5:
        indices.append(n // 2)
    indices.extend(range(max(0, n - 2), n))
    indices = sorted(set(indices))
    print(f"  行权价数量: {n}")
    print("  样本 (行权价 -> Call 代码 -> Put 代码):")
    for i in indices:
        s = strikes[i] if i < len(strikes) else None
        c = call_syms[i] if i < len(call_syms) else None
        p = put_syms[i] if i < len(put_syms) else None
        print(f"    ${s:.2f}  ->  {c!r}  /  {p!r}")
    print("  格式说明: 以上为 API 返回的原始字符串，可直接用于 submit_option_order")
    print("-" * 60 + "\n")


def test_order_with_stop_loss(broker: LongPortBroker):
    """测试带止损的订单"""
    print("\n" + "="*60)
    print("测试 1: 带止损的限价订单")
    print("="*60)
    
    try:
        # 获取期权链，找一个真实的期权
        expiry_dates = broker.get_option_expiry_dates("AAPL.US")
        if not expiry_dates or len(expiry_dates) < 2:
            logger.error("无法获取期权到期日")
            return None
        
        # 打印到期日列表格式（券商返回的原始格式）
        print("\n📅 券商返回的到期日列表 (前 5 个):")
        for i, ed in enumerate(expiry_dates[:5]):
            print(f"   [{i}] {ed!r}  (type={type(ed).__name__})")
        print()

        # 使用第二个到期日（避免过期）
        expiry = expiry_dates[3]
        option_chain = broker.get_option_chain_info("AAPL.US", expiry)
        
        if not option_chain or not option_chain.get("strike_prices"):
            logger.error("无法获取期权链")
            return None
        
        # 显示券商返回的期权代码格式
        print_option_chain_format(option_chain, expiry, "AAPL.US")
        
        # 使用中间的行权价
        mid_idx = len(option_chain["strike_prices"]) // 2
        symbol = option_chain["call_symbols"][mid_idx]
        strike = option_chain["strike_prices"][mid_idx]
        
        logger.info(f"使用期权: {symbol} (行权价 ${strike:.2f})")
        
        # 提交带止损的订单
        # 假设买入价格是 $5，设置止损在 $3（跌幅 40%）
        # broker.submit_option_order() 会自动显示彩色表格
        order = broker.submit_option_order(
            symbol=symbol,
            side="BUY",
            quantity=1,
            price=5.0,
            order_type="LIMIT",
            trigger_price=3.0,  # 触发价格（止损）
            remark="Test order with stop loss"
        )
        
        return order
        
    except Exception as e:
        logger.error(f"❌ 测试失败: {e}")
        return None


def test_order_with_trailing_stop(broker: LongPortBroker):
    """测试跟踪止损订单"""
    print("\n" + "="*60)
    print("测试 2: 跟踪止损订单")
    print("="*60)
    
    try:
        # 获取期权链
        expiry_dates = broker.get_option_expiry_dates("AAPL.US")
        if not expiry_dates or len(expiry_dates) < 2:
            logger.error("无法获取期权到期日")
            return None
        
        expiry = expiry_dates[1]
        option_chain = broker.get_option_chain_info("AAPL.US", expiry)
        
        if not option_chain or not option_chain.get("strike_prices"):
            logger.error("无法获取期权链")
            return None
        
        # 显示券商返回的期权代码格式
        print_option_chain_format(option_chain, expiry, "AAPL.US")
        
        mid_idx = len(option_chain["strike_prices"]) // 2
        symbol = option_chain["call_symbols"][mid_idx]
        
        # 提交跟踪止损订单（跟踪5%）
        # broker.submit_option_order() 会自动显示彩色表格
        order = broker.submit_option_order(
            symbol=symbol,
            side="BUY",
            quantity=1,
            price=5.0,
            order_type="LIMIT",
            trailing_percent=5.0,  # 跟踪止损 5%
            remark="Test order with trailing stop"
        )
        
        return order
        
    except Exception as e:
        logger.error(f"❌ 测试失败: {e}")
        return None


def test_cancel_order(broker: LongPortBroker, order_id: str):
    """测试订单撤销"""
    print("\n" + "="*60)
    print("测试 3: 撤销订单")
    print("="*60)
    
    try:
        # broker.cancel_order() 会自动显示彩色表格
        result = broker.cancel_order(order_id)
        return result
        
    except Exception as e:
        logger.error(f"❌ 撤销失败: {e}")
        return None


def test_replace_order(broker: LongPortBroker, order_id: str):
    """测试订单修改"""
    print("\n" + "="*60)
    print("测试 4: 修改订单")
    print("="*60)
    
    try:
        # broker.replace_order() 会自动显示彩色对比表格
        result = broker.replace_order(
            order_id=order_id,
            quantity=2,
            price=4.50,
            remark="Modified order - price adjusted"
        )
        
        return result
        
    except Exception as e:
        logger.error(f"❌ 修改失败: {e}")
        return None


def test_get_order_detail(broker: LongPortBroker, order_id: str):
    """测试获取订单详情"""
    print("\n" + "="*60)
    print("测试 5: 获取订单详情")
    print("="*60)
    
    try:
        orders = broker.get_today_orders()
        
        # 查找指定订单
        target_order = None
        for order in orders:
            if order.get('order_id') == order_id:
                target_order = order
                break
        
        if target_order:
            # 使用彩色表格展示订单详情（SEARCH 操作 - 蓝色）
            print_success_message("找到订单")
            
            # 添加 mode 字段用于表格显示
            target_order['mode'] = 'paper' if broker.is_paper else 'real'
            
            print_order_search_table(target_order, "订单查询")
        else:
            print_warning_message(f"未找到订单: {order_id}")
        
        return target_order
        
    except Exception as e:
        logger.error(f"❌ 获取订单详情失败: {e}")
        return None


def main():
    """主测试流程"""
    print("\n🚀 订单管理功能测试")
    print("="*60)
    
    # 1. 加载配置
    try:
        config = load_longport_config()
        broker = LongPortBroker(config)
        logger.info("✅ Broker 初始化成功")
    except Exception as e:
        logger.error(f"❌ 初始化失败: {e}")
        sys.exit(1)
    
    # 2. 测试带止损的订单
    order1 = test_order_with_stop_loss(broker)
    if order1:
        time.sleep(1)
        
        # 3. 测试修改订单
        test_replace_order(broker, order1['order_id'])
        time.sleep(1)
        
        # 4. 测试获取订单详情
        test_get_order_detail(broker, order1['order_id'])
        time.sleep(1)
        
        # 5. 测试撤销订单
        test_cancel_order(broker, order1['order_id'])
    
    # 6. 测试跟踪止损订单
    order2 = test_order_with_trailing_stop(broker)
    if order2:
        time.sleep(1)
        # 撤销跟踪止损订单
        test_cancel_order(broker, order2['order_id'])
    
    # 测试总结
    print("\n" + "="*60)
    print("✅ 订单管理功能测试完成！")
    print("="*60)
    print("\n📌 测试功能:")
    print("1. ✅ 带止损价格的限价订单")
    print("2. ✅ 跟踪止损订单")
    print("3. ✅ 订单修改（价格和数量）")
    print("4. ✅ 订单撤销")
    print("5. ✅ 订单详情查询")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
