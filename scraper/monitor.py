"""
实时消息监控模块
监控 Whop 页面的新消息并解析。
消息提取与解析统一由 EnhancedMessageExtractor 完成（含上下文、引用、消息组）。
支持长桥交易推送（订单状态变化）监听，参见：https://open.longbridge.com/zh-CN/docs/trade/trade-push
"""
import asyncio
import logging
import os
import threading
import time
from datetime import datetime
from typing import Callable, Optional, Set
from playwright.async_api import Page

from rich.console import Console

from models.record_manager import RecordManager
from models.instruction import OptionInstruction, InstructionStore
from models.record import Record
from scraper.message_extractor import EnhancedMessageExtractor

logger = logging.getLogger(__name__)
console = Console()


def _display_width(s: str) -> int:
    """终端显示宽度：ASCII=1，CJK=2。"""
    return len(s) + sum(1 for c in s if "\u4e00" <= c <= "\u9fff")


# 长桥交易推送（订单状态变化）依赖可选：未配置长桥时仅禁用订单推送监听
try:
    from longport.openapi import TradeContext, PushOrderChanged, TopicType
    from broker import load_longport_config
    _LONGPORT_AVAILABLE = True
except Exception:
    TradeContext = PushOrderChanged = TopicType = load_longport_config = None  # type: ignore
    _LONGPORT_AVAILABLE = False


class MessageMonitor:
    """消息监控器"""
    
    def __init__(
        self,
        page: Page,
        poll_interval: float = 2.0,
        skip_initial_messages: bool = False
    ):
        """
        初始化消息监控器
        
        Args:
            page: Playwright 页面对象
            poll_interval: 轮询间隔（秒）
            skip_initial_messages: 为 True 时首次连接不处理当前页消息，只处理连接后新产生的消息
        """
        self.page = page
        self.poll_interval = poll_interval
        self.skip_initial_messages = skip_initial_messages
        self.record_manager = RecordManager()
        
        
        # 已处理的消息 ID 集合（用于去重）
        self._processed_ids: Set[str] = set()
        # 是否尚未完成首次扫描（用于 skip_initial_messages）
        self._first_scan_done = False
        
        # 回调函数
        self._on_new_record: Optional[Callable[[Record], None]] = None
        # 运行状态
        self._running = False
    
    def on_new_record(self, callback: Callable[[Record], None]):
        """
        设置新记录回调
        
        Args:
            callback: 当解析出新记录时调用的函数
        """
        self._on_new_record = callback
    
    async def scan_once(self) -> list[OptionInstruction]:
        """
        扫描一次页面，返回新的指令
        
        Returns:
            新解析出的指令列表
        """        
        # 统一使用 EnhancedMessageExtractor 提取并解析页面消息（含消息组、引用、上下文）
        extractor = EnhancedMessageExtractor(self.page)
        try:
            messages = await extractor.extract_message_groups()
        except Exception as e:
            print(f"消息提取失败: {e}")
            messages = []
        
        # 若开启“跳过首次历史”：首次扫描仅将当前页消息 ID 登记为已处理，不展示、不解析、不回调
        # env RECENT_MESSAGES_PARSE_COUNT=N 时，首次只标记「除最后 N 条外」为已处理，最后 N 条下一轮会参与解析一次
        if self.skip_initial_messages and not self._first_scan_done:
            recent_n = int(os.getenv("RECENT_MESSAGES_PARSE_COUNT", "0"))
            to_mark = messages
            if recent_n > 0 and len(messages) > recent_n:
                to_mark = messages[:-recent_n]  # 不标记最后 N 条，下一轮会被当作新消息解析一次
            for msg in to_mark:
                self._processed_ids.add(msg.group_id)
            self._first_scan_done = True
            if messages:
                tail = f"，最近 {min(recent_n, len(messages))} 条将在下次扫描解析" if recent_n > 0 else ""
                print(f"已跳过首次连接时的 {len(messages)} 条历史消息{tail}，仅处理此后新消息")
                print('=' * 80)

            return []

        # 只处理尚未处理过的消息（过滤历史/已处理）；已处理过的不会再次触发
        new_messages = [msg for msg in messages if msg.group_id not in self._processed_ids]
        for msg in new_messages:
            self._processed_ids.add(msg.group_id)
        # 仅对新消息创建 Records
        records = self.record_manager.create_records(new_messages)
        # 分析 Records，更新record.instruction
        self.record_manager.analyze_records(records)

        for record in records:
            print('=' * 80)
            record.message.display()
            if record.instruction is not None:
                record.instruction.display()
            else:
                OptionInstruction.display_parse_failed(
                    getattr(record.message, "timestamp", None)
                )
            if self._on_new_record and record.instruction is not None and record.instruction.has_symbol():
                self._on_new_record(record)

        return [r.instruction for r in records if r.instruction is not None]
    
    async def start(self):
        """开始实时监控"""
        self._running = True
        print(f"开始监控，轮询间隔: {self.poll_interval} 秒")
        print("按 Ctrl+C 停止监控")
        
        while self._running:
            try:
                await self.scan_once()
                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                print("监控已取消")
                break
            except Exception as e:
                print(f"监控出错: {e}")
                await asyncio.sleep(self.poll_interval)
    
    def stop(self):
        """停止监控"""
        self._running = False
        print("正在停止监控...")


