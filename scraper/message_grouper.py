#!/usr/bin/env python3
"""
消息分组器 - 将相关的交易消息聚合成交易组
识别买入、卖出、止损等操作的关联关系
"""
from typing import List, Dict, Optional
from datetime import datetime
import hashlib
import re
from rich.console import Console, Group
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

try:
    from config import Config
except ImportError:
    # 如果导入失败，使用默认配置
    class Config:
        FILTER_AUTHORS = []


class TradeMessageGroup:
    """交易消息组 - 一组相关的交易消息"""
    
    def __init__(self, group_id: str, symbol: str = ""):
        """
        Args:
            group_id: 消息组ID
            symbol: 交易标的（如 GILD, NVDA）
        """
        self.group_id = group_id
        self.symbol = symbol
        self.entry_message = None  # 买入消息
        self.exit_messages = []     # 卖出消息列表
        self.update_messages = []   # 更新消息（调整止损等）
        self.raw_messages = []      # 原始消息列表
    
    def add_message(self, message: Dict, message_type: str):
        """
        添加消息到组
        
        Args:
            message: 消息字典
            message_type: 消息类型 ('entry', 'exit', 'update')
        """
        self.raw_messages.append(message)
        
        if message_type == 'entry':
            self.entry_message = message
        elif message_type == 'exit':
            self.exit_messages.append(message)
        elif message_type == 'update':
            self.update_messages.append(message)
    
    def get_summary(self) -> Dict:
        """
        获取消息组摘要
        
        Returns:
            包含消息组信息的字典
        """
        return {
            'group_id': self.group_id,
            'symbol': self.symbol,
            'entry': self.entry_message,
            'exits': self.exit_messages,
            'updates': self.update_messages,
            'total_messages': len(self.raw_messages)
        }


