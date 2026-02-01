"""
带上下文关联的期权指令解析器
支持：
1. 时间上下文 - 根据消息时间完善到期日期
2. 持仓上下文 - 关联止盈/止损到前面的开仓指令
"""
import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from dataclasses import dataclass, field
from parser.option_parser import OptionParser
from models.instruction import OptionInstruction

@dataclass
class PositionContext:
    """持仓上下文"""
    ticker: str
    option_type: str  # CALL/PUT
    strike: float
    expiry: Optional[str]
    entry_price: float
    position_size: Optional[str]
    open_time: datetime
    message_id: str
    
    def __str__(self):
        return f"{self.ticker} ${self.strike} {self.option_type} @ ${self.entry_price}"


class ContextParser:
    """带上下文的期权指令解析器"""
    
    def __init__(self):
        self.position_contexts: List[PositionContext] = []  # 当前持仓上下文
        self.base_parser = OptionParser()
        
    def parse_message_time(self, message_text: str) -> Optional[datetime]:
        """从消息中提取时间"""
        # 尝试匹配各种时间格式
        patterns = [
            # Jan 20, 2026 10:37 PM
            (r'(\w+)\s+(\d+),\s+(\d{4})\s+(\d+):(\d+)\s+(AM|PM)', self._parse_full_datetime),
            # Yesterday at 10:39 PM - 需要基准时间
            (r'Yesterday at (\d+):(\d+)\s+(AM|PM)', self._parse_yesterday),
            # 2:22 AM (今天)
            (r'^(\d+):(\d+)\s+(AM|PM)$', self._parse_time_only),
        ]
        
        for pattern, parser_func in patterns:
            match = re.search(pattern, message_text)
            if match:
                return parser_func(match)
        
        return None
    
    def _parse_full_datetime(self, match) -> datetime:
        """解析完整日期时间"""
        month_str, day, year, hour, minute, ampm = match.groups()
        
        # 月份映射
        months = {
            'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
            'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12,
            'January': 1, 'February': 2, 'March': 3, 'April': 4,
            'May': 5, 'June': 6, 'July': 7, 'August': 8,
            'September': 9, 'October': 10, 'November': 11, 'December': 12
        }
        
        month = months.get(month_str, 1)
        hour = int(hour)
        if ampm == 'PM' and hour != 12:
            hour += 12
        elif ampm == 'AM' and hour == 12:
            hour = 0
            
        return datetime(int(year), month, int(day), hour, int(minute))
    
    def _parse_yesterday(self, match) -> datetime:
        """解析Yesterday格式 - 假设基准时间为2026-01-30"""
        hour, minute, ampm = match.groups()
        hour = int(hour)
        if ampm == 'PM' and hour != 12:
            hour += 12
        elif ampm == 'AM' and hour == 12:
            hour = 0
        
        # 假设基准日期为2026-01-30
        base_date = datetime(2026, 1, 30)
        yesterday = base_date - timedelta(days=1)
        return datetime(yesterday.year, yesterday.month, yesterday.day, hour, int(minute))
    
    def _parse_time_only(self, match) -> datetime:
        """解析仅时间格式 - 假设是今天"""
        hour, minute, ampm = match.groups()
        hour = int(hour)
        if ampm == 'PM' and hour != 12:
            hour += 12
        elif ampm == 'AM' and hour == 12:
            hour = 0
        
        # 假设是2026-01-30
        return datetime(2026, 1, 30, hour, int(minute))
    
    def calculate_expiry_date(self, expiry_str: Optional[str], message_time: Optional[datetime]) -> Optional[str]:
        """根据消息时间计算到期日期"""
        if not expiry_str or not message_time:
            return expiry_str
        
        # 如果已经是明确日期，直接返回
        if re.match(r'\d{1,2}/\d{1,2}', expiry_str):
            return expiry_str
        
        # 处理相对时间
        if expiry_str in ['本周', '这周', '当周']:
            # 找到本周五
            days_until_friday = (4 - message_time.weekday()) % 7
            if days_until_friday == 0 and message_time.hour >= 16:
                days_until_friday = 7  # 如果是周五下午4点后，指下周五
            friday = message_time + timedelta(days=days_until_friday)
            return f"{friday.month}/{friday.day}"
        
        elif expiry_str in ['下周']:
            # 找到下周五
            days_until_friday = (4 - message_time.weekday()) % 7
            if days_until_friday == 0:
                days_until_friday = 7
            else:
                days_until_friday += 7
            friday = message_time + timedelta(days=days_until_friday)
            return f"{friday.month}/{friday.day}"
        
        elif expiry_str == '今天':
            return f"{message_time.month}/{message_time.day}"
        
        # 处理"1月30"格式，补充年份
        month_day_match = re.match(r'(\d{1,2})月(\d{1,2})日?', expiry_str)
        if month_day_match:
            month, day = month_day_match.groups()
            return f"{month}/{day}"
        
        return expiry_str
    
    def parse_with_context(self, message_text: str, message_id: Optional[str] = None) -> Optional[OptionInstruction]:
        """带上下文解析消息"""
        
        # 提取消息时间
        message_time = self.parse_message_time(message_text)
        
        # 先用基础解析器解析
        instruction = self.base_parser.parse(message_text, message_id)
        
        if not instruction:
            return None
        
        # 如果是开仓指令
        if instruction.instruction_type == 'OPEN':
            # 完善到期时间
            if instruction.expiry and message_time:
                instruction.expiry = self.calculate_expiry_date(instruction.expiry, message_time)
            
            # 添加到持仓上下文
            context = PositionContext(
                ticker=instruction.ticker,
                option_type=instruction.option_type,
                strike=instruction.strike,
                expiry=instruction.expiry,
                entry_price=instruction.price,
                position_size=instruction.position_size,
                open_time=message_time or datetime.now(),
                message_id=message_id or instruction.message_id
            )
            self.position_contexts.append(context)
            
        # 如果是止损/止盈指令，但没有标的信息
        elif instruction.instruction_type in ['STOP_LOSS', 'TAKE_PROFIT', 'ADJUST']:
            if not instruction.ticker and self.position_contexts:
                # 关联到最近的持仓
                latest_context = self.position_contexts[-1]
                instruction.ticker = latest_context.ticker
                instruction.option_type = latest_context.option_type
                instruction.strike = latest_context.strike
                instruction.expiry = latest_context.expiry
                
                # 如果是"全部"出货，清除该持仓上下文
                if instruction.instruction_type == 'TAKE_PROFIT' and instruction.portion == '全部':
                    # 检查是否明确说"全部"/"剩下"
                    if any(keyword in message_text for keyword in ['全部', '剩下', '全出', '都出']):
                        # 移除最后一个持仓（已清仓）
                        if self.position_contexts:
                            self.position_contexts.pop()
        
        return instruction
    
    def get_current_positions(self) -> List[PositionContext]:
        """获取当前持仓上下文"""
        return self.position_contexts.copy()
    
    def clear_position(self, ticker: str, strike: float):
        """清除特定持仓"""
        self.position_contexts = [
            ctx for ctx in self.position_contexts
            if not (ctx.ticker == ticker and ctx.strike == strike)
        ]
    
    def clear_all_positions(self):
        """清除所有持仓上下文"""
        self.position_contexts.clear()