class OrderPushMonitor:
    """
    长桥订单状态推送监听器
    通过长桥交易长连接订阅 private topic，接收订单/资产变更推送。
    参考：https://open.longbridge.com/zh-CN/docs/trade/trade-push
    """

    def __init__(self, config=None):
        """
        初始化订单推送监听器

        Args:
            config: 长桥 Config，为 None 时从环境变量加载（需先成功 load_longport_config）
        """
        if not _LONGPORT_AVAILABLE:
            raise RuntimeError("长桥 SDK 不可用，无法创建 OrderPushMonitor")
        self._config = config
        self._ctx: Optional[TradeContext] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._on_order_changed: Optional[Callable] = None

    def on_order_changed(self, callback: Callable):
        """
        设置订单状态变化回调

        Args:
            callback: 签名为 (event: PushOrderChanged) -> None 的回调
        """
        self._on_order_changed = callback

    @staticmethod
    def display_order_changed(event) -> None:
        """
        打印订单推送关键信息，格式与订单校验一致：首行 [订单推送] [OrderSide.Buy] symbol=xxx，下附 status/quantity/price/time（灰色缩进）。
        """
        symbol = getattr(event, "symbol", "")
        side = getattr(event, "side", "")
        qty = getattr(event, "submitted_quantity", 0)
        price = getattr(event, "submitted_price", None)
        status = getattr(event, "status", "")
        submitted_at = getattr(event, "submitted_at", "")
        side_str = f"{type(side).__name__}.{side.name}" if hasattr(side, "name") else str(side)
        status_str = f"{type(status).__name__}.{status.name}" if hasattr(status, "name") else str(status)
        status_name = (getattr(status, "name", "") or "").upper() if status else ""
        if not status_name and status_str:
            status_name = status_str.upper().split(".")[-1] if "." in status_str else status_str.upper()
        if status_name == "WAITTONEW":
            return  # 不展示 WaitToNew 推送
        if status_name == "PENDINGREPLACE":
            return  # 不展示 PendingReplace 推送
        if status_name in ("CANCELED", "CANCELLED"):
            status_rich = f"[dim white]{status_str}[/dim white]"
        elif status_name == "FILLED":
            status_rich = f"[green]{status_str}[/green]"
        elif status_name == "REJECTED":
            status_rich = f"[red]{status_str}[/red]"
        else:
            status_rich = status_str
        if hasattr(submitted_at, "strftime"):
            time_str = submitted_at.strftime("%Y-%m-%d %H:%M:%S") if submitted_at else ""
        elif submitted_at:
            time_str = str(submitted_at).replace("T", " ", 1).strip()
            if "." in time_str:
                time_str = time_str[: time_str.rfind(".")] if time_str.rfind(".") > 0 else time_str
        else:
            time_str = ""
        now = datetime.now()
        ts = now.strftime("%Y-%m-%d %H:%M:%S") + f".{now.microsecond // 1000:03d}"
        label = "[订单推送]"
        indent = " " * (len(ts) + 1 + _display_width(label) + 1)
        console.print(
            f"[dim]{ts}[/dim]",
            "[bold white][订单推送][/bold white]",
            f"[{side_str}]",
            f"symbol={symbol}",
        )
        console.print(f"{indent}status={status_rich}")
        console.print(f"{indent}submitted_quantity={qty}")
        console.print(f"{indent}submitted_price={price}")
        console.print(f"{indent}[dim white]time={time_str}[/dim white]")
        console.print()

    def _run_loop(self):
        """在后台线程中：创建连接、注册回调、订阅，并保持运行"""
        try:
            config = self._config or load_longport_config()
            self._ctx = TradeContext(config)

            def _handle(event: PushOrderChanged):
                OrderPushMonitor.display_order_changed(event)
                if self._on_order_changed:
                    try:
                        self._on_order_changed(event)
                    except Exception as e:
                        logger.exception("订单推送回调异常: %s", e)

            self._ctx.set_on_order_changed(_handle)
            self._ctx.subscribe([TopicType.Private])
            logger.info("已订阅长桥交易推送 (TopicType.Private)")
            while self._running:
                time.sleep(1)
        except Exception as e:
            logger.exception("订单推送监听异常: %s", e)
        finally:
            if self._ctx and self._running is False:
                try:
                    self._ctx.unsubscribe([TopicType.Private])
                    logger.info("已取消订阅长桥交易推送")
                except Exception as e:
                    logger.warning("取消订阅时出错: %s", e)
            self._ctx = None  # 释放引用，便于连接回收

    def start(self):
        """在后台线程中启动订单推送监听"""
        if self._running:
            logger.warning("订单推送监听已在运行")
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("订单推送监听已启动（后台线程）")

    def stop(self):
        """停止订单推送监听并释放 TradeContext 引用，便于连接回收"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        self._ctx = None
        logger.info("订单推送监听已停止")