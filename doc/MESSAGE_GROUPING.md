# 消息分组与关联识别指南

## 📖 概述

本文档详细说明了如何使用消息分组器（MessageGrouper）将相关的交易消息聚合成交易组，识别买入-卖出的关联关系，并以表格形式展示。

## 🎯 问题场景

### 原始问题

在实际交易中，一笔完整的交易通常包含多条消息：

```
10:41 PM - xiaozhaolucky: GILD - $130 CALLS 这周 1.5-1.60
10:42 PM - xiaozhaolucky: 小仓位 止损 在 1.3
10:45 PM - xiaozhaolucky: 1.9附近出三分之一
10:50 PM - xiaozhaolucky: 2.23出三分之一
10:55 PM - xiaozhaolucky: 2.3附近都出
```

**期望：**
- 识别这5条消息属于同一笔交易（GILD $130 CALLS）
- 第1条是买入信号
- 第2条是止损设置
- 第3-5条是分批卖出

**v2.6.4的问题：**
- 每条消息被独立提取
- 看不出消息之间的关联
- 卖出消息不知道对应哪笔买入

## 🔧 解决方案

### 架构设计

```
原始消息 → EnhancedMessageExtractor
    ↓
提取的消息列表
    ↓
MessageGrouper → 分析关联关系
    ↓
交易消息组列表
    ↓
表格格式展示
```

### 核心组件

**1. TradeMessageGroup - 交易消息组**

```python
class TradeMessageGroup:
    group_id: str          # 消息组ID (如: GILD_a1b2c3d4)
    symbol: str            # 交易标的 (如: GILD)
    entry_message: Dict    # 买入消息
    exit_messages: List    # 卖出消息列表
    update_messages: List  # 更新消息列表
    raw_messages: List     # 所有原始消息
```

**2. MessageGrouper - 消息分组器**

```python
class MessageGrouper:
    def group_messages(messages: List[Dict]) -> List[TradeMessageGroup]:
        """将消息列表按交易组聚合"""
        
    def _extract_symbol(text: str) -> str:
        """从文本中提取交易标的"""
        
    def _classify_message(message: Dict) -> str:
        """分类消息类型: entry/exit/update"""
        
    def _generate_group_id(symbol, author, timestamp) -> str:
        """生成唯一的消息组ID"""
```

## 📊 工作流程

### 第一步：提取交易标的

**支持的格式：**

```python
# 格式1: $符号
"$GILD - 130 CALLS"  →  GILD

# 格式2: 标的-价格
"GILD - $130 CALLS"  →  GILD

# 格式3: 标的+期权类型
"NVDA call 本周"     →  NVDA
"TSLA put 2/20"      →  TSLA
```

**实现：**

```python
patterns = [
    r'\$([A-Z]{1,5})\b',           # $GILD
    r'\b([A-Z]{2,5})\s*-\s*\$',    # GILD - $130
    r'\b([A-Z]{2,5})\s+call',      # GILD call
    r'\b([A-Z]{2,5})\s+put',       # GILD put
]

for pattern in patterns:
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return match.group(1).upper()
```

### 第二步：分类消息类型

**分类规则：**

| 类型 | 关键词 | 示例 |
|------|--------|------|
| **买入** (entry) | call, put, calls, puts, 买入, buy | GILD - $130 CALLS 这周 1.5-1.60 |
| **卖出** (exit) | 出, 卖, sell, exit, 平仓 | 1.9附近出三分之一 |
| **更新** (update) | 止损, 上移, 调整, stop loss | 止损上移到2.0 |

**优先级：** 卖出 > 更新 > 买入

**为什么？**
```python
# 卖出消息可能包含 "call" 或 "put"
"goog call也都出了"  # 这是卖出，不是买入

# 因此优先判断卖出
if any(keyword in content for keyword in exit_keywords):
    return 'exit'  # 先判断卖出
```

### 第三步：生成消息组ID

**生成逻辑：**

```python
# 输入
symbol = "GILD"
author = "xiaozhaolucky"
timestamp = "Jan 22, 2026 10:41 PM"

# 提取日期（不包含时间）
date = "Jan 22, 2026"

# 生成key
key = f"{symbol}_{author}_{date}"
# "GILD_xiaozhaolucky_Jan 22, 2026"

# MD5哈希
hash = md5(key).hexdigest()[:8]
# "a1b2c3d4"

# 最终ID
group_id = f"{symbol}_{hash}"
# "GILD_a1b2c3d4"
```

