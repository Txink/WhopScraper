"""
期权指令正则解析器
解析各种类型的期权交易信号
"""
import re
import hashlib
from typing import Optional
from models.instruction import OptionInstruction, InstructionType


class OptionParser:
    """期权指令解析器"""
    
    @staticmethod
    def _resolve_relative_date(relative_date: str, message_timestamp: Optional[str] = None) -> str:
        """
        将相对日期（如"今天"、"下周"）转换为具体日期
        
        Args:
            relative_date: 相对日期字符串
            message_timestamp: 消息时间戳（如 "Jan 22, 2026 10:41 PM"）
            
        Returns:
            具体日期字符串
        """
        from datetime import datetime, timedelta
        
        # 如果没有消息时间戳，返回原值
        if not message_timestamp:
            return relative_date
        
        # 解析消息时间戳
        try:
            # 尝试解析 "Jan 22, 2026 10:41 PM" 格式
            msg_date = datetime.strptime(message_timestamp, '%b %d, %Y %I:%M %p')
        except:
            return relative_date
        
        # 计算相对日期
        relative_lower = relative_date.lower()
        
        if relative_lower in ['今天', 'today']:
            target_date = msg_date
        elif relative_lower in ['明天', 'tomorrow']:
            target_date = msg_date + timedelta(days=1)
        elif relative_lower in ['本周', '这周', '当周', 'this week']:
            # 本周五
            days_until_friday = (4 - msg_date.weekday()) % 7
            if days_until_friday == 0:
                days_until_friday = 7  # 如果今天是周五，指向下周五
            target_date = msg_date + timedelta(days=days_until_friday)
        elif relative_lower in ['下周', 'next week']:
            # 下周五
            days_until_friday = (4 - msg_date.weekday()) % 7
            target_date = msg_date + timedelta(days=days_until_friday + 7)
        else:
            return relative_date
        
        # 返回格式化的日期（如 "1/31"）
        return target_date.strftime('%-m/%-d')
    
    # 开仓指令正则（多种格式支持）
    # 格式1: INTC - $52 CALLS 1月30 $1.25
    # 格式2: QQQ 11/20 614c 入场价：1.1
    # 格式3: EOSE 1月9日13.5的call 0.45
    # 格式4: RIVN 16c 3/20 1.35
    # 格式5: META 900call 2.1
    
    # 模式1: 标准格式 - 股票 行权价 CALL/PUT 到期 价格（支持价格范围）
    OPEN_PATTERN_1 = re.compile(
        r'([A-Z]{2,5})\s*[-–]?\s*\$?(\d+(?:\.\d+)?)\s*'
        r'(CALLS?|PUTS?)\s*'
        r'(?:(本周|下周|这周|当周|今天|EXPIRATION\s+)?\s*(\d{1,2}/\d{1,2}|\d{1,2}月\d{1,2}日?|1月\d{1,2}|2月\d{1,2})\s*)?'
        r'\$?(\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?)',  # 支持价格范围 如 0.8-0.85 或 1.5-1.60
        re.IGNORECASE
    )
    
    # 模式2: 简化格式 - 股票 行权价c/p 到期 价格 (如: QQQ 614c 11/20 1.1)
    OPEN_PATTERN_2 = re.compile(
        r'([A-Z]{2,5})\s+(?:\d{1,2}/\d{1,2}\s+)?'
        r'(\d+(?:\.\d+)?)[cCpP]\s+'
        r'(?:(\d{1,2}/\d{1,2}|1月\d{1,2}|2月\d{1,2}|本周|下周|这周)\s+)?'
        r'(?:入场价?[：:])?\s*'
        r'(\d+(?:\.\d+)?)',
        re.IGNORECASE
    )
    
    # 模式3: 到期在前格式 - 股票 到期 行权价 call/put 价格 (如: EOSE 1月9日 13.5的call 0.45)
    OPEN_PATTERN_3 = re.compile(
        r'([A-Z]{2,5})\s+'
        r'(\d{1,2}月\d{1,2}日?|本周|下周|这周)\s*'
        r'(\d+(?:\.\d+)?)(?:的)?\s*'
        r'(call|put)s?\s+'
        r'(\d+(?:\.\d+)?)',
        re.IGNORECASE
    )
    
    # 模式4: 紧凑格式 - 股票 行权价call/put 价格 (如: META 900call 2.1)
    OPEN_PATTERN_4 = re.compile(
        r'([A-Z]{2,5})\s+'
        r'(\d+(?:\.\d+)?)(call|put)s?\s*'
        r'(?:可以)?(?:在)?'
        r'(\d+(?:\.\d+)?)',
        re.IGNORECASE
    )
    
    # 模式5: 带$符号开头 - $RIVN 1月9日 $20 call $0.35 或 $EOSE call 本周 $18 0.5
    OPEN_PATTERN_5 = re.compile(
        r'\$([A-Z]{2,5})\s+'
        r'(?:(call|put)s?\s+)?'  # call/put可以在前面
        r'(?:(本周|下周|这周|当周|今天)?\s*)?'  # 支持相对日期
        r'(?:(\d{1,2}月\d{1,2}日?)\s+)?'
        r'\$?(\d+(?:\.\d+)?)\s+'
        r'(?:(call|put)s?\s+)?'  # call/put也可以在后面
        r'\$?(\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?)',  # 支持价格范围
        re.IGNORECASE
    )
    
    # 模式6: 日期格式YYMMDD - rklb 251017 本周的 71call 0.6
    OPEN_PATTERN_6 = re.compile(
        r'([a-zA-Z]{2,5})\s+'
        r'\d{6}\s+'
        r'(本周|下周|这周)(?:的)?\s+'
        r'(\d+(?:\.\d+)?)(call|put)s?\s+'
        r'(?:可以注意)?.*?'
        r'(\d+(?:\.\d+)?)',
        re.IGNORECASE
    )
    
    # 止损指令正则
    # 示例: 止损 0.95
    # 示例: 止损在1.00
    # 示例: 止损设置在0.17
    # 示例: 止损 在 1.3
    # 示例: SL 0.95
    STOP_LOSS_PATTERN = re.compile(
        r'(?:止损|SL|stop\s*loss)\s*(?:设置)?(?:在)?\s*(\d+(?:\.\d+)?)',
        re.IGNORECASE
    )
    
    # 调整止损正则
    # 示例: 止损提高到1.5
    # 示例: 止损调整到 1.5
    # 示例: 止损设置上移到2.16
    # 示例: 止损上移到2.25
    ADJUST_STOP_PATTERN = re.compile(
        r'(?:止损|SL|stop\s*loss)\s*(?:设置)?(?:提高|调整|移动|上调|上移)(?:到|至)?\s*(\d+(?:\.\d+)?)',
        re.IGNORECASE
    )
    
    # 止盈/出货指令正则（多种格式）
    # 示例: 1.75出三分之一
    # 示例: 1.65附近出剩下三分之二
    # 示例: 2.0 出一半
    # 示例: 0.9剩下都出
    # 示例: 1.5附近把剩下都出了
    # 示例: 0.61出剩余的
    # 示例: 4.75 amd全出
    # 示例: 2.3附近都出
    # 示例: 2.45也在剩下减一半
    
    # 模式1: 价格+出+比例
    TAKE_PROFIT_PATTERN_1 = re.compile(
        r'(\d+(?:\.\d+)?)\s*(?:附近|左右)?\s*(?:也)?'
        r'(?:出|减)\s*'
        r'(?:剩下|剩余|个)?\s*'
        r'(三分之一|三分之二|三之一|一半|全部|1/3|2/3|1/2|\d+%)',
        re.IGNORECASE
    )
    
    # 模式2: 价格+剩下+都出 (如: 0.9剩下都出)
    TAKE_PROFIT_PATTERN_2 = re.compile(
        r'(\d+(?:\.\d+)?)\s*(?:附近|左右)?\s*'
        r'(?:把)?(?:剩下|剩余)(?:的)?(?:都|全)?出(?:了)?',
        re.IGNORECASE
    )
    
    # 模式3: 价格+出+剩余的 (如: 0.61出剩余的)
    TAKE_PROFIT_PATTERN_3 = re.compile(
        r'(\d+(?:\.\d+)?)\s*(?:附近)?\s*出\s*(?:剩余|剩下)(?:的)?(?:\s+\w+)?',
        re.IGNORECASE
    )
    
    # 模式4: 价格+股票+全出 (如: 4.75 amd全出)
    TAKE_PROFIT_PATTERN_4 = re.compile(
        r'(\d+(?:\.\d+)?)\s*\w*\s*全出',
        re.IGNORECASE
    )
    
    # 模式5: 价格+附近+都出 (如: 2.3附近都出)
    TAKE_PROFIT_PATTERN_5 = re.compile(
        r'(\d+(?:\.\d+)?)\s*附近\s*都出',
        re.IGNORECASE
    )
    
    # 模式6: 价格+再出+比例 (如: 0.7再出剩下的一半)
    TAKE_PROFIT_PATTERN_6 = re.compile(
        r'(\d+(?:\.\d+)?)\s*(?:再|也)?(?:在)?\s*(?:剩下)?\s*(?:出|减)\s*(?:剩下|剩余)?\s*(一半|三分之一|三分之二)',
        re.IGNORECASE
    )
    
    # 模式7: 行权价描述+到价格出 (如: 47 call到1.1出)
    TAKE_PROFIT_PATTERN_7 = re.compile(
        r'\d+\s*(?:call|put)\s*到\s*(\d+(?:\.\d+)?)\s*出',
        re.IGNORECASE
    )
    
    # 模式8: 价格+也在剩下减一半 (如: 2.45也在剩下减一半)
    TAKE_PROFIT_PATTERN_8 = re.compile(
        r'(\d+(?:\.\d+)?)\s*也在?\s*剩下\s*减\s*(一半|三分之一|三分之二)',
        re.IGNORECASE
    )
    
    # 仓位大小正则
    # 示例: 小仓位
    # 示例: 中仓位
    # 示例: 大仓位
    POSITION_SIZE_PATTERN = re.compile(
        r'(小仓位|中仓位|大仓位|轻仓|重仓|半仓|满仓)',
        re.IGNORECASE
    )
    
    # 比例映射
    PORTION_MAP = {
        '三分之一': '1/3',
        '三之一': '1/3',  # 错别字
        '三分之二': '2/3',
        '一半': '1/2',
        '全部': '全部',
        '1/3': '1/3',
        '2/3': '2/3',
        '1/2': '1/2',
    }
    
    @classmethod
    def parse(cls, message: str, message_id: Optional[str] = None, message_timestamp: Optional[str] = None) -> Optional[OptionInstruction]:
        """
        解析消息文本，返回期权指令
        
        Args:
            message: 原始消息文本
            message_id: 消息唯一标识（用于去重）
            message_timestamp: 消息发送时间（用于计算相对日期，如"今天"、"下周"）
            
        Returns:
            OptionInstruction 或 None（如果无法解析）
        """
        message = message.strip()
        if not message:
            return None
        
        # 生成消息 ID（如果未提供）
        if not message_id:
            message_id = hashlib.md5(message.encode()).hexdigest()[:12]
        
        # 尝试解析修改指令（止损/止盈）
        instruction = cls._parse_modify(message, message_id)
        if instruction:
            return instruction
        
        # 尝试解析买入指令（传入时间戳用于计算相对日期）
        instruction = cls._parse_buy(message, message_id, message_timestamp)
        if instruction:
            return instruction
        
        # 尝试解析卖出/清仓指令
        instruction = cls._parse_sell(message, message_id)
        if instruction:
            return instruction
        
        # 无法解析
        return None
    
    @staticmethod
    def _parse_price_range(price_str: str) -> tuple:
        """
        解析价格字符串，返回 (单价, 价格区间)
        
        Args:
            price_str: 价格字符串，如 "0.83" 或 "0.83-0.85"
            
        Returns:
            (price, price_range): 单价和价格区间
            - 如果是单价：返回 (0.83, None)
            - 如果是区间：返回 (0.84, [0.83, 0.85])  # 单价取中间值
        """
        if '-' in price_str:
            try:
                parts = price_str.split('-')
                price_low = float(parts[0])
                price_high = float(parts[1])
                price_mid = (price_low + price_high) / 2
                return (price_mid, [price_low, price_high])
            except:
                return (float(price_str.split('-')[0]), None)
        else:
            return (float(price_str), None)
    
    @classmethod
    def _parse_buy(cls, message: str, message_id: str, message_timestamp: Optional[str] = None) -> Optional[OptionInstruction]:
        """解析买入指令 - 尝试多种模式"""
        
        # 尝试模式1: 标准格式
        match = cls.OPEN_PATTERN_1.search(message)
        if match:
            ticker = match.group(1).upper()
            strike = float(match.group(2))
            option_type = match.group(3).upper()
            option_type = 'CALL' if option_type.startswith('CALL') else 'PUT'
            expiry_raw = match.group(5) if match.group(5) else None
            price_str = match.group(6)
            
            # 解析价格（支持价格区间）
            price, price_range = cls._parse_price_range(price_str)
            
            # 处理相对日期
            expiry = cls._resolve_relative_date(expiry_raw, message_timestamp) if expiry_raw else None
            
            position_match = cls.POSITION_SIZE_PATTERN.search(message)
            position_size = position_match.group(1) if position_match else None
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                option_type=option_type,
                strike=strike,
                expiry=expiry,
                price=price,
                price_range=price_range,
                position_size=position_size,
                message_id=message_id
            )
        
        # 尝试模式2: 简化格式 (614c)
        match = cls.OPEN_PATTERN_2.search(message)
        if match:
            ticker = match.group(1).upper()
            strike = float(match.group(2))
            # 从614c中提取c或p
            option_indicator = message[match.start():match.end()]
            option_type = 'CALL' if 'c' in option_indicator or 'C' in option_indicator else 'PUT'
            expiry_raw = match.group(3) if match.group(3) else None
            price_str = match.group(4)
            
            # 解析价格（支持价格区间）
            price, price_range = cls._parse_price_range(price_str)
            
            # 处理相对日期
            expiry = cls._resolve_relative_date(expiry_raw, message_timestamp) if expiry_raw else None
            
            position_match = cls.POSITION_SIZE_PATTERN.search(message)
            position_size = position_match.group(1) if position_match else None
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                option_type=option_type,
                strike=strike,
                expiry=expiry,
                price=price,
                price_range=price_range,
                position_size=position_size,
                message_id=message_id
            )
        
        # 尝试模式3: 到期在前格式
        match = cls.OPEN_PATTERN_3.search(message)
        if match:
            ticker = match.group(1).upper()
            expiry_raw = match.group(2)
            strike = float(match.group(3))
            option_type = match.group(4).upper()
            option_type = 'CALL' if option_type.startswith('CALL') else 'PUT'
            price_str = match.group(5)
            
            # 解析价格（支持价格区间）
            price, price_range = cls._parse_price_range(price_str)
            
            # 处理相对日期
            expiry = cls._resolve_relative_date(expiry_raw, message_timestamp) if expiry_raw else None
            
            position_match = cls.POSITION_SIZE_PATTERN.search(message)
            position_size = position_match.group(1) if position_match else None
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                option_type=option_type,
                strike=strike,
                expiry=expiry,
                price=price,
                price_range=price_range,
                position_size=position_size,
                message_id=message_id
            )
        
        # 尝试模式4: 紧凑格式 (900call)
        match = cls.OPEN_PATTERN_4.search(message)
        if match:
            ticker = match.group(1).upper()
            strike = float(match.group(2))
            option_type = match.group(3).upper()
            option_type = 'CALL' if option_type.startswith('CALL') else 'PUT'
            price_str = match.group(4)
            
            # 解析价格（支持价格区间）
            price, price_range = cls._parse_price_range(price_str)
            
            position_match = cls.POSITION_SIZE_PATTERN.search(message)
            position_size = position_match.group(1) if position_match else None
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                option_type=option_type,
                strike=strike,
                expiry=None,
                price=price,
                price_range=price_range,
                position_size=position_size,
                message_id=message_id
            )
        
        # 尝试模式5: 带$符号开头（$EOSE call 本周 $18 0.5）
        match = cls.OPEN_PATTERN_5.search(message)
        if match:
            ticker = match.group(1).upper()
            # call/put可能在group 2或group 6
            option_type_str = match.group(2) or match.group(6)
            if option_type_str:
                option_type = 'CALL' if option_type_str.upper().startswith('CALL') else 'PUT'
            else:
                option_type = 'CALL'  # 默认CALL
            
            # 获取相对日期和具体日期
            relative_date = match.group(3)  # 本周、下周
            specific_date = match.group(4)  # 1月9日
            expiry_raw = relative_date or specific_date
            
            strike = float(match.group(5))
            price_str = match.group(7)
            
            # 解析价格（支持价格区间）
            price, price_range = cls._parse_price_range(price_str)
            
            # 处理相对日期
            expiry = cls._resolve_relative_date(expiry_raw, message_timestamp) if expiry_raw else None
            
            position_match = cls.POSITION_SIZE_PATTERN.search(message)
            position_size = position_match.group(1) if position_match else None
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                option_type=option_type,
                strike=strike,
                expiry=expiry,
                price=price,
                price_range=price_range,
                position_size=position_size,
                message_id=message_id
            )
        
        # 尝试模式6: 日期格式YYMMDD
        match = cls.OPEN_PATTERN_6.search(message)
        if match:
            ticker = match.group(1).upper()
            expiry_raw = match.group(2)
            strike = float(match.group(3))
            option_type = match.group(4).upper()
            option_type = 'CALL' if option_type.startswith('CALL') else 'PUT'
            price_str = match.group(5)
            
            # 解析价格（支持价格区间）
            price, price_range = cls._parse_price_range(price_str)
            
            # 处理相对日期
            expiry = cls._resolve_relative_date(expiry_raw, message_timestamp) if expiry_raw else None
            
            position_match = cls.POSITION_SIZE_PATTERN.search(message)
            position_size = position_match.group(1) if position_match else None
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.BUY.value,
                ticker=ticker,
                option_type=option_type,
                strike=strike,
                expiry=expiry,
                price=price,
                price_range=price_range,
                position_size=position_size,
                message_id=message_id
            )
        
        return None
    
    @classmethod
    def _parse_modify(cls, message: str, message_id: str) -> Optional[OptionInstruction]:
        """
        解析修改指令（止损/止盈）
        
        支持格式：
        - 止损 0.95
        - 止损提高到1.5
        - 止盈一半intc
        """
        # 尝试匹配调整止损（优先级高）
        adjust_match = cls.ADJUST_STOP_PATTERN.search(message)
        if adjust_match:
            price_str = adjust_match.group(1)
            price, price_range = cls._parse_price_range(price_str)
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.MODIFY.value,
                stop_loss_price=price,
                stop_loss_range=price_range,
                message_id=message_id
            )
        
        # 尝试匹配普通止损
        stop_loss_match = cls.STOP_LOSS_PATTERN.search(message)
        if stop_loss_match:
            price_str = stop_loss_match.group(1)
            price, price_range = cls._parse_price_range(price_str)
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.MODIFY.value,
                stop_loss_price=price,
                stop_loss_range=price_range,
                message_id=message_id
            )
        
        return None
    
    @staticmethod
    def _parse_sell_quantity(portion_str: str) -> tuple:
        """
        解析卖出数量，返回 (instruction_type, sell_quantity)
        
        Args:
            portion_str: 数量字符串，如 "1/3", "30%", "100", "全部"
            
        Returns:
            (instruction_type, sell_quantity):
            - SELL类型: ("SELL", "1/3") 或 ("SELL", "30%") 或 ("SELL", "100")
            - CLOSE类型: ("CLOSE", None)
        """
        portion_str = portion_str.strip()
        
        # 判断是否为清仓
        if portion_str in ['全部', '剩下', '都', '剩余']:
            return (InstructionType.CLOSE.value, None)
        
        # 判断是否为百分比
        if portion_str.endswith('%'):
            return (InstructionType.SELL.value, portion_str)
        
        # 判断是否为比例（如 1/3, 2/3）
        if '/' in portion_str or portion_str in ['三分之一', '三分之二', '一半']:
            # 转换中文比例
            portion_map = {
                '三分之一': '1/3',
                '三之一': '1/3',
                '三分之二': '2/3',
                '一半': '1/2',
            }
            quantity = portion_map.get(portion_str, portion_str)
            return (InstructionType.SELL.value, quantity)
        
        # 判断是否为具体数量（纯数字）
        try:
            int(portion_str)
            return (InstructionType.SELL.value, portion_str)
        except:
            pass
        
        # 默认当作全部
        return (InstructionType.CLOSE.value, None)
    
    @classmethod
    def _parse_sell(cls, message: str, message_id: str) -> Optional[OptionInstruction]:
        """解析卖出/清仓指令 - 尝试多种模式"""
        
        # 尝试模式1: 价格+出+比例（如: 1.75出三分之一）
        match = cls.TAKE_PROFIT_PATTERN_1.search(message)
        if match:
            price_str = match.group(1)
            portion_raw = match.group(2)
            
            # 解析价格
            price, price_range = cls._parse_price_range(price_str)
            
            # 解析卖出数量
            instruction_type, sell_quantity = cls._parse_sell_quantity(portion_raw)
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=instruction_type,
                price=price,
                price_range=price_range,
                sell_quantity=sell_quantity,
                message_id=message_id
            )
        
        # 尝试模式2: 价格+剩下都出（如: 0.9剩下都出）
        match = cls.TAKE_PROFIT_PATTERN_2.search(message)
        if match:
            price_str = match.group(1)
            price, price_range = cls._parse_price_range(price_str)
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.CLOSE.value,
                price=price,
                price_range=price_range,
                message_id=message_id
            )
        
        # 尝试模式3: 价格+出剩余的（如: 0.61出剩余的）
        match = cls.TAKE_PROFIT_PATTERN_3.search(message)
        if match:
            price_str = match.group(1)
            price, price_range = cls._parse_price_range(price_str)
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.CLOSE.value,
                price=price,
                price_range=price_range,
                message_id=message_id
            )
        
        # 尝试模式4: 价格+全出（如: 4.75 amd全出）
        match = cls.TAKE_PROFIT_PATTERN_4.search(message)
        if match:
            price_str = match.group(1)
            price, price_range = cls._parse_price_range(price_str)
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.CLOSE.value,
                price=price,
                price_range=price_range,
                message_id=message_id
            )
        
        # 尝试模式5: 价格+附近都出（如: 2.3附近都出）
        match = cls.TAKE_PROFIT_PATTERN_5.search(message)
        if match:
            price_str = match.group(1)
            price, price_range = cls._parse_price_range(price_str)
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.CLOSE.value,
                price=price,
                price_range=price_range,
                message_id=message_id
            )
        
        # 尝试模式6: 价格+再出+比例（如: 0.7再出剩下的一半，2.45也在剩下减一半）
        match = cls.TAKE_PROFIT_PATTERN_6.search(message)
        if match:
            price_str = match.group(1)
            portion_raw = match.group(2)
            
            # 解析价格
            price, price_range = cls._parse_price_range(price_str)
            
            # 解析卖出数量
            instruction_type, sell_quantity = cls._parse_sell_quantity(portion_raw)
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=instruction_type,
                price=price,
                price_range=price_range,
                sell_quantity=sell_quantity,
                message_id=message_id
            )
        
        # 尝试模式7: 行权价描述+到价格出（如: 47 call到1.1出）
        match = cls.TAKE_PROFIT_PATTERN_7.search(message)
        if match:
            price_str = match.group(1)
            price, price_range = cls._parse_price_range(price_str)
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.CLOSE.value,
                price=price,
                price_range=price_range,
                message_id=message_id
            )
        
        # 尝试模式8: 价格+也在剩下减一半（如: 2.45也在剩下减一半）
        match = cls.TAKE_PROFIT_PATTERN_8.search(message)
        if match:
            price_str = match.group(1)
            portion_raw = match.group(2)
            
            # 解析价格
            price, price_range = cls._parse_price_range(price_str)
            
            # 解析卖出数量
            instruction_type, sell_quantity = cls._parse_sell_quantity(portion_raw)
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=instruction_type,
                price=price,
                price_range=price_range,
                sell_quantity=sell_quantity,
                message_id=message_id
            )
        
        return None
    
    @classmethod
    def parse_multi_line(cls, text: str) -> list[OptionInstruction]:
        """
        解析多行文本，返回所有识别的指令
        
        Args:
            text: 包含多行的文本
            
        Returns:
            解析出的指令列表
        """
        instructions = []
        lines = text.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            instruction = cls.parse(line)
            if instruction:
                instructions.append(instruction)
        
        return instructions


# 测试用例
if __name__ == "__main__":
    test_messages = [
        "INTC - $48 CALLS 本周 $1.2",
        "小仓位  止损 0.95",
        "1.75出三分之一",
        "止损提高到1.5",
        "1.65附近出剩下三分之二",
        "AAPL $150 PUTS 1/31 $2.5",
        "TSLA - 250 CALL $3.0 小仓位",
        "2.0 出一半",
        "止损调整到 1.8",
    ]
    
    print("=" * 60)
    print("期权指令解析测试")
    print("=" * 60)
    
    for msg in test_messages:
        print(f"\n原始消息: {msg}")
        instruction = OptionParser.parse(msg)
        if instruction:
            print(f"解析结果: {instruction}")
            print(f"JSON: {instruction.to_json()}")
        else:
            print("解析结果: 未能识别")
