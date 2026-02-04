"""
实时消息监控模块
监控 Whop 页面的新消息并解析。
消息提取与解析统一由 EnhancedMessageExtractor 完成（含上下文、引用、消息组）。
"""
import asyncio
import datetime
from typing import Callable, Optional, Set
from playwright.async_api import Page
from rich.console import Console
from rich.table import Table
from rich import box

from parser.option_parser import OptionParser
from models.instruction import OptionInstruction, InstructionStore
from samples.sample_manager import SampleManager, SampleCategory
from scraper.message_extractor import EnhancedMessageExtractor


class MessageMonitor:
    """消息监控器"""
    
    def __init__(
        self,
        page: Page,
        poll_interval: float = 2.0,
        output_file: str = "output/signals.json",
        enable_sample_collection: bool = True,
        display_mode: str = "both",
        skip_initial_messages: bool = False
    ):
        """
        初始化消息监控器
        
        Args:
            page: Playwright 页面对象
            poll_interval: 轮询间隔（秒）
            output_file: 输出文件路径
            enable_sample_collection: 是否启用样本收集
            display_mode: 展示模式 ('raw', 'parsed', 'both')
            skip_initial_messages: 为 True 时首次连接不处理当前页消息，只处理连接后新产生的消息
        """
        self.page = page
        self.poll_interval = poll_interval
        self.store = InstructionStore(output_file)
        self.display_mode = display_mode
        self.skip_initial_messages = skip_initial_messages
        
        # 验证展示模式
        if self.display_mode not in ['raw', 'parsed', 'both']:
            print(f"⚠️  无效的展示模式 '{self.display_mode}'，使用默认值 'both'")
            self.display_mode = 'both'
        
        # 样本管理器
        self.enable_sample_collection = enable_sample_collection
        self.sample_manager = SampleManager() if enable_sample_collection else None
        
        # 已处理的消息 ID 集合（用于去重）
        self._processed_ids: Set[str] = set()
        # 是否尚未完成首次扫描（用于 skip_initial_messages）
        self._first_scan_done = False
        
        # 回调函数
        self._on_new_instruction: Optional[Callable[[OptionInstruction], None]] = None
        self._on_new_message: Optional[Callable[[str], None]] = None
        
        # 运行状态
        self._running = False
    
    def on_new_instruction(self, callback: Callable[[OptionInstruction], None]):
        """
        设置新指令回调
        
        Args:
            callback: 当解析出新指令时调用的函数
        """
        self._on_new_instruction = callback
    
    def on_new_message(self, callback: Callable[[str], None]):
        """
        设置新消息回调
        
        Args:
            callback: 当检测到新消息时调用的函数
        """
        self._on_new_message = callback
    
    def _determine_category(self, instruction: OptionInstruction) -> str:
        """
        根据指令类型确定样本分类
        
        Args:
            instruction: 指令对象
            
        Returns:
            样本分类
        """
        # 支持新旧两种指令类型
        type_map = {
            # 新版指令类型
            "BUY": SampleCategory.OPEN.value,
            "SELL": SampleCategory.TAKE_PROFIT.value,
            "CLOSE": SampleCategory.TAKE_PROFIT.value,
            "MODIFY": SampleCategory.ADJUST.value,
            # 旧版指令类型（向后兼容）
            "OPEN": SampleCategory.OPEN.value,
            "STOP_LOSS": SampleCategory.STOP_LOSS.value,
            "TAKE_PROFIT": SampleCategory.TAKE_PROFIT.value,
            "ADJUST": SampleCategory.ADJUST.value,
        }
        return type_map.get(instruction.instruction_type, SampleCategory.UNKNOWN.value)
    
    def _display_message_table(self, msg: dict):
        """
        使用 Rich Table 按文档格式展示单条提取的消息。
        格式：domID, position, timestamp, content, history（与 analyze_local_messages_guide 一致）
        """
        table = Table(
            title="[bold blue]原始消息[/bold blue]",
            show_header=True,
            header_style="bold cyan",
            box=box.ROUNDED,
            show_lines=True,
            padding=(0, 1),
            width=70,
        )
        table.add_column("字段", style="cyan", width=6, no_wrap=True)
        table.add_column("值", style="white", no_wrap=False)
        # 添加一行显示当前时间
        now = datetime.datetime.now()
        table.add_row("current", now.strftime("%Y-%m-%d %H:%M:%S") + ".%03d" % (now.microsecond // 1000))
        table.add_row("timestamp", str(msg.get("timestamp", "")))
        dom_id = msg.get("domID", msg.get("id", "").split("-")[0] if msg.get("id") else "")
        table.add_row("domID", dom_id)
        table.add_row("position", str(msg.get("position", "")))
        table.add_row("content", str(msg.get("content", msg.get("text", ""))))

        history = msg.get("history") or []
        if isinstance(history, list):
            history_str = "\n".join(f"[{i+1}] {h}" for i, h in enumerate(history)) if history else ""
        else:
            history_str = str(history)
        table.add_row("history", history_str)

        Console().print(table)

    def _display_message(self, text: str, instruction: Optional[OptionInstruction] = None):
        """
        根据展示模式显示消息
        
        Args:
            text: 原始消息文本
            instruction: 解析后的指令（如果有）
        """
        if self.display_mode == "raw":
            # 仅显示原始消息（Table 已在 _display_message_table 中展示）
            print(f"[原始消息] {text}")
        
        elif self.display_mode == "parsed":
            # 仅显示解析后的指令
            if instruction:
                print(f"[新指令] {instruction}")
        
        elif self.display_mode == "both":
            # 两者都显示（Table 已在 _display_message_table 中展示）
            print(f"[原始消息] {text}")
            if instruction:
                print(f"[新指令] {instruction}")
                print(f"[JSON] {instruction.to_json()}")
    
    async def scan_once(self) -> list[OptionInstruction]:
        """
        扫描一次页面，返回新的指令
        
        Returns:
            新解析出的指令列表
        """
        new_instructions = []
        
        # 统一使用 EnhancedMessageExtractor 提取并解析页面消息（含消息组、引用、上下文）
        extractor = EnhancedMessageExtractor(self.page)
        try:
            messages = await extractor.extract_with_context()
        except Exception as e:
            print(f"消息提取失败: {e}")
            messages = []
        
        # 若开启“跳过首次历史”：首次扫描仅将当前页消息 ID 登记为已处理，不展示、不解析、不回调
        if self.skip_initial_messages and not self._first_scan_done:
            for msg in messages:
                self._processed_ids.add(msg["id"])
            self._first_scan_done = True
            if messages:
                print(f"已跳过首次连接时的 {len(messages)} 条历史消息，仅处理此后新消息")
            return []
        
        for msg in messages:
            msg_id = msg['id']
            text = msg['text']
            
            # 跳过已处理的消息
            if msg_id in self._processed_ids:
                continue
            
            self._processed_ids.add(msg_id)

            # 使用 Table 按文档格式展示提取的消息（raw / both 模式）
            if self.display_mode in ["raw", "both"]:
                self._display_message_table(msg)
            
            # 触发新消息回调
            if self._on_new_message:
                self._on_new_message(text)
            
            print("=" * 80)
            # 尝试解析指令
            # 消息可能包含多行，逐行解析
            lines = text.split('\n')
            parsed_any = False
            
            for line in lines:
                line = line.strip()
                if not line or len(line) < 3:
                    continue
                
                instruction = OptionParser.parse(line, msg_id)
                if instruction:
                    parsed_any = True
                    # 显示消息（根据展示模式）
                    self._display_message(line, instruction)
                    
                    # 保存到存储
                    if self.store.add(instruction):
                        new_instructions.append(instruction)
                        
                        # 触发新指令回调
                        if self._on_new_instruction:
                            self._on_new_instruction(instruction)
                        
                        # 添加已解析样本
                        if self.sample_manager:
                            category = self._determine_category(instruction)
                            self.sample_manager.add_parsed_sample(
                                message=line,
                                category=category,
                                parsed_result=instruction.to_dict(),
                                notes="自动收集"
                            )
            
            # 如果整条消息都没有被解析，添加为未解析样本
            if not parsed_any and len(text) > 5:
                # 只在 raw 或 both 模式下显示未解析的原始消息
                if self.display_mode in ["raw", "both"]:
                    self._display_message(text, None)
                
                if self.sample_manager:
                    self.sample_manager.add_unparsed_sample(
                        message=text,
                        notes="监控时未能解析"
                    )
        
        return new_instructions
    
    async def start(self):
        """开始实时监控"""
        self._running = True
        print(f"开始监控，轮询间隔: {self.poll_interval} 秒")
        print(f"展示模式: {self.display_mode}")
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
    
    async def wait_for_new_messages(self, timeout: float = 60.0) -> list[OptionInstruction]:
        """
        等待新消息出现
        
        Args:
            timeout: 超时时间（秒）
            
        Returns:
            新的指令列表
        """
        start_time = asyncio.get_event_loop().time()
        all_new = []
        
        while asyncio.get_event_loop().time() - start_time < timeout:
            new_instructions = await self.scan_once()
            all_new.extend(new_instructions)
            
            if new_instructions:
                return all_new
            
            await asyncio.sleep(self.poll_interval)
        
        return all_new