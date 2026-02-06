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

from parser.message_context_resolver import MessageContextResolver
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
    
    def _display_origin_table(self, msg: dict):
        """
        使用 Rich Table 按文档格式展示单条提取的消息。
        格式：domID, position, timestamp, content, history（与 analyze_local_messages_guide 一致）
        """
        table = Table(
            title="[bold blue]原始消息[/bold blue]",
            show_header=True,
            header_style="bold cyan",
            box=box.SIMPLE,
            show_lines=False,
            padding=(0, 0),
            width=65,
            expand=False,
        )
        table.add_column("字段", style="cyan", width=6, no_wrap=True)
        table.add_column("值", style="white", no_wrap=False)
        # 添加一行显示当前时间
        now = datetime.datetime.now()
        table.add_row("current", now.strftime("%Y-%m-%d %H:%M:%S") + ".%03d" % (now.microsecond // 1000))
        table.add_row("time", str(msg.get("timestamp", "")))
        dom_id = msg.get("domID", msg.get("id", "").split("-")[0] if msg.get("id") else "")
        table.add_row("domID", dom_id)
        table.add_row("position", str(msg.get("position", "")))
        table.add_row("content", str(msg.get("content", msg.get("text", ""))))
        table.add_row("refer", str(msg.get("refer", "")))

        history = msg.get("history") or []
        if isinstance(history, list):
            history_str = "\n".join(f"[{i+1}] {h}" for i, h in enumerate(history)) if history else ""
        else:
            history_str = str(history)
        table.add_row("history", history_str)

        Console().print(table)

    def _display_parsed_message(self, instruction: Optional[OptionInstruction] = None):
        table = Table(
            title="[bold blue]解析后消息[/bold blue]",
            show_header=True,
            header_style="bold cyan",
            box=box.SIMPLE,
            show_lines=False,
            padding=(0, 0),
            width=65,
            expand=False,
        )
        table.add_column("字段", style="cyan", width=14, no_wrap=True)
        table.add_column("值", style="white", width=49, no_wrap=False)

        if instruction is None:
            # 红色字体
            table.add_row("状态", "[bold red]解析失败[/bold red]")
            Console().print(table)
            return

        inst = instruction
        table.add_row("时间", inst.timestamp)
        table.add_row(
            "期权",
            inst.symbol
            or OptionInstruction.generate_option_symbol(
                inst.ticker, inst.option_type, inst.strike, inst.expiry, inst.timestamp
            ),
        )
        table.add_row("指令类型", inst.instruction_type)
        if inst.instruction_type == 'BUY':
            # 买入指令
            if inst.option_type:
                table.add_row("期权类型", inst.option_type)
            if inst.strike:
                table.add_row("行权价", f"${inst.strike}")
            if inst.expiry:
                table.add_row("到期日", inst.expiry)
            if inst.price_range:
                table.add_row("价格区间", f"${inst.price_range[0]} - ${inst.price_range[1]}")
                table.add_row("价格(中间值)", f"${inst.price}")
            elif inst.price:
                table.add_row("价格", f"${inst.price}")
            if inst.position_size:
                table.add_row("仓位大小", inst.position_size)

        elif inst.instruction_type == 'SELL':
            # 卖出指令
            if inst.price_range:
                table.add_row("价格区间", f"${inst.price_range[0]} - ${inst.price_range[1]}")
                table.add_row("价格(中间值)", f"${inst.price}")
            elif inst.price:
                table.add_row("价格", f"${inst.price}")
            if inst.sell_quantity:
                table.add_row("卖出数量", inst.sell_quantity)

        elif inst.instruction_type == 'CLOSE':
            # 清仓指令
            if inst.price_range:
                table.add_row("价格区间", f"${inst.price_range[0]} - ${inst.price_range[1]}")
                table.add_row("价格(中间值)", f"${inst.price}")
            elif inst.price:
                table.add_row("价格", f"${inst.price}")
            table.add_row("数量", "全部")

        elif inst.instruction_type == 'MODIFY':
            # 修改指令
            if inst.stop_loss_range:
                table.add_row("止损区间", f"${inst.stop_loss_range[0]} - ${inst.stop_loss_range[1]}")
                table.add_row("止损(中间值)", f"${inst.stop_loss_price}")
            elif inst.stop_loss_price:
                table.add_row("止损价格", f"${inst.stop_loss_price}")

            if inst.take_profit_range:
                table.add_row("止盈区间", f"${inst.take_profit_range[0]} - ${inst.take_profit_range[1]}")
                table.add_row("止盈(中间值)", f"${inst.take_profit_price}")
            elif inst.take_profit_price:
                table.add_row("止盈价格", f"${inst.take_profit_price}")

        # 显示上下文补全信息
        if inst.source:
            table.add_row("上下文来源", inst.source)
            if inst.depend_message:
                ctx_msg = inst.depend_message[:60]
                if len(inst.depend_message) > 60:
                    ctx_msg += "..."
                table.add_row("上下文消息", ctx_msg)

        Console().print(table)
    
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

        import re
        simples = []
        for msg in messages:
            # msg 为 MessageGroup，转为字典供后续使用
            msg_dict = msg.to_simple_dict()
            msg_dict["id"] = msg.group_id
            msg_id = msg_dict["id"]
            text = msg.get_full_content()
            time = msg_dict["timestamp"]
            # 跳过已处理的消息
            if msg_id in self._processed_ids:
                continue

            self._processed_ids.add(msg_id)

            # 触发新消息回调
            if self._on_new_message:
                self._on_new_message(text)
            
            dict = msg_dict
            content = dict['content'].strip()
            # 清理消息内容
            content_clean = content
            content_clean = re.sub(r'^\[引用\]\s*', '', content_clean)
            content_clean = re.sub(r'^[\w]+•[A-Z][a-z]{2,9}\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2}\s+[AP]M\s*', '', content_clean)
            content_clean = re.sub(r'^[XxＸｘ]+', '', content_clean)
            content_clean = re.sub(r'^[\w]+•[A-Z][a-z]{2,9}\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2}\s+[AP]M\s*', '', content_clean)
            content_clean = re.sub(r'^•?\s*[A-Z][a-z]+\s+\d{1,2}:\d{2}\s+[AP]M\s*', '', content_clean)
            content_clean = content_clean.strip()
                
            # 更新清理后的内容
            dict['content'] = content_clean
            simples.append(dict)

        # 创建上下文解析器
        resolver = MessageContextResolver(simples)
        # 收集解析结果用于表格展示
        parse_results = []
        for simple in simples:
            result = resolver.resolve_instruction(simple)
            if result:
                instruction, context_source, context_message = result
                instruction.origin = simple
                parse_results.append([simple, instruction])
            else:
                 parse_results.append([simple, None])
        
        for simple, instruction in parse_results:
            print('=' * 80)
            self._display_origin_table(simple)
            self._display_parsed_message(instruction)
            # 触发新指令回调（只有成功解析时才调用）
            if self._on_new_instruction and instruction:
                self._on_new_instruction(instruction)

        return [inst for _, inst in parse_results]
    
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