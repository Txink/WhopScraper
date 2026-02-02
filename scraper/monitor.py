"""
实时消息监控模块
监控 Whop 页面的新消息并解析
"""
import asyncio
import hashlib
from typing import Callable, Optional, Set
from playwright.async_api import Page

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
        display_mode: str = "both"
    ):
        """
        初始化消息监控器
        
        Args:
            page: Playwright 页面对象
            poll_interval: 轮询间隔（秒）
            output_file: 输出文件路径
            enable_sample_collection: 是否启用样本收集
            display_mode: 展示模式 ('raw', 'parsed', 'both')
        """
        self.page = page
        self.poll_interval = poll_interval
        self.store = InstructionStore(output_file)
        self.display_mode = display_mode
        
        # 验证展示模式
        if self.display_mode not in ['raw', 'parsed', 'both']:
            print(f"⚠️  无效的展示模式 '{self.display_mode}'，使用默认值 'both'")
            self.display_mode = 'both'
        
        # 样本管理器
        self.enable_sample_collection = enable_sample_collection
        self.sample_manager = SampleManager() if enable_sample_collection else None
        
        # 已处理的消息 ID 集合（用于去重）
        self._processed_ids: Set[str] = set()
        
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
        type_map = {
            "OPEN": SampleCategory.OPEN.value,
            "STOP_LOSS": SampleCategory.STOP_LOSS.value,
            "TAKE_PROFIT": SampleCategory.TAKE_PROFIT.value,
            "ADJUST": SampleCategory.ADJUST.value,
        }
        return type_map.get(instruction.instruction_type, SampleCategory.UNKNOWN.value)
    
    def _display_message(self, text: str, instruction: Optional[OptionInstruction] = None):
        """
        根据展示模式显示消息
        
        Args:
            text: 原始消息文本
            instruction: 解析后的指令（如果有）
        """
        if self.display_mode == "raw":
            # 仅显示原始消息
            print(f"[原始消息] {text}")
        
        elif self.display_mode == "parsed":
            # 仅显示解析后的指令
            if instruction:
                print(f"[新指令] {instruction}")
        
        elif self.display_mode == "both":
            # 两者都显示
            print(f"[原始消息] {text}")
            if instruction:
                print(f"[新指令] {instruction}")
                print(f"[JSON] {instruction.to_json()}")
    
    async def _extract_messages(self) -> list[dict]:
        """
        从页面提取消息
        
        Returns:
            消息列表，每个消息包含 id 和 text
        """
        # Whop 页面的消息选择器可能需要根据实际页面结构调整
        # 这里提供多种可能的选择器
        message_selectors = [
            # 聊天消息容器
            '[class*="message"]',
            '[class*="chat-message"]',
            '[class*="MessageContent"]',
            '[data-message-id]',
            # 帖子/讨论内容
            '[class*="post"]',
            '[class*="Post"]',
            '[class*="content"]',
            'article',
            # 通用容器
            '.prose',
            '[class*="text-content"]',
        ]
        
        messages = []
        
        for selector in message_selectors:
            try:
                elements = await self.page.query_selector_all(selector)
                for element in elements:
                    try:
                        # 获取文本内容
                        text = await element.inner_text()
                        text = text.strip()
                        
                        if not text or len(text) < 5:
                            continue
                        
                        # 尝试获取消息 ID
                        msg_id = await element.get_attribute('data-message-id')
                        if not msg_id:
                            # 使用内容哈希作为 ID
                            msg_id = hashlib.md5(text.encode()).hexdigest()[:12]
                        
                        messages.append({
                            'id': msg_id,
                            'text': text
                        })
                    except Exception:
                        continue
                        
                if messages:
                    break  # 如果找到消息，停止尝试其他选择器
                    
            except Exception:
                continue
        
        return messages
    
    async def _extract_messages_js(self) -> list[dict]:
        """
        使用 JavaScript 从页面提取消息（备用方法）
        
        Returns:
            消息列表
        """
        js_code = """
        () => {
            const messages = [];
            
            // 尝试多种选择器
            const selectors = [
                '[class*="message"]',
                '[class*="post"]',
                '[class*="content"]',
                'article',
                '.prose'
            ];
            
            for (const selector of selectors) {
                const elements = document.querySelectorAll(selector);
                for (const el of elements) {
                    const text = el.innerText?.trim();
                    if (text && text.length > 5) {
                        const id = el.getAttribute('data-message-id') || 
                                   el.id || 
                                   btoa(text.substring(0, 50)).substring(0, 12);
                        messages.push({ id, text });
                    }
                }
                if (messages.length > 0) break;
            }
            
            return messages;
        }
        """
        
        try:
            return await self.page.evaluate(js_code)
        except Exception as e:
            print(f"JavaScript 提取消息失败: {e}")
            return []
    
    async def scan_once(self) -> list[OptionInstruction]:
        """
        扫描一次页面，返回新的指令
        
        Returns:
            新解析出的指令列表
        """
        new_instructions = []
        
        # 使用增强的消息提取器（包含上下文和关联）
        extractor = EnhancedMessageExtractor(self.page)
        try:
            messages = await extractor.extract_with_context()
            if not messages:
                # 降级到原始提取方法
                messages = await self._extract_messages()
                if not messages:
                    messages = await self._extract_messages_js()
        except Exception as e:
            # 如果增强提取失败，使用原始方法
            print(f"增强提取失败，使用备用方法: {e}")
            messages = await self._extract_messages()
            if not messages:
                messages = await self._extract_messages_js()
        
        for msg in messages:
            msg_id = msg['id']
            text = msg['text']
            
            # 跳过已处理的消息
            if msg_id in self._processed_ids:
                continue
            
            self._processed_ids.add(msg_id)
            
            # 触发新消息回调
            if self._on_new_message:
                self._on_new_message(text)
            
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


