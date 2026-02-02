"""
期权指令数据模型
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Optional
import json


class InstructionType(Enum):
    """指令类型枚举"""
    BUY = "BUY"                # 买入
    SELL = "SELL"              # 卖出（部分）
    CLOSE = "CLOSE"            # 清仓（全部卖出）
    MODIFY = "MODIFY"          # 修改（止损/止盈）
    UNKNOWN = "UNKNOWN"        # 未识别


class OptionType(Enum):
    """期权类型"""
    CALL = "CALL"
    PUT = "PUT"


@dataclass
class OptionInstruction:
    """期权交易指令数据模型"""
    
    # 基础信息
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    raw_message: str = ""
    instruction_type: str = InstructionType.UNKNOWN.value
    
    # 期权合约信息
    ticker: Optional[str] = None
    option_type: Optional[str] = None  # CALL 或 PUT
    strike: Optional[float] = None
    expiry: Optional[str] = None  # 如 "1/31", "2/20"
    
    # 价格信息（支持单个价格或价格区间）
    price: Optional[float] = None  # 单个价格
    price_range: Optional[list] = None  # 价格区间 [min, max]
    
    # 买入指令专用
    position_size: Optional[str] = None  # 如 "小仓位", "中仓位", "大仓位"
    
    # 卖出指令专用
    sell_quantity: Optional[str] = None  # 卖出数量：支持 "100"(具体股数), "1/3"(比例), "30%"(百分比)
    
    # 修改指令专用
    stop_loss_price: Optional[float] = None  # 止损价格（单个）
    stop_loss_range: Optional[list] = None  # 止损价格区间 [min, max]
    take_profit_price: Optional[float] = None  # 止盈价格（单个）
    take_profit_range: Optional[list] = None  # 止盈价格区间 [min, max]
    
    # 消息标识（用于去重）
    message_id: Optional[str] = None
    
    def to_dict(self) -> dict:
        """转换为字典，过滤掉 None 值"""
        result = {}
        for key, value in asdict(self).items():
            if value is not None:
                result[key] = value
        return result
    
    def to_json(self, indent: int = 2) -> str:
        """转换为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)
    
    @classmethod
    def from_dict(cls, data: dict) -> "OptionInstruction":
        """从字典创建实例"""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
    
    def __str__(self) -> str:
        """友好的字符串表示"""
        if self.instruction_type == InstructionType.BUY.value:
            # 格式化价格
            if self.price_range:
                price_str = f"${self.price_range[0]}-${self.price_range[1]}"
            else:
                price_str = f"${self.price}" if self.price else "市价"
            
            return (
                f"[买入] {self.ticker} ${self.strike} {self.option_type} "
                f"@ {price_str} ({self.expiry or '未知到期日'}) "
                f"{self.position_size or ''}"
            ).strip()
            
        elif self.instruction_type == InstructionType.SELL.value:
            # 格式化价格
            if self.price_range:
                price_str = f"${self.price_range[0]}-${self.price_range[1]}"
            else:
                price_str = f"${self.price}" if self.price else "市价"
            
            # 格式化数量
            quantity_str = f"数量: {self.sell_quantity}" if self.sell_quantity else ""
            
            return f"[卖出] {self.ticker or '未识别'} @ {price_str} {quantity_str}".strip()
            
        elif self.instruction_type == InstructionType.CLOSE.value:
            # 格式化价格
            if self.price_range:
                price_str = f"${self.price_range[0]}-${self.price_range[1]}"
            else:
                price_str = f"${self.price}" if self.price else "市价"
            
            return f"[清仓] {self.ticker or '未识别'} @ {price_str}"
            
        elif self.instruction_type == InstructionType.MODIFY.value:
            parts = [f"[修改] {self.ticker or '未识别'}"]
            
            # 止损价格
            if self.stop_loss_range:
                parts.append(f"止损: ${self.stop_loss_range[0]}-${self.stop_loss_range[1]}")
            elif self.stop_loss_price:
                parts.append(f"止损: ${self.stop_loss_price}")
            
            # 止盈价格
            if self.take_profit_range:
                parts.append(f"止盈: ${self.take_profit_range[0]}-${self.take_profit_range[1]}")
            elif self.take_profit_price:
                parts.append(f"止盈: ${self.take_profit_price}")
            
            return " ".join(parts)
            
        else:
            return f"[未识别] {self.raw_message[:50]}..."


class InstructionStore:
    """指令存储管理"""
    
    def __init__(self, output_file: str = "output/signals.json"):
        self.output_file = output_file
        self.instructions: list[OptionInstruction] = []
        self._load_existing()
    
    def _load_existing(self):
        """加载已有的指令"""
        try:
            with open(self.output_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.instructions = [
                    OptionInstruction.from_dict(item) for item in data
                ]
        except (FileNotFoundError, json.JSONDecodeError):
            self.instructions = []
    
    def add(self, instruction: OptionInstruction) -> bool:
        """
        添加新指令
        返回 True 如果成功添加，False 如果是重复指令
        """
        # 检查是否重复（基于 message_id 或 raw_message）
        for existing in self.instructions:
            if instruction.message_id and existing.message_id == instruction.message_id:
                return False
            if existing.raw_message == instruction.raw_message:
                return False
        
        self.instructions.append(instruction)
        self._save()
        return True
    
    def _save(self):
        """保存到文件"""
        import os
        os.makedirs(os.path.dirname(self.output_file) or ".", exist_ok=True)
        
        with open(self.output_file, "w", encoding="utf-8") as f:
            json.dump(
                [inst.to_dict() for inst in self.instructions],
                f,
                ensure_ascii=False,
                indent=2
            )
    
    def get_all(self) -> list[OptionInstruction]:
        """获取所有指令"""
        return self.instructions.copy()
    
    def get_recent(self, count: int = 10) -> list[OptionInstruction]:
        """获取最近的指令"""
        return self.instructions[-count:]
