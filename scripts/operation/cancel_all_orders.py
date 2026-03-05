#!/usr/bin/env python3
"""
批量撤销今日所有订单
支持 --paper（模拟账户）、--real（真实账户）选择账户类型。
"""
import argparse
import sys
import os
import logging
from typing import List, Dict

# 添加项目根目录到 Python 路径（脚本在 scripts/operation/ 下，根目录需上溯两级）
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _project_root)

from broker.config_loader import LongPortConfigLoader
from broker.longport_broker import LongPortBroker
from broker.order_formatter import (
    print_orders_summary_table,
    print_order_cancel_table,
    print_success_message,
    print_error_message,
    print_warning_message
)
from rich.console import Console

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
console = Console()


def can_cancel_order(order: Dict) -> bool:
    """
    判断订单是否可以撤销
    
    Args:
        order: 订单信息字典
    
    Returns:
        bool: 是否可以撤销
    """
    status = order.get('status', '')
    
    # 可以撤销的状态：
    # - NotReported: 待报
    # - ReplacedNotReported: 待报修改
    # - PendingReplace: 修改待报
    # - PendingCancel: 撤销待报
    # - RejectedCancel: 撤销已拒绝
    # - NewOrder: 已报
    # - PartiallyFilled: 部分成交
    
    cancellable_statuses = [
        'OrderStatus.NotReported',
        'OrderStatus.ReplacedNotReported', 
        'OrderStatus.PendingReplace',
        'OrderStatus.NewOrder',
        'OrderStatus.PartiallyFilled',
        'OrderStatus.RejectedCancel'
    ]
    
    # 不能撤销的状态：
    # - Filled: 已成交
    # - Cancelled: 已撤销
    # - Rejected: 已拒绝
    # - Expired: 已过期
    
    return status in cancellable_statuses


def cancel_all_today_orders(mode: str = "paper"):
    """
    批量撤销今日所有订单

    Args:
        mode: 账户类型 'paper'（模拟）或 'real'（真实）
    """
    mode_label = "🧪 模拟账户" if mode == "paper" else "💰 真实账户"
    console.print("\n" + "="*60, style="bold cyan")
    console.print("📋 批量撤销今日订单", style="bold cyan")
    console.print(f"   账户: {mode_label}", style="yellow")
    console.print("="*60 + "\n", style="bold cyan")

    # 初始化 broker（按参数指定账户类型）
    try:
        config_loader = LongPortConfigLoader(mode=mode)
        broker = LongPortBroker(config_loader=config_loader)
        logger.info("✅ LongPort broker 初始化成功 (%s)", mode_label)
    except Exception as e:
        print_error_message(f"初始化 broker 失败: {e}")
        return
    
    # 获取今日所有订单
    console.print("\n📊 正在获取今日所有订单...\n", style="bold yellow")
    try:
        orders = broker.get_today_orders()
        logger.info(f"当日订单数: {len(orders)}")
    except Exception as e:
        print_error_message(f"获取订单失败: {e}")
        return
    
    if not orders:
        print_warning_message("今日暂无订单")
        return
    
    # 显示所有订单
    print_orders_summary_table(orders, title=f"今日订单 (共 {len(orders)} 个)")
    
    # 过滤可撤销的订单
    cancellable_orders = [order for order in orders if can_cancel_order(order)]
    
    if not cancellable_orders:
        print_warning_message("没有可撤销的订单（所有订单已完成、已撤销或已拒绝）")
        return
    
    # 显示可撤销订单数量
    console.print(
        f"\n📝 发现 {len(cancellable_orders)} 个可撤销订单 "
        f"(共 {len(orders)} 个订单)\n",
        style="bold yellow"
    )
    
    # 确认是否继续
    console.print("⚠️  确认要撤销这些订单吗？", style="bold red")
    console.print("   输入 'yes' 或 'y' 确认撤销", style="yellow")
    console.print("   输入其他任何内容取消操作\n", style="yellow")
    
    confirmation = input("请输入: ").strip().lower()
    
    if confirmation not in ['yes', 'y']:
        print_warning_message("操作已取消")
        return
    
    # 开始撤销订单
    console.print("\n🔄 开始撤销订单...\n", style="bold cyan")
    
    success_count = 0
    failed_count = 0
    skipped_count = 0
    results = []
    
    for i, order in enumerate(cancellable_orders, 1):
        order_id = order.get('order_id')
        symbol = order.get('symbol', 'N/A')
        
        console.print(
            f"[{i}/{len(cancellable_orders)}] 撤销订单: {order_id} ({symbol})",
            style="cyan"
        )
        
        try:
            result = broker.cancel_order(order_id)
            
            if result.get('status') == 'skipped':
                skipped_count += 1
                reason = result.get('reason', 'unknown')
                logger.warning(f"⚠️  订单 {order_id} 跳过: {reason}")
            else:
                success_count += 1
                # 显示撤销订单详情
                if result.get('order_info'):
                    print_order_cancel_table(result['order_info'])
                else:
                    logger.info(f"✅ 订单 {order_id} 撤销成功")
            
            results.append({
                'order_id': order_id,
                'symbol': symbol,
                'status': 'success' if result.get('status') != 'skipped' else 'skipped',
                'result': result
            })
            
        except Exception as e:
            failed_count += 1
            logger.error(f"❌ 订单 {order_id} 撤销失败: {e}")
            results.append({
                'order_id': order_id,
                'symbol': symbol,
                'status': 'failed',
                'error': str(e)
            })
    
    # 显示汇总结果
    console.print("\n" + "="*60, style="bold cyan")
    console.print("📊 撤销结果汇总", style="bold cyan")
    console.print("="*60 + "\n", style="bold cyan")
    
    console.print(f"总订单数: {len(orders)}", style="white")
    console.print(f"可撤销订单: {len(cancellable_orders)}", style="white")
    console.print(f"✅ 成功撤销: {success_count}", style="bold green")
    console.print(f"⚠️  跳过: {skipped_count}", style="bold yellow")
    console.print(f"❌ 失败: {failed_count}", style="bold red")
    
    if success_count > 0:
        print_success_message(f"成功撤销 {success_count} 个订单")
    
    if failed_count > 0:
        print_error_message(f"{failed_count} 个订单撤销失败")


def parse_args():
    parser = argparse.ArgumentParser(
        description="批量撤销今日所有订单。使用 --paper 操作模拟账户，--real 操作真实账户。"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--paper",
        action="store_const",
        dest="mode",
        const="paper",
        help="使用模拟账户",
    )
    group.add_argument(
        "--real",
        action="store_const",
        dest="mode",
        const="real",
        help="使用真实账户",
    )
    parser.set_defaults(mode=os.getenv("LONGPORT_MODE", "paper"))
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        cancel_all_today_orders(mode=args.mode)
    except KeyboardInterrupt:
        print_warning_message("\n操作已被用户中断")
        sys.exit(0)
    except Exception as e:
        print_error_message(f"程序执行失败: {e}")
        logger.exception(e)
        sys.exit(1)