class MutationObserverMonitor:
    """
    使用 MutationObserver 的事件驱动监控器
    能够实时检测 DOM 变化，只在消息更新时触发处理
    """
    
    def __init__(
        self,
        page: Page,
        output_file: str = "output/signals.json",
        enable_sample_collection: bool = True,
        display_mode: str = "both",
        check_interval: float = 0.5,
        status_report_interval: int = 60
    ):
        """
        Args:
            page: Playwright 页面对象
            output_file: 输出文件路径
            enable_sample_collection: 是否启用样本收集
            display_mode: 展示模式 ('raw', 'parsed', 'both')
            check_interval: 检查新消息的间隔（秒）
            status_report_interval: 状态报告间隔（秒）
        """
        self.page = page
        self.store = InstructionStore(output_file)
        self.display_mode = display_mode
        self.check_interval = check_interval
        self.status_report_interval = status_report_interval
        
        # 样本管理器
        self.enable_sample_collection = enable_sample_collection
        self.sample_manager = SampleManager() if enable_sample_collection else None
        
        # 回调函数
        self._on_new_instruction: Optional[Callable[[OptionInstruction], None]] = None
        self._on_new_message: Optional[Callable[[str], None]] = None
        
        # 统计信息
        self._stats = {
            'messages_processed': 0,
            'instructions_parsed': 0,
            'last_message_time': None,
            'start_time': None,
            'errors': 0
        }
        
        # 运行状态
        self._running = False
        self._processed_ids = set()
    
    def on_new_instruction(self, callback: Callable[[OptionInstruction], None]):
        """设置新指令回调"""
        self._on_new_instruction = callback
    
    def on_new_message(self, callback: Callable[[str], None]):
        """设置新消息回调"""
        self._on_new_message = callback
    
    def _determine_category(self, instruction: OptionInstruction) -> str:
        """根据指令类型确定样本分类"""
        type_map = {
            "OPEN": SampleCategory.OPEN.value,
            "STOP_LOSS": SampleCategory.STOP_LOSS.value,
            "TAKE_PROFIT": SampleCategory.TAKE_PROFIT.value,
            "ADJUST": SampleCategory.ADJUST.value,
        }
        return type_map.get(instruction.instruction_type, SampleCategory.UNKNOWN.value)
    
    def _display_message(self, text: str, instruction: Optional[OptionInstruction] = None):
        """根据展示模式显示消息"""
        if self.display_mode == "raw":
            print(f"[原始消息] {text}")
        elif self.display_mode == "parsed":
            if instruction:
                print(f"[新指令] {instruction}")
        elif self.display_mode == "both":
            print(f"[原始消息] {text}")
            if instruction:
                print(f"[新指令] {instruction}")
                print(f"[JSON] {instruction.to_json()}")
    
    async def setup_observer(self, container_selectors: list[str] = None):
        """
        设置 MutationObserver 监听 DOM 变化
        
        Args:
            container_selectors: 要监听的容器选择器列表
        """
        if container_selectors is None:
            container_selectors = [
                '[class*="message"]',
                '[class*="chat"]',
                '[class*="content"]',
                'main',
                'body'
            ]
        
        # 注入 MutationObserver 监听代码
        js_code = """
        (selectors) => {
            window.__newMessages = [];
            window.__messageCount = 0;
            
            const observer = new MutationObserver((mutations) => {
                for (const mutation of mutations) {
                    for (const node of mutation.addedNodes) {
                        if (node.nodeType === Node.ELEMENT_NODE) {
                            const text = node.innerText?.trim();
                            if (text && text.length > 5) {
                                window.__messageCount++;
                                window.__newMessages.push({
                                    id: `msg-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
                                    text: text,
                                    timestamp: new Date().toISOString()
                                });
                            }
                        }
                    }
                }
            });
            
            // 尝试找到合适的容器并开始监听
            for (const selector of selectors) {
                const containers = document.querySelectorAll(selector);
                for (const container of containers) {
                    observer.observe(container, {
                        childList: true,
                        subtree: true
                    });
                }
                if (containers.length > 0) {
                    return {
                        success: true,
                        selector: selector,
                        containers: containers.length
                    };
                }
            }
            
            // 如果都没找到，监听整个 body
            observer.observe(document.body, {
                childList: true,
                subtree: true
            });
            
            return {
                success: true,
                selector: 'body (fallback)',
                containers: 1
            };
        }
        """
        
        result = await self.page.evaluate(js_code, container_selectors)
        if result['success']:
            print(f"✅ MutationObserver 已设置")
            print(f"   监听容器: {result['selector']}")
            print(f"   容器数量: {result['containers']}")
        else:
            print("⚠️  MutationObserver 设置失败")
        
        return result['success']
    
    async def get_new_messages(self) -> list[dict]:
        """获取并清空新消息队列"""
        js_code = """
        () => {
            const messages = window.__newMessages || [];
            window.__newMessages = [];
            return messages;
        }
        """
        try:
            return await self.page.evaluate(js_code)
        except Exception as e:
            print(f"⚠️  获取新消息失败: {e}")
            return []
    
    def get_status(self) -> dict:
        """获取监控器运行状态"""
        import datetime
        
        status = {
            'running': self._running,
            'messages_processed': self._stats['messages_processed'],
            'instructions_parsed': self._stats['instructions_parsed'],
            'errors': self._stats['errors'],
            'processed_ids_count': len(self._processed_ids),
        }
        
        if self._stats['start_time']:
            uptime = datetime.datetime.now() - self._stats['start_time']
            status['uptime_seconds'] = int(uptime.total_seconds())
            status['uptime_str'] = str(uptime).split('.')[0]
        
        if self._stats['last_message_time']:
            idle_time = datetime.datetime.now() - self._stats['last_message_time']
            status['idle_seconds'] = int(idle_time.total_seconds())
        
        return status
    
    def print_status(self):
        """打印运行状态"""
        status = self.get_status()
        
        print("\n" + "=" * 60)
        print("📊 监控器运行状态")
        print("=" * 60)
        print(f"运行状态:       {'✅ 运行中' if status['running'] else '❌ 已停止'}")
        print(f"处理消息数:     {status['messages_processed']}")
        print(f"解析指令数:     {status['instructions_parsed']}")
        print(f"错误次数:       {status['errors']}")
        print(f"去重缓存:       {status['processed_ids_count']} 条")
        
        if 'uptime_str' in status:
            print(f"运行时长:       {status['uptime_str']}")
        
        if 'idle_seconds' in status:
            print(f"空闲时间:       {status['idle_seconds']} 秒")
        else:
            print(f"空闲时间:       N/A (未收到消息)")
        
        print("=" * 60 + "\n")
    
    async def _status_reporter_loop(self):
        """状态报告循环"""
        import datetime
        
        while self._running:
            try:
                await asyncio.sleep(self.status_report_interval)
                if self._running:
                    self.print_status()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"⚠️  状态报告出错: {e}")
    
    async def start(self, container_selectors: list[str] = None):
        """
        开始事件驱动监控
        
        Args:
            container_selectors: 容器选择器列表
        """
        import datetime
        
        # 设置 MutationObserver
        success = await self.setup_observer(container_selectors)
        if not success:
            print("❌ MutationObserver 设置失败，无法启动监控")
            return
        
        self._running = True
        self._stats['start_time'] = datetime.datetime.now()
        
        print("\n" + "=" * 60)
        print("🚀 事件驱动监控已启动")
        print("=" * 60)
        print(f"检查间隔:       {self.check_interval} 秒")
        print(f"状态报告间隔:   {self.status_report_interval} 秒")
        print(f"展示模式:       {self.display_mode}")
        print("监控模式:       事件驱动 (仅在消息更新时处理)")
        print("按 Ctrl+C 停止")
        print("=" * 60 + "\n")
        
        # 启动状态报告任务
        status_task = asyncio.create_task(self._status_reporter_loop())
        
        try:
            while self._running:
                try:
                    # 获取新消息（只在有消息时才处理）
                    messages = await self.get_new_messages()
                    
                    if messages:
                        # 有新消息才执行处理
                        import datetime
                        self._stats['last_message_time'] = datetime.datetime.now()
                        self._stats['messages_processed'] += len(messages)
                        
                        print(f"📨 检测到 {len(messages)} 条新消息")
                        
                        for msg in messages:
                            text = msg['text']
                            msg_id = msg['id']
                            
                            # 跳过已处理的消息
                            if msg_id in self._processed_ids:
                                continue
                            
                            self._processed_ids.add(msg_id)
                            
                            # 触发新消息回调
                            if self._on_new_message:
                                self._on_new_message(text)
                            
                            # 逐行解析
                            lines = text.split('\n')
                            parsed_any = False
                            
                            for line in lines:
                                line = line.strip()
                                if not line or len(line) < 3:
                                    continue
                                
                                instruction = OptionParser.parse(line, msg_id)
                                if instruction:
                                    parsed_any = True
                                    self._stats['instructions_parsed'] += 1
                                    
                                    # 显示消息
                                    self._display_message(line, instruction)
                                    
                                    # 保存到存储
                                    if self.store.add(instruction):
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
                                                notes="事件驱动自动收集"
                                            )
                            
                            # 如果整条消息都没有被解析，添加为未解析样本
                            if not parsed_any and len(text) > 5:
                                if self.display_mode in ["raw", "both"]:
                                    self._display_message(text, None)
                                
                                if self.sample_manager:
                                    self.sample_manager.add_unparsed_sample(
                                        message=text,
                                        notes="事件驱动监控-未能解析"
                                    )
                    
                    # 等待下一次检查
                    await asyncio.sleep(self.check_interval)
                    
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    self._stats['errors'] += 1
                    print(f"❌ 监控出错: {e}")
                    await asyncio.sleep(self.check_interval)
        
        finally:
            status_task.cancel()
            try:
                await status_task
            except asyncio.CancelledError:
                pass
    
    def stop(self):
        """停止监控"""
        self._running = False
        print("正在停止事件驱动监控...")
        self.print_status()
