"""
消息组模型：单条消息及其关联上下文
"""
from typing import List, Dict
from rich.console import Console
from rich.table import Table
from rich import box
from datetime import datetime

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
        has_message_below: bool = False,
        has_attachment: bool = False,
        image_url: str = "",
        history: List[str] = None,
    ):
        """
        Args:
            group_id: 消息组ID (DOM: data-message-id)
            author: 作者
            timestamp: 时间戳 (从消息组第一条获取)
            primary_message: 主消息内容
            related_messages: 关联的后续消息列表
            quoted_message: 引用的消息标题/预览
            quoted_context: 引用的完整上下文 (refer)
            has_message_above: 是否有上一条相关消息（DOM层级关系）
            has_message_below: 是否有下一条相关消息（DOM层级关系）
            has_attachment: 是否包含附件（图片等）
            image_url: 图片URL（如果有）
            history: 同消息组的历史消息列表（按时间顺序，不包含当前消息）
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
        self.has_attachment = has_attachment
        self.image_url = image_url
        self.history = history or []

    def get_position(self) -> str:
        """
        获取消息在消息组中的位置

        Returns:
            "single" | "first" | "middle" | "last"
        """
        if not self.has_message_above and not self.has_message_below:
            return "single"
        elif not self.has_message_above and self.has_message_below:
            return "first"
        elif self.has_message_above and self.has_message_below:
            return "middle"
        else:  # has_message_above and not has_message_below
            return "last"

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
        """
        转换为简化格式的字典（scraper层唯一输出格式）

        格式：
        {
            'domID': 'post_xxx',
            'content': '主消息',
            'timestamp': '2026-02-04 22:35:00.020',
            'refer': '引用的消息内容（如果有）',
            'position': 'first',
            'history': ['第一条消息内容', '第二条消息内容']
        }

        注意：
        - content 原始消息
        - refer 是引用消息的副本，用于快速访问
        - history 是同组历史消息，用于上下文理解
        """
        return {
            "domID": self.group_id,
            "content": self.primary_message,
            "timestamp": self.timestamp,
            "refer": self.quoted_context if self.quoted_context else None,
            "position": self.get_position(),
            "history": self.history,
        }

    def display(self):
        """
        使用 Rich Table 按文档格式展示单条提取的消息。
        """
        
        msg = self.to_dict()
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
        now = datetime.now()
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
        return f"MessageGroup(author={self.author}, messages={len(self.related_messages)+1})"

    def __repr__(self):
        return f"MessageGroup(author={self.author}, messages={len(self.related_messages)+1})"


    @staticmethod
    def normalize_timestamp(timestamp: str, milliseconds: int = 0) -> str:
        """
        将各种格式的时间戳转换为标准格式 YYYY-MM-DD HH:MM:SS.XXX
        
        Args:
            timestamp: 原始时间戳，支持以下格式：
                - "Jan 23, 2026 12:51 AM"
                - "1月23日 12:51"
                - "2026-01-23 12:51"
                - "Yesterday at 11:51 PM"
                - "Today 10:45 PM"
                - "Wednesday 10:45 PM"
            milliseconds: 毫秒数 (0-999)
        
        Returns:
            标准格式的时间戳 "YYYY-MM-DD HH:MM:SS.XXX"，例如 "2026-01-23 12:51:00.000"
            如果解析失败，返回原始时间戳
        """
        if not timestamp:
            return ""
        
        try:
            from datetime import timedelta
            
            # 尝试解析英文格式: "Jan 23, 2026 12:51 AM"
            if re.match(r'[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2}\s+[AP]M', timestamp):
                dt = datetime.strptime(timestamp, "%b %d, %Y %I:%M %p")
                return f"{dt.strftime('%Y-%m-%d %H:%M:%S')}.{milliseconds:03d}"
            
            # 尝试解析相对时间格式: "Yesterday at 11:51 PM", "Today 10:45 PM", "Wednesday 10:45 PM"
            relative_match = re.match(r'^(Yesterday at|Today|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+(\d{1,2}:\d{2}\s+[AP]M|at\s+\d{1,2}:\d{2}\s+[AP]M)$', timestamp, re.IGNORECASE)
            if relative_match:
                day_part = relative_match.group(1).strip()
                time_part = relative_match.group(2).strip()
                
                # 提取时间（去掉可能的"at"）
                time_str = time_part.replace('at ', '').strip()
                time_obj = datetime.strptime(time_str, "%I:%M %p")
                
                now = datetime.now()
                
                # 计算日期
                if day_part.lower() == 'yesterday at':
                    target_date = now.date() - timedelta(days=1)
                elif day_part.lower() == 'today':
                    target_date = now.date()
                else:
                    # 星期几的情况：Monday, Tuesday, ...
                    weekday_map = {
                        'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
                        'friday': 4, 'saturday': 5, 'sunday': 6
                    }
                    target_weekday = weekday_map.get(day_part.lower())
                    if target_weekday is not None:
                        current_weekday = now.weekday()
                        # 计算距离该星期几的天数（向前查找，最多7天）
                        days_back = (current_weekday - target_weekday) % 7
                        if days_back == 0:
                            # 如果是今天，检查时间是否已过，如果已过则取上周同一天
                            days_back = 7 if time_obj.time() > now.time() else 0
                        target_date = now.date() - timedelta(days=days_back)
                    else:
                        return timestamp  # 无法识别的星期
                
                # 组合日期和时间
                dt = datetime.combine(target_date, time_obj.time())
                return f"{dt.strftime('%Y-%m-%d %H:%M:%S')}.{milliseconds:03d}"
            
            # 尝试解析中文格式: "1月23日 12:51"
            if re.match(r'\d{1,2}月\d{1,2}日\s+\d{1,2}:\d{2}', timestamp):
                # 假设是当前年份
                current_year = datetime.now().year
                month_day = re.match(r'(\d{1,2})月(\d{1,2})日\s+(\d{1,2}):(\d{2})', timestamp)
                if month_day:
                    month, day, hour, minute = month_day.groups()
                    dt = datetime(current_year, int(month), int(day), int(hour), int(minute))
                    return f"{dt.strftime('%Y-%m-%d %H:%M:%S')}.{milliseconds:03d}"
            
            # 尝试解析 ISO 格式: "2026-01-23 12:51"
            if re.match(r'\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}', timestamp):
                dt = datetime.strptime(timestamp, "%Y-%m-%d %H:%M")
                return f"{dt.strftime('%Y-%m-%d %H:%M:%S')}.{milliseconds:03d}"
            
            # 如果都不匹配，返回原始时间戳
            return timestamp
            
        except Exception as e:
            # 解析失败，返回原始时间戳
            print(f"⚠️ 时间戳解析失败: {timestamp}, 错误: {e}")
            return timestamp
