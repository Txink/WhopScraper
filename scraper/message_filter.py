"""
消息过滤器 - 统一的过滤规则
基于DOM结构特征过滤辅助信息和元数据
"""
import re
from typing import Dict, Optional


class MessageFilter:
    """统一的消息过滤规则"""
    
    # 元数据正则模式
    METADATA_PATTERNS = {
        'read_count': r'^(由\s*)?\d+\s*阅读$',  # 阅读量: "由 268阅读" 或 "268阅读"
        'edited': r'^(已编辑|Edited)$',  # 编辑标记
        'action': r'^(回复|Reply|删除|Delete)$',  # 操作标记
        'timestamp_line': r'^•.*\d{1,2}:\d{2}\s+[AP]M$',  # 时间戳行: "•Wednesday 11:04 PM"
        'weekday_metadata': r'^[•·]\s*[A-Z]',  # 以 "•" 或 "·" 开头的元数据
    }
    
    # 需要排除的固定文本
    EXCLUDE_TEXTS = {
        '•', 'Tail', 'X',  # 特殊标记
        'Edited', 'Reply', 'Delete',  # 英文操作
        '已编辑', '回复', '删除',  # 中文操作
    }
    
    # 星期名称（用于识别纯时间戳消息）
    WEEKDAYS = {
        'Monday', 'Tuesday', 'Wednesday', 'Thursday', 
        'Friday', 'Saturday', 'Sunday'
    }
    
    # 股票相关的排除词（不应作为股票代码）
    EXCLUDE_STOCK_WORDS = {
        'CALL', 'PUT', 'CALLS', 'PUTS', 'TAIL', 
        'ALSO', 'FROM', 'WITH', 'THAT', 'THIS', 
        'ABOUT', 'WHEN', 'PM', 'AM'
    }
    
    # 公司名称相关（可能出现在股票卡片中）
    COMPANY_SUFFIXES = {
        'Inc.', 'Corp.', 'Ltd.', 'LLC', 'Enterprises'
    }
    
    @classmethod
    def should_filter_text(cls, text: str, context: Optional[Dict] = None) -> bool:
        """
        判断文本是否应该被过滤
        
        Args:
            text: 要判断的文本
            context: 上下文信息（可选），包含：
                - in_stock_card: 是否在股票卡片中
                - is_author: 是否是作者字段
                - is_timestamp: 是否是时间戳字段
                
        Returns:
            True 如果应该过滤，False 如果应该保留
        """
        if not text or not text.strip():
            return True
        
        text = text.strip()
        context = context or {}
        
        # 1. 检查固定排除文本
        if text in cls.EXCLUDE_TEXTS:
            return True
        
        # 2. 检查元数据模式
        for pattern_name, pattern in cls.METADATA_PATTERNS.items():
            if re.match(pattern, text):
                return True
        
        # 3. 检查是否是纯时间戳消息（包含星期和AM/PM，且字数少）
        if cls._is_timestamp_only(text):
            return True
        
        # 4. 检查上下文相关的过滤
        if context.get('in_stock_card', False):
            # 在股票卡片中，过滤公司名称等
            if any(suffix in text for suffix in cls.COMPANY_SUFFIXES):
                return True
            if 'Updated' in text or 'NASDAQ' in text or 'NYSE' in text:
                return True
        
        # 5. 文本长度检查
        if len(text) < 2:  # 太短的文本（除了已知的有效单字符）
            return True
        
        return False
    
    @classmethod
    def _is_timestamp_only(cls, text: str) -> bool:
        """
        检查是否是纯时间戳消息
        
        Args:
            text: 要检查的文本
            
        Returns:
            True 如果是纯时间戳
        """
        # 清理特殊字符
        clean_text = re.sub(r'[•·]', '', text).strip()
        words = clean_text.split()
        
        # 检查是否包含星期名称和时间标记
        has_weekday = any(day in clean_text for day in cls.WEEKDAYS)
        has_time = 'PM' in clean_text or 'AM' in clean_text
        
        # 纯时间戳：包含星期+时间，且单词数少于5个，总长度少于30
        return has_weekday and has_time and len(words) <= 4 and len(clean_text) < 30
    
    @classmethod
    def is_valid_author_text(cls, text: str, in_stock_card: bool = False) -> bool:
        """
        检查文本是否可能是有效的作者名
        
        Args:
            text: 要检查的文本
            in_stock_card: 是否在股票卡片中
            
        Returns:
            True 如果可能是作者名
        """
        if not text or len(text) > 50:
            return False
        
        # 排除特殊标记
        if text == 'Tail' or text in cls.EXCLUDE_TEXTS:
            return False
        
        # 排除包含时间标记的文本
        if 'PM' in text or 'AM' in text:
            return False
        
        # 排除日期
        if '2026' in text or '2025' in text or re.search(r'\d{4}', text):
            return False
        
        # 排除分隔符
        if '•' in text:
            return False
        
        # 排除价格相关
        if '$' in text:
            return False
        
        # 排除公司名称相关
        if any(suffix in text for suffix in cls.COMPANY_SUFFIXES):
            return False
        
        # 排除月份日期格式（如 "Jan 22"）
        if re.search(r'\d{1,2}月', text):
            return False
        
        if re.search(r'\d+:\d+', text):
            return False
        
        # 如果在股票卡片中，直接拒绝
        if in_stock_card:
            return False
        
        return True
    
    @classmethod
    def clean_text(cls, text: str) -> str:
        """
        清理文本，移除结尾标记和多余空格
        
        Args:
            text: 要清理的文本
            
        Returns:
            清理后的文本
        """
        if not text:
            return ""
        
        # 移除 "Tail" 结尾标记
        text = re.sub(r'Tail$', '', text).strip()
        
        # 移除多余空格
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
    
    @classmethod
    def extract_content_lines(cls, full_text: str, author: str = "", timestamp: str = "") -> list:
        """
        从完整文本中提取有效内容行，过滤元数据
        
        Args:
            full_text: 完整文本
            author: 作者名（用于过滤）
            timestamp: 时间戳（用于过滤）
            
        Returns:
            有效内容行列表
        """
        if not full_text:
            return []
        
        lines = full_text.split('\n')
        valid_lines = []
        
        for line in lines:
            line = cls.clean_text(line)
            
            if not line:
                continue
            
            # 过滤元数据
            if cls.should_filter_text(line):
                continue
            
            # 过滤作者和时间戳行
            if line == author or line == timestamp:
                continue
            
            # 过滤日期格式
            if re.match(r'^[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}', line):
                continue
            
            # 过滤时间格式
            if re.match(r'^\d{1,2}:\d{2}\s+[AP]M$', line):
                continue
            
            valid_lines.append(line)
        
        return valid_lines
    
    @classmethod
    def is_image_only_message(
        cls, 
        has_attachment: bool, 
        primary_message: str, 
        related_messages: list
    ) -> bool:
        """
        判断是否是纯图片消息（只有图片和阅读量，没有实质内容）
        
        Args:
            has_attachment: 是否有附件
            primary_message: 主消息内容
            related_messages: 关联消息列表
            
        Returns:
            True 如果是纯图片消息（应该忽略）
        """
        if not has_attachment:
            return False
        
        # 检查主消息是否只是阅读量
        is_read_count_only = (
            primary_message and 
            re.match(cls.METADATA_PATTERNS['read_count'], primary_message)
        )
        
        # 检查是否没有实质内容
        has_no_content = (
            not primary_message or 
            len(primary_message) < 10
        )
        
        # 检查关联消息是否也没有内容
        has_no_related = len(related_messages) == 0
        
        return is_read_count_only or (has_no_content and has_no_related)