**优势：**
- ✅ 同一天、同一人、同一标的的交易归为一组
- ✅ 短hash易于识别
- ✅ 包含symbol便于快速定位

### 第四步：关联识别

**匹配规则：**

```python
# 卖出消息匹配买入消息的条件：
1. 交易标的相同 (symbol == target_symbol)
2. 作者相同 (author == entry_author)
3. 日期相同 (date == entry_date)
4. [可选] 引用内容包含买入消息
```

**示例：**

```python
# 买入消息
entry = {
    'symbol': 'GILD',
    'author': 'xiaozhaolucky',
    'timestamp': 'Jan 22, 2026 10:41 PM',
    'content': 'GILD - $130 CALLS 这周 1.5-1.60'
}

# 卖出消息1
exit1 = {
    'symbol': None,  # 没有明确标的
    'author': 'xiaozhaolucky',
    'timestamp': 'Jan 22, 2026 10:45 PM',
    'content': '1.9附近出三分之一',
    'quoted_context': 'GILD - $130 CALLS...'  # 引用了买入消息
}

# 提取引用中的symbol
quoted_symbol = extract_symbol(exit1['quoted_context'])  # GILD

# 匹配条件
quoted_symbol == entry['symbol']  # ✅ GILD == GILD
exit1['author'] == entry['author']  # ✅ 相同作者
same_date(exit1['timestamp'], entry['timestamp'])  # ✅ 同一天

# 结论：exit1 属于 entry 的交易组
```

## 📋 表格展示

### 方式1：详细表格视图

**格式：**

```
消息组ID        标的     时间                 操作类型    消息内容                    关联买入
--------------------------------------------------------------------------------
GILD_a1b2c3d4   GILD     Jan 22 10:41        🟢 买入    GILD $130 CALLS 1.5-1.60   -
GILD_a1b2c3d4   GILD     Jan 22 10:45        🔴 卖出    1.9附近出三分之一          GILD $130 CALLS 1.5-1.60
GILD_a1b2c3d4   GILD     Jan 22 10:50        🔴 卖出    2.23出三分之一             GILD $130 CALLS 1.5-1.60
GILD_a1b2c3d4   GILD     Jan 22 10:55        🔴 卖出    2.3附近都出                GILD $130 CALLS 1.5-1.60
```

**特点：**
- ✅ 每行一条消息
- ✅ 卖出消息显示对应买入
- ✅ 类似数据库表格式
- ✅ 易于查询和过滤

**使用场景：**
- 需要快速查看所有操作
- 需要追踪特定交易的所有动作
- 需要导出为CSV/Excel

### 方式2：分组摘要视图

**格式：**

```
============================================================
【消息组 #1】
组ID: GILD_a1b2c3d4
交易标的: GILD
消息总数: 4
------------------------------------------------------------

📈 【买入信号】
   作者: xiaozhaolucky
   时间: Jan 22, 2026 10:41 PM
   内容: GILD - $130 CALLS 这周 1.5-1.60
   
📉 【卖出操作】 (3条)
   1. 1.9附近出三分之一
      时间: Jan 22, 2026 10:45 PM
      ⬅️ 对应买入: GILD - $130 CALLS 这周 1.5-1.60
      
   2. 2.23出三分之一
      时间: Jan 22, 2026 10:50 PM
      ⬅️ 对应买入: GILD - $130 CALLS 这周 1.5-1.60
      
   3. 2.3附近都出
      时间: Jan 22, 2026 10:55 PM
      ⬅️ 对应买入: GILD - $130 CALLS 这周 1.5-1.60

🔄 【止损/调整】无
------------------------------------------------------------
```

**特点：**
- ✅ 按交易组聚合
- ✅ 清晰的层级结构
- ✅ 统计信息一目了然
- ✅ 便于理解交易全貌

**使用场景：**
- 需要查看完整的交易流程
- 需要统计每笔交易的操作次数
- 需要分析交易策略

## 🚀 使用方法

### 命令行测试

```bash
# 运行消息提取器测试
python3 main.py --test message-extractor
```

**输出内容：**

```
1. ✅ 成功提取 X 条消息
2. ✅ 识别出 Y 个交易组

3. 【方式1】详细表格视图
   - 数据库表格式
   - 每行一条消息
   
4. 【方式2】分组摘要视图
   - 按交易组聚合
   - 显示买入-卖出关联
   
5. 【原始消息示例】（前5条）
   - 原始提取的消息
   - 用于验证提取准确性
```

