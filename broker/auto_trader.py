"""
自动化交易模块
将parser处理后的operation转化为broker接口调用，完成自动化下单
"""
import logging
import os
from typing import Optional, Dict, List
from decimal import Decimal

from models.instruction import OptionInstruction, InstructionType
from broker.longport_broker import LongPortBroker
from broker.order_formatter import (
    print_success_message,
    print_error_message,
    print_warning_message,
    print_info_message,
    print_order_validation_display,
    print_sell_validation_display,
    print_modify_validation_display,
    print_close_validation_display,
)

logger = logging.getLogger(__name__)


class AutoTrader:
    """自动化交易执行器"""

    def __init__(self, broker: LongPortBroker, position_manager=None):
        """
        初始化自动交易执行器

        Args:
            broker: LongPortBroker实例
            position_manager: 可选，持仓管理器；卖出比例（如 1/3）相对该期权「所有买入数量」时用其 trade_records 计算分母
        """
        self.broker = broker
        self.position_manager = position_manager
        
        # 从环境变量加载配置
        self.max_option_total_price = float(os.getenv('MAX_OPTION_TOTAL_PRICE', '10000'))  # 单个期权总价上限
        self.max_option_quantity = int(os.getenv('MAX_OPTION_QUANTITY', '10'))  # 单次购买最大数量
        self.require_confirmation = os.getenv('REQUIRE_CONFIRMATION', 'false').lower() in ('true', '1', 'yes')
        self.price_deviation_tolerance = float(os.getenv('PRICE_DEVIATION_TOLERANCE', '5'))  # 价格偏差容忍度（百分比）
        # 价格在容忍度内时买入用市价还是指令价：market=用市价（易成交），instruction=用指令价（不超付）
        buy_price_mode = (os.getenv('BUY_PRICE_WHEN_WITHIN_TOLERANCE', 'instruction') or 'instruction').lower()
        self.buy_use_market_when_within_tolerance = buy_price_mode in ('market', '市价', 'true', '1')
        # 未成交订单的「成交后补偿止盈止损」任务：order_id -> { symbol, stop_loss_price?, take_profit_price? }
        self._pending_modify_after_fill: Dict[str, dict] = {}

    def on_order_push_for_pending_modify(self, event) -> None:
        """
        订单推送时检查是否有待补偿的止盈止损任务：
        - 若该订单成交（Filled）：对对应持仓补偿设置止盈/止损，并移除任务
        - 若该订单已撤（Cancelled）：仅移除任务
        """
        order_id = getattr(event, "order_id", None) or ""
        if not order_id:
            return
        status = getattr(event, "status", None)
        status_name = (getattr(status, "name", "") or "").upper() if status else ""
        if not status_name and hasattr(event, "status"):
            status_name = str(getattr(event, "status", "")).upper().split(".")[-1]
        if status_name in ("CANCELLED", "CANCELED", "REJECTED"):
            if order_id in self._pending_modify_after_fill:
                self._pending_modify_after_fill.pop(order_id, None)
                logger.debug("订单 %s 已撤/拒，移除止盈止损补偿任务", order_id)
            return
        if status_name != "FILLED":
            return
        task = self._pending_modify_after_fill.pop(order_id, None)
        if not task or not self.position_manager:
            return
        symbol = task.get("symbol")
        if not symbol:
            return
        pos = self.position_manager.get_position(symbol)
        if not pos:
            logger.warning("补偿止盈止损：未找到持仓 %s，跳过", symbol)
            return
        applied = []
        if task.get("stop_loss_price") is not None:
            pos.set_stop_loss(float(task["stop_loss_price"]))
            applied.append(f"止损=${task['stop_loss_price']}")
        if task.get("take_profit_price") is not None:
            pos.set_take_profit(float(task["take_profit_price"]))
            applied.append(f"止盈=${task['take_profit_price']}")
        if applied:
            self.position_manager._save_positions()
            print_info_message(f"订单 {order_id} 已成交，已补偿设置：{', '.join(applied)}（{symbol}）")

    def execute_instruction(self, instruction: OptionInstruction) -> Optional[Dict]:
        """
        执行单条指令
        
        Args:
            instruction: 期权交易指令
            
        Returns:
            执行结果字典，失败返回None
        """
        try:
            instruction_type = instruction.instruction_type
            
            if instruction_type == InstructionType.BUY.value:
                return self._execute_buy(instruction)
            elif instruction_type == InstructionType.SELL.value:
                return self._execute_sell(instruction)
            elif instruction_type == InstructionType.CLOSE.value:
                return self._execute_close(instruction)
            elif instruction_type == InstructionType.MODIFY.value:
                return self._execute_modify(instruction)
            else:
                print_warning_message(f"未知指令类型: {instruction_type}")
                return None
                
        except Exception as e:
            print_error_message(f"执行指令失败: {e}")
            logger.error(f"执行指令失败: {e}", exc_info=True)
            return None
    
    def _execute_buy(self, instruction: OptionInstruction) -> Optional[Dict]:
        """
        执行买入指令
        
        买入规则：
        1. 获取账户余额，根据env配置和实际余额的较小值决定总价上限
        2. 根据总价上限和单价确认买入数量
        3. 校验结束后统一输出 [订单校验] 格式，再根据配置决定是否确认后下单
        """
        symbol = instruction.symbol
        if not symbol:
            return None

        if instruction.price_range:
            instruction_price = (instruction.price_range[0] + instruction.price_range[1]) / 2
        elif instruction.price is not None:
            instruction_price = instruction.price
        else:
            print_error_message("买入指令缺少价格信息")
            return None

        price = instruction_price
        price_line = ""
        reject_reason = None

        try:
            quotes = self.broker.get_option_quote([symbol])
            if quotes and len(quotes) > 0:
                market_price = quotes[0].get("last_done", 0)
                if market_price > 0:
                    # 买入只校验「市价高于指令价」的偏差，避免多付；市价低于指令价更优，不拒单
                    deviation_pct = (market_price - instruction_price) / instruction_price * 100
                    if deviation_pct > self.price_deviation_tolerance:
                        reject_reason = f"当前市价 ${market_price:.2f} 高于指令价 ${instruction_price:.2f} 超过 {self.price_deviation_tolerance}%，未提交订单"
                        price_line = f"查询价格：当前市场价=${market_price:.2f}，指令价=${instruction_price:.2f}，偏差={deviation_pct:.1f}%"
                    else:
                        deviation = abs(market_price - instruction_price) / instruction_price * 100
                        if market_price < instruction_price:
                            price = market_price
                        else:
                            # 市价 >= 指令价且在容忍度内：按配置用市价或指令价
                            price = market_price if self.buy_use_market_when_within_tolerance else instruction_price
                        price_line = f"查询价格：当前市场价=${market_price:.2f}，指令价=${instruction_price:.2f}，偏差={deviation:.1f}%，使用价格=${price:.2f}"
                else:
                    price_line = "查询价格：市场价格无效，使用指令价格"
            else:
                price_line = "查询价格：无法获取该期权市场报价"
                reject_reason = "无法获取该期权市场报价，未提交订单"
        except Exception as e:
            price_line = f"查询价格：获取报价失败（{e}），使用指令价格=${price:.2f}"

        try:
            balance_info = self.broker.get_account_balance()
            available_cash = balance_info.get("available_cash", 0)
        except Exception:
            available_cash = float("inf")

        max_total_price = min(self.max_option_total_price, available_cash)
        single_contract_price = price * 100
        max_quantity_by_price = int(max_total_price / single_contract_price) if single_contract_price > 0 else 0
        max_quantity_by_limit = self.max_option_quantity
        quantity = min(max_quantity_by_price, max_quantity_by_limit)
        if quantity < 1:
            quantity = 0

        if quantity <= 0 and not reject_reason:
            reject_reason = f"计算的买入数量为0，单价: ${price}, 总价上限: ${max_total_price:.2f}，未提交订单"

        total_price = quantity * single_contract_price
        quantity_line = f"买入数量：账户余额=${available_cash:.2f}，单次购买上限=${max_total_price:.2f}，张数限制={max_quantity_by_limit}张，按总价上限可买{max_quantity_by_price}张，最终买入数量={quantity}张"
        total_line = f"买入总价：${total_price:.2f}"

        print_order_validation_display(
            side="BUY",
            symbol=symbol,
            price=price,
            price_line=price_line,
            quantity_line=quantity_line,
            total_line=total_line,
            instruction_timestamp=instruction.timestamp,
            reject_reason=reject_reason,
        )

        if reject_reason:
            return None

        # 如果需要确认
        if self.require_confirmation:
            print_warning_message("=" * 80)
            print_warning_message("请确认订单信息:")
            print_warning_message(f"  期权代码: {symbol}")
            print_warning_message(f"  方向: 买入")
            print_warning_message(f"  数量: {quantity} 张")
            print_warning_message(f"  价格: ${price:.2f}")
            print_warning_message(f"  总价: ${total_price:.2f}")
            print_warning_message("=" * 80)
            
            confirm = input("确认下单? (yes/no): ").strip().lower()
            if confirm not in ('yes', 'y'):
                print_info_message("订单已取消")
                return None
        
        # 提交订单
        try:
            order_params = {
                'symbol': symbol,
                'side': 'BUY',
                'quantity': quantity,
                'price': price,
                'order_type': 'LIMIT',
                'remark': f"Auto buy: {instruction.raw_message[:50]}",
                'instruction_timestamp': instruction.timestamp,
            }
            
            # 如果有止损价格，添加trigger_price
            if instruction.stop_loss_price:
                order_params['trigger_price'] = instruction.stop_loss_price
                print_info_message(f"设置止损价格: ${instruction.stop_loss_price}")
            
            result = self.broker.submit_option_order(**order_params)
            return result
            
        except Exception as e:
            print_error_message(f"买入订单提交失败: {e}")
            return None
    
    def _execute_sell(self, instruction: OptionInstruction) -> Optional[Dict]:
        """
        执行卖出指令
        
        卖出规则：
        1. 先尝试获取持仓，在存在持仓的情况下再去处理
        2. 卖出比例（如 1/3、1/2）相对「该期权所有买入数量」，不是相对当前持仓：有 position_manager 时用其 trade_records 汇总；否则用当日成交买入量，再否则用当前持仓
        """
        symbol = instruction.symbol
        if not symbol:
            return None

        # 1. 检查持仓
        positions = self.broker.get_positions()
        target_position = None
        for pos in positions:
            if pos['symbol'] == symbol:
                target_position = pos
                break

        if not target_position:
            print_sell_validation_display(
                symbol=symbol,
                quantity=0,
                instruction_timestamp=instruction.timestamp,
                detail_lines=[],
                reject_reason="无持仓，跳过卖出",
            )
            return None

        available_quantity = int(target_position.get('available_quantity', 0))

        # 2. 确定比例分母：该期权「所有买入数量」
        total_buy_quantity = 0
        if self.position_manager and hasattr(self.position_manager, 'get_total_buy_quantity'):
            total_buy_quantity = self.position_manager.get_total_buy_quantity(symbol)
        if total_buy_quantity <= 0:
            try:
                orders = self.broker.get_today_orders()
                for order in orders or []:
                    if (order.get('symbol') == symbol and
                            (order.get('side') or '').upper() == 'BUY' and
                            str(order.get('status') or '').upper().endswith('FILLED')):
                        total_buy_quantity += int(float(order.get('executed_quantity') or order.get('quantity') or 0))
            except Exception:
                pass
            if total_buy_quantity <= 0:
                total_buy_quantity = available_quantity

        # 3. 计算卖出数量
        sell_quantity_str = instruction.sell_quantity
        if sell_quantity_str:
            if '/' in sell_quantity_str:
                parts = sell_quantity_str.split('/')
                numerator, denominator = int(parts[0]), int(parts[1])
                sell_quantity = int(total_buy_quantity * numerator / denominator)
            elif '%' in sell_quantity_str:
                percent = float(sell_quantity_str.replace('%', ''))
                sell_quantity = int(total_buy_quantity * percent / 100)
            else:
                sell_quantity = int(sell_quantity_str)
        else:
            sell_quantity = available_quantity

        if sell_quantity > available_quantity:
            sell_quantity = available_quantity

        # 确定卖出价格
        if instruction.price_range:
            price = (instruction.price_range[0] + instruction.price_range[1]) / 2
        elif instruction.price:
            price = instruction.price
        else:
            price = None

        # 构建与买入校验同风格的卖出校验展示（明细行）
        detail_lines = [
            f"当前持仓：{available_quantity} 张",
            f"该期权所有买入总量（比例分母）：{total_buy_quantity} 张",
        ]
        if sell_quantity_str:
            if '/' in sell_quantity_str or '%' in sell_quantity_str:
                detail_lines.append(f"卖出比例：{sell_quantity_str}，计算数量：{sell_quantity} 张")
            else:
                detail_lines.append(f"卖出数量：{sell_quantity} 张")
        else:
            detail_lines.append(f"未指定卖出数量，默认卖出全部持仓：{sell_quantity} 张")
        if price is not None:
            if instruction.price_range:
                detail_lines.append(f"价格区间：${instruction.price_range[0]} - ${instruction.price_range[1]}，使用中间值：${price}")
            else:
                detail_lines.append(f"卖出价格：${price}")
        else:
            detail_lines.append("未指定卖出价格，使用市价单")

        if sell_quantity <= 0:
            print_sell_validation_display(
                symbol=symbol,
                quantity=0,
                instruction_timestamp=instruction.timestamp,
                detail_lines=detail_lines,
                reject_reason="卖出数量为0，跳过",
            )
            return None

        print_sell_validation_display(
            symbol=symbol,
            quantity=sell_quantity,
            instruction_timestamp=instruction.timestamp,
            detail_lines=detail_lines,
            reject_reason=None,
        )
        
        # 如果需要确认
        if self.require_confirmation:
            print_warning_message("=" * 80)
            print_warning_message("请确认订单信息:")
            print_warning_message(f"  期权代码: {symbol}")
            print_warning_message(f"  方向: 卖出")
            print_warning_message(f"  数量: {sell_quantity} 张")
            print_warning_message(f"  价格: ${price:.2f}" if price else "  价格: 市价")
            print_warning_message("=" * 80)
            
            confirm = input("确认下单? (yes/no): ").strip().lower()
            if confirm not in ('yes', 'y'):
                print_info_message("订单已取消")
                return None
        
        # 提交卖出订单
        try:
            order_params = {
                'symbol': symbol,
                'side': 'SELL',
                'quantity': sell_quantity,
                'order_type': 'LIMIT' if price else 'MARKET',
                'remark': f"Auto sell: {instruction.raw_message[:50]}",
                'instruction_timestamp': instruction.timestamp,
            }
            
            if price:
                order_params['price'] = price
            
            result = self.broker.submit_option_order(**order_params)
            print_success_message("卖出订单提交成功!")
            return result
            
        except Exception as e:
            print_error_message(f"卖出订单提交失败: {e}")
            return None
    
    def _execute_close(self, instruction: OptionInstruction) -> Optional[Dict]:
        """
        执行清仓指令

        清仓规则：
        1. 先尝试获取持仓，在存在持仓的情况下再去处理
        2. 清仓即卖出全部持仓
        """
        symbol = instruction.symbol
        if not symbol:
            return None

        # 1. 检查持仓
        positions = self.broker.get_positions()
        target_position = None
        for pos in positions:
            if pos['symbol'] == symbol:
                target_position = pos
                break

        if not target_position:
            print_close_validation_display(
                symbol=symbol,
                quantity=0,
                instruction_timestamp=instruction.timestamp,
                detail_lines=[],
                reject_reason="无持仓，跳过清仓",
            )
            return None

        available_quantity = int(target_position.get('available_quantity', 0))

        # 确定卖出价格
        if instruction.price_range:
            price = (instruction.price_range[0] + instruction.price_range[1]) / 2
        elif instruction.price:
            price = instruction.price
        else:
            price = None

        # 构建与买入/卖出同风格的校验展示
        detail_lines = [f"当前持仓：{available_quantity} 张", f"清仓数量：{available_quantity} 张（全部）"]
        if price is not None:
            if instruction.price_range:
                detail_lines.append(f"价格区间：${instruction.price_range[0]} - ${instruction.price_range[1]}，使用中间值：${price}")
            else:
                detail_lines.append(f"卖出价格：${price}")
        else:
            detail_lines.append("未指定清仓价格，使用市价单")

        if available_quantity <= 0:
            print_close_validation_display(
                symbol=symbol,
                quantity=0,
                instruction_timestamp=instruction.timestamp,
                detail_lines=detail_lines,
                reject_reason="可用持仓为0，跳过清仓",
            )
            return None

        print_close_validation_display(
            symbol=symbol,
            quantity=available_quantity,
            instruction_timestamp=instruction.timestamp,
            detail_lines=detail_lines,
            reject_reason=None,
        )

        # 如果需要确认
        if self.require_confirmation:
            print_warning_message("=" * 80)
            print_warning_message("请确认清仓订单:")
            print_warning_message(f"  期权代码: {symbol}")
            print_warning_message(f"  方向: 清仓（卖出全部）")
            print_warning_message(f"  数量: {available_quantity} 张")
            print_warning_message(f"  价格: ${price:.2f}" if price else "  价格: 市价")
            print_warning_message("=" * 80)
            
            confirm = input("确认清仓? (yes/no): ").strip().lower()
            if confirm not in ('yes', 'y'):
                print_info_message("清仓已取消")
                return None
        
        # 提交清仓订单
        try:
            order_params = {
                'symbol': symbol,
                'side': 'SELL',
                'quantity': available_quantity,
                'order_type': 'LIMIT' if price else 'MARKET',
                'remark': f"Auto close: {instruction.raw_message[:50]}",
                'instruction_timestamp': instruction.timestamp,
            }
            
            if price:
                order_params['price'] = price
            
            result = self.broker.submit_option_order(**order_params)
            print_success_message("清仓订单提交成功!")
            return result
            
        except Exception as e:
            print_error_message(f"清仓订单提交失败: {e}")
            return None
    
    def _execute_modify(self, instruction: OptionInstruction) -> Optional[Dict]:
        """
        执行修改指令（止盈止损）
        
        修改规则：
        1. 先尝试获取持仓，在存在持仓的情况下再去修改止盈止损值
        2. 获取当前期权最新价格，如果满足止盈止损条件，立马清仓
        """
        symbol = instruction.symbol
        if not symbol:
            return None

        # 1. 检查持仓
        positions = self.broker.get_positions()
        target_position = None
        for pos in positions:
            if pos['symbol'] == symbol:
                target_position = pos
                break

        if not target_position:
            print_modify_validation_display(
                symbol=symbol,
                instruction_timestamp=instruction.timestamp,
                detail_lines=[],
                reject_reason="无持仓，跳过修改",
            )
            return None

        available_quantity = int(target_position.get('available_quantity', 0))
        # 长桥 get_positions 返回的 cost_price 已是「每股美元」，无需再除 100
        cost_price = float(target_position.get('cost_price', 0))

        # 2. 获取当前市场价格
        try:
            quotes = self.broker.get_option_quote([symbol])
            if quotes and len(quotes) > 0:
                current_price = quotes[0].get('last_done', 0)
            else:
                current_price = None
        except Exception:
            current_price = None

        # 构建与买入/卖出同风格的校验展示明细
        detail_lines = [
            f"当前持仓：{available_quantity} 张",
            f"成本价：${cost_price:.2f}",
        ]
        if current_price is not None:
            detail_lines.append(f"当前市场价：${current_price:.2f}")
        else:
            detail_lines.append("当前市场价：无法获取")

        # 3. 检查是否满足止盈止损条件
        should_close = False
        close_reason = ""

        # 止损检查
        if instruction.stop_loss_price:
            stop_loss = instruction.stop_loss_price
            detail_lines.append(f"设置止损价：${stop_loss:.2f}")
            if current_price is not None and current_price <= stop_loss:
                should_close = True
                close_reason = f"触发止损 (当前价 ${current_price:.2f} <= 止损价 ${stop_loss:.2f})"
        elif instruction.stop_loss_range:
            stop_loss = (instruction.stop_loss_range[0] + instruction.stop_loss_range[1]) / 2
            detail_lines.append(f"设置止损价区间：${instruction.stop_loss_range[0]} - ${instruction.stop_loss_range[1]}，使用中间值：${stop_loss:.2f}")
            if current_price is not None and current_price <= stop_loss:
                should_close = True
                close_reason = f"触发止损 (当前价 ${current_price:.2f} <= 止损价 ${stop_loss:.2f})"

        # 止盈检查
        if instruction.take_profit_price:
            take_profit = instruction.take_profit_price
            detail_lines.append(f"设置止盈价：${take_profit:.2f}")
            if current_price is not None and current_price >= take_profit:
                should_close = True
                close_reason = f"触发止盈 (当前价 ${current_price:.2f} >= 止盈价 ${take_profit:.2f})"
        elif instruction.take_profit_range:
            take_profit = (instruction.take_profit_range[0] + instruction.take_profit_range[1]) / 2
            detail_lines.append(f"设置止盈价区间：${instruction.take_profit_range[0]} - ${instruction.take_profit_range[1]}，使用中间值：${take_profit:.2f}")
            if current_price is not None and current_price >= take_profit:
                should_close = True
                close_reason = f"触发止盈 (当前价 ${current_price:.2f} >= 止盈价 ${take_profit:.2f})"

        # 4. 如果满足止盈止损条件，立即清仓（先输出校验块再执行）
        if should_close:
            print_modify_validation_display(
                symbol=symbol,
                instruction_timestamp=instruction.timestamp,
                detail_lines=detail_lines,
                reject_reason=None,
            )
            print_warning_message(f"⚠️  {close_reason}")
            print_warning_message("立即执行清仓...")

            if self.require_confirmation:
                print_warning_message("=" * 80)
                print_warning_message("请确认清仓订单:")
                print_warning_message(f"  期权代码: {symbol}")
                print_warning_message(f"  原因: {close_reason}")
                print_warning_message(f"  数量: {available_quantity} 张")
                print_warning_message(f"  当前价: ${current_price:.2f}")
                print_warning_message("=" * 80)

                confirm = input("确认清仓? (yes/no): ").strip().lower()
                if confirm not in ('yes', 'y'):
                    print_info_message("清仓已取消")
                    return None

            try:
                result = self.broker.submit_option_order(
                    symbol=symbol,
                    side='SELL',
                    quantity=available_quantity,
                    price=None,
                    order_type='MARKET',
                    remark=f"Auto close: {close_reason}",
                    instruction_timestamp=instruction.timestamp,
                )
                print_success_message(f"清仓订单提交成功! ({close_reason})")
                return result
            except Exception as e:
                print_error_message(f"清仓订单提交失败: {e}")
                return None

        # 5. 未触发时，查询未成交订单，并把「未触发…」「找到订单」塞进同一校验块
        detail_lines.append("未触发止盈止损条件，查询未成交订单...")

        try:
            orders = self.broker.get_today_orders()
            target_order = None
            for order in orders:
                if (order.get('symbol') == symbol and
                    order.get('side') == 'BUY' and
                    order.get('status') not in ['Filled', 'filled', 'Cancelled', 'cancelled']):
                    target_order = order
                    break

            if not target_order:
                print_modify_validation_display(
                    symbol=symbol,
                    instruction_timestamp=instruction.timestamp,
                    detail_lines=detail_lines,
                    reject_reason="未找到可修改的未成交买入订单",
                )
                return None

            order_id = target_order['order_id']
            detail_lines.append(f"找到订单：{order_id}")
            print_modify_validation_display(
                symbol=symbol,
                instruction_timestamp=instruction.timestamp,
                detail_lines=detail_lines,
                reject_reason=None,
            )

            # 先登记「成交后补偿止盈止损」任务，若 replace 失败或订单未支持修改，成交时仍会补偿
            stop_loss_val = None
            if instruction.stop_loss_price is not None:
                stop_loss_val = float(instruction.stop_loss_price)
            elif instruction.stop_loss_range:
                stop_loss_val = (instruction.stop_loss_range[0] + instruction.stop_loss_range[1]) / 2
            take_profit_val = None
            if instruction.take_profit_price is not None:
                take_profit_val = float(instruction.take_profit_price)
            elif instruction.take_profit_range:
                take_profit_val = (instruction.take_profit_range[0] + instruction.take_profit_range[1]) / 2
            self._pending_modify_after_fill[order_id] = {
                "symbol": symbol,
                "stop_loss_price": stop_loss_val,
                "take_profit_price": take_profit_val,
            }

            # 修改订单（添加止盈止损）
            modify_params = {
                'order_id': order_id,
                'quantity': target_order['quantity']
            }
            if stop_loss_val is not None:
                modify_params['trigger_price'] = stop_loss_val

            try:
                result = self.broker.replace_order(**modify_params)
                self._pending_modify_after_fill.pop(order_id, None)  # 修改成功则不再补偿
                print_success_message("订单修改成功!")
                return result
            except Exception as e:
                print_error_message(f"修改订单失败: {e}")
                print_info_message(f"已登记补偿任务：订单 {order_id} 成交后将自动设置止盈止损")
                return None
            
        except Exception as e:
            print_error_message(f"修改订单失败: {e}")
            return None
    
    def execute_batch_instructions(self, instructions: List[OptionInstruction]) -> List[Dict]:
        """
        批量执行指令
        
        Args:
            instructions: 指令列表
            
        Returns:
            执行结果列表
        """
        results = []
        for i, instruction in enumerate(instructions, 1):
            print_info_message(f"\n处理指令 {i}/{len(instructions)}")
            print_info_message(f"原始消息: {instruction.raw_message[:100]}")
            
            result = self.execute_instruction(instruction)
            results.append(result)
            
            # 在指令之间添加分隔
            if i < len(instructions):
                print_info_message("\n" + "=" * 80 + "\n")
        
        return results
