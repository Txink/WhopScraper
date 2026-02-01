"""
正股指令解析器
解析正股买卖交易信号
"""
import re
import hashlib
from typing import Optional
from models.instruction import OptionInstruction, InstructionType


class StockParser:
    """正股指令解析器"""
    
    # 买入指令正则
    # 格式1: AAPL 买入 $150
    # 格式2: 买入 TSLA 在 $250 附近
    # 格式3: NVDA $900 买
    # 格式4: 建仓 META 价格 $450
    BUY_PATTERN_1 = re.compile(
        r'([A-Z]{2,5})\s+(?:买入|买)\s+\$?(\d+(?:\.\d+)?)',
        re.IGNORECASE
    )
    
    BUY_PATTERN_2 = re.compile(
        r'(?:买入|买|建仓)\s+([A-Z]{2,5})\s+(?:在|价格)?\s*\$?(\d+(?:\.\d+)?)',
        re.IGNORECASE
    )
    
    BUY_PATTERN_3 = re.compile(
        r'([A-Z]{2,5})\s+\$?(\d+(?:\.\d+)?)\s+(?:买入|买)',
        re.IGNORECASE
    )
    
    # 卖出指令正则
    # 格式1: AAPL 卖出 $180
    # 格式2: 卖出 TSLA 在 $300
    # 格式3: NVDA $950 出
    # 格式4: 平仓 META 价格 $480
    SELL_PATTERN_1 = re.compile(
        r'([A-Z]{2,5})\s+(?:卖出|卖|出)\s+\$?(\d+(?:\.\d+)?)',
        re.IGNORECASE
    )
    
    SELL_PATTERN_2 = re.compile(
        r'(?:卖出|卖|出|平仓)\s+([A-Z]{2,5})\s+(?:在|价格)?\s*\$?(\d+(?:\.\d+)?)',
        re.IGNORECASE
    )
    
    SELL_PATTERN_3 = re.compile(
        r'([A-Z]{2,5})\s+\$?(\d+(?:\.\d+)?)\s+(?:卖出|卖|出)',
        re.IGNORECASE
    )
    
    # 止损指令正则
    # 示例: AAPL 止损 $145
    # 示例: 止损 TSLA 在 $240
    STOCK_STOP_LOSS_PATTERN = re.compile(
        r'(?:([A-Z]{2,5})\s+)?(?:止损|SL|stop\s*loss)\s+(?:([A-Z]{2,5})\s+)?(?:在)?\s*\$?(\d+(?:\.\d+)?)',
        re.IGNORECASE
    )
    
    # 止盈指令正则
    # 示例: AAPL 止盈 $200
    # 示例: 止盈 TSLA 在 $350 出一半
    STOCK_TAKE_PROFIT_PATTERN = re.compile(
        r'(?:([A-Z]{2,5})\s+)?(?:止盈|TP|take\s*profit)\s+(?:([A-Z]{2,5})\s+)?(?:在)?\s*\$?(\d+(?:\.\d+)?)'
        r'(?:\s+出\s*(一半|三分之一|三分之二|全部|1/2|1/3|2/3))?',
        re.IGNORECASE
    )
    
    # 仓位大小正则
    POSITION_SIZE_PATTERN = re.compile(
        r'(小仓位|中仓位|大仓位|轻仓|重仓|半仓|满仓)',
        re.IGNORECASE
    )
    
    # 比例映射
    PORTION_MAP = {
        '三分之一': '1/3',
        '三分之二': '2/3',
        '一半': '1/2',
        '全部': '全部',
        '1/3': '1/3',
        '2/3': '2/3',
        '1/2': '1/2',
    }
    
    @classmethod
    def parse(cls, message: str, message_id: Optional[str] = None) -> Optional[OptionInstruction]:
        """
        解析消息文本，返回正股指令
        
        注意: 为了保持与现有系统的兼容性，返回类型仍为 OptionInstruction
        但会在 option_type 字段标记为 'STOCK' 以区分
        
        Args:
            message: 原始消息文本
            message_id: 消息唯一标识（用于去重）
            
        Returns:
            OptionInstruction 或 None（如果无法解析）
        """
        message = message.strip()
        if not message:
            return None
        
        # 生成消息 ID（如果未提供）
        if not message_id:
            message_id = hashlib.md5(message.encode()).hexdigest()[:12]
        
        # 尝试解析买入指令
        instruction = cls._parse_buy(message, message_id)
        if instruction:
            return instruction
        
        # 尝试解析卖出指令
        instruction = cls._parse_sell(message, message_id)
        if instruction:
            return instruction
        
        # 尝试解析止损指令
        instruction = cls._parse_stop_loss(message, message_id)
        if instruction:
            return instruction
        
        # 尝试解析止盈指令
        instruction = cls._parse_take_profit(message, message_id)
        if instruction:
            return instruction
        
        # 无法解析
        return None
    
    @classmethod
    def _parse_buy(cls, message: str, message_id: str) -> Optional[OptionInstruction]:
        """解析买入指令 - 尝试多种模式"""
        
        # 尝试模式1
        match = cls.BUY_PATTERN_1.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            
            position_match = cls.POSITION_SIZE_PATTERN.search(message)
            position_size = position_match.group(1) if position_match else None
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.OPEN.value,
                ticker=ticker,
                option_type='STOCK',  # 标记为正股
                price=price,
                position_size=position_size,
                message_id=message_id
            )
        
        # 尝试模式2
        match = cls.BUY_PATTERN_2.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            
            position_match = cls.POSITION_SIZE_PATTERN.search(message)
            position_size = position_match.group(1) if position_match else None
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.OPEN.value,
                ticker=ticker,
                option_type='STOCK',
                price=price,
                position_size=position_size,
                message_id=message_id
            )
        
        # 尝试模式3
        match = cls.BUY_PATTERN_3.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            
            position_match = cls.POSITION_SIZE_PATTERN.search(message)
            position_size = position_match.group(1) if position_match else None
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.OPEN.value,
                ticker=ticker,
                option_type='STOCK',
                price=price,
                position_size=position_size,
                message_id=message_id
            )
        
        return None
    
    @classmethod
    def _parse_sell(cls, message: str, message_id: str) -> Optional[OptionInstruction]:
        """解析卖出指令 - 尝试多种模式"""
        
        # 尝试模式1
        match = cls.SELL_PATTERN_1.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.TAKE_PROFIT.value,
                ticker=ticker,
                option_type='STOCK',
                price=price,
                portion='全部',  # 默认全部卖出
                message_id=message_id
            )
        
        # 尝试模式2
        match = cls.SELL_PATTERN_2.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.TAKE_PROFIT.value,
                ticker=ticker,
                option_type='STOCK',
                price=price,
                portion='全部',
                message_id=message_id
            )
        
        # 尝试模式3
        match = cls.SELL_PATTERN_3.search(message)
        if match:
            ticker = match.group(1).upper()
            price = float(match.group(2))
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.TAKE_PROFIT.value,
                ticker=ticker,
                option_type='STOCK',
                price=price,
                portion='全部',
                message_id=message_id
            )
        
        return None
    
    @classmethod
    def _parse_stop_loss(cls, message: str, message_id: str) -> Optional[OptionInstruction]:
        """解析止损指令"""
        match = cls.STOCK_STOP_LOSS_PATTERN.search(message)
        if not match:
            return None
        
        ticker = match.group(1) or match.group(2)  # 股票代码可能在前或后
        price = float(match.group(3))
        
        return OptionInstruction(
            raw_message=message,
            instruction_type=InstructionType.STOP_LOSS.value,
            ticker=ticker.upper() if ticker else None,
            option_type='STOCK',
            price=price,
            message_id=message_id
        )
    
    @classmethod
    def _parse_take_profit(cls, message: str, message_id: str) -> Optional[OptionInstruction]:
        """解析止盈指令"""
        match = cls.STOCK_TAKE_PROFIT_PATTERN.search(message)
        if not match:
            return None
        
        ticker = match.group(1) or match.group(2)
        price = float(match.group(3))
        portion_raw = match.group(4) if len(match.groups()) >= 4 and match.group(4) else '全部'
        
        # 转换比例
        portion = cls.PORTION_MAP.get(portion_raw, portion_raw)
        
        return OptionInstruction(
            raw_message=message,
            instruction_type=InstructionType.TAKE_PROFIT.value,
            ticker=ticker.upper() if ticker else None,
            option_type='STOCK',
            price=price,
            portion=portion,
            message_id=message_id
        )
    
    @classmethod
    def parse_multi_line(cls, text: str) -> list:
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
        "AAPL 买入 $150",
        "买入 TSLA 在 $250",
        "NVDA $900 买",
        "AAPL 卖出 $180",
        "卖出 TSLA 在 $300",
        "NVDA $950 出",
        "AAPL 止损 $145",
        "止损 TSLA 在 $240",
        "AAPL 止盈 $200",
        "止盈 TSLA 在 $350 出一半",
    ]
    
    print("=" * 60)
    print("正股指令解析测试")
    print("=" * 60)
    
    for msg in test_messages:
        print(f"\n原始消息: {msg}")
        instruction = StockParser.parse(msg)
        if instruction:
            print(f"解析结果: {instruction}")
            print(f"JSON: {instruction.to_json()}")
        else:
            print("解析结果: 未能识别")
