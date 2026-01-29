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
    
    # 开仓指令正则
    # 示例: INTC - $48 CALLS 本周 $1.2
    # 示例: AAPL $150 PUTS 1/31 $2.5
    # 示例: TSLA - 250 CALL $3.0
    OPEN_PATTERN = re.compile(
        r'([A-Z]{1,5})\s*[-–]?\s*\$?(\d+(?:\.\d+)?)\s*'
        r'(CALLS?|PUTS?|call|put)\s*'
        r'(?:(本周|下周|这周|当周|\d{1,2}/\d{1,2}|\d{1,2}月\d{1,2}日?)\s*)?'
        r'\$?(\d+(?:\.\d+)?)',
        re.IGNORECASE
    )
    
    # 止损指令正则
    # 示例: 止损 0.95
    # 示例: 止损0.95
    # 示例: SL 0.95
    # 示例: stop loss 0.95
    STOP_LOSS_PATTERN = re.compile(
        r'(?:止损|SL|stop\s*loss)\s*(\d+(?:\.\d+)?)',
        re.IGNORECASE
    )
    
    # 调整止损正则
    # 示例: 止损提高到1.5
    # 示例: 止损调整到 1.5
    # 示例: 移动止损到 1.5
    ADJUST_STOP_PATTERN = re.compile(
        r'(?:止损|SL|stop\s*loss)\s*(?:提高|调整|移动|上调)(?:到|至)?\s*(\d+(?:\.\d+)?)',
        re.IGNORECASE
    )
    
    # 止盈/出货指令正则
    # 示例: 1.75出三分之一
    # 示例: 1.75 出 1/3
    # 示例: 1.65附近出剩下三分之二
    # 示例: 2.0 出一半
    # 示例: 2.5出50%
    # 示例: 全部出
    TAKE_PROFIT_PATTERN = re.compile(
        r'(\d+(?:\.\d+)?)\s*(?:附近|左右)?\s*出\s*'
        r'(?:剩下|剩余)?\s*'
        r'(三分之一|三分之二|一半|全部|1/3|2/3|1/2|\d+%)',
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
        解析消息文本，返回期权指令
        
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
        
        # 尝试解析调整止损（优先于普通止损）
        instruction = cls._parse_adjust_stop(message, message_id)
        if instruction:
            return instruction
        
        # 尝试解析开仓指令
        instruction = cls._parse_open(message, message_id)
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
    def _parse_open(cls, message: str, message_id: str) -> Optional[OptionInstruction]:
        """解析开仓指令"""
        match = cls.OPEN_PATTERN.search(message)
        if not match:
            return None
        
        ticker = match.group(1).upper()
        strike = float(match.group(2))
        option_type = match.group(3).upper()
        if option_type.startswith('CALL'):
            option_type = 'CALL'
        elif option_type.startswith('PUT'):
            option_type = 'PUT'
        
        expiry = match.group(4)
        price = float(match.group(5))
        
        # 检查仓位大小
        position_match = cls.POSITION_SIZE_PATTERN.search(message)
        position_size = position_match.group(1) if position_match else None
        
        return OptionInstruction(
            raw_message=message,
            instruction_type=InstructionType.OPEN.value,
            ticker=ticker,
            option_type=option_type,
            strike=strike,
            expiry=expiry,
            price=price,
            position_size=position_size,
            message_id=message_id
        )
    
    @classmethod
    def _parse_stop_loss(cls, message: str, message_id: str) -> Optional[OptionInstruction]:
        """解析止损指令"""
        match = cls.STOP_LOSS_PATTERN.search(message)
        if not match:
            return None
        
        price = float(match.group(1))
        
        return OptionInstruction(
            raw_message=message,
            instruction_type=InstructionType.STOP_LOSS.value,
            price=price,
            message_id=message_id
        )
    
    @classmethod
    def _parse_adjust_stop(cls, message: str, message_id: str) -> Optional[OptionInstruction]:
        """解析调整止损指令"""
        match = cls.ADJUST_STOP_PATTERN.search(message)
        if not match:
            return None
        
        price = float(match.group(1))
        
        return OptionInstruction(
            raw_message=message,
            instruction_type=InstructionType.ADJUST.value,
            price=price,
            message_id=message_id
        )
    
    @classmethod
    def _parse_take_profit(cls, message: str, message_id: str) -> Optional[OptionInstruction]:
        """解析止盈指令"""
        match = cls.TAKE_PROFIT_PATTERN.search(message)
        if not match:
            return None
        
        price = float(match.group(1))
        portion_raw = match.group(2)
        
        # 转换比例
        if portion_raw.endswith('%'):
            portion = portion_raw
        else:
            portion = cls.PORTION_MAP.get(portion_raw, portion_raw)
        
        return OptionInstruction(
            raw_message=message,
            instruction_type=InstructionType.TAKE_PROFIT.value,
            price=price,
            portion=portion,
            message_id=message_id
        )
    
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
