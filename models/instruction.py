"""
期权指令数据模型
"""
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Optional
import json
from rich.console import Console
from models.message import MessageGroup, _display_width, _format_timestamp_display

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
    symbol: Optional[str] = None  # 期权代码：${ticker}${YYMMDD}${C|P}${price}.US，价格为行权价×1000 不补零，如 EOSE260109C13500.US

    # 上下文
    source: Optional[str] = None  # 上下文来源，如 history, refer, last_N
    depend_message: Optional[str] = None  # 依赖的消息内容

    origin: Optional[MessageGroup] = None  # 原始消息
    
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

    def generate_symbol(self) -> bool:
        if self.symbol is not None:
            return True
        
        # 格式化时间日期
        timestamp = getattr(self.origin, "timestamp", None) if self.origin else None
        if self.expiry:
            normalized = OptionInstruction.normalize_expiry_to_yymmdd(
                self.expiry, timestamp
            )
            if normalized:
                self.expiry = normalized

        # 价格区间在生成 symbol 前取中间值赋给 price
        if self.price is None and self.price_range and len(self.price_range) == 2:
            self.price = (self.price_range[0] + self.price_range[1]) / 2
        # 创建 symbol
        if all(
            [self.ticker, self.option_type, self.strike, self.expiry]
        ):
            self.symbol = OptionInstruction.generate_option_symbol(
                self.ticker,
                self.option_type,
                self.strike,
                self.expiry,
                self.timestamp,
            )
            return True
        return False

    def has_symbol(self) -> bool:
        """判断是否具备完整 symbol 信息（ticker, option_type, strike, expiry）。"""
        return self.symbol is not None or bool(
            self.ticker
            and self.option_type
            and self.strike
            and self.expiry
        )

    def sync_with_instruction(self, other: "OptionInstruction") -> None:
        """从另一条指令补全本指令缺失的 ticker、option_type、strike、expiry。"""
        if not other:
            return
        if not self.ticker and other.ticker:
            self.ticker = other.ticker
        if not self.option_type and other.option_type:
            self.option_type = other.option_type
        if self.strike is None and other.strike is not None:
            self.strike = other.strike
        if not self.expiry and other.expiry:
            self.expiry = other.expiry

    def _format_time_with_diff(self, timestamp_str: str, now: datetime) -> tuple:
        """时间显示：去掉 T 为 2026-02-09 00:22:00.995；并返回 (显示文本, [+Nms] 的 rich 片段)。"""
        if not timestamp_str:
            return "", ""
        t = timestamp_str.replace("T", " ", 1).strip()
        if "." in t:
            idx = t.rfind(".")
            t = t[: idx + 4] if len(t) > idx + 4 else t
        # 解析用于计算差值（ISO 格式 YYYY-MM-DDTHH:MM:SS.mmm，取前 23 位）
        try:
            s = (timestamp_str or "").replace("T ", "T").strip()[:23]
            if len(s) >= 19:
                parsed = datetime.fromisoformat(s)
                diff_ms = int((now - parsed).total_seconds() * 1000)
                sign = "+" if diff_ms >= 0 else ""
                ms_tag = f"[{sign}{diff_ms}ms]"
                if abs(diff_ms) < 1000:
                    ms_rich = f"[green]{ms_tag}[/green]"
                else:
                    ms_rich = f"[yellow]{ms_tag}[/yellow]"
            else:
                ms_rich = ""
        except Exception:
            ms_rich = ""
        return t, ms_rich

    def display(self):
        """使用 console.print 展示单条解析后的指令（时间 + [解析消息] + symbol，下附字段明细）。"""
        console = Console()
        now = datetime.now()
        ts = now.strftime("%Y-%m-%d %H:%M:%S") + f".{now.microsecond // 1000:03d}"
        label = "[解析消息]"
        indent = " " * (len(ts) + 1 + _display_width(label) + 1)

        if self is None:
            console.print(f"[dim]{ts}[/dim]", "[bold blue][解析消息][/bold blue]", "[bold red]解析失败[/bold red]")
            console.print()
            return

        inst = self
        sym = inst.symbol or OptionInstruction.generate_option_symbol(
            inst.ticker, inst.option_type, inst.strike, inst.expiry, inst.timestamp
        ) or ""

        _, ms_rich = self._format_time_with_diff(inst.timestamp or "", now)
        console.print(
            f"[dim]{ts}[/dim]",
            "[bold blue][解析消息][/bold blue]",
            f"[yellow]symbol[/yellow] = [bold blue]{sym}[/bold blue]",
            ms_rich,
        )
        console.print(f'{indent}[yellow]operation[/yellow]: [bold green]{inst.instruction_type}[/bold green]')

        if inst.instruction_type == "BUY":
            if inst.price_range:
                console.print(f'{indent}[yellow]price_range[/yellow]: [bold]${inst.price_range[0]} - ${inst.price_range[1]}[/bold]')
                if inst.price is not None:
                    console.print(f'{indent}[yellow]price[/yellow]: [bold]${inst.price}[/bold]')
            elif inst.price is not None:
                console.print(f'{indent}[yellow]price[/yellow]: [bold]${inst.price}[/bold]')
            if inst.position_size:
                console.print(f'{indent}[yellow]position_size[/yellow]: [bold]{inst.position_size}[/bold]')

        elif inst.instruction_type == "SELL":
            if inst.price_range:
                console.print(f'{indent}[yellow]price_range[/yellow]: [bold]${inst.price_range[0]} - ${inst.price_range[1]}[/bold]')
                if inst.price is not None:
                    console.print(f'{indent}[yellow]price[/yellow]: [bold]${inst.price}[/bold]')
            elif inst.price is not None:
                console.print(f'{indent}[yellow]price[/yellow]: [bold]${inst.price}[/bold]')
            if inst.sell_quantity:
                console.print(f'{indent}[yellow]sell_quantity[/yellow]: [bold]{inst.sell_quantity}[/bold]')

        elif inst.instruction_type == "CLOSE":
            if inst.price_range:
                console.print(f'{indent}[yellow]price_range[/yellow]: [bold]${inst.price_range[0]} - ${inst.price_range[1]}[/bold]')
                if inst.price is not None:
                    console.print(f'{indent}[yellow]price[/yellow]: [bold]${inst.price}[/bold]')
            elif inst.price is not None:
                console.print(f'{indent}[yellow]price[/yellow]: [bold]${inst.price}[/bold]')
            console.print(f'{indent}[yellow]quantity[/yellow]: [bold]全部[/bold]')

        elif inst.instruction_type == "MODIFY":
            if inst.stop_loss_range:
                console.print(f'{indent}[yellow]stop_loss_range[/yellow]: [bold]${inst.stop_loss_range[0]} - ${inst.stop_loss_range[1]}[/bold]')
                if inst.stop_loss_price is not None:
                    console.print(f'{indent}[yellow]stop_loss[/yellow]: [bold]${inst.stop_loss_price}[/bold]')
            elif inst.stop_loss_price is not None:
                console.print(f'{indent}[yellow]stop_loss[/yellow]: [bold]${inst.stop_loss_price}[/bold]')
            if inst.take_profit_range:
                console.print(f'{indent}[yellow]take_profit_range[/yellow]: [bold]${inst.take_profit_range[0]} - ${inst.take_profit_range[1]}[/bold]')
                if inst.take_profit_price is not None:
                    console.print(f'{indent}[yellow]take_profit[/yellow]: [bold]${inst.take_profit_price}[/bold]')
            elif inst.take_profit_price is not None:
                console.print(f'{indent}[yellow]take_profit[/yellow]: [bold]${inst.take_profit_price}[/bold]')

        if inst.source:
            console.print(f'{indent}[yellow]source[/yellow]: [bold]{inst.source}[/bold]')
            if inst.depend_message:
                ctx_msg = inst.depend_message[:60] + ("..." if len(inst.depend_message) > 60 else "")
                console.print(f'{indent}[yellow]depend_message[/yellow]: [bold]{ctx_msg}[/bold]')

        console.print()

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

    @classmethod
    def normalize_expiry_to_yymmdd(cls, expiry: Optional[str], timestamp: Optional[str] = None) -> Optional[str]:
        """
        将到期日统一转为 YYMMDD 格式（6 位字符串）。
        
        Args:
            expiry: 到期日（如 "2/13", "2月13", "本周", "260213"）
            timestamp: 消息时间戳（如 "Jan 23, 2026 12:51 AM"），用于推断年份和相对日期
            
        Returns:
            "YYMMDD" 字符串，如 "260213"；无法解析时返回 None
        """
        import re
        from datetime import datetime, timedelta

        if not expiry or not str(expiry).strip():
            return None
        expiry = str(expiry).strip()

        # 已是 6 位数字 YYMMDD
        if re.match(r"^\d{6}$", expiry):
            return expiry

        # 从 timestamp 提取年份和日期
        year = 26
        msg_date = None
        if timestamp:
            try:
                # 尝试解析标准格式: "Jan 23, 2026 12:51 AM"
                ts_match = re.search(r", (\d{4})", timestamp)
                if ts_match:
                    year = int(ts_match.group(1)) % 100
                msg_date = datetime.strptime(timestamp, "%b %d, %Y %I:%M %p")
            except Exception:
                # 尝试解析标准化格式: "2026-02-05 23:51:00.010"
                try:
                    if re.match(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", timestamp):
                        # 提取年份
                        year_match = re.match(r"(\d{4})", timestamp)
                        if year_match:
                            year = int(year_match.group(1)) % 100
                        # 解析日期
                        msg_date = datetime.strptime(timestamp[:19], "%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass

        month = None
        day = None

        # 相对日期：今天/本周/下周 -> 具体日期
        relative_lower = expiry.lower()
        if msg_date and relative_lower in ["今天", "today"]:
            # 今天
            month, day = msg_date.month, msg_date.day
        elif msg_date and relative_lower in ["本周", "这周", "当周", "this week"]:
            # 本周五
            days_until_friday = (4 - msg_date.weekday()) % 7
            if days_until_friday == 0:
                days_until_friday = 7
            target = msg_date + timedelta(days=days_until_friday)
            month, day = target.month, target.day
        elif msg_date and relative_lower in ["下周", "next week"]:
            # 下周五
            days_until_friday = (4 - msg_date.weekday()) % 7
            target = msg_date + timedelta(days=days_until_friday + 7)
            month, day = target.month, target.day
        else:
            # "2/13"
            match = re.match(r"(\d{1,2})/(\d{1,2})", expiry)
            if match:
                month = int(match.group(1))
                day = int(match.group(2))
            else:
                # "2月13" / "2月13日"
                match = re.match(r"(\d{1,2})月(\d{1,2})日?", expiry)
                if match:
                    month = int(match.group(1))
                    day = int(match.group(2))

        if not month or not day:
            return None
        return f"{year:02d}{month:02d}{day:02d}"

    @classmethod
    def generate_option_symbol(cls, ticker: str, option_type: str, strike: float, expiry: str, timestamp: str = None) -> str:
        """
        生成完整的期权代码
        
        Args:
            ticker: 股票代码（如 "BA"）
            option_type: 期权类型（"CALL" 或 "PUT"）
            strike: 行权价（如 240.0）
            expiry: 到期日（如 "2/13", "2月13" 或已规范化的 "260213"）
            timestamp: 消息时间戳（如 "Jan 23, 2026 12:51 AM"），用于推断年份
            
        Returns:
            完整期权代码（如 "EOSE260109C13500.US"，价格为行权价×1000 不补零）
        """
        import re

        if not all([ticker, option_type, strike, expiry]):
            return ticker or "未知"

        # 已是 YYMMDD（6 位），直接用作日期部分
        if re.match(r"^\d{6}$", str(expiry)):
            date_str = str(expiry)
        else:
            # 从 timestamp 提取年份
            year = 26
            if timestamp:
                try:
                    # 尝试标准格式: "Jan 23, 2026 12:51 AM"
                    ts_match = re.search(r", (\d{4})", timestamp)
                    if ts_match:
                        year = int(ts_match.group(1)) % 100
                except Exception:
                    # 尝试标准化格式: "2026-02-05 23:51:00.010"
                    try:
                        year_match = re.match(r"(\d{4})", timestamp)
                        if year_match:
                            year = int(year_match.group(1)) % 100
                    except Exception:
                        pass
            month = None
            day = None
            match = re.match(r"(\d{1,2})/(\d{1,2})", expiry)
            if match:
                month = int(match.group(1))
                day = int(match.group(2))
            else:
                match = re.match(r"(\d{1,2})月(\d{1,2})", expiry)
                if match:
                    month = int(match.group(1))
                    day = int(match.group(2))
            if not month or not day:
                return ticker
            date_str = f"{year:02d}{month:02d}{day:02d}"

        option_code = "C" if option_type == "CALL" else "P"
        # 价格为实际行权价×1000，不补前导零。例：13.5 → 13500, 240 → 240000
        strike_code = str(int(strike * 1000))
        return f"{ticker}{date_str}{option_code}{strike_code}.US"


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
