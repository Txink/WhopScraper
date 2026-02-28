"""
交易指令数据模型：基类 OperationInstruction，期权子类 OptionInstruction。
"""
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Optional, Any
import json
from rich.console import Console
from models.message import MessageGroup, _display_width

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


def _serializable_dict(obj: Any) -> dict:
    """asdict 且排除不可序列化键（如 origin），过滤 None。"""
    result = {}
    for key, value in asdict(obj).items():
        if key == "origin" or value is None:
            continue
        result[key] = value
    return result


@dataclass
class OperationInstruction:
    """交易操作指令基类：通用字段与展示逻辑。"""

    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    raw_message: str = ""
    instruction_type: str = InstructionType.UNKNOWN.value

    source: Optional[str] = None
    depend_message: Optional[str] = None
    origin: Optional[MessageGroup] = None
    message_id: Optional[str] = None

    price: Optional[float] = None
    price_range: Optional[list] = None
    position_size: Optional[str] = None
    sell_quantity: Optional[str] = None
    stop_loss_price: Optional[float] = None
    stop_loss_range: Optional[list] = None
    take_profit_price: Optional[float] = None
    take_profit_range: Optional[list] = None

    def to_dict(self) -> dict:
        """转换为字典，过滤 None 与不可序列化字段。"""
        return _serializable_dict(self)

    def to_json(self, indent: int = 2) -> str:
        """转换为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def _format_time_with_diff(self, timestamp_str: str, now: datetime) -> tuple:
        """时间显示：去掉 T 为 2026-02-09 00:22:00.995；并返回 (显示文本, [+Nms] 的 rich 片段)。"""
        if not timestamp_str:
            return "", ""
        t = timestamp_str.replace("T", " ", 1).strip()
        if "." in t:
            idx = t.rfind(".")
            t = t[: idx + 4] if len(t) > idx + 4 else t
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

    def _display_header(self, now: datetime, label: str, sym_str: str) -> tuple:
        """返回 (indent 字符串, ms_rich)。子类 display 用此打印首行。"""
        ts = now.strftime("%Y-%m-%d %H:%M:%S") + f".{now.microsecond // 1000:03d}"
        indent = " " * (len(ts) + 1 + _display_width(label) + 1)
        _, ms_rich = self._format_time_with_diff(self.timestamp or "", now)
        return indent, ms_rich, ts

    def _get_footer_details(self) -> list:
        """返回 source / depend_message 的详情行列表。"""
        lines = []
        if self.source:
            lines.append(f"[yellow]source[/yellow]: [bold]{self.source}[/bold]")
            if self.depend_message:
                ctx_msg = self.depend_message[:60] + ("..." if len(self.depend_message) > 60 else "")
                lines.append(f"[yellow]depend_message[/yellow]: [bold]{ctx_msg}[/bold]")
        return lines

    def has_symbol(self) -> bool:
        """子类实现：是否具备可执行所需的 symbol/ticker 信息。"""
        return False

    @staticmethod
    def display_parse_failed(message_timestamp: Optional[str] = None, symbol_label: str = "symbol") -> None:
        """解析失败时展示：与 display() 同格式。"""
        from utils.rich_logger import get_logger
        logger = get_logger()
        logger.trade_stage("解析消息", rows=[
            (symbol_label, "[bold red]X[/bold red]"),
            ("operation", "[bold red]FAIL[/bold red]"),
        ], tag_style="bold blue")

    def display(self) -> None:
        """子类覆盖：展示单条解析后的指令。"""
        raise NotImplementedError


@dataclass
class OptionInstruction(OperationInstruction):
    """期权交易指令数据模型"""

    ticker: Optional[str] = None
    option_type: Optional[str] = None  # CALL 或 PUT
    strike: Optional[float] = None
    expiry: Optional[str] = None  # 如 "1/31", "2/20"
    symbol: Optional[str] = None  # 期权代码
    expiry_fallback_time: bool = False

    def to_dict(self) -> dict:
        return _serializable_dict(self)

    def generate_symbol(self) -> bool:
        if self.symbol is not None:
            return True

        timestamp = getattr(self.origin, "timestamp", None) if self.origin else None
        if self.expiry:
            normalized = OptionInstruction.normalize_expiry_to_yymmdd(
                self.expiry, timestamp
            )
            if normalized:
                self.expiry = normalized

        if self.price is None and self.price_range and len(self.price_range) == 2:
            self.price = (self.price_range[0] + self.price_range[1]) / 2
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
        return self.symbol is not None or bool(
            self.ticker
            and self.option_type
            and self.strike
            and self.expiry
        )

    def sync_with_instruction(self, other: "OptionInstruction") -> None:
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

    def display(self) -> None:
        from utils.rich_logger import get_logger
        logger = get_logger()

        inst = self
        sym = inst.symbol or OptionInstruction.generate_option_symbol(
            inst.ticker, inst.option_type, inst.strike, inst.expiry, inst.timestamp
        ) or ""

        summary_parts = [f"[green]\\[{inst.instruction_type}][/green]", f"[bold blue]{sym}[/bold blue]"]
        if inst.price is not None:
            summary_parts.append(f"${inst.price}")
        elif inst.price_range:
            summary_parts.append(f"${inst.price_range[0]}-${inst.price_range[1]}")

        rows = [("", " ".join(summary_parts))]

        if inst.price_range and inst.price is not None:
            rows.append(("price_range", f"${inst.price_range[0]} - ${inst.price_range[1]}"))
        if inst.instruction_type == "BUY" and inst.position_size:
            rows.append(("position_size", str(inst.position_size)))
        elif inst.instruction_type == "SELL" and inst.sell_quantity:
            rows.append(("sell_quantity", str(inst.sell_quantity)))
        elif inst.instruction_type == "CLOSE":
            rows.append(("quantity", "全部"))
        elif inst.instruction_type == "MODIFY":
            if inst.stop_loss_price is not None:
                rows.append(("stop_loss", f"${inst.stop_loss_price}"))
            if inst.take_profit_price is not None:
                rows.append(("take_profit", f"${inst.take_profit_price}"))

        if inst.source:
            rows.append(("source", str(inst.source)))

        logger.trade_stage("解析消息", rows=rows, tag_style="bold blue")

    @staticmethod
    def display_parse_failed(message_timestamp: Optional[str] = None) -> None:
        """期权解析失败时展示（symbol = X）。"""
        OperationInstruction.display_parse_failed(message_timestamp, symbol_label="symbol")

    @classmethod
    def from_dict(cls, data: dict) -> "OptionInstruction":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def __str__(self) -> str:
        if self.instruction_type == InstructionType.BUY.value:
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
            if self.price_range:
                price_str = f"${self.price_range[0]}-${self.price_range[1]}"
            else:
                price_str = f"${self.price}" if self.price else "市价"
            quantity_str = f"数量: {self.sell_quantity}" if self.sell_quantity else ""
            return f"[卖出] {self.ticker or '未识别'} @ {price_str} {quantity_str}".strip()
        elif self.instruction_type == InstructionType.CLOSE.value:
            if self.price_range:
                price_str = f"${self.price_range[0]}-${self.price_range[1]}"
            else:
                price_str = f"${self.price}" if self.price else "市价"
            return f"[清仓] {self.ticker or '未识别'} @ {price_str}"
        elif self.instruction_type == InstructionType.MODIFY.value:
            parts = [f"[修改] {self.ticker or '未识别'}"]
            if self.stop_loss_range:
                parts.append(f"止损: ${self.stop_loss_range[0]}-${self.stop_loss_range[1]}")
            elif self.stop_loss_price:
                parts.append(f"止损: ${self.stop_loss_price}")
            if self.take_profit_range:
                parts.append(f"止盈: ${self.take_profit_range[0]}-${self.take_profit_range[1]}")
            elif self.take_profit_price:
                parts.append(f"止盈: ${self.take_profit_price}")
            return " ".join(parts)
        else:
            return f"[未识别] {self.raw_message[:50]}..."

    @classmethod
    def normalize_expiry_to_yymmdd(cls, expiry: Optional[str], timestamp: Optional[str] = None) -> Optional[str]:
        import re
        from datetime import datetime, timedelta

        if not expiry or not str(expiry).strip():
            return None
        expiry = str(expiry).strip()
        if re.match(r"^\d{6}$", expiry):
            return expiry

        year = datetime.now().year % 100
        msg_date = None
        if timestamp:
            try:
                ts_match = re.search(r", (\d{4})", timestamp)
                if ts_match:
                    year = int(ts_match.group(1)) % 100
                msg_date = datetime.strptime(timestamp, "%b %d, %Y %I:%M %p")
            except Exception:
                try:
                    if re.match(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", timestamp):
                        year_match = re.match(r"(\d{4})", timestamp)
                        if year_match:
                            year = int(year_match.group(1)) % 100
                        msg_date = datetime.strptime(timestamp[:19], "%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass
        relative_lower = expiry.lower()
        if msg_date is None and relative_lower in ["今天", "today", "本周", "这周", "当周", "this week", "下周", "next week"]:
            msg_date = datetime.now()

        month = None
        day = None
        if msg_date and relative_lower in ["今天", "today"]:
            month, day = msg_date.month, msg_date.day
        elif msg_date and relative_lower in ["本周", "这周", "当周", "this week"]:
            days_until_friday = (4 - msg_date.weekday()) % 7
            if days_until_friday == 0:
                days_until_friday = 7
            target = msg_date + timedelta(days=days_until_friday)
            month, day = target.month, target.day
        elif msg_date and relative_lower in ["下周", "next week"]:
            days_until_friday = (4 - msg_date.weekday()) % 7
            target = msg_date + timedelta(days=days_until_friday + 7)
            month, day = target.month, target.day
        else:
            match = re.match(r"(\d{1,2})/(\d{1,2})", expiry)
            if match:
                month = int(match.group(1))
                day = int(match.group(2))
            else:
                match = re.match(r"(\d{1,2})月(\d{1,2})日?", expiry)
                if match:
                    month = int(match.group(1))
                    day = int(match.group(2))

        if not month or not day:
            return None
        return f"{year:02d}{month:02d}{day:02d}"

    @classmethod
    def generate_option_symbol(cls, ticker: str, option_type: str, strike: float, expiry: str, timestamp: str = None) -> str:
        import re

        if not all([ticker, option_type, strike, expiry]):
            return ticker or "未知"
        if re.match(r"^\d{6}$", str(expiry)):
            date_str = str(expiry)
        else:
            year = 26
            if timestamp:
                try:
                    ts_match = re.search(r", (\d{4})", timestamp)
                    if ts_match:
                        year = int(ts_match.group(1)) % 100
                except Exception:
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
        strike_code = str(int(strike * 1000))
        return f"{ticker}{date_str}{option_code}{strike_code}.US"


class InstructionStore:
    """指令存储管理（期权指令）"""

    def __init__(self, output_file: str = "output/signals.json"):
        self.output_file = output_file
        self.instructions: list[OptionInstruction] = []
        self._load_existing()

    def _load_existing(self):
        try:
            with open(self.output_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.instructions = [
                    OptionInstruction.from_dict(item) for item in data
                ]
        except (FileNotFoundError, json.JSONDecodeError):
            self.instructions = []

    def add(self, instruction: OptionInstruction) -> bool:
        for existing in self.instructions:
            if instruction.message_id and existing.message_id == instruction.message_id:
                return False
            if existing.raw_message == instruction.raw_message:
                return False
        self.instructions.append(instruction)
        self._save()
        return True

    def _save(self):
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
        return self.instructions.copy()

    def get_recent(self, count: int = 10) -> list[OptionInstruction]:
        return self.instructions[-count:]
