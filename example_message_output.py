#!/usr/bin/env python3
"""
示例：展示优化后的消息输出格式
"""
from scraper.message_extractor import MessageGroup
import json

# 模拟几条不同类型的消息

# 示例1：单条消息
msg1 = MessageGroup(
    group_id="post_1CXNmCYpbYheKjRX4MLWLE",
    author="xiaozhaolucky",
    timestamp="Jan 23, 2026 12:51 AM",
    primary_message="nvda剩下部分也2.45附近出",
    has_message_above=False,
    has_message_below=False
)

# 示例2：消息组第一条（有引用）
msg2 = MessageGroup(
    group_id="post_1CXNbG1zAyv8MfM1oD7dEz",
    author="xiaozhaolucky",
    timestamp="Jan 22, 2026 10:41 PM",
    primary_message="小仓位 止损 在 1.3",
    quoted_context="GILD - $130 CALLS 这周 1.5-1.60",
    has_message_above=False,
    has_message_below=True,
    history=[]
)

# 示例3：消息组中间消息
msg3 = MessageGroup(
    group_id="post_1CXNbKK8oK74QriUZv3rmK",
    author="xiaozhaolucky",
    timestamp="Jan 22, 2026 10:41 PM",  # 继承自第一条
    primary_message="1.9附近出三分之一",
    has_message_above=True,
    has_message_below=True,
    history=["小仓位 止损 在 1.3"]
)

# 示例4：消息组最后一条
msg4 = MessageGroup(
    group_id="post_1CXNbUMakmSCcQD2NCbgn4",
    author="xiaozhaolucky",
    timestamp="Jan 22, 2026 10:41 PM",  # 继承自第一条
    primary_message="剩下看转弯往下时候都出 止损上移到2.25",
    has_message_above=True,
    has_message_below=False,
    history=["小仓位 止损 在 1.3", "1.9附近出三分之一"]
)

print("=" * 80)
print("消息输出格式示例")
print("=" * 80 + "\n")

print("📋 简化格式 (to_simple_dict)：")
print("-" * 80)

messages = [msg1, msg2, msg3, msg4]
for i, msg in enumerate(messages, 1):
    simple = msg.to_simple_dict()
    print(f"\n消息 #{i}:")
    print(json.dumps(simple, ensure_ascii=False, indent=2))

print("\n" + "=" * 80)
print("📊 完整格式 (to_dict) - 示例：")
print("-" * 80)
print("\n消息 #2 (有引用的第一条消息):")
print(json.dumps(msg2.to_dict(), ensure_ascii=False, indent=2))

print("\n" + "=" * 80)
print("✨ 格式说明：")
print("-" * 80)
print("""
简化格式字段：
  - domID: DOM中的 data-message-id 属性值
  - content: 消息的主要内容
  - timestamp: 发送时间（从消息组第一条继承）
  - refer: 引用的消息内容（如果有引用，否则为 null）
  - position: 消息在组中的位置
    * "single" - 独立消息（单条消息）
    * "first" - 消息组的第一条（有完整头部）
    * "middle" - 消息组的中间消息（无头部，需继承）
    * "last" - 消息组的最后一条
  - history: 同消息组的历史消息列表（按时间顺序）
    * 第一条消息的 history 为 []
    * 中间/最后消息的 history 包含之前所有同组消息

完整格式包含所有原始字段，用于高级处理。
""")
print("=" * 80 + "\n")
