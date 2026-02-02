"""
增强的消息提取器
识别消息的关联关系、引用关系和上下文
"""
import hashlib
import re
from typing import List, Dict, Optional
from datetime import datetime
from playwright.async_api import Page, ElementHandle


class MessageGroup:
    """消息组 - 包含一组相关联的消息"""
    
    def __init__(
        self,
        group_id: str,
        author: str = "",
        timestamp: str = "",
        primary_message: str = "",
        related_messages: List[str] = None,
        quoted_message: str = "",
        quoted_context: str = "",
        has_message_above: bool = False,
        has_message_below: bool = False
    ):
        """
        Args:
            group_id: 消息组ID
            author: 作者
            timestamp: 时间戳
            primary_message: 主消息内容
            related_messages: 关联的后续消息列表
            quoted_message: 引用的消息标题/预览
            quoted_context: 引用的完整上下文
            has_message_above: 是否有上一条相关消息（DOM层级关系）
            has_message_below: 是否有下一条相关消息（DOM层级关系）
        """
        self.group_id = group_id
        self.author = author
        self.timestamp = timestamp
        self.primary_message = primary_message
        self.related_messages = related_messages or []
        self.quoted_message = quoted_message
        self.quoted_context = quoted_context
        self.has_message_above = has_message_above
        self.has_message_below = has_message_below
    
    def get_full_content(self) -> str:
        """获取完整内容（包含所有关联消息）"""
        parts = []
        
        # 添加引用内容
        if self.quoted_context:
            parts.append(f"[引用] {self.quoted_context}")
        
        # 添加主消息
        if self.primary_message:
            parts.append(self.primary_message)
        
        # 添加关联消息
        if self.related_messages:
            parts.extend(self.related_messages)
        
        return "\n".join(parts)
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'group_id': self.group_id,
            'author': self.author,
            'timestamp': self.timestamp,
            'primary_message': self.primary_message,
            'related_messages': self.related_messages,
            'quoted_message': self.quoted_message,
            'quoted_context': self.quoted_context,
            'has_message_above': self.has_message_above,
            'has_message_below': self.has_message_below,
            'full_content': self.get_full_content()
        }
    
    def __repr__(self):
        return f"MessageGroup(author={self.author}, messages={len(self.related_messages)+1})"


