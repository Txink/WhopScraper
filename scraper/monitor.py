"""
实时消息监控模块
监控 Whop 页面的新消息并解析。
消息提取与解析统一由 EnhancedMessageExtractor 完成（含上下文、引用、消息组）。
"""
import asyncio
from typing import Callable, Optional, Set
from playwright.async_api import Page

from models.record_manager import RecordManager
from models.instruction import OptionInstruction, InstructionStore
from models.record import Record
from scraper.message_extractor import EnhancedMessageExtractor


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
        if self.skip_initial_messages and not self._first_scan_done:
            for msg in messages:
                self._processed_ids.add(msg.group_id)
            self._first_scan_done = True
            if messages:
                print(f"已跳过首次连接时的 {len(messages)} 条历史消息，仅处理此后新消息")
            return []

        # 只处理尚未处理过的消息（过滤历史/已处理）
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