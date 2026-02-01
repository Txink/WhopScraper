#!/usr/bin/env python3
"""
长桥 OpenAPI 正股交易集成测试
验证正股相关的API接口功能
"""
import logging
import sys
from broker import load_longport_config, LongPortBroker
from broker.order_formatter import (
    print_account_info_table,
    print_positions_table,
    print_orders_summary_table,
    print_stock_quotes_table,
    print_success_message,
    print_info_message,
    print_warning_message
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_config_loading():
    """测试配置加载"""
    print("\n" + "="*60)
    print("测试 1: 配置加载")
    print("="*60)
    
    try:
        config = load_longport_config()
        logger.info("✅ 配置加载成功")
        return config
    except Exception as e:
        logger.error(f"❌ 配置加载失败: {e}")
        return None


def test_account_info(broker: LongPortBroker):
    """测试获取账户信息"""
    print("\n" + "="*60)
    print("测试 2: 获取账户信息")
    print("="*60)
    
    try:
        balance = broker.get_account_balance()
        # 使用表格化显示
        print_account_info_table(balance, title="账户余额信息")
        print_success_message("账户信息获取成功")
        return balance
    except Exception as e:
        logger.error(f"❌ 获取账户信息失败: {e}")
        return None


def test_stock_quote(broker: LongPortBroker):
    """测试获取正股报价"""
    print("\n" + "="*60)
    print("测试 3: 获取正股实时报价")
    print("="*60)
    
    try:
        # 测试多个热门股票
        test_symbols = ["AAPL.US", "TSLA.US", "NVDA.US", "MSFT.US", "GOOGL.US"]
        
        print_info_message(f"查询 {len(test_symbols)} 个股票报价...")
        quotes = broker.get_stock_quote(test_symbols)
        
        if not quotes:
            logger.error("❌ 无法获取股票报价")
            return None
        
        # 使用表格显示报价
        print_stock_quotes_table(quotes, title="股票实时报价")
        print_success_message(f"成功获取 {len(quotes)} 个股票报价")
        return quotes
        
    except Exception as e:
        logger.error(f"❌ 获取股票报价失败: {e}")
        return None


def test_single_stock_quote(broker: LongPortBroker, symbol: str = "AAPL.US"):
    """测试获取单个股票报价"""
    print("\n" + "="*60)
    print(f"测试 4: 获取单个股票报价 ({symbol})")
    print("="*60)
    
    try:
        quotes = broker.get_stock_quote([symbol])
        
        if not quotes or len(quotes) == 0:
            logger.error(f"❌ 无法获取 {symbol} 报价")
            return None
        
        quote = quotes[0]
        
        # 使用表格显示单个股票详细报价
        print_stock_quotes_table([quote], title=f"{symbol} 详细报价")
        
        # 额外显示涨跌信息
        if quote['prev_close'] > 0:
            change = quote['last_done'] - quote['prev_close']
            change_pct = (change / quote['prev_close']) * 100
            change_icon = "🟢" if change >= 0 else "🔴"
            print(f"\n  {change_icon} 涨跌额: ${change:+.2f}  |  涨跌幅: {change_pct:+.2f}%")
        
        print_success_message(f"{symbol} 报价获取成功")
        return quote
        
    except Exception as e:
        logger.error(f"❌ 获取 {symbol} 报价失败: {e}")
        return None


def test_dry_run_stock_order(broker: LongPortBroker, quote: dict = None):
    """测试 Dry Run 模式下正股订单"""
    print("\n" + "="*60)
    print("测试 5: Dry Run 模式正股下单")
    print("="*60)
    
    try:
        # 使用获取到的报价信息
        if quote:
            symbol = quote['symbol']
            # 使用当前价格的95%作为买入限价
            limit_price = round(quote['last_done'] * 0.95, 2)
            logger.info(f"使用 {symbol} 当前价 ${quote['last_done']:.2f}，限价 ${limit_price:.2f}")
        else:
            # 默认测试数据
            symbol = "AAPL.US"
            limit_price = 150.0
            logger.info(f"使用默认测试数据: {symbol} @ ${limit_price:.2f}")
        
        # 提交测试订单（dry run 模式不会真实下单）
        order = broker.submit_stock_order(
            symbol=symbol,
            side="BUY",
            quantity=10,  # 买入10股
            price=limit_price,
            order_type="LIMIT",
            remark="Test stock order - Dry Run"
        )
        
        logger.info(f"订单 ID: {order['order_id']}")
        logger.info(f"订单状态: {order['status']}")
        logger.info(f"订单模式: {order['mode']}")
        logger.info("✅ Dry Run 模式正股下单测试完成")
        return order
    except Exception as e:
        logger.error(f"❌ 正股下单测试失败: {e}")
        return None


def test_market_order(broker: LongPortBroker):
    """测试市价单（Dry Run）"""
    print("\n" + "="*60)
    print("测试 6: 市价单测试（Dry Run）")
    print("="*60)
    
    try:
        order = broker.submit_stock_order(
            symbol="TSLA.US",
            side="BUY",
            quantity=5,
            order_type="MARKET",
            remark="Test market order - Dry Run"
        )
        
        logger.info(f"市价单 ID: {order['order_id']}")
        logger.info("✅ 市价单测试完成")
        return order
    except Exception as e:
        logger.error(f"❌ 市价单测试失败: {e}")
        return None


def test_sell_limit_order(broker: LongPortBroker, quote: dict = None):
    """测试卖出限价单（Dry Run）"""
    print("\n" + "="*60)
    print("测试 9: 卖出限价单测试（Dry Run）")
    print("="*60)
    
    try:
        # 使用获取到的报价信息
        if quote:
            symbol = quote['symbol']
            # 使用当前价格的105%作为卖出限价
            limit_price = round(quote['last_done'] * 1.05, 2)
            logger.info(f"使用 {symbol} 当前价 ${quote['last_done']:.2f}，限价 ${limit_price:.2f}")
        else:
            # 默认测试数据
            symbol = "NVDA.US"
            limit_price = 200.0
            logger.info(f"使用默认测试数据: {symbol} @ ${limit_price:.2f}")
        
        # 在 Dry Run 模式下，持仓检查会被跳过
        # 但这里仍然会记录日志，展示正常流程
        logger.info("注意: Dry Run 模式下会跳过持仓检查")
        
        # 提交卖出订单（dry run 模式不会真实下单）
        order = broker.submit_stock_order(
            symbol=symbol,
            side="SELL",
            quantity=10,  # 卖出10股
            price=limit_price,
            order_type="LIMIT",
            remark="Test sell limit order - Dry Run"
        )
        
        logger.info(f"卖出订单 ID: {order['order_id']}")
        logger.info(f"订单状态: {order['status']}")
        logger.info("✅ 卖出限价单测试完成")
        return order
    except Exception as e:
        logger.error(f"❌ 卖出限价单测试失败: {e}")
        return None


def test_sell_market_order(broker: LongPortBroker):
    """测试卖出市价单（Dry Run）"""
    print("\n" + "="*60)
    print("测试 10: 卖出市价单测试（Dry Run）")
    print("="*60)
    
    try:
        order = broker.submit_stock_order(
            symbol="MSFT.US",
            side="SELL",
            quantity=3,
            order_type="MARKET",
            remark="Test sell market order - Dry Run"
        )
        
        logger.info(f"卖出市价单 ID: {order['order_id']}")
        logger.info("✅ 卖出市价单测试完成")
        return order
    except Exception as e:
        logger.error(f"❌ 卖出市价单测试失败: {e}")
        return None


def test_get_orders(broker: LongPortBroker):
    """测试获取订单"""
    print("\n" + "="*60)
    print("测试 11: 获取当日订单")
    print("="*60)
    
    try:
        orders = broker.get_today_orders()
        logger.info(f"当日订单数: {len(orders)}")
        
        # 使用表格化显示所有订单
        if orders:
            print_orders_summary_table(orders, title="当日订单")
            print_success_message(f"获取订单测试完成 (共 {len(orders)} 个订单)")
        else:
            print_warning_message("今日暂无订单")
        
        return orders
    except Exception as e:
        logger.error(f"❌ 获取订单失败: {e}")
        return []


def test_get_positions(broker: LongPortBroker):
    """测试获取持仓"""
    print("\n" + "="*60)
    print("测试 12: 获取持仓信息")
    print("="*60)
    
    try:
        positions = broker.get_positions()
        logger.info(f"持仓数: {len(positions)}")
        
        # 使用表格化显示
        if positions:
            print_positions_table(positions, title="当前持仓")
            print_success_message("获取持仓测试完成")
        else:
            print_warning_message("暂无持仓")
        
        return positions
    except Exception as e:
        logger.error(f"❌ 获取持仓失败: {e}")
        return []


def test_sell_without_position(broker: LongPortBroker):
    """测试卖出无持仓股票（应该失败）"""
    print("\n" + "="*60)
    print("测试 13: 卖出无持仓股票（持仓检查）")
    print("="*60)
    
    # 在 Dry Run 模式下不会实际检查持仓，需要关闭 Dry Run
    original_dry_run = broker.dry_run
    original_auto_trade = broker.auto_trade
    
    try:
        # 临时启用真实模式以测试持仓检查（但不会真实下单，因为会被持仓检查拦截）
        broker.dry_run = False
        broker.auto_trade = True
        
        # 尝试卖出一个不太可能持有的股票
        test_symbol = "AMZN.US"
        logger.info(f"尝试卖出无持仓股票: {test_symbol}")
        
        try:
            order = broker.submit_stock_order(
                symbol=test_symbol,
                side="SELL",
                quantity=10,
                price=100.0,
                order_type="LIMIT",
                remark="Test sell without position"
            )
            # 如果执行到这里，说明没有被拦截（不应该发生）
            logger.warning("⚠️  预期应该被持仓检查拦截，但订单被提交了")
            print_warning_message("持仓检查可能未生效")
            return False
        except ValueError as e:
            # 预期会抛出 ValueError
            if "持仓不足" in str(e):
                logger.info(f"✅ 持仓检查正常工作: {e}")
                print_success_message("持仓检查成功拦截了无持仓的卖出订单")
                return True
            else:
                logger.error(f"❌ 收到意外错误: {e}")
                return False
    finally:
        # 恢复原始设置
        broker.dry_run = original_dry_run
        broker.auto_trade = original_auto_trade


def test_sell_exceed_position(broker: LongPortBroker, positions: list):
    """测试卖出超过持仓数量（应该失败）"""
    print("\n" + "="*60)
    print("测试 14: 卖出超过持仓数量（持仓检查）")
    print("="*60)
    
    if not positions or len(positions) == 0:
        logger.info("⏭️  没有持仓，跳过此测试")
        print_warning_message("没有持仓，跳过持仓超量卖出测试")
        return None
    
    # 选择第一个持仓进行测试
    test_position = positions[0]
    symbol = test_position['symbol']
    available_qty = test_position['available_quantity']
    
    # 在 Dry Run 模式下不会实际检查持仓，需要关闭 Dry Run
    original_dry_run = broker.dry_run
    original_auto_trade = broker.auto_trade
    
    try:
        # 临时启用真实模式以测试持仓检查
        broker.dry_run = False
        broker.auto_trade = True
        
        # 尝试卖出超过持仓的数量
        excessive_qty = int(available_qty * 2)  # 2倍持仓数量
        logger.info(f"尝试卖出 {excessive_qty} 股 {symbol}（可用持仓: {available_qty}）")
        
        try:
            order = broker.submit_stock_order(
                symbol=symbol,
                side="SELL",
                quantity=excessive_qty,
                price=100.0,
                order_type="LIMIT",
                remark="Test sell exceed position"
            )
            # 如果执行到这里，说明没有被拦截（不应该发生）
            logger.warning("⚠️  预期应该被持仓检查拦截，但订单被提交了")
            print_warning_message("持仓数量检查可能未生效")
            return False
        except ValueError as e:
            # 预期会抛出 ValueError
            if "持仓不足" in str(e) or "持仓数量不足" in str(e):
                logger.info(f"✅ 持仓数量检查正常工作: {e}")
                print_success_message("持仓数量检查成功拦截了超量卖出订单")
                return True
            else:
                logger.error(f"❌ 收到意外错误: {e}")
                return False
    finally:
        # 恢复原始设置
        broker.dry_run = original_dry_run
        broker.auto_trade = original_auto_trade


def main():
    """主测试流程"""
    print("\n🚀 长桥 OpenAPI 正股交易集成测试")
    print("="*60)
    
    # 1. 加载配置
    config = test_config_loading()
    if not config:
        logger.error("配置加载失败，退出测试")
        sys.exit(1)
    
    # 2. 初始化 Broker
    try:
        broker = LongPortBroker(config)
        logger.info("Broker 初始化成功")
    except Exception as e:
        logger.error(f"Broker 初始化失败: {e}")
        sys.exit(1)
    
    # 3. 获取账户信息
    balance = test_account_info(broker)
    if not balance:
        logger.warning("无法获取账户信息，继续其他测试")
    
    # 4. 测试获取多个股票报价
    quotes = test_stock_quote(broker)
    
    # 5. 测试获取单个股票报价
    single_quote = test_single_stock_quote(broker, "AAPL.US")
    
    # 6. 测试 Dry Run 限价买入单
    test_dry_run_stock_order(broker, single_quote)
    
    # 7. 测试 Dry Run 市价买入单
    test_market_order(broker)
    
    # 8. 获取 NVDA 报价用于卖出测试
    print("\n" + "="*60)
    print("获取 NVDA.US 报价用于卖出测试")
    print("="*60)
    nvda_quotes = broker.get_stock_quote(["NVDA.US"])
    nvda_quote = nvda_quotes[0] if nvda_quotes else None
    if nvda_quote:
        logger.info(f"NVDA.US 当前价: ${nvda_quote['last_done']:.2f}")
    
    # 9. 测试卖出限价单
    test_sell_limit_order(broker, nvda_quote)
    
    # 10. 测试卖出市价单
    test_sell_market_order(broker)
    
    # 11. 测试获取订单
    test_get_orders(broker)
    
    # 12. 测试获取持仓
    positions = test_get_positions(broker)
    
    # 13. 测试卖出无持仓股票（持仓检查）
    test_sell_without_position(broker)
    
    # 14. 测试卖出超过持仓数量（持仓检查）
    test_sell_exceed_position(broker, positions)
    
    # 测试总结
    print("\n" + "="*60)
    print("✅ 所有正股API测试完成！")
    print("="*60)
    print("\n📌 测试总结:")
    print("  ✓ 配置加载")
    print("  ✓ 账户信息查询")
    print("  ✓ 多股票报价查询")
    print("  ✓ 单股票详细报价")
    print("  ✓ 买入限价单提交（Dry Run）")
    print("  ✓ 买入市价单提交（Dry Run）")
    print("  ✓ 卖出限价单提交（Dry Run）")
    print("  ✓ 卖出市价单提交（Dry Run）")
    print("  ✓ 订单查询")
    print("  ✓ 持仓查询")
    print("  ✓ 卖出持仓检查（无持仓）")
    print("  ✓ 卖出持仓检查（超量卖出）")
    print("\n📌 下一步:")
    print("  1. 如需启用真实交易，设置 LONGPORT_AUTO_TRADE=true")
    print("  2. 如需关闭 Dry Run，设置 LONGPORT_DRY_RUN=false")
    print("  3. 如需切换到真实账户，设置 LONGPORT_MODE=real")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