class MessageGrouper:
    """消息分组器 - 将消息按交易组聚合"""
    
    def __init__(self):
        self.groups: Dict[str, TradeMessageGroup] = {}
    
    def _extract_symbol(self, text: str) -> Optional[str]:
        """
        从消息文本中提取交易标的
        
        Args:
            text: 消息文本
            
        Returns:
            交易标的符号，如 GILD, NVDA
        """
        # 预处理：清理文本
        # 1. 移除开头的 X（引用标记）- 只移除大写X，避免移除作者名的首字母
        text_cleaned = re.sub(r'^[XＸ]+', '', text)
        # 2. 移除 X 后直接跟大写字母的情况（如 "XAPLD" -> "APLD"）
        #    但要排除真实的股票代码如 XOM（以$开头的不处理）
        #    只处理没有$符号前缀的情况
        if '$X' not in text:  # 如果不是 $XOM 这种格式
            text_cleaned = re.sub(r'\bX([A-Z]{2,5})\b', r'\1', text_cleaned)
        # 3. 移除时间标记（PM/AM）和前面的数字，避免如 "11:13 PMAMD" 被识别为 "PMAMD"
        text_cleaned = re.sub(r'\d{1,2}:\d{2}\s*[AP]M', '', text_cleaned)
        text_cleaned = re.sub(r'\s+[AP]M\s+', ' ', text_cleaned)  # 移除独立的 PM/AM
        # 4. 移除作者名（常见模式：作者名+•+时间 或 连在一起的作者名+股票代码）
        #    例如："xiaozhaolucky•Jan 22, 2026 10:41 PM" 或 "xiaozhaoluckyGILD"
        text_cleaned = re.sub(r'[\w]+•\s*[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2}\s+[AP]M', '', text_cleaned)
        # 5. 在小写字母和大写字母之间插入空格（处理作者名+股票代码的情况）
        #    例如："xiaozhaoluckyGILD" -> "xiaozhaolucky GILD"
        text_cleaned = re.sub(r'([a-z])([A-Z]{2,})', r'\1 \2', text_cleaned)
        
        # 匹配股票代码模式（支持大小写）
        # 按优先级排序，从最具体到最宽泛
        patterns = [
            r'\$([A-Za-z]{1,5})\b',                    # $GILD 或 $gild 或 $XOM
            r'\b([A-Za-z]{2,5})\s*-\s*\$',             # GILD - $130 或 gild - $130
            r'\b([A-Za-z]{2,5})\s+\d+[cp]',            # NVDA 190c 或 GILD 130p (期权格式)
            r'[\u4e00-\u9fa5]+([A-Za-z]{2,5})期权',    # "三分之一cmcsa期权" 
            r'\b([A-Za-z]{2,5})期权',                   # gild期权
            r'\b([A-Za-z]{2,5})\s+call',               # GILD call 或 gild call
            r'\b([A-Za-z]{2,5})\s+put',                # GILD put 或 gild put
            r'\b([A-Za-z]{2,5})[\u4e00-\u9fa5]+call',  # amzn亚马逊call
            r'\b([A-Za-z]{2,5})[\u4e00-\u9fa5]+put',   # amzn亚马逊put
            r'\b([A-Za-z]{2,5})价内',                   # gild价内
            r'\b([A-Za-z]{2,5})\s+\d+\.?\d*\s*出',     # NVDA 2.25 出三分之一
            r'\b([A-Za-z]{2,5})剩下',                   # nvda剩下部分
            r'\b([A-Za-z]{2,5})\s+\d+\.?\d*\s*(附近)?都出', # GILD 2.3附近都出
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text_cleaned, re.IGNORECASE)
            if match:
                symbol = match.group(1).upper()
                # 过滤掉常见的非股票代码词汇和时间标记
                exclude_words = {'CALL', 'PUT', 'CALLS', 'PUTS', 'TAIL', 'ALSO', 'FROM', 'WITH', 'THAT', 'THIS', 'ABOUT', 'WHEN', 'PM', 'AM'}
                if symbol not in exclude_words:
                    return symbol
        
        return None
    
    def _classify_message(self, message: Dict) -> str:
        """
        分类消息类型
        
        Args:
            message: 消息字典
            
        Returns:
            消息类型: 'entry' (买入), 'exit' (卖出), 'update' (更新)
        """
        content = message.get('content', '').lower()
        
        # 卖出关键词
        exit_keywords = ['出', '卖', 'sell', 'exit', '平仓']
        # 买入关键词
        entry_keywords = ['call', 'put', 'calls', 'puts', '买入', 'buy', 'entry']
        # 更新关键词
        update_keywords = ['止损', '上移', '调整', 'stop loss', 'trailing']
        
        # 优先判断卖出（因为可能包含call/put等词）
        if any(keyword in content for keyword in exit_keywords):
            return 'exit'
        
        # 判断更新
        if any(keyword in content for keyword in update_keywords):
            return 'update'
        
        # 判断买入
        # 1. 检查关键词
        if any(keyword in content for keyword in entry_keywords):
            return 'entry'
        
        # 2. 检查期权格式（如 "190c" 或 "130p"）
        if re.search(r'\d+[cp]\b', content):
            return 'entry'
        
        # 3. 检查带价格的格式（如 "- $130 CALLS"）
        if re.search(r'-\s*\$\d+', content):
            return 'entry'
        
        # 默认为更新
        return 'update'
    
    def _get_quoted_symbol(self, message: Dict) -> Optional[str]:
        """
        从消息的引用内容中提取交易标的
        
        Args:
            message: 消息字典
            
        Returns:
            引用消息中的交易标的
        """
        quoted = message.get('quoted_context', '')
        if quoted:
            return self._extract_symbol(quoted)
        return None
    
    def _generate_group_id(self, symbol: str, author: str, timestamp: str) -> str:
        """
        生成消息组ID
        
        Args:
            symbol: 交易标的
            author: 作者
            timestamp: 时间戳
            
        Returns:
            消息组ID
        """
        # 使用 symbol + author + 日期 生成组ID
        # 提取日期部分（不包含具体时间）
        date_part = timestamp.split()[0:3] if timestamp else ['']
        date_str = '-'.join(date_part)
        
        key = f"{symbol}_{author}_{date_str}"
        # 生成短hash
        hash_obj = hashlib.md5(key.encode())
        short_hash = hash_obj.hexdigest()[:8]
        
        return f"{symbol}_{short_hash}"
    
    def _print_message_immediately(self, message: Dict, group_id: str, symbol: str, msg_type: str):
        """
        立即输出一条消息（流式处理）
        
        Args:
            message: 消息字典
            group_id: 分组ID
            symbol: 股票代码
            msg_type: 消息类型 ('entry', 'exit', 'update')
        """
        # 提取消息内容
        content = message.get('content', '').strip()
        
        # 过滤纯元数据消息
        weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        # 检查是否是纯时间戳：包含星期名称、时间，且单词数少于5个
        words = content.split()
        is_timestamp_only = (
            any(day in content for day in weekdays) and
            any(pm_am in content for pm_am in ['PM', 'AM']) and
            len(words) <= 4  # "•Wednesday 11:04 PM" 只有3个词
        )
        
        if (not content or 
            content == '•' or
            is_timestamp_only or  # 纯时间戳
            re.match(r'^由\s*\d+\s*阅读$', content) or  # "由 223阅读"
            re.match(r'^\d+\s*阅读$', content) or  # "223阅读"
            content in ['Edited', 'Reply', '编辑', '回复', '删除', '已编辑']):
            return  # 跳过这条消息
        
        lines = content.split('\n')
        main_content = lines[-1] if len(lines) > 1 else content
        # 截断过长内容
        if len(main_content) > 55:
            main_content = main_content[:52] + "..."
        
        timestamp = message.get('timestamp', '未知')
        
        # 确定操作类型
        if msg_type == 'entry':
            operation = "🟢 买入"
        elif msg_type == 'exit':
            operation = "🔴 卖出"
        else:
            operation = "🟡 调整"
        
        # 使用固定宽度格式化输出
        # 时间(22) | 分组ID(20) | 股票(8) | 操作(10) | 内容(55)
        line = f" {timestamp:<22} {group_id:<20} {symbol:<8} {operation:<10} {main_content:<55}"
        print(line)
    
    def group_messages(self, messages: List[Dict], stream_output: bool = False) -> List[TradeMessageGroup]:
        """
        流式处理消息：按时间顺序逐条处理，立即输出
        
        处理流程（模拟真实监控场景）：
        1. 监听到新消息（按时间顺序）
        2. 立即分析：提取股票代码、判断类型、生成groupId
        3. 立即输出到表格
        4. 记录到对应group（用于统计）
        
        Args:
            messages: 消息列表
            stream_output: 是否启用流式输出（默认False，兼容旧代码）
            
        Returns:
            交易消息组列表
        """
        self.groups = {}
        last_symbol_by_author = {}  # 记录每个作者最近提到的标的
        
        # 应用作者过滤器（两阶段过滤）
        filter_authors = Config.FILTER_AUTHORS
        filtered_messages = messages
        
        if filter_authors:
            print(f"🔍 启用作者过滤器，只处理以下作者的消息: {', '.join(filter_authors)}")
            
            # 阶段1：收集白名单作者的消息ID和被引用的消息内容
            allowed_message_ids = set()
            quoted_contents = set()
            
            for msg in messages:
                author = msg.get('author', '')
                if author in filter_authors:
                    allowed_message_ids.add(msg.get('group_id', ''))
                    # 收集这条消息引用的内容
                    quoted = msg.get('quoted_context', '')
                    if quoted:
                        # 提取引用的关键内容
                        quoted_clean = re.sub(r'[XxＸｘ]', '', quoted)
                        quoted_clean = re.sub(r'[\w]+•.*?[AP]M', '', quoted_clean)
                        quoted_clean = re.sub(r'\s+', ' ', quoted_clean).strip()
                        if quoted_clean:
                            quoted_contents.add(quoted_clean)
            
            # 阶段2：保留白名单作者的消息 + 被引用的消息
            filtered_messages = []
            for msg in messages:
                author = msg.get('author', '')
                msg_id = msg.get('group_id', '')
                content = msg.get('content', '')
                
                # 保留条件：作者在白名单 或 消息内容被白名单作者引用
                if author in filter_authors:
                    filtered_messages.append(msg)
                else:
                    # 检查这条消息是否被引用
                    content_clean = re.sub(r'\s+', ' ', content).strip()
                    is_quoted = False
                    for quoted in quoted_contents:
                        if len(quoted) > 10 and (quoted in content_clean or content_clean in quoted):
                            is_quoted = True
                            break
                    
                    if is_quoted:
                        filtered_messages.append(msg)
            
            print(f"📊 过滤前: {len(messages)} 条消息，过滤后: {len(filtered_messages)} 条消息")
        
        # 如果启用流式输出，先按时间排序消息（模拟真实监控场景）
        if stream_output:
            from datetime import datetime
            def parse_ts(msg):
                ts = msg.get('timestamp', '')
                if not ts:
                    return datetime.max
                try:
                    return datetime.strptime(ts, '%b %d, %Y %I:%M %p')
                except:
                    return datetime.max
            filtered_messages = sorted(filtered_messages, key=lambda x: (parse_ts(x), x.get('id', '')))
            
            # 打印表头
            print("\n" + "="*120)
            print("【流式处理 - 按时间顺序监听消息】")
            print("="*120)
            # 表头：时间(22) | 分组ID(20) | 股票(8) | 操作(10) | 内容(55)
            header = f" {'时间':<22} {'分组ID':<20} {'股票':<8} {'操作':<10} {'内容':<55}"
            print(header)
            print("-"*120)
        
        # 记录前一条消息的信息（用于DOM层级关系推断）
        last_processed_message = None
        last_processed_group_id = None
        
        for i, message in enumerate(filtered_messages):
            
            # 过滤纯元数据消息
            content = message.get('content', '').strip()
            
            # 清理content，移除特殊字符和多余空格
            content_clean = re.sub(r'[•·]', '', content).strip()
            words = content_clean.split()
            
            # 检查是否是纯时间戳
            weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            has_weekday = any(day in content_clean for day in weekdays)
            has_time = 'PM' in content_clean or 'AM' in content_clean
            is_timestamp_only = has_weekday and has_time and len(words) <= 4 and len(content_clean) < 30
            
            # 检查是否是阅读量
            is_read_count = re.match(r'^(由\s*)?\d+\s*阅读$', content)
            
            # 检查是否是操作标记
            is_action_label = content in ['•', 'Edited', 'Reply', '编辑', '回复', '删除', '已编辑']
            
            if not content or is_timestamp_only or is_read_count or is_action_label:
                continue  # 跳过此消息
            
            # 策略0: 检查DOM层级关系（has_message_above）
            # 如果当前消息的 has_message_above=true，说明它与前一条消息在同一个消息组
            has_above = message.get('has_message_above', False)
            
            # 提取交易标的
            symbol = self._extract_symbol(content)
            
            # 如果当前消息没有symbol，尝试从上下文推断
            # 优先级：DOM关系 > 时间上下文 > 引用内容（可能过时） > 作者上下文
            if not symbol:
                author = message.get('author', '')
                timestamp = message.get('timestamp', '')
                
                # 策略1: 如果有DOM层级关系（has_message_above=true），使用前一条消息的标的
                if has_above and last_processed_message:
                    prev_symbol = self._extract_symbol(last_processed_message.get('content', ''))
                    if not prev_symbol:
                        prev_symbol = self._get_quoted_symbol(last_processed_message)
                    if prev_symbol:
                        symbol = prev_symbol
                
                # 策略2: 查找前10条消息中的最近标的（时间上下文推断）
                # 适用于不同作者在短时间内讨论同一标的的情况
                if not symbol:
                    context_window = 10  # 扩大窗口以捕获更多上下文
                    # 从最近的消息开始往前查找
                    for j in range(i - 1, max(0, i - context_window) - 1, -1):
                        prev_message = filtered_messages[j]
                        prev_symbol = self._extract_symbol(prev_message.get('content', ''))
                        if not prev_symbol:
                            prev_symbol = self._get_quoted_symbol(prev_message)
                        
                        if prev_symbol:
                            # 找到最近的有标的的消息，使用它的标的
                            symbol = prev_symbol
                            break
                
                # 策略3: 从引用中获取（但优先级低于时间上下文）
                # 因为引用的消息可能是很久之前的
                if not symbol:
                    symbol = self._get_quoted_symbol(message)
                
                # 策略4: 如果都没找到，尝试从作者的最近标的中获取
                if not symbol and author in last_symbol_by_author:
                    symbol = last_symbol_by_author[author]
            
            # 如果还是没有symbol，跳过
            if not symbol:
                continue
            
            # 记录当前处理的消息（用于下一轮DOM层级关系推断）
            last_processed_message = message
            
            # 更新该作者的最近标的
            author = message.get('author', '')
            if author:
                last_symbol_by_author[author] = symbol
            
            # 分类消息
            message_type = self._classify_message(message)
            
            # 为买入消息创建新组
            if message_type == 'entry':
                group_id = self._generate_group_id(
                    symbol,
                    message.get('author', ''),
                    message.get('timestamp', '')
                )
                
                if group_id not in self.groups:
                    self.groups[group_id] = TradeMessageGroup(group_id, symbol)
                
                self.groups[group_id].add_message(message, 'entry')
                last_processed_group_id = group_id
                
                # 流式输出：立即输出这条消息
                if stream_output:
                    self._print_message_immediately(message, group_id, symbol, message_type)
            
            # 卖出或更新消息：找到对应的买入组
            else:
                # 尝试从引用中找到对应的买入组
                quoted_symbol = self._get_quoted_symbol(message)
                target_symbol = quoted_symbol or symbol
                
                # 查找匹配的组
                matched_group = None
                author = message.get('author', '')
                timestamp = message.get('timestamp', '')
                date_part = timestamp.split()[0:3] if timestamp else ['']
                
                # 策略0: DOM层级关系优先 - 如果有has_message_above，直接使用前一条消息所在的组
                if has_above and last_processed_group_id and last_processed_group_id in self.groups:
                    matched_group = self.groups[last_processed_group_id]
                
                # 策略1: 优先查找引用内容匹配的组
                # 如果消息引用了买入消息的内容，尝试找到对应的买入组
                quoted_context = message.get('quoted_context', '')
                if quoted_context:
                    for group_id, group in self.groups.items():
                        if group.symbol == target_symbol and group.entry_message:
                            # 检查引用内容是否包含在买入消息中
                            entry_content = group.entry_message.get('content', '')
                            # 提取引用中的关键内容（去掉作者和时间）
                            quoted_clean = re.sub(r'[XxＸｘ]?[\w]+•.*?[AP]M', '', quoted_context)
                            quoted_clean = re.sub(r'\s+', ' ', quoted_clean).strip()
                            
                            if quoted_clean and (quoted_clean in entry_content or 
                                               any(part in entry_content for part in quoted_clean.split() if len(part) > 3)):
                                # 检查是否同一天或相近时间
                                entry_date = group.entry_message.get('timestamp', '').split()[0:3]
                                if entry_date == date_part or not date_part[0]:
                                    matched_group = group
                                    break
                
                # 策略2: 如果没有通过引用匹配，使用作者匹配
                if not matched_group:
                    for group_id, group in self.groups.items():
                        if (group.symbol == target_symbol and 
                            group.entry_message and
                            group.entry_message.get('author') == author):
                            # 检查是否同一天
                            entry_date = group.entry_message.get('timestamp', '').split()[0:3]
                            if entry_date == date_part:
                                matched_group = group
                                break
                
                # 策略3: 如果仍未匹配，检查是否有同一标的、同一天、最近时间的买入组
                # 这处理买入消息作者被错误识别的情况
                if not matched_group:
                    for group_id, group in self.groups.items():
                        if group.symbol == target_symbol and group.entry_message:
                            entry_date = group.entry_message.get('timestamp', '').split()[0:3]
                            # 同一天且时间相近（通过检查组内最近消息的作者）
                            if entry_date == date_part:
                                # 检查这个组是否有其他来自同一作者的消息
                                has_same_author = False
                                for msg in group.raw_messages:
                                    if msg.get('author') == author:
                                        has_same_author = True
                                        break
                                
                                if has_same_author:
                                    matched_group = group
                                    break
                
                # 如果找到匹配的组，添加到该组
                if matched_group:
                    matched_group.add_message(message, message_type)
                    last_processed_group_id = matched_group.group_id
                    
                    # 流式输出：立即输出这条消息
                    if stream_output:
                        self._print_message_immediately(message, matched_group.group_id, matched_group.symbol, message_type)
                else:
                    # 没有找到匹配的组，创建新组
                    group_id = self._generate_group_id(target_symbol, author, timestamp)
                    if group_id not in self.groups:
                        self.groups[group_id] = TradeMessageGroup(group_id, target_symbol)
                    self.groups[group_id].add_message(message, message_type)
                    last_processed_group_id = group_id
                    
                    # 流式输出：立即输出这条消息
                    if stream_output:
                        self._print_message_immediately(message, group_id, target_symbol, message_type)
        
        # 如果启用流式输出，打印统计信息
        if stream_output:
            print("="*120)
            print(f"共处理 {len(filtered_messages)} 条消息，识别出 {len(self.groups)} 个交易组")
            print("="*120 + "\n")
        
        return list(self.groups.values())


