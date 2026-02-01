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
    
    # 开仓指令正则（多种格式支持）
    # 格式1: INTC - $52 CALLS 1月30 $1.25
    # 格式2: QQQ 11/20 614c 入场价：1.1
    # 格式3: EOSE 1月9日13.5的call 0.45
    # 格式4: RIVN 16c 3/20 1.35
    # 格式5: META 900call 2.1
    
    # 模式1: 标准格式 - 股票 行权价 CALL/PUT 到期 价格
    OPEN_PATTERN_1 = re.compile(
        r'([A-Z]{2,5})\s*[-–]?\s*\$?(\d+(?:\.\d+)?)\s*'
        r'(CALLS?|PUTS?)\s*'
        r'(?:(本周|下周|这周|当周|今天|EXPIRATION\s+)?\s*(\d{1,2}/\d{1,2}|\d{1,2}月\d{1,2}日?|1月\d{1,2}|2月\d{1,2})\s*)?'
        r'\$?(\d+(?:\.\d+)?)',
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
    
    # 模式5: 带$符号开头 - $RIVN 1月9日 $20 call $0.35
    OPEN_PATTERN_5 = re.compile(
        r'\$([A-Z]{2,5})\s+'
        r'(?:(\d{1,2}月\d{1,2}日?)\s+)?'
        r'\$?(\d+(?:\.\d+)?)\s+'
        r'(call|put)s?\s+'
        r'\$?(\d+(?:\.\d+)?)',
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
    
    # 模式5: 价格+附近+出 (没有比例，默认全部) (如: 0.9附近出)
    TAKE_PROFIT_PATTERN_5 = re.compile(
        r'(\d+(?:\.\d+)?)\s*(?:附近|左右)\s*出(?!\s*(?:三分之|一半|剩|个))',
        re.IGNORECASE
    )
    
    # 模式6: 价格+再出+比例 (如: 0.7再出剩下的一半)
    TAKE_PROFIT_PATTERN_6 = re.compile(
        r'(\d+(?:\.\d+)?)\s*(?:再|也)?出\s*(?:剩下|剩余)(?:的)?\s*(一半|三分之一|三分之二)',
        re.IGNORECASE
    )
    
    # 模式7: 行权价描述+到价格出 (如: 47 call到1.1出)
    TAKE_PROFIT_PATTERN_7 = re.compile(
        r'\d+\s*(?:call|put)\s*到\s*(\d+(?:\.\d+)?)\s*出',
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
        """解析开仓指令 - 尝试多种模式"""
        
        # 尝试模式1: 标准格式
        match = cls.OPEN_PATTERN_1.search(message)
        if match:
            ticker = match.group(1).upper()
            strike = float(match.group(2))
            option_type = match.group(3).upper()
            option_type = 'CALL' if option_type.startswith('CALL') else 'PUT'
            expiry = match.group(5) if match.group(5) else None
            price = float(match.group(6))
            
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
        
        # 尝试模式2: 简化格式 (614c)
        match = cls.OPEN_PATTERN_2.search(message)
        if match:
            ticker = match.group(1).upper()
            strike = float(match.group(2))
            # 从614c中提取c或p
            option_indicator = message[match.start():match.end()]
            option_type = 'CALL' if 'c' in option_indicator or 'C' in option_indicator else 'PUT'
            expiry = match.group(3) if match.group(3) else None
            price = float(match.group(4))
            
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
        
        # 尝试模式3: 到期在前格式
        match = cls.OPEN_PATTERN_3.search(message)
        if match:
            ticker = match.group(1).upper()
            expiry = match.group(2)
            strike = float(match.group(3))
            option_type = match.group(4).upper()
            option_type = 'CALL' if option_type.startswith('CALL') else 'PUT'
            price = float(match.group(5))
            
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
        
        # 尝试模式4: 紧凑格式 (900call)
        match = cls.OPEN_PATTERN_4.search(message)
        if match:
            ticker = match.group(1).upper()
            strike = float(match.group(2))
            option_type = match.group(3).upper()
            option_type = 'CALL' if option_type.startswith('CALL') else 'PUT'
            price = float(match.group(4))
            
            position_match = cls.POSITION_SIZE_PATTERN.search(message)
            position_size = position_match.group(1) if position_match else None
            
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.OPEN.value,
                ticker=ticker,
                option_type=option_type,
                strike=strike,
                expiry=None,
                price=price,
                position_size=position_size,
                message_id=message_id
            )
        
        # 尝试模式5: 带$符号开头
        match = cls.OPEN_PATTERN_5.search(message)
        if match:
            ticker = match.group(1).upper()
            expiry = match.group(2) if match.group(2) else None
            strike = float(match.group(3))
            option_type = match.group(4).upper()
            option_type = 'CALL' if option_type.startswith('CALL') else 'PUT'
            price = float(match.group(5))
            
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
        
        # 尝试模式6: 日期格式YYMMDD
        match = cls.OPEN_PATTERN_6.search(message)
        if match:
            ticker = match.group(1).upper()
            expiry = match.group(2)
            strike = float(match.group(3))
            option_type = match.group(4).upper()
            option_type = 'CALL' if option_type.startswith('CALL') else 'PUT'
            price = float(match.group(5))
            
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
        
        return None
    
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
        """解析止盈指令 - 尝试多种模式"""
        
        # 尝试模式1: 价格+出+比例
        match = cls.TAKE_PROFIT_PATTERN_1.search(message)
        if match:
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
        
        # 尝试模式2: 价格+剩下都出
        match = cls.TAKE_PROFIT_PATTERN_2.search(message)
        if match:
            price = float(match.group(1))
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.TAKE_PROFIT.value,
                price=price,
                portion='全部',
                message_id=message_id
            )
        
        # 尝试模式3: 价格+出剩余的
        match = cls.TAKE_PROFIT_PATTERN_3.search(message)
        if match:
            price = float(match.group(1))
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.TAKE_PROFIT.value,
                price=price,
                portion='全部',
                message_id=message_id
            )
        
        # 尝试模式4: 价格+全出
        match = cls.TAKE_PROFIT_PATTERN_4.search(message)
        if match:
            price = float(match.group(1))
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.TAKE_PROFIT.value,
                price=price,
                portion='全部',
                message_id=message_id
            )
        
        # 尝试模式5: 价格+附近出 (默认全部)
        match = cls.TAKE_PROFIT_PATTERN_5.search(message)
        if match:
            price = float(match.group(1))
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.TAKE_PROFIT.value,
                price=price,
                portion='全部',
                message_id=message_id
            )
        
        # 尝试模式6: 价格+再出+比例
        match = cls.TAKE_PROFIT_PATTERN_6.search(message)
        if match:
            price = float(match.group(1))
            portion_raw = match.group(2)
            portion = cls.PORTION_MAP.get(portion_raw, portion_raw)
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.TAKE_PROFIT.value,
                price=price,
                portion=portion,
                message_id=message_id
            )
        
        # 尝试模式7: 行权价描述+到价格出
        match = cls.TAKE_PROFIT_PATTERN_7.search(message)
        if match:
            price = float(match.group(1))
            return OptionInstruction(
                raw_message=message,
                instruction_type=InstructionType.TAKE_PROFIT.value,
                price=price,
                portion='全部',
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