class EnhancedMessageExtractor:
    """增强的消息提取器 - 识别消息关联和引用"""
    
    def __init__(self, page: Page):
        """
        Args:
            page: Playwright 页面对象
        """
        self.page = page
    
    async def extract_message_groups(self) -> List[MessageGroup]:
        """
        提取消息组（包含关联关系）
        
        Returns:
            消息组列表
        """
        js_code = """
        () => {
            const messageGroups = [];
            
            // 查找所有消息容器
            // 根据Whop页面实际结构调整选择器
            const messageSelectors = [
                '[data-message-id]',          // 最准确:有唯一ID
                '.group\\/message',           // Whop使用的类名 (需要转义斜杠)
                '[class*="group/message"]',   // 包含group/message的类名
                '[class*="message"]',         // 备用:包含message
                '[role="article"]'            // 备用:语义化标签
            ];
            
            let messageElements = [];
            for (const selector of messageSelectors) {
                try {
                    messageElements = document.querySelectorAll(selector);
                    if (messageElements.length > 0) {
                        console.log(`✅ 使用选择器: ${selector}, 找到 ${messageElements.length} 个消息`);
                        break;
                    }
                } catch (e) {
                    console.log(`⚠️ 选择器错误: ${selector}`, e);
                }
            }
            
            if (messageElements.length === 0) {
                console.log('❌ 未找到任何消息元素');
                return [];
            }
            
            for (const msgEl of messageElements) {
                try {
                    const group = {
                        group_id: '',
                        author: '',
                        timestamp: '',
                        primary_message: '',
                        related_messages: [],
                        quoted_message: '',
                        quoted_context: '',
                        has_timestamp: false,
                        element_html: msgEl.outerHTML.substring(0, 500) // 用于调试
                    };
                    
                    // 提取消息ID
                    group.group_id = msgEl.getAttribute('data-message-id') || 
                                     msgEl.getAttribute('id') || 
                                     'msg-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9);
                    
                    // 提取消息组关系属性
                    group.has_message_above = msgEl.getAttribute('data-has-message-above') === 'true';
                    group.has_message_below = msgEl.getAttribute('data-has-message-below') === 'true';
                    
                    // 提取作者信息
                    // Whop页面中作者信息可能在多个位置
                    const authorSelectors = [
                        '[class*="fui-Text"][class*="truncate"]',  // Whop使用的作者类名
                        '[class*="author"]',
                        '[class*="username"]',
                        '[class*="user"]',
                        '[data-author]',
                        'span.fui-Text'  // 可能的作者标签
                    ];
                    
                    // 尝试从选择器提取
                    for (const selector of authorSelectors) {
                        const authorEl = msgEl.querySelector(selector);
                        if (authorEl) {
                            const text = authorEl.textContent.trim();
                            
                            // 检查父元素是否是股票卡片
                            const isInStockCard = authorEl.closest('[class*="stock"]') || 
                                                authorEl.closest('[class*="card"]') ||
                                                authorEl.closest('[class*="embed"]') ||
                                                // 检查是否在包含股价信息的容器中
                                                (authorEl.parentElement && 
                                                 (authorEl.parentElement.textContent.includes('Updated') ||
                                                  authorEl.parentElement.textContent.includes('NASDAQ') ||
                                                  authorEl.parentElement.textContent.includes('NYSE')));
                            
                            // 过滤掉时间、日期、公司名称、结尾标记等无关文本
                            if (text && 
                                text.length > 0 && 
                                text.length < 50 &&  // 作者名不会太长
                                text !== 'Tail' &&  // 排除结尾标记
                                !text.includes('PM') && 
                                !text.includes('AM') && 
                                !text.includes('2026') &&
                                !text.includes('•') &&
                                !text.includes('$') &&  // 排除交易内容
                                !text.includes('Inc.') &&  // 排除公司名
                                !text.includes('Corp.') &&
                                !text.includes('Ltd.') &&
                                !text.includes('LLC') &&
                                !text.includes('Enterprises') &&
                                !/\d{1,2}月/.test(text) &&  // 排除中文日期
                                !/\d+:\d+/.test(text) &&  // 排除时间格式
                                !isInStockCard) {  // 排除股票卡片中的文本
                                group.author = text;
                                break;
                            }
                        }
                    }
                    
                    // 如果还是没找到,尝试从文本节点中查找
                    if (!group.author) {
                        const textNodes = [];
                        const walker = document.createTreeWalker(
                            msgEl,
                            NodeFilter.SHOW_TEXT,
                            null,
                            false
                        );
                        let node;
                        while (node = walker.nextNode()) {
                            const text = node.textContent.trim();
                            
                            // 检查节点是否在股票卡片中
                            const parentEl = node.parentElement;
                            const isInStockCard = parentEl && (
                                parentEl.closest('[class*="stock"]') ||
                                parentEl.closest('[class*="card"]') ||
                                parentEl.closest('[class*="embed"]') ||
                                (parentEl.textContent.includes('Updated') ||
                                 parentEl.textContent.includes('NASDAQ') ||
                                 parentEl.textContent.includes('NYSE'))
                            );
                            
                            if (text && 
                                text.length > 2 && 
                                text.length < 30 &&
                                text !== 'Tail' &&  // 排除结尾标记
                                !text.includes('•') &&
                                !text.includes('$') &&
                                !text.includes('Inc.') &&
                                !text.includes('Corp.') &&
                                !text.includes('Enterprises') &&
                                !isInStockCard &&
                                !/\d/.test(text)) {  // 不包含数字
                                textNodes.push(text);
                                if (textNodes.length === 1) {
                                    group.author = text;
                                    break;
                                }
                            }
                        }
                    }
                    
                    // 提取时间戳
                    // Whop页面中时间戳格式: "Jan 22, 2026 10:41 PM"
                    const timestampSelectors = [
                        'time',                        // HTML5语义化标签(最优先)
                        '[datetime]',                  // 带datetime属性的元素
                        '[class*="timestamp"]',
                        '[class*="time"]',
                        '[class*="date"]'
                    ];
                    
                    // 尝试从标准时间标签提取
                    for (const selector of timestampSelectors) {
                        const timeEl = msgEl.querySelector(selector);
                        if (timeEl) {
                            group.timestamp = timeEl.textContent.trim() || 
                                            timeEl.getAttribute('datetime') || '';
                            if (group.timestamp) {
                                group.has_timestamp = true;
                                break;
                            }
                        }
                    }
                    
                    // 如果没找到,尝试用正则表达式匹配时间戳格式
                    if (!group.has_timestamp) {
                        const allText = msgEl.textContent;
                        // 匹配 "Jan 22, 2026 10:41 PM" 或类似格式
                        const timePatterns = [
                            /[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2}\s+[AP]M/,  // Jan 22, 2026 10:41 PM
                            /\d{1,2}月\d{1,2}日\s+\d{1,2}:\d{2}/,  // 中文格式
                            /\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}/,  // 2026-01-22 10:41
                            /\d{1,2}:\d{2}\s+[AP]M/  // 10:41 PM (简短格式)
                        ];
                        
                        for (const pattern of timePatterns) {
                            const match = allText.match(pattern);
                            if (match) {
                                group.timestamp = match[0];
                                group.has_timestamp = true;
                                break;
                            }
                        }
                    }
                    
                    // 检查是否有引用/回复
                    // Whop可能使用 peer/reply 等类名
                    const quoteSelectors = [
                        '[class*="peer/reply"]',       // Whop引用样式
                        '[class*="reply"]',
                        '[class*="quote"]',
                        '[class*="reference"]',
                        '[class*="mention"]',
                        '[class*="border-t"]'          // 引用可能有特殊边框
                    ];
                    
                    for (const selector of quoteSelectors) {
                        const quoteEl = msgEl.querySelector(selector);
                        if (quoteEl) {
                            let quoteText = quoteEl.textContent.trim();
                            // 清理结尾标记
                            quoteText = quoteText.replace(/Tail$/g, '').trim();
                            // 只有文本长度合理时才认为是引用
                            if (quoteText.length > 5 && quoteText.length < 500) {
                                group.quoted_message = quoteText.substring(0, 200);
                                group.quoted_context = quoteText;
                                break;
                            }
                        }
                    }
                    
                    // 提取消息内容
                    // Whop页面使用特定的消息气泡样式
                    const contentSelectors = [
                        '[class*="bg-gray-3"][class*="rounded"]',  // Whop消息气泡
                        '[class*="whitespace-pre-wrap"]',          // 消息文本容器
                        'p',                                        // 段落标签
                        '[class*="prose"]',                        // 通用内容类
                        '[class*="content"]',
                        '[class*="body"]',
                        '[class*="text"]'
                    ];
                    
                    // 尝试找到所有的消息气泡/段落
                    let contentElements = [];
                    for (const selector of contentSelectors) {
                        const elements = msgEl.querySelectorAll(selector);
                        if (elements.length > 0) {
                            contentElements = Array.from(elements);
                            break;
                        }
                    }
                    
                    if (contentElements.length > 0) {
                        // 提取所有段落的文本内容
                        const texts = [];
                        for (const el of contentElements) {
                            // 跳过头像相关元素
                            if (el.closest('[class*="fui-Avatar"]') || 
                                el.closest('[class*="avatar"]') ||
                                el.classList.contains('hidden') ||
                                window.getComputedStyle(el).display === 'none') {
                                continue;
                            }
                            
                            let text = el.innerText.trim();
                            // 清理结尾标记
                            text = text.replace(/Tail$/g, '').trim();
                            // 过滤掉元数据(作者、时间、符号等)
                            if (text && 
                                text.length > 1 && 
                                text !== '•' &&
                                text !== 'Tail' &&  // 排除Tail标记
                                text !== 'X' &&     // 排除头像fallback
                                text !== 'Edited' &&  // 排除编辑标记
                                text !== 'Reply' &&   // 排除回复标记
                                text !== '编辑' &&
                                text !== '回复' &&
                                text !== '删除' &&
                                text !== group.author &&
                                text !== group.timestamp &&
                                !text.match(/^[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}/) &&  // 不是日期
                                !text.match(/^\d{1,2}:\d{2}\s+[AP]M$/) &&  // 不是时间
                                !text.match(/^•.*\d{1,2}:\d{2}\s+[AP]M$/) &&  // 不是 "•Wednesday 11:04 PM" 或类似格式
                                !text.match(/^[•·]\s*[A-Z]/) &&  // 不是以 "•" 或 "·" 开头的元数据
                                !text.match(/^由\s*\d+\s*阅读$/) &&  // 不是阅读量 "由 223阅读"
                                !text.match(/^\d+\s*阅读$/) &&  // 不是阅读量 "223阅读"
                                !text.match(/^已编辑$/)) {  // 不是编辑标记
                                texts.push(text);
                            }
                        }
                        
                        // 去重(同一段文本可能被多个选择器匹配到)
                        const uniqueTexts = [...new Set(texts)];
                        
                        if (uniqueTexts.length > 0) {
                            group.primary_message = uniqueTexts[0];
                            group.related_messages = uniqueTexts.slice(1);
                        }
                    } else {
                        // 备用方案:从整个消息元素提取
                        // 先克隆元素，移除头像相关的子元素
                        const clonedEl = msgEl.cloneNode(true);
                        const avatarEls = clonedEl.querySelectorAll('[class*="fui-Avatar"], [class*="avatar"], .hidden');
                        avatarEls.forEach(el => el.remove());
                        
                        const fullText = clonedEl.innerText.trim();
                        const lines = fullText.split('\\n')
                            .map(line => line.trim())
                            .map(line => line.replace(/Tail$/g, '').trim())  // 清理结尾标记
                            .filter(line => {
                                // 过滤掉元数据行
                                return line.length > 1 && 
                                       line !== '•' &&
                                       line !== 'Tail' &&  // 排除Tail标记
                                       line !== 'X' &&     // 排除头像fallback
                                       line !== 'Edited' &&
                                       line !== 'Reply' &&
                                       line !== '编辑' &&
                                       line !== '回复' &&
                                       line !== '删除' &&
                                       line !== group.author &&
                                       line !== group.timestamp &&
                                       !line.match(/^[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}/) &&
                                       !line.match(/^\d{1,2}:\d{2}\s+[AP]M$/) &&
                                       !line.match(/^•.*\d{1,2}:\d{2}\s+[AP]M$/) &&  // 不是 "•Wednesday 11:04 PM" 或类似格式
                                       !line.match(/^[•·]\s*[A-Z]/) &&  // 不是以 "•" 或 "·" 开头的元数据
                                       !line.match(/^由\s*\d+\s*阅读$/) &&  // 不是阅读量
                                       !line.match(/^\d+\s*阅读$/) &&  // 不是阅读量
                                       !line.match(/^已编辑$/);  // 不是编辑标记
                            });
                        
                        // 去重
                        const uniqueLines = [...new Set(lines)];
                        
                        if (uniqueLines.length > 0) {
                            group.primary_message = uniqueLines[0];
                            group.related_messages = uniqueLines.slice(1);
                        }
                    }
                    
                    // 检查是否包含附件（图片/文件）
                    const hasAttachment = msgEl.querySelector('[data-attachment-id]') || 
                                         msgEl.querySelector('img[src*="whop.com"]') ||
                                         msgEl.querySelector('[class*="attachment"]');
                    
                    // 检查是否只有阅读量信息
                    const isOnlyReadCount = group.primary_message && 
                                           group.primary_message.match(/^(由\s*)?\d+\s*阅读$/);
                    
                    // 如果只有附件和阅读量，没有实质内容，则跳过
                    const isImageOnlyMessage = hasAttachment && 
                                              (isOnlyReadCount || !group.primary_message || group.primary_message.length < 10);
                    
                    // 过滤纯元数据的消息组
                    const weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
                    const isPureMetadata = group.primary_message && 
                                          group.primary_message.length < 30 &&
                                          weekdays.some(day => group.primary_message.includes(day)) &&
                                          (group.primary_message.includes('PM') || group.primary_message.includes('AM'));
                    
                    // 只添加有实际内容的消息组（排除纯元数据和纯图片消息）
                    if (!isPureMetadata && !isImageOnlyMessage && (group.primary_message || group.related_messages.length > 0)) {
                        messageGroups.push(group);
                    }
                    
                } catch (err) {
                    console.error('提取消息失败:', err);
                }
            }
            
            return messageGroups;
        }
        """
        
        try:
            raw_groups = await self.page.evaluate(js_code)
            
            # 转换为 MessageGroup 对象
            message_groups = []
            last_timestamp_group = None  # 记录最后一个有时间戳的消息组
            
            for raw in raw_groups:
                group = MessageGroup(
                    group_id=raw['group_id'],
                    author=raw['author'],
                    timestamp=raw['timestamp'],
                    primary_message=raw['primary_message'],
                    related_messages=raw['related_messages'],
                    quoted_message=raw['quoted_message'],
                    quoted_context=raw['quoted_context'],
                    has_message_above=raw.get('has_message_above', False),
                    has_message_below=raw.get('has_message_below', False)
                )
                
                # 如果消息有上一条相关消息（has_message_above=true），继承上一条消息的作者和时间戳
                if group.has_message_above and last_timestamp_group:
                    if not group.author:
                        group.author = last_timestamp_group.author
                    if not group.timestamp:
                        group.timestamp = last_timestamp_group.timestamp
                # 否则，如果消息没有时间戳，尝试继承上一个有时间戳的消息的信息
                elif not group.timestamp and last_timestamp_group:
                    group.timestamp = last_timestamp_group.timestamp
                    if not group.author:
                        group.author = last_timestamp_group.author
                
                # 更新最后一个有时间戳的消息组
                if raw.get('has_timestamp') or group.timestamp:
                    last_timestamp_group = group
                
                message_groups.append(group)
            
            return message_groups
            
        except Exception as e:
            print(f"提取消息组失败: {e}")
            return []
    
    async def extract_with_context(self) -> List[Dict]:
        """
        提取消息并保留完整上下文
        
        Returns:
            消息列表，每条消息包含完整上下文
        """
        groups = await self.extract_message_groups()
        
        messages = []
        for group in groups:
            # 生成唯一ID
            content_hash = hashlib.md5(
                group.get_full_content().encode()
            ).hexdigest()[:12]
            
            msg = {
                'id': f"{group.group_id}-{content_hash}",
                'text': group.get_full_content(),
                'author': group.author,
                'timestamp': group.timestamp,
                'primary_message': group.primary_message,
                'has_quote': bool(group.quoted_context),
                'message_count': len(group.related_messages) + 1,
                'group': group.to_dict()
            }
            
            messages.append(msg)
        
        return messages


async def test_extractor(page: Page):
    """测试消息提取器"""
    extractor = EnhancedMessageExtractor(page)
    
    print("=" * 60)
    print("测试增强的消息提取器")
    print("=" * 60)
    
    groups = await extractor.extract_message_groups()
    
    print(f"\n提取到 {len(groups)} 个消息组:\n")
    
    for i, group in enumerate(groups, 1):
        print(f"{i}. {group}")
        print(f"   作者: {group.author}")
        print(f"   时间: {group.timestamp}")
        print(f"   主消息: {group.primary_message[:50]}...")
        print(f"   关联消息数: {len(group.related_messages)}")
        if group.quoted_context:
            print(f"   引用内容: {group.quoted_context[:50]}...")
        print(f"   完整内容预览:")
        print(f"   {group.get_full_content()[:100]}...")
        print()