def format_as_table(groups: List[TradeMessageGroup]) -> str:
    """
    将消息组格式化为表格显示
    
    Args:
        groups: 交易消息组列表
        
    Returns:
        格式化的表格字符串
    """
    if not groups:
        return "没有消息组"
    
    output = []
    output.append("\n" + "=" * 120)
    output.append("交易消息组汇总表")
    output.append("=" * 120)
    
    for i, group in enumerate(groups, 1):
        summary = group.get_summary()
        
        output.append(f"\n【消息组 #{i}】")
        output.append(f"组ID: {summary['group_id']}")
        output.append(f"交易标的: {summary['symbol']}")
        output.append(f"消息总数: {summary['total_messages']}")
        output.append("-" * 120)
        
        # 买入信息
        if summary['entry']:
            entry = summary['entry']
            output.append("\n📈 【买入信号】")
            output.append(f"   作者: {entry.get('author', '未知')}")
            output.append(f"   时间: {entry.get('timestamp', '未知')}")
            output.append(f"   内容: {entry.get('content', '')[:100]}")
            if entry.get('quoted_context'):
                output.append(f"   引用: {entry.get('quoted_context', '')[:80]}")
        else:
            output.append("\n📈 【买入信号】无")
        
        # 卖出信息
        if summary['exits']:
            output.append(f"\n📉 【卖出操作】 ({len(summary['exits'])}条)")
            for j, exit_msg in enumerate(summary['exits'], 1):
                output.append(f"   {j}. {exit_msg.get('content', '')[:80]}")
                output.append(f"      时间: {exit_msg.get('timestamp', '未知')}")
                if summary['entry']:
                    output.append(f"      ⬅️ 对应买入: {summary['entry'].get('content', '')[:60]}")
        else:
            output.append("\n📉 【卖出操作】无")
        
        # 更新信息
        if summary['updates']:
            output.append(f"\n🔄 【止损/调整】 ({len(summary['updates'])}条)")
            for j, update_msg in enumerate(summary['updates'], 1):
                output.append(f"   {j}. {update_msg.get('content', '')[:80]}")
                output.append(f"      时间: {update_msg.get('timestamp', '未知')}")
        
        output.append("\n" + "-" * 120)
    
    output.append("\n" + "=" * 120)
    output.append(f"共 {len(groups)} 个消息组")
    output.append("=" * 120 + "\n")
    
    return "\n".join(output)