def parse_messages_with_context(messages: List[Dict]) -> List[Dict]:
    """
    批量解析消息并关联上下文
    
    Args:
        messages: 消息列表，每个消息包含 'text', 'id', 'timestamp' 等字段
        
    Returns:
        解析后的指令列表，包含上下文信息
    """
    parser = ContextParser()
    results = []
    
    for msg in messages:
        text = msg.get('text', '')
        msg_id = msg.get('id', '')
        
        if len(text) < 10:
            continue
        
        instruction = parser.parse_with_context(text, msg_id)
        
        if instruction:
            # 添加上下文信息到结果
            result = {
                'instruction': instruction.to_dict(),
                'original_text': text[:200],
                'message_id': msg_id,
                'has_context': bool(instruction.ticker),
                'current_positions': len(parser.get_current_positions())
            }
            results.append(result)
    
    return results


# 测试用例
if __name__ == "__main__":
    parser = ContextParser()
    
    test_messages = [
        # 开仓
        ("Jan 20, 2026 10:37 PM", "INTC - $52 CALLS 1月30 1.25 止损在1.00 小仓位", "msg1"),
        # 止盈 - 应该关联到INTC
        ("Jan 20, 2026 10:41 PM", "1.4出三分之一", "msg2"),
        # 止盈 - 应该关联到INTC
        ("Jan 20, 2026 10:42 PM", "1.35出剩下的intc", "msg3"),
        # 新的开仓
        ("Jan 21, 2026 10:57 PM", "AMZN 250c 2/20 4.00 小仓位", "msg4"),
        # 止损 - 应该关联到AMZN
        ("Jan 21, 2026 11:00 PM", "日内止损在3.7", "msg5"),
        # 止盈 - 应该关联到AMZN
        ("Jan 21, 2026 11:35 PM", "4.15-4.2出", "msg6"),
    ]
    
    print("=" * 80)
    print("带上下文的期权指令解析测试")
    print("=" * 80)
    
    for time_str, text, msg_id in test_messages:
        full_text = f"{time_str}\n\n{text}"
        instruction = parser.parse_with_context(full_text, msg_id)
        
        print(f"\n消息: {text}")
        if instruction:
            print(f"解析结果: {instruction.instruction_type}")
            if instruction.ticker:
                print(f"  标的: {instruction.ticker}")
            if instruction.option_type:
                print(f"  类型: {instruction.option_type}")
            if instruction.strike:
                print(f"  行权价: ${instruction.strike}")
            if instruction.expiry:
                print(f"  到期: {instruction.expiry}")
            if instruction.price:
                print(f"  价格: ${instruction.price}")
            if instruction.portion:
                print(f"  比例: {instruction.portion}")
            print(f"  当前持仓数: {len(parser.get_current_positions())}")
        else:
            print("未能解析")
    
    print("\n" + "=" * 80)
    print("最终持仓上下文:")
    print("=" * 80)
    for ctx in parser.get_current_positions():
        print(f"  {ctx}")
