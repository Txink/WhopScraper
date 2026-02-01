"""
多页面监控管理器
支持同时监控多个页面，使用不同的解析器
"""
import asyncio
from typing import Callable, Optional, List, Dict
from playwright.async_api import Page

from parser.option_parser import OptionParser
from parser.stock_parser import StockParser
from models.instruction import OptionInstruction, InstructionStore
from samples.sample_manager import SampleManager, SampleCategory


class PageMonitorConfig:
    """单个页面的监控配置"""
    
    def __init__(
        self,
        page: Page,
        page_type: str,
        url: str,
        enabled: bool = True
    ):
        """
        Args:
            page: Playwright 页面对象
            page_type: 页面类型 ('option' 或 'stock')
            url: 页面URL
            enabled: 是否启用监控
        """
        self.page = page
        self.page_type = page_type
        self.url = url
        self.enabled = enabled
        
        # 根据页面类型选择解析器
        if page_type == 'option':
            self.parser = OptionParser
        elif page_type == 'stock':
            self.parser = StockParser
        else:
            raise ValueError(f"不支持的页面类型: {page_type}")
        
        # 已处理的消息 ID 集合
        self.processed_ids = set()


class MultiPageMonitor:
    """多页面监控管理器"""
    
    def __init__(
        self,
        poll_interval: float = 2.0,
        output_file: str = "output/signals.json",
        enable_sample_collection: bool = True,
        display_mode: str = "both"
    ):
        """
        初始化多页面监控器
        
        Args:
            poll_interval: 轮询间隔（秒）
            output_file: 输出文件路径
            enable_sample_collection: 是否启用样本收集
            display_mode: 展示模式 ('raw', 'parsed', 'both')
        """
        self.poll_interval = poll_interval
        self.store = InstructionStore(output_file)
        self.display_mode = display_mode
        
        # 样本管理器
        self.enable_sample_collection = enable_sample_collection
        self.sample_manager = SampleManager() if enable_sample_collection else None
        
        # 页面配置列表
        self.page_configs: List[PageMonitorConfig] = []
        
        # 回调函数
        self._on_new_instruction: Optional[Callable[[OptionInstruction, str], None]] = None
        self._on_new_message: Optional[Callable[[str, str], None]] = None
        
        # 运行状态
        self._running = False
        self._tasks = []
    
    def add_page(
        self,
        page: Page,
        page_type: str,
        url: str,
        enabled: bool = True
    ):
        """
        添加要监控的页面
        
        Args:
            page: Playwright 页面对象
            page_type: 页面类型 ('option' 或 'stock')
            url: 页面URL
            enabled: 是否启用监控
        """
        config = PageMonitorConfig(page, page_type, url, enabled)
        self.page_configs.append(config)
        print(f"✅ 已添加监控页面: {page_type.upper()} - {url}")
    
    def on_new_instruction(self, callback: Callable[[OptionInstruction, str], None]):
        """
        设置新指令回调
        
        Args:
            callback: 回调函数，参数为 (instruction, page_type)
        """
        self._on_new_instruction = callback
    
    def on_new_message(self, callback: Callable[[str, str], None]):
        """
        设置新消息回调
        
        Args:
            callback: 回调函数，参数为 (message, page_type)
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
    
    def _display_message(self, text: str, page_type: str, instruction: Optional[OptionInstruction] = None):
        """
        根据展示模式显示消息
        
        Args:
            text: 原始消息
            page_type: 页面类型
            instruction: 解析后的指令（如果有）
        """
        page_label = f"[{page_type.upper()}]"
        
        if self.display_mode == "raw":
            # 仅显示原始消息
            print(f"{page_label} 原始消息: {text}")
        
        elif self.display_mode == "parsed":
            # 仅显示解析后的指令
            if instruction:
                print(f"{page_label} 解析指令: {instruction}")
        
        elif self.display_mode == "both":
            # 两者都显示
            print(f"{page_label} 原始消息: {text}")
            if instruction:
                print(f"{page_label} 解析指令: {instruction}")
                print(f"{page_label} JSON: {instruction.to_json()}")
    
    async def _extract_messages(self, page: Page) -> List[Dict]:
        """
        从页面提取消息
        
        Args:
            page: Playwright 页面对象
            
        Returns:
            消息列表，每个消息包含 id 和 text
        """
        # 多种可能的消息选择器
        message_selectors = [
            '[class*="message"]',
            '[class*="chat-message"]',
            '[class*="MessageContent"]',
            '[data-message-id]',
            '[class*="post"]',
            '[class*="Post"]',
            '[class*="content"]',
            'article',
            '.prose',
            '[class*="text-content"]',
        ]
        
        messages = []
        
        for selector in message_selectors:
            try:
                elements = await page.query_selector_all(selector)
                for element in elements:
                    try:
                        text = await element.inner_text()
                        text = text.strip()
                        
                        if not text or len(text) < 5:
                            continue
                        
                        # 尝试获取消息 ID
                        msg_id = await element.get_attribute('data-message-id')
                        if not msg_id:
                            # 使用内容哈希作为 ID
                            import hashlib
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
    
    async def _scan_page(self, config: PageMonitorConfig) -> List[OptionInstruction]:
        """
        扫描单个页面，返回新的指令
        
        Args:
            config: 页面配置
            
        Returns:
            新解析出的指令列表
        """
        if not config.enabled:
            return []
        
        new_instructions = []
        
        try:
            messages = await self._extract_messages(config.page)
            
            for msg in messages:
                msg_id = msg['id']
                text = msg['text']
                
                # 跳过已处理的消息
                if msg_id in config.processed_ids:
                    continue
                
                config.processed_ids.add(msg_id)
                
                # 触发新消息回调
                if self._on_new_message:
                    self._on_new_message(text, config.page_type)
                
                # 尝试解析指令（逐行解析）
                lines = text.split('\n')
                parsed_any = False
                
                for line in lines:
                    line = line.strip()
                    if not line or len(line) < 3:
                        continue
                    
                    instruction = config.parser.parse(line, msg_id)
                    if instruction:
                        parsed_any = True
                        
                        # 显示消息（根据展示模式）
                        self._display_message(line, config.page_type, instruction)
                        
                        # 保存到存储
                        if self.store.add(instruction):
                            new_instructions.append(instruction)
                            
                            # 触发新指令回调
                            if self._on_new_instruction:
                                self._on_new_instruction(instruction, config.page_type)
                            
                            # 添加已解析样本
                            if self.sample_manager:
                                category = self._determine_category(instruction)
                                self.sample_manager.add_parsed_sample(
                                    message=line,
                                    category=category,
                                    parsed_result=instruction.to_dict(),
                                    notes=f"自动收集-{config.page_type}"
                                )
                
                # 如果整条消息都没有被解析，添加为未解析样本
                if not parsed_any and self.sample_manager and len(text) > 5:
                    # 只显示原始消息（如果模式允许）
                    if self.display_mode in ["raw", "both"]:
                        print(f"[{config.page_type.upper()}] 原始消息（未解析）: {text}")
                    
                    self.sample_manager.add_unparsed_sample(
                        message=text,
                        notes=f"监控时未能解析-{config.page_type}"
                    )
        
        except Exception as e:
            print(f"⚠️  扫描页面出错 ({config.page_type}): {e}")
        
        return new_instructions
    
    async def scan_once(self) -> Dict[str, List[OptionInstruction]]:
        """
        扫描所有页面一次
        
        Returns:
            按页面类型分组的新指令字典
        """
        results = {}
        
        # 并发扫描所有页面
        tasks = [self._scan_page(config) for config in self.page_configs]
        all_instructions = await asyncio.gather(*tasks)
        
        # 按页面类型分组
        for config, instructions in zip(self.page_configs, all_instructions):
            if instructions:
                if config.page_type not in results:
                    results[config.page_type] = []
                results[config.page_type].extend(instructions)
        
        return results
    
    async def start(self):
        """开始实时监控所有页面"""
        if not self.page_configs:
            print("错误: 没有添加任何页面进行监控")
            return
        
        self._running = True
        enabled_count = sum(1 for c in self.page_configs if c.enabled)
        
        print("\n" + "=" * 60)
        print(f"多页面监控已启动")
        print(f"监控页面数: {enabled_count}/{len(self.page_configs)}")
        for config in self.page_configs:
            status = "✅ 启用" if config.enabled else "❌ 禁用"
            print(f"  - {config.page_type.upper()}: {config.url} ({status})")
        print(f"轮询间隔: {self.poll_interval} 秒")
        print(f"展示模式: {self.display_mode}")
        print("按 Ctrl+C 停止")
        print("=" * 60 + "\n")
        
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
        print("正在停止多页面监控...")
    
    def get_stats(self) -> Dict:
        """
        获取监控统计信息
        
        Returns:
            统计信息字典
        """
        stats = {
            'total_pages': len(self.page_configs),
            'enabled_pages': sum(1 for c in self.page_configs if c.enabled),
            'pages': []
        }
        
        for config in self.page_configs:
            stats['pages'].append({
                'type': config.page_type,
                'url': config.url,
                'enabled': config.enabled,
                'processed_messages': len(config.processed_ids)
            })
        
        return stats