def format_as_detailed_table(groups: List[TradeMessageGroup]) -> str:
    """
    将消息组格式化为详细表格（类似数据库表）
    
    Args:
        groups: 交易消息组列表
        
    Returns:
        格式化的表格字符串
    """
    if not groups:
        return "没有消息组"
    
    output = []
    
    # 表头
    header_format = "{:<15} {:<8} {:<20} {:<12} {:<50} {:<50}"
    separator = "-" * 155
    
    output.append("\n" + "=" * 155)
    output.append("交易消息明细表")
    output.append("=" * 155)
    output.append(header_format.format("消息组ID", "标的", "时间", "操作类型", "消息内容", "关联买入"))
    output.append(separator)
    
    for group in groups:
        summary = group.get_summary()
        group_id = summary['group_id']
        symbol = summary['symbol']
        
        # 买入消息
        if summary['entry']:
            entry = summary['entry']
            output.append(header_format.format(
                group_id,
                symbol,
                entry.get('timestamp', '')[:19],
                "🟢 买入",
                entry.get('content', '')[:48],
                "-"
            ))
        
        # 卖出消息
        for exit_msg in summary['exits']:
            entry_ref = ""
            if summary['entry']:
                entry_ref = summary['entry'].get('content', '')[:48]
            
            output.append(header_format.format(
                group_id,
                symbol,
                exit_msg.get('timestamp', '')[:19],
                "🔴 卖出",
                exit_msg.get('content', '')[:48],
                entry_ref
            ))
        
        # 更新消息
        for update_msg in summary['updates']:
            output.append(header_format.format(
                group_id,
                symbol,
                update_msg.get('timestamp', '')[:19],
                "🟡 调整",
                update_msg.get('content', '')[:48],
                "-"
            ))
        
        output.append(separator)
    
    output.append(f"共 {len(groups)} 个消息组\n")
    
    return "\n".join(output)


