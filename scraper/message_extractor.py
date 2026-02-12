"""
增强的消息提取器
识别消息的关联关系、引用关系和上下文
"""
from typing import List
from playwright.async_api import Page
from models.message import MessageGroup

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
            
            // 基于真实DOM的选择器: <div class="group/message" data-message-id="...">
            const messageSelectors = [
                '.group\\/message[data-message-id]',  // 最精确: class和data属性都有
                '[data-message-id]',                  // 次优: 有唯一ID
                '.group\\/message',                   // Whop主要使用的类名
            ];
            
            // 辅助函数：提取指定消息元素的内容
            const extractMessageContent = (msgEl) => {
                const contentSelectors = [
                    '.bg-gray-3[class*="rounded"]',
                    '[class*="bg-gray-3"][class*="rounded"]',
                    '.whitespace-pre-wrap',
                    '[class*="whitespace-pre-wrap"]'
                ];
                
                const contentElements = msgEl.querySelectorAll(contentSelectors.join(', '));
                const texts = [];
                
                for (const el of contentElements) {
                    if (el.closest('.peer\\\\/reply, [class*="peer/reply"]')) continue;
                    if (el.closest('[class*="fui-Avatar"]') || el.closest('[class*="avatar"]')) continue;
                    if (el.classList.contains('hidden') || window.getComputedStyle(el).display === 'none') continue;
                    if (el.classList.contains('text-gray-11') && el.classList.contains('text-0')) continue;
                    
                    let text = el.innerText.trim();
                    text = text.replace(/Tail$/g, '').trim();
                    text = text.replace(/\s+/g, ' ');
                    
                    // 简单过滤（允许2个字符以上的内容，如"都出"）
                    if (text && text.length >= 2 && !text.match(/^\d+阅读$/) && !text.match(/^已编辑$/)) {
                        texts.push(text);
                    }
                }
                
                const uniqueTexts = [...new Set(texts)];
                return uniqueTexts[0] || '';
            };
            
            // 辅助函数：获取同消息组的历史消息和引用信息
            const getGroupHistory = (currentMsgEl) => {
                const history = [];
                let groupQuotedContext = '';
                let prevEl = currentMsgEl.previousElementSibling;
                let count = 0;
                let firstMsgEl = null;
                
                // 向上遍历，找到同组的所有前序消息
                while (prevEl && count < 50) {  // 限制最多查找50条，防止死循环
                    count++;
                    
                    // 跳过分隔符等非消息元素
                    if (!prevEl.getAttribute || !prevEl.getAttribute('data-message-id')) {
                        prevEl = prevEl.previousElementSibling;
                        continue;
                    }
                    
                    const hasAbove = prevEl.getAttribute('data-has-message-above');
                    
                    // 提取消息内容
                    const content = extractMessageContent(prevEl);
                    if (content) {
                        history.unshift(content);  // 添加到数组前面，保持顺序
                    }
                    
                    // 如果这条消息的 has_message_above 为 false，说明是消息组的第一条
                    if (hasAbove === 'false') {
                        firstMsgEl = prevEl;
                        break;
                    }
                    
                    prevEl = prevEl.previousElementSibling;
                }
                
                // 如果找到了消息组的第一条消息，提取其引用信息
                if (firstMsgEl) {
                    const quoteEl = firstMsgEl.querySelector('.peer\\\\/reply, [class*="peer/reply"]');
                    if (quoteEl) {
                        let quoteText = '';
                        
                        // 找到所有符合条件的 span
                        const quoteSpans = quoteEl.querySelectorAll('[class*="fui-Text"][class*="truncate"][class*="fui-r-size-1"]');
                        
                        if (quoteSpans.length > 0) {
                            // 过滤掉包含 fui-r-weight-medium 的 span（作者名）
                            const contentSpans = Array.from(quoteSpans).filter(span => 
                                !span.className.includes('fui-r-weight-medium')
                            );
                            
                            if (contentSpans.length > 0) {
                                quoteText = contentSpans[0].textContent.trim();
                            } else if (quoteSpans.length > 1) {
                                quoteText = quoteSpans[quoteSpans.length - 1].textContent.trim();
                            }
                        }
                        
                        if (!quoteText) {
                            quoteText = quoteEl.textContent.trim();
                        }
                        
                        // 清理
                        quoteText = quoteText.replace(/Tail$/g, '').trim();
                        quoteText = quoteText.replace(/\s+/g, ' ');
                        quoteText = quoteText.replace(/^X\s*/, '');
                        quoteText = quoteText.replace(/^xiaozhaolucky\s*/i, '');
                        
                        if (quoteText.length > 5 && quoteText.length < 500) {
                            groupQuotedContext = quoteText;
                        }
                    }
                }
                
                return {
                    history: history,
                    quoted_context: groupQuotedContext
                };
            };
            
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
                    // 基于真实DOM: <span role="button" class="truncate cursor-pointer hover:underline fui-HoverCardTrigger">
                    const authorSelectors = [
                        'span[role="button"].truncate.fui-HoverCardTrigger',  // 真实DOM中的用户名
                        'span[role="button"][class*="truncate"]',
                        '[class*="fui-Text"][class*="truncate"]',
                    ];
                    
                    // 尝试从精确选择器提取
                    for (const selector of authorSelectors) {
                        const authorEl = msgEl.querySelector(selector);
                        if (authorEl) {
                            const text = authorEl.textContent.trim();
                            
                            // 简化过滤逻辑 - 基于MessageFilter规则
                            if (text && 
                                text.length > 0 && 
                                text.length < 50 &&
                                text !== 'Tail' &&
                                !text.includes('PM') && 
                                !text.includes('AM') && 
                                !/\d/.test(text) &&  // 不包含数字
                                !text.includes('•') &&
                                !text.includes('$')) {
                                group.author = text;
                                break;
                            }
                        }
                    }
                    
                    // 提取时间戳
                    // 基于真实DOM: <span>•</span><span>Jan 23, 2026 12:51 AM</span>
                    // 或相对时间: <span>Yesterday at 11:51 PM</span>, <span>Wednesday 10:45 PM</span>, <span>Today 10:45 PM</span>
                    // 在包含"•"的父元素中查找时间戳
                    const timestampContainer = msgEl.querySelector('.inline-flex.items-center.gap-1');
                    if (timestampContainer) {
                        // 查找包含时间格式的span
                        const spans = timestampContainer.querySelectorAll('span');
                        for (const span of spans) {
                            const text = span.textContent.trim();
                            // 匹配绝对时间戳格式 "Jan 23, 2026 12:51 AM"
                            if (/[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2}\s+[AP]M/.test(text)) {
                                group.timestamp = text;
                                group.has_timestamp = true;
                                break;
                            }
                            // 匹配相对时间格式 "Yesterday at 11:51 PM", "Today 10:45 PM", "Wednesday 10:45 PM"
                            if (/^(Yesterday at|Today|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+(\d{1,2}:\d{2}\s+[AP]M|at\s+\d{1,2}:\d{2}\s+[AP]M)$/i.test(text)) {
                                group.timestamp = text;
                                group.has_timestamp = true;
                                break;
                            }
                            // 仅时间、无日期无星期（如 "10:49 PM"），后端会解析为今天
                            if (/^\d{1,2}:\d{2}\s+[AP]M$/i.test(text)) {
                                group.timestamp = text;
                                group.has_timestamp = true;
                                break;
                            }
                        }
                    }
                    
                    // 备用方案：从整个元素文本中匹配
                    if (!group.has_timestamp) {
                        const allText = msgEl.textContent;
                        const timePatterns = [
                            /[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2}\s+[AP]M/,  // Jan 22, 2026 10:41 PM
                            /(Yesterday at|Today|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+(\d{1,2}:\d{2}\s+[AP]M|at\s+\d{1,2}:\d{2}\s+[AP]M)/i,  // 相对时间
                            /\d{1,2}:\d{2}\s+[AP]M/i,  // 仅时间如 "10:49 PM"（子串），表示今天
                            /\d{1,2}月\d{1,2}日\s+\d{1,2}:\d{2}/,  // 中文格式
                            /\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}/,  // ISO格式
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
                    // DOM特征: 引用在 class*="peer/reply" 的 div 下
                    //          引用文本在 class*="fui-Text truncate fui-r-size-1" 的 span 中（不包含 fui-r-weight-medium）
                    const quoteEl = msgEl.querySelector('.peer\\\\/reply, [class*="peer/reply"]');
                    if (quoteEl) {
                        let quoteText = '';
                        
                        // 找到所有符合条件的 span：class 包含 "fui-Text truncate fui-r-size-1"
                        const quoteSpans = quoteEl.querySelectorAll('[class*="fui-Text"][class*="truncate"][class*="fui-r-size-1"]');
                        
                        if (quoteSpans.length > 0) {
                            // 过滤掉包含 fui-r-weight-medium 的 span（作者名）
                            const contentSpans = Array.from(quoteSpans).filter(span => 
                                !span.className.includes('fui-r-weight-medium')
                            );
                            
                            if (contentSpans.length > 0) {
                                // 取第一个不是作者名的 span 作为引用内容
                                quoteText = contentSpans[0].textContent.trim();
                            } else if (quoteSpans.length > 1) {
                                // 如果没有找到，尝试取最后一个 span（通常作者名在前，内容在后）
                                quoteText = quoteSpans[quoteSpans.length - 1].textContent.trim();
                            }
                        }
                        
                        // 如果上述方法都失败，使用备用方案
                        if (!quoteText) {
                            quoteText = quoteEl.textContent.trim();
                        }
                        
                        // 清理结尾标记和多余空格
                        quoteText = quoteText.replace(/Tail$/g, '').trim();
                        quoteText = quoteText.replace(/\s+/g, ' ');
                        
                        // 过滤掉头像fallback "X"
                        quoteText = quoteText.replace(/^X\s*/, '');
                        
                        // 过滤掉作者名（如果文本以作者名开头）
                        quoteText = quoteText.replace(/^xiaozhaolucky\s*/i, '');
                        
                        // 只有文本长度合理时才认为是引用
                        if (quoteText.length > 5 && quoteText.length < 500) {
                            group.quoted_message = quoteText.substring(0, 200);
                            group.quoted_context = quoteText;
                        }
                    }
                    
                    // 提取消息内容
                    // 基于真实DOM: <div class="bg-gray-3 rounded-[18px] px-3 py-1.5">
                    //   <div class="text-[15px] whitespace-pre-wrap"><p>消息内容<br></p></div>
                    // </div>
                    const contentSelectors = [
                        '.bg-gray-3[class*="rounded"]',            // 最精确：消息气泡
                        '[class*="whitespace-pre-wrap"]',          // 消息文本容器
                        'p',                                        // 段落标签（在气泡内）
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
                    
                    // 过滤元数据的辅助函数
                    const shouldFilterText = (text) => {
                        if (!text || text.length < 2) return true;
                        
                        // 固定排除文本
                        const excludeTexts = ['•', 'Tail', 'X', 'Edited', 'Reply', '编辑', '回复', '删除'];
                        if (excludeTexts.includes(text)) return true;
                        
                        // 元数据模式
                        if (/^(由\s*)?\d+\s*阅读$/.test(text)) return true;  // 阅读量
                        if (/^(已编辑|Edited)$/.test(text)) return true;
                        if (/^•.*\d{1,2}:\d{2}\s+[AP]M$/.test(text)) return true;  // 时间戳行
                        if (/^[•·]\s*[A-Z]/.test(text)) return true;  // 以 "•" 开头的元数据
                        if (/^[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}/.test(text)) return true;  // 日期
                        if (/^\d{1,2}:\d{2}\s+[AP]M$/.test(text)) return true;  // 时间
                        
                        // 纯时间戳消息
                        const weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
                        const hasWeekday = weekdays.some(day => text.includes(day));
                        const hasTime = text.includes('PM') || text.includes('AM');
                        if (hasWeekday && hasTime && text.length < 30) return true;
                        
                        return false;
                    };
                    
                    if (contentElements.length > 0) {
                        // 提取所有消息气泡的文本内容
                        const texts = [];
                        for (const el of contentElements) {
                            // 跳过引用区域（引用有自己的处理逻辑）
                            if (el.closest('.peer\\\\/reply, [class*="peer/reply"]')) {
                                continue;
                            }
                            
                            // 跳过头像和隐藏元素
                            if (el.closest('[class*="fui-Avatar"]') || 
                                el.closest('[class*="avatar"]') ||
                                el.classList.contains('hidden') ||
                                window.getComputedStyle(el).display === 'none') {
                                continue;
                            }
                            
                            // 跳过阅读量元素（真实DOM: <span class="text-gray-11 text-0 h-[15px]">）
                            if (el.classList.contains('text-gray-11') && 
                                el.classList.contains('text-0')) {
                                continue;
                            }
                            
                            let text = el.innerText.trim();
                            // 清理结尾标记和多余空格
                            text = text.replace(/Tail$/g, '').trim();
                            text = text.replace(/\s+/g, ' ');
                            
                            // 使用过滤函数
                            if (!shouldFilterText(text) && 
                                text !== group.author &&
                                text !== group.timestamp) {
                                texts.push(text);
                            }
                        }
                        
                        // 去重
                        const uniqueTexts = [...new Set(texts)];
                        
                        if (uniqueTexts.length > 0) {
                            group.primary_message = uniqueTexts[0];
                            group.related_messages = uniqueTexts.slice(1);
                        }
                    }
                    
                    // 检查是否包含附件（图片/文件）
                    const hasAttachment = msgEl.querySelector('[data-attachment-id]') || 
                                         msgEl.querySelector('img[src*="whop.com"]') ||
                                         msgEl.querySelector('[class*="attachment"]');
                    group.has_attachment = !!hasAttachment;
                    
                    // 提取图片URL（如果有）
                    if (hasAttachment) {
                        const imgEl = msgEl.querySelector('img[src*="whop.com"]');
                        if (imgEl) {
                            group.image_url = imgEl.getAttribute('src');
                        }
                    }
                    
                    // 使用统一的过滤逻辑判断是否应该跳过
                    const shouldSkip = () => {
                        // 1. 没有任何内容
                        if (!group.primary_message && group.related_messages.length === 0) {
                            return '无内容';
                        }
                        
                        // 2. 纯图片消息（只有图片+阅读量，没有实质内容）
                        if (hasAttachment) {
                            const isOnlyReadCount = group.primary_message && 
                                                   /^(由\s*)?\d+\s*阅读$/.test(group.primary_message);
                            // 只有当真的没有内容，或者只有阅读量时才跳过
                            const hasNoContent = !group.primary_message || group.primary_message.trim().length === 0;
                            if (isOnlyReadCount || (hasNoContent && group.related_messages.length === 0)) {
                                return '纯图片消息';
                            }
                        }
                        
                        // 3. 纯元数据消息（使用shouldFilterText检查）
                        if (group.primary_message && shouldFilterText(group.primary_message)) {
                            return '元数据消息';
                        }
                        
                        return false;
                    };
                    
                    // 提取历史消息和消息组引用（仅当有上级消息时）
                    if (group.has_message_above) {
                        const groupInfo = getGroupHistory(msgEl);
                        group.history = groupInfo.history;
                        // 如果消息组有引用，非首条消息应该继承这个引用
                        if (groupInfo.quoted_context && !group.quoted_context) {
                            group.quoted_context = groupInfo.quoted_context;
                            group.quoted_message = groupInfo.quoted_context.substring(0, 200);
                        }
                    } else {
                        group.history = [];
                    }
                    
                    // 只添加有实际内容的消息组
                    if (!shouldSkip()) {
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
            
            # 转换为 MessageGroup 对象并处理时间戳继承
            message_groups = []
            last_timestamp_group = None  # 记录最后一个有时间戳的消息组（用于继承）
            current_group_header = None  # 记录当前消息组的头部信息（用于DOM层级继承）
            current_group_base_timestamp = None  # 记录当前消息组的基础时间戳
            timestamp_counter = {}  # 记录每个基础时间戳的消息计数 {base_timestamp: count}
            
            for raw in raw_groups:
                # 确定基础时间戳（原始时间戳，不含毫秒）
                base_timestamp = raw['timestamp']
                
                # 基于DOM层级关系处理时间戳继承
                # has_message_above=true 表示与上一条消息在同一个消息组内
                if raw.get('has_message_above', False) and current_group_base_timestamp:
                    # 同组消息：继承组头部的基础时间戳
                    if not base_timestamp:
                        base_timestamp = current_group_base_timestamp
                else:
                    # 新消息组开始
                    if base_timestamp:
                        current_group_base_timestamp = base_timestamp
                    elif last_timestamp_group:
                        # 备用方案：继承最近的有时间戳的消息
                        base_timestamp = current_group_base_timestamp or raw['timestamp']
                
                # 初始化或获取该时间戳的计数
                if base_timestamp not in timestamp_counter:
                    timestamp_counter[base_timestamp] = 0
                
                # 计算毫秒数（每条消息加10ms）
                milliseconds = timestamp_counter[base_timestamp] * 10
                timestamp_counter[base_timestamp] += 1
                
                # 标准化时间戳格式（包含毫秒）
                normalized_timestamp = MessageGroup.normalize_timestamp(base_timestamp, milliseconds)
                
                group = MessageGroup(
                    group_id=raw['group_id'],
                    author=raw['author'],
                    timestamp=normalized_timestamp,
                    primary_message=raw['primary_message'],
                    related_messages=raw['related_messages'],
                    quoted_message=raw['quoted_message'],
                    quoted_context=raw['quoted_context'],
                    has_message_above=raw.get('has_message_above', False),
                    has_message_below=raw.get('has_message_below', False),
                    has_attachment=raw.get('has_attachment', False),
                    image_url=raw.get('image_url', ''),
                    history=raw.get('history', [])
                )
                
                # 基于DOM层级关系的作者继承
                if group.has_message_above and current_group_header:
                    # 继承消息组头部的作者信息
                    if not group.author:
                        group.author = current_group_header.author
                else:
                    # 新消息组开始
                    if raw.get('has_timestamp') or group.timestamp:
                        current_group_header = group
                    elif last_timestamp_group:
                        if not group.author:
                            group.author = last_timestamp_group.author
                
                # 更新最后一个有时间戳的消息组（用于跨组继承）
                if raw.get('has_timestamp') or group.timestamp:
                    last_timestamp_group = group
                
                message_groups.append(group)
            
            return message_groups
            
        except Exception as e:
            err_msg = str(e)
            # 浏览器/页面已关闭，无法恢复，向上层传播以终止程序
            if "Target page, context or browser has been closed" in err_msg or "Target closed" in err_msg:
                raise
            print(f"提取消息组失败: {e}")
            return []