### 代码集成

```python
from scraper.message_extractor import EnhancedMessageExtractor
from scraper.message_grouper import MessageGrouper, format_as_table

# 1. 提取消息
extractor = EnhancedMessageExtractor(page)
raw_groups = await extractor.extract_message_groups()

# 2. 转换为字典
messages = [
    {
        'content': group.get_full_content(),
        'author': group.author,
        'timestamp': group.timestamp,
        'quoted_context': group.quoted_context
    }
    for group in raw_groups
]

# 3. 分组
grouper = MessageGrouper()
trade_groups = grouper.group_messages(messages)

# 4. 展示
print(format_as_table(trade_groups))
```

## 🎯 高级场景

### 场景1：同一天多笔相同标的交易

**问题：**
```
10:00 AM - 买入 GILD $130 CALLS
11:00 AM - 卖出 GILD (第一笔)
02:00 PM - 买入 GILD $135 CALLS  # 第二笔
03:00 PM - 卖出 GILD (第二笔)
```

**解决：**
- 使用时间顺序：卖出消息关联最近的买入
- 使用价格差异：$130 和 $135 是不同的交易
- 使用引用关系：卖出消息引用特定的买入

### 场景2：部分卖出

**问题：**
```
买入 GILD $130 CALLS
出三分之一 @ 1.9
出三分之一 @ 2.23
剩余全出 @ 2.3
```

**处理：**
- 所有卖出都关联同一笔买入
- 在exit_messages列表中保留顺序
- 可统计：总共3次卖出操作

### 场景3：止损调整

**问题：**
```
买入 GILD $130 CALLS
止损设置 @ 1.3
止损上移 @ 1.5
止损上移 @ 2.0
```

**处理：**
- 归类为update_messages
- 按时间顺序排列
- 可追踪止损调整历史

### 场景4：缺少买入信息

**问题：**
```
# 没有看到买入消息
出三分之一 @ 1.9
```

**处理：**
- 创建独立的消息组
- entry_message为空
- 在表格中显示"无对应买入"

## 📝 最佳实践

### 1. 确保消息包含清晰的交易标的

**好的示例：**
```
✅ "GILD - $130 CALLS 这周 1.5-1.60"
✅ "$NVDA call 本周 2.5"
✅ "TSLA put 2/20 $200"
```

**不好的示例：**
```
❌ "130的call 1.5买"  # 没有标的
❌ "今天的那个 2.0出"  # 模糊引用
❌ "出了"  # 完全没有信息
```

### 2. 使用引用功能

**Whop页面：**
- 回复买入消息时，消息会自动引用
- 引用内容帮助系统识别关联

**示例：**
```
买入消息：GILD - $130 CALLS 1.5-1.60
回复卖出：1.9出三分之一
  ↓
系统自动添加引用：
  quoted_context: "GILD - $130 CALLS 1.5-1.60"
```

### 3. 保持消息的时间顺序

- 买入消息应该在卖出消息之前
- 卖出消息按时间排列
- 止损调整按时间排列

### 4. 统一命名规范

**标的代码：**
- 使用大写字母
- 长度2-5个字符
- 如：GILD, NVDA, TSLA, GOOGL

**价格格式：**
- 使用数字和小数点
- 如：1.5, 2.23, 130

## 🐛 故障排查

### Q: 卖出消息没有关联到买入？

A: 检查以下几点：
1. 标的代码是否一致（大小写）
2. 作者是否相同
3. 是否在同一天
4. 引用内容是否正确

### Q: 同一标的被分成多个组？

A: 可能的原因：
1. 时间跨天了（分为两组）
2. 引用了不同的买入消息
3. 标的代码不一致（如GOOG vs GOOGL）

### Q: 消息类型分类错误？

A: 检查关键词：
1. 是否使用了特殊词汇
2. 是否混合了多种操作
3. 调整分类关键词列表

### Q: 表格显示不完整？

A: 可能的原因：
1. 消息内容过长被截断
2. 终端宽度不够
3. 使用更宽的终端或导出到文件

## 📚 相关文档

- [消息上下文识别](MESSAGE_CONTEXT.md)
- [DOM导出调试](DEBUG_DOM.md)
- [选择器优化](SELECTOR_OPTIMIZATION.md)
- [CHANGELOG v2.6.5](../CHANGELOG.md#265)