def format_as_rich_panels(groups: List[TradeMessageGroup]) -> None:
    """
    使用 Rich 库将消息组格式化为彩色面板显示
    严格按照消息的时间顺序输出，每条消息显示它所属的分组
    这样符合真实场景：消息按时间顺序到达和处理
    
    Args:
        groups: 交易消息组列表
    """
    console = Console()
    
    if not groups:
        console.print("[yellow]没有消息组[/yellow]")
        return
    
    # 从所有组中收集所有消息（每条消息记录它所属的组）
    all_messages = []
    
    for group in groups:
        summary = group.get_summary()
        group_id = summary['group_id']
        symbol = summary['symbol']
        
        # 添加买入消息
        if summary['entry']:
            all_messages.append({
                'type': 'entry',
                'data': summary['entry'],
                'group_id': group_id,
                'symbol': symbol,
                'timestamp': summary['entry'].get('timestamp', ''),
                'id': summary['entry'].get('id', '')
            })
        
        # 添加卖出消息
        for exit_msg in summary['exits']:
            all_messages.append({
                'type': 'exit',
                'data': exit_msg,
                'group_id': group_id,
                'symbol': symbol,
                'timestamp': exit_msg.get('timestamp', ''),
                'id': exit_msg.get('id', '')
            })
        
        # 添加调整消息
        for update_msg in summary['updates']:
            all_messages.append({
                'type': 'update',
                'data': update_msg,
                'group_id': group_id,
                'symbol': symbol,
                'timestamp': update_msg.get('timestamp', ''),
                'id': update_msg.get('id', '')
            })
    
    # 按时间戳排序所有消息（还原真实的消息到达顺序）
    from datetime import datetime
    def parse_timestamp(ts):
        """解析时间戳用于排序，返回 datetime 对象"""
        if not ts:
            return datetime.max  # 没有时间戳的放最后
        try:
            # 尝试解析 "Jan 22, 2026 10:41 PM" 格式
            return datetime.strptime(ts, '%b %d, %Y %I:%M %p')
        except:
            # 如果解析失败，返回最大值放到最后
            return datetime.max
    
    all_messages.sort(key=lambda x: (parse_timestamp(x['timestamp']), x['id']))
    
    # 按时间顺序输出所有消息
    import textwrap
    for msg_item in all_messages:
        msg_type = msg_item['type']
        msg_data = msg_item['data']
        group_id = msg_item['group_id']  # 从消息项中获取
        symbol = msg_item['symbol']      # 从消息项中获取
        
        content = msg_data.get('content', '').strip()
        lines = content.split('\n')
        main_content = lines[-1] if len(lines) > 1 else content
        
        # 设置固定宽度
        PANEL_WIDTH = 70
        
        # 格式化各字段
        panel_lines = []
        panel_lines.append(f"[bold]分组ID:[/bold] {group_id}")
        
        # 原始消息：使用固定宽度，超长自动换行
        msg_label_display_len = 10  # "原始消息: " 的实际显示长度
        available_width = PANEL_WIDTH - msg_label_display_len
        
        if len(main_content) > available_width:
            panel_lines.append("[bold]原始消息:[/bold]")
            wrapped_lines = textwrap.wrap(main_content, width=PANEL_WIDTH - 2)
            for wline in wrapped_lines:
                panel_lines.append(f"  {wline}")
        else:
            panel_lines.append(f"[bold]原始消息:[/bold] {main_content}")
        
        panel_lines.append(f"[bold]期权:[/bold] {symbol}")
        panel_lines.append(f"[bold]时间:[/bold] {msg_data.get('timestamp', '未知')}")
        
        if msg_type == 'entry':
            panel_lines.append(f"[bold]操作:[/bold] 🟢 [bold green]买入[/bold green]")
            border_style = "bold blue"
        elif msg_type == 'exit':
            panel_lines.append(f"[bold]操作:[/bold] 🔴 [bold red]卖出[/bold red]")
            border_style = "bold green"
        elif msg_type == 'update':
            panel_lines.append(f"[bold]操作:[/bold] 🟡 [bold yellow]调整[/bold yellow]")
            border_style = "bold yellow"
        
        panel_content = "\n".join(panel_lines)
        
        panel = Panel(
            panel_content,
            border_style=border_style,
            box=box.HEAVY,
            padding=(0, 1),
            width=PANEL_WIDTH + 4,
            expand=False
        )
        console.print(panel)
    
    console.print(f"\n[bold cyan]共 {len(all_messages)} 条消息，{len(groups)} 个消息组[/bold cyan]")
