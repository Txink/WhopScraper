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
    print_info_message
)

logger = logging.getLogger(__name__)


class AutoTrader:
    """自动化交易执行器"""
    
    def __init__(self, broker: LongPortBroker):
        """
        初始化自动交易执行器
        
        Args:
            broker: LongPortBroker实例
        """
        self.broker = broker
        
        # 从环境变量加载配置
        self.max_option_total_price = float(os.getenv('MAX_OPTION_TOTAL_PRICE', '10000'))  # 单个期权总价上限
        self.max_option_quantity = int(os.getenv('MAX_OPTION_QUANTITY', '10'))  # 单次购买最大数量
        self.require_confirmation = os.getenv('REQUIRE_CONFIRMATION', 'false').lower() in ('true', '1', 'yes')
        self.price_deviation_tolerance = float(os.getenv('PRICE_DEVIATION_TOLERANCE', '5'))  # 价格偏差容忍度（百分比）
        
        logger.info(f"自动交易执行器初始化完成 - 单期权总价上限: ${self.max_option_total_price}, 最大数量: {self.max_option_quantity}张, 确认模式: {self.require_confirmation}")
    
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
        3. 如果配置需要确认，等待控制台确认后再下单
        """
        print_info_message("=" * 80)
        print_info_message("执行买入指令")
        print_info_message("=" * 80)
        
        # 生成期权代码
        symbol = instruction.symbol
        if not symbol:
            return None
        
        # 确定买入价格（指令价格）
        if instruction.price_range:
            # 使用价格区间的中间值
            instruction_price = (instruction.price_range[0] + instruction.price_range[1]) / 2
            print_info_message(f"指令价格区间: ${instruction.price_range[0]} - ${instruction.price_range[1]}, 使用中间值: ${instruction_price}")
        elif instruction.price:
            instruction_price = instruction.price
            print_info_message(f"指令价格: ${instruction_price}")
        else:
            print_error_message("买入指令缺少价格信息")
            return None
        
        # 获取当前市场价格，决定最终买入价格
        price = instruction_price  # 默认使用指令价格
        try:
            quotes = self.broker.get_option_quote([symbol])
            if quotes and len(quotes) > 0:
                market_price = quotes[0].get('last_done', 0)
                if market_price > 0:
                    deviation = abs(market_price - instruction_price) / instruction_price * 100
                    print_info_message(f"当前市场价: ${market_price:.2f}, 指令价: ${instruction_price:.2f}, 偏差: {deviation:.1f}%")
                    
                    # 如果偏差超过容忍度，拒绝下单
                    if deviation > self.price_deviation_tolerance:
                        print_warning_message(f"价格偏差超过容忍度 {self.price_deviation_tolerance}%，拒绝下单")
                        print_warning_message(f"请核对消息中的目标价或调高 PRICE_DEVIATION_TOLERANCE（当前 {self.price_deviation_tolerance}%）")
                        return None
                    
                    # 如果市场价格更优（更低），使用市场价格
                    if market_price < instruction_price:
                        price = market_price
                        print_info_message(f"✅ 使用更优的市场价格: ${price:.2f}")
                    else:
                        price = instruction_price
                        print_info_message(f"✅ 使用指令价格: ${price:.2f}")
                else:
                    print_warning_message("市场价格无效，使用指令价格")
            else:
                print_warning_message("无法获取市场报价，使用指令价格")
        except Exception as e:
            print_warning_message(f"获取市场报价失败: {e}，使用指令价格")
        
        # 获取账户余额
        try:
            balance_info = self.broker.get_account_balance()
            available_cash = balance_info.get('available_cash', 0)
            print_info_message(f"账户可用余额: ${available_cash:.2f}")
        except Exception as e:
            print_warning_message(f"无法获取账户余额: {e}，使用配置的上限")
            available_cash = float('inf')
        
        # 确定总价上限（取配置和余额的较小值）
        max_total_price = min(self.max_option_total_price, available_cash)
        print_info_message(f"总价上限: ${max_total_price:.2f}")
        
        # 计算买入数量：由总价上限和数量上限共同控制
        single_contract_price = price * 100
        max_quantity_by_price = int(max_total_price / single_contract_price)  # 根据总价计算的最大数量
        max_quantity_by_limit = self.max_option_quantity  # 配置的数量上限
        
        # 取两者较小值，默认买入 1 张
        quantity = min(1, max_quantity_by_price, max_quantity_by_limit)
        
        if quantity <= 0:
            print_error_message(f"计算的买入数量为0，单价: ${price}, 总价上限: ${max_total_price:.2f}")
            return None
        
        total_price = quantity * single_contract_price
        print_info_message(f"买入数量: {quantity} 张 (总价限制: {max_quantity_by_price}张, 数量限制: {max_quantity_by_limit}张), 总价: ${total_price:.2f}")
        
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
                'remark': f"Auto buy: {instruction.raw_message[:50]}"
            }
            
            # 如果有止损价格，添加trigger_price
            if instruction.stop_loss_price:
                order_params['trigger_price'] = instruction.stop_loss_price
                print_info_message(f"设置止损价格: ${instruction.stop_loss_price}")
            
            result = self.broker.submit_option_order(**order_params)
            print_success_message("买入订单提交成功!")
            return result
            
        except Exception as e:
            print_error_message(f"买入订单提交失败: {e}")
            return None
    
    def _execute_sell(self, instruction: OptionInstruction) -> Optional[Dict]:
        """
        执行卖出指令
        
        卖出规则：
        1. 先尝试获取持仓，在存在持仓的情况下再去处理
        2. 卖出比例相对最开始买入的比例，需要先查询买入订单确认总量
        """
        print_info_message("=" * 80)
        print_info_message("执行卖出指令")
        print_info_message("=" * 80)
        
        # 生成期权代码
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
            print_warning_message(f"无持仓: {symbol}，跳过卖出")
            return None
        
        available_quantity = int(target_position.get('available_quantity', 0))
        print_info_message(f"当前持仓: {available_quantity} 张")
        
        # 2. 查询历史买入订单，确认总买入量
        try:
            orders = self.broker.get_today_orders()
            total_buy_quantity = 0
            for order in orders:
                if (order.get('symbol') == symbol and 
                    order.get('side') == 'BUY' and 
                    order.get('status') in ['Filled', 'filled']):
                    total_buy_quantity += order.get('executed_quantity', 0)
            
            print_info_message(f"历史买入总量: {total_buy_quantity} 张")
        except Exception as e:
            print_warning_message(f"无法查询历史订单: {e}，使用当前持仓作为基准")
            total_buy_quantity = available_quantity
        
        # 3. 计算卖出数量
        sell_quantity_str = instruction.sell_quantity
        
        if sell_quantity_str:
            # 解析卖出数量
            if '/' in sell_quantity_str:
                # 分数形式: "1/3"
                parts = sell_quantity_str.split('/')
                numerator = int(parts[0])
                denominator = int(parts[1])
                sell_quantity = int(total_buy_quantity * numerator / denominator)
                print_info_message(f"卖出比例: {sell_quantity_str}, 计算数量: {sell_quantity} 张")
            elif '%' in sell_quantity_str:
                # 百分比形式: "30%"
                percent = float(sell_quantity_str.replace('%', ''))
                sell_quantity = int(total_buy_quantity * percent / 100)
                print_info_message(f"卖出比例: {sell_quantity_str}, 计算数量: {sell_quantity} 张")
            else:
                # 具体数量: "10"
                sell_quantity = int(sell_quantity_str)
                print_info_message(f"卖出数量: {sell_quantity} 张")
        else:
            # 默认卖出全部持仓
            sell_quantity = available_quantity
            print_info_message(f"未指定卖出数量，默认卖出全部持仓: {sell_quantity} 张")
        
        # 检查是否超过可用数量
        if sell_quantity > available_quantity:
            print_warning_message(f"卖出数量 {sell_quantity} 超过可用持仓 {available_quantity}，调整为可用数量")
            sell_quantity = available_quantity
        
        if sell_quantity <= 0:
            print_warning_message("卖出数量为0，跳过")
            return None
        
        # 确定卖出价格
        if instruction.price_range:
            price = (instruction.price_range[0] + instruction.price_range[1]) / 2
            print_info_message(f"价格区间: ${instruction.price_range[0]} - ${instruction.price_range[1]}, 使用中间值: ${price}")
        elif instruction.price:
            price = instruction.price
        else:
            print_warning_message("未指定卖出价格，使用市价单")
            price = None
        
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
                'remark': f"Auto sell: {instruction.raw_message[:50]}"
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
        print_info_message("=" * 80)
        print_info_message("执行清仓指令")
        print_info_message("=" * 80)
        
        # 生成期权代码
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
            print_warning_message(f"无持仓: {symbol}，跳过清仓")
            return None
        
        available_quantity = int(target_position.get('available_quantity', 0))
        print_info_message(f"当前持仓: {available_quantity} 张")
        
        if available_quantity <= 0:
            print_warning_message("可用持仓为0，跳过清仓")
            return None
        
        # 确定卖出价格
        if instruction.price_range:
            price = (instruction.price_range[0] + instruction.price_range[1]) / 2
            print_info_message(f"价格区间: ${instruction.price_range[0]} - ${instruction.price_range[1]}, 使用中间值: ${price}")
        elif instruction.price:
            price = instruction.price
        else:
            print_warning_message("未指定清仓价格，使用市价单")
            price = None
        
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
                'remark': f"Auto close: {instruction.raw_message[:50]}"
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
        print_info_message("=" * 80)
        print_info_message("执行修改指令（止盈止损）")
        print_info_message("=" * 80)
        
        # 生成期权代码
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
            print_warning_message(f"无持仓: {symbol}，跳过修改")
            return None
        
        available_quantity = int(target_position.get('available_quantity', 0))
        cost_price = target_position.get('cost_price', 0) / 100  # 转换为每股价格
        print_info_message(f"当前持仓: {available_quantity} 张, 成本价: ${cost_price:.2f}")
        
        # 2. 获取当前市场价格
        try:
            quotes = self.broker.get_option_quote([symbol])
            if quotes and len(quotes) > 0:
                current_price = quotes[0].get('last_done', 0)
                print_info_message(f"当前市场价: ${current_price:.2f}")
            else:
                print_warning_message("无法获取市场价格")
                current_price = None
        except Exception as e:
            print_warning_message(f"获取市场价格失败: {e}")
            current_price = None
        
        # 3. 检查是否满足止盈止损条件
        should_close = False
        close_reason = ""
        
        # 止损检查
        if instruction.stop_loss_price:
            stop_loss = instruction.stop_loss_price
            print_info_message(f"设置止损价: ${stop_loss:.2f}")
            
            if current_price and current_price <= stop_loss:
                should_close = True
                close_reason = f"触发止损 (当前价 ${current_price:.2f} <= 止损价 ${stop_loss:.2f})"
        elif instruction.stop_loss_range:
            stop_loss = (instruction.stop_loss_range[0] + instruction.stop_loss_range[1]) / 2
            print_info_message(f"设置止损价区间: ${instruction.stop_loss_range[0]} - ${instruction.stop_loss_range[1]}, 使用中间值: ${stop_loss:.2f}")
            
            if current_price and current_price <= stop_loss:
                should_close = True
                close_reason = f"触发止损 (当前价 ${current_price:.2f} <= 止损价 ${stop_loss:.2f})"
        
        # 止盈检查
        if instruction.take_profit_price:
            take_profit = instruction.take_profit_price
            print_info_message(f"设置止盈价: ${take_profit:.2f}")
            
            if current_price and current_price >= take_profit:
                should_close = True
                close_reason = f"触发止盈 (当前价 ${current_price:.2f} >= 止盈价 ${take_profit:.2f})"
        elif instruction.take_profit_range:
            take_profit = (instruction.take_profit_range[0] + instruction.take_profit_range[1]) / 2
            print_info_message(f"设置止盈价区间: ${instruction.take_profit_range[0]} - ${instruction.take_profit_range[1]}, 使用中间值: ${take_profit:.2f}")
            
            if current_price and current_price >= take_profit:
                should_close = True
                close_reason = f"触发止盈 (当前价 ${current_price:.2f} >= 止盈价 ${take_profit:.2f})"
        
        # 4. 如果满足止盈止损条件，立即清仓
        if should_close:
            print_warning_message(f"⚠️  {close_reason}")
            print_warning_message("立即执行清仓...")
            
            # 如果需要确认
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
            
            # 提交市价清仓订单
            try:
                result = self.broker.submit_option_order(
                    symbol=symbol,
                    side='SELL',
                    quantity=available_quantity,
                    price=None,
                    order_type='MARKET',
                    remark=f"Auto close: {close_reason}"
                )
                print_success_message(f"清仓订单提交成功! ({close_reason})")
                return result
            except Exception as e:
                print_error_message(f"清仓订单提交失败: {e}")
                return None
        
        # 5. 如果未触发，查询当前订单并修改止盈止损
        print_info_message("未触发止盈止损条件，查询未成交订单...")
        
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
                print_warning_message("未找到可修改的未成交买入订单")
                return None
            
            order_id = target_order['order_id']
            print_info_message(f"找到订单: {order_id}")
            
            # 修改订单（添加止盈止损）
            modify_params = {
                'order_id': order_id,
                'quantity': target_order['quantity']
            }
            
            # 添加止损价格
            if instruction.stop_loss_price:
                modify_params['trigger_price'] = instruction.stop_loss_price
            elif instruction.stop_loss_range:
                modify_params['trigger_price'] = (instruction.stop_loss_range[0] + instruction.stop_loss_range[1]) / 2
            
            # 添加止盈价格（通过trailing_percent实现）
            # 注意：longport API可能不直接支持止盈，这里仅作示例
            # 实际使用时需要根据API文档调整
            
            result = self.broker.replace_order(**modify_params)
            print_success_message("订单修改成功!")
            return result
            
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
