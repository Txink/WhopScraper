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


class MessageMonitor:
    """消息监控器"""
    
    def __init__(
        self,
        page: Page,
        poll_interval: float = 2.0,
        output_file: str = "output/signals.json",
        enable_sample_collection: bool = True
    ):
        """
        初始化消息监控器
        
        Args:
            page: Playwright 页面对象
            poll_interval: 轮询间隔（秒）
            output_file: 输出文件路径
            enable_sample_collection: 是否启用样本收集
        """
        self.page = page
        self.poll_interval = poll_interval
        self.store = InstructionStore(output_file)
        
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
        
        # 尝试提取消息
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
                    # 保存到存储
                    if self.store.add(instruction):
                        new_instructions.append(instruction)
                        print(f"[新指令] {instruction}")
                        
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
            if not parsed_any and self.sample_manager and len(text) > 5:
                self.sample_manager.add_unparsed_sample(
                    message=text,
                    notes="监控时未能解析"
                )
        
        return new_instructions
    
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
    使用 MutationObserver 的高级监控器
    能够更快地检测到 DOM 变化
    """
    
    def __init__(
        self,
        page: Page,
        output_file: str = "output/signals.json"
    ):
        self.page = page
        self.store = InstructionStore(output_file)
        self._on_new_instruction: Optional[Callable[[OptionInstruction], None]] = None
    
    def on_new_instruction(self, callback: Callable[[OptionInstruction], None]):
        """设置新指令回调"""
        self._on_new_instruction = callback
    
    async def setup_observer(self, container_selector: str = "body"):
        """
        设置 MutationObserver 监听 DOM 变化
        
        Args:
            container_selector: 要监听的容器选择器
        """
        # 注入 MutationObserver 监听代码
        js_code = f"""
        () => {{
            window.__newMessages = [];
            
            const observer = new MutationObserver((mutations) => {{
                for (const mutation of mutations) {{
                    for (const node of mutation.addedNodes) {{
                        if (node.nodeType === Node.ELEMENT_NODE) {{
                            const text = node.innerText?.trim();
                            if (text && text.length > 5) {{
                                window.__newMessages.push({{
                                    id: Date.now().toString(),
                                    text: text
                                }});
                            }}
                        }}
                    }}
                }}
            }});
            
            const container = document.querySelector('{container_selector}');
            if (container) {{
                observer.observe(container, {{
                    childList: true,
                    subtree: true
                }});
                return true;
            }}
            return false;
        }}
        """
        
        result = await self.page.evaluate(js_code)
        if result:
            print(f"MutationObserver 已设置在: {container_selector}")
        else:
            print(f"警告: 找不到容器 {container_selector}")
        
        return result
    
    async def get_new_messages(self) -> list[dict]:
        """获取并清空新消息队列"""
        js_code = """
        () => {
            const messages = window.__newMessages || [];
            window.__newMessages = [];
            return messages;
        }
        """
        return await self.page.evaluate(js_code)
    
    async def start(self, container_selector: str = "body", poll_interval: float = 0.5):
        """
        开始监控
        
        Args:
            container_selector: 容器选择器
            poll_interval: 检查间隔（秒）
        """
        await self.setup_observer(container_selector)
        
        print(f"开始 MutationObserver 监控，检查间隔: {poll_interval} 秒")
        
        while True:
            try:
                messages = await self.get_new_messages()
                
                for msg in messages:
                    text = msg['text']
                    msg_id = msg['id']
                    
                    # 逐行解析
                    for line in text.split('\n'):
                        line = line.strip()
                        if not line:
                            continue
                        
                        instruction = OptionParser.parse(line, msg_id)
                        if instruction:
                            if self.store.add(instruction):
                                print(f"[新指令] {instruction}")
                                
                                if self._on_new_instruction:
                                    self._on_new_instruction(instruction)
                
                await asyncio.sleep(poll_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"监控出错: {e}")
                await asyncio.sleep(poll_interval)