class DOMStructureHelper:
    """DOM结构辅助类 - 基于真实DOM结构的特征识别"""
    
    # 基于真实DOM的选择器
    MESSAGE_CONTAINER_SELECTORS = [
        '.group\\/message',           # Whop主要使用: <div class="group/message">
        '[data-message-id]',          # 每个消息都有唯一ID
        '[class*="group/message"]',   # 备用
    ]
    
    # 头像相关选择器（注意：头像可能在消息组的最后一条）
    AVATAR_SELECTORS = [
        '.fui-AvatarRoot',           # 真实DOM: <span class="fui-AvatarRoot size-8">
        '.fui-AvatarImage',          # <img class="fui-AvatarImage">
        '[class*="fui-Avatar"]',
    ]
    
    # 用户名选择器
    USERNAME_SELECTORS = [
        'span[role="button"].truncate.fui-HoverCardTrigger',  # 真实DOM中的用户名
        '[class*="fui-Text"][class*="truncate"]',
        '[class*="truncate"][class*="cursor-pointer"]',
    ]
    
    # 时间戳选择器
    TIMESTAMP_SELECTORS = [
        'time',                      # HTML5标准
        '[datetime]',                # datetime属性
        'span:has(> span:contains("•"))',  # 包含 "•" 的时间戳容器
    ]
    
    # 消息气泡选择器
    MESSAGE_BUBBLE_SELECTORS = [
        '.bg-gray-3.rounded-\\[18px\\]',  # 真实DOM: <div class="bg-gray-3 rounded-[18px] px-3 py-1.5">
        '[class*="bg-gray-3"][class*="rounded"]',
        '[class*="whitespace-pre-wrap"]',
    ]
    
    # 引用消息选择器（基于真实DOM 5949-5971行）
    QUOTE_SELECTORS = [
        '.peer\\/reply',              # 真实DOM: <div class="peer/reply relative mb-1.5">
        '[class*="peer/reply"]',
        '[class*="border-t-2"][class*="border-l-2"]',  # 引用的边框线特征
    ]
    
    # 阅读量选择器（基于真实DOM）
    READ_COUNT_SELECTORS = [
        'span.text-gray-11.text-0',  # 真实DOM: <span class="text-gray-11 text-0 h-[15px]">
        '[class*="text-gray-11"][class*="text-0"]',
    ]
    
    # 图片/附件选择器
    ATTACHMENT_SELECTORS = [
        '[data-attachment-id]',
        'img[src*="whop.com"]',
        '[class*="attachment"]',
    ]
    
    @classmethod
    def has_avatar(cls, element) -> bool:
        """检查元素是否包含头像"""
        for selector in cls.AVATAR_SELECTORS:
            if element.querySelector(selector):
                return True
        return False
    
    @classmethod
    def is_message_group_start(cls, element) -> bool:
        """
        判断是否是消息组的开始
        基于DOM特征：has_message_above="false" 表示新消息组开始
        """
        has_above = element.getAttribute('data-has-message-above')
        return has_above == 'false' or has_above is None
    
    @classmethod
    def is_in_same_group(cls, element) -> bool:
        """
        判断消息是否在同一组内
        基于DOM特征：has_message_above="true" 表示与上一条消息在同一组
        """
        has_above = element.getAttribute('data-has-message-above')
        return has_above == 'true'
    
    @classmethod
    def is_single_message_group(cls, element) -> bool:
        """
        判断是否是单条消息的消息组
        DOM特征：has_message_above="false" AND has_message_below="false"
        """
        has_above = element.getAttribute('data-has-message-above')
        has_below = element.getAttribute('data-has-message-below')
        return has_above == 'false' and has_below == 'false'
    
    @classmethod
    def is_first_in_group(cls, element) -> bool:
        """
        判断是否是消息组的第一条消息
        DOM特征：has_message_above="false" AND has_message_below="true"
        """
        has_above = element.getAttribute('data-has-message-above')
        has_below = element.getAttribute('data-has-message-below')
        return has_above == 'false' and has_below == 'true'
    
    @classmethod
    def is_middle_in_group(cls, element) -> bool:
        """
        判断是否是消息组的中间消息
        DOM特征：has_message_above="true" AND has_message_below="true"
        """
        has_above = element.getAttribute('data-has-message-above')
        has_below = element.getAttribute('data-has-message-below')
        return has_above == 'true' and has_below == 'true'
    
    @classmethod
    def is_last_in_group(cls, element) -> bool:
        """
        判断是否是消息组的最后一条消息
        DOM特征：has_message_above="true" AND has_message_below="false"
        """
        has_above = element.getAttribute('data-has-message-above')
        has_below = element.getAttribute('data-has-message-below')
        return has_above == 'true' and has_below == 'false'
    
    @classmethod
    def has_quote(cls, element) -> bool:
        """检查元素是否包含引用"""
        for selector in cls.QUOTE_SELECTORS:
            if element.querySelector(selector):
                return True
        return False
