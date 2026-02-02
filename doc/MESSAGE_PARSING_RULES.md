# 消息解析规则

## 概述

本文档详细说明 Whop 期权交易消息的解析规则和实现策略。

### 核心原则

**消息是按时间顺序到达和处理的**，不是按"组"处理的：

```
真实场景（流式处理）：
监听消息流 → 按时间顺序到达：
10:41 PM - GILD 买入        ← 消息1：分析 → 生成GILD_xxx → 立即输出 → 记录
10:41 PM - GILD 止损设置    ← 消息2：分析 → 匹配GILD_xxx → 立即输出 → 记录
10:41 PM - EOSE 买入        ← 消息3：分析 → 生成EOSE_xxx → 立即输出 → 记录
10:44 PM - EOSE 卖出        ← 消息4：分析 → 匹配EOSE_xxx → 立即输出 → 记录
11:10 PM - GILD 卖出        ← 消息5：分析 → 匹配GILD_xxx → 立即输出 → 记录

错误理解（批处理）：
[GILD组] 收集所有GILD消息 → 统一输出  ← 先处理完GILD组
[EOSE组] 收集所有EOSE消息 → 统一输出  ← 再处理EOSE组
结果：时间顺序混乱，不符合真实场景

正确理解（流式处理）：
逐条按时间处理 → 每条消息独立分析 → 立即输出 → 记录到组
```

**分组ID的生成**：每条消息通过"股票代码 + 作者 + 日期哈希"独立生成分组ID，不需要依赖其他消息。

**输出格式（表格化）**：
```
时间                     分组ID                 股票       操作         内容
Jan 22, 2026 10:41 PM  GILD_4b6cf055        GILD     🟢 买入       GILD - $130 CALLS 这周 1.5-1.60
Jan 22, 2026 10:41 PM  GILD_4b6cf055        GILD     🟡 调整       小仓位 止损 在 1.3
Jan 22, 2026 10:41 PM  EOSE_4183c31e        EOSE     🟢 买入       $EOSE call 本周 $18 0.5
Jan 22, 2026 10:44 PM  EOSE_4183c31e        EOSE     🔴 卖出       0.75出三分之一
Jan 22, 2026 11:10 PM  GILD_4b6cf055        GILD     🔴 卖出       gild价内溢价了 还有的也2.5-2.6都出
```

特点：
- ✅ 严格按时间顺序
- ✅ 不同组的消息正确交错
- ✅ 每条消息显示所属分组
- ✅ 固定宽度，易于阅读

---

## 1. 消息排序规则

**规则：** 每条消息按时间先后排列

**实现：**
```python
# scraper/message_grouper.py - format_as_rich_panels()
def parse_timestamp(ts):
    """解析 "Jan 22, 2026 10:41 PM" 格式的时间戳"""
    from datetime import datetime
    return datetime.strptime(ts, '%b %d, %Y %I:%M %p')

all_messages.sort(key=lambda x: (parse_timestamp(x['timestamp']), x['id']))
```

**效果：**
```
10:41 PM - 买入消息
10:41 PM - 调整消息
10:41 PM - 卖出消息
11:10 PM - 卖出消息  ← 正确排在最后
```

---

## 2. 消息组概念

**规则：** 
- 消息组的**第一条消息**有发送者和时间
- 消息组内**剩余消息**没有发送者和时间

**DOM 特征：**

```html
<!-- 消息组第一条 -->
<div data-message-id="post_xxx" 
     data-has-message-above="false"     ← 上面没有相关消息
     data-has-message-below="true">     ← 下面有相关消息
    <author>xiaozhaolucky</author>
    <time>Jan 22, 2026 10:41 PM</time>
    <content>GILD - $130 CALLS 这周 1.5-1.60</content>
</div>

<!-- 消息组第二条 -->
<div data-message-id="post_yyy" 
     data-has-message-above="true"      ← 上面有相关消息（与上一条同组）
     data-has-message-below="true">     ← 下面还有相关消息
    <content>小仓位 止损 在 1.3</content>  <!-- 无作者、无时间 -->
</div>

<!-- 消息组第三条 -->
<div data-message-id="post_zzz" 
     data-has-message-above="true"      ← 上面有相关消息
     data-has-message-below="false">    ← 这是消息组最后一条
    <content>1.9附近出三分之一</content>
</div>
```

**实现：**

```python
# scraper/message_extractor.py
group.has_message_above = msgEl.getAttribute('data-has-message-above') === 'true'
group.has_message_below = msgEl.getAttribute('data-has-message-below') === 'true'

# 如果有上一条相关消息，继承作者和时间戳
if group.has_message_above and last_timestamp_group:
    if not group.author:
        group.author = last_timestamp_group.author
    if not group.timestamp:
        group.timestamp = last_timestamp_group.timestamp
```

---

## 3. 引用消息识别

**规则：** 消息组的第一条消息还能看到引用的历史消息（如果有）

**DOM 特征：**

```html
<div class="peer/reply">  <!-- 引用标记 -->
    <content>xiaozhaolucky•Jan 22, 2026 10:41 PM GILD - $130 CALLS...</content>
</div>
<div class="message-content">
    小仓位 止损 在 1.3
</div>
```

**实现：**

```javascript
// scraper/message_extractor.js
const quoteSelectors = [
    '[class*="peer/reply"]',
    '[class*="reply"]',
    '[class*="quote"]'
];

for (const selector of quoteSelectors) {
    const quoteEl = msgEl.querySelector(selector);
    if (quoteEl) {
        let quoteText = quoteEl.textContent.trim();
        quoteText = quoteText.replace(/Tail$/g, '').trim();  // 清理标记
        group.quoted_context = quoteText;
    }
}
```

---

## 4. DOM 结构分析规则

### 4.1 消息组关系属性

| 属性 | 含义 | 用途 |
|-----|------|------|
| `data-has-message-above="true"` | 上面有相关消息 | 与前一条消息同组 |
| `data-has-message-below="true"` | 下面有相关消息 | 消息组未结束 |
| `data-has-message-above="false"` | 独立消息或组首 | 消息组的第一条 |
| `data-has-message-below="false"` | 消息组结束 | 消息组的最后一条 |

### 4.2 消息类型判断

```html
<!-- 类型1: 独立消息 -->
<div data-has-message-above="false" data-has-message-below="false">
    完整的消息（有作者、时间）
</div>

<!-- 类型2: 消息组 -->
<div data-has-message-above="false" data-has-message-below="true">
    消息组第一条（有作者、时间）
</div>
<div data-has-message-above="true" data-has-message-below="true">
    消息组中间（无作者、无时间）
</div>
<div data-has-message-above="true" data-has-message-below="false">
    消息组最后一条（无作者、无时间）
</div>
```

### 4.3 引用关系标记

```html
<!-- 有引用的消息 -->
<div class="peer/reply">引用内容</div>
<div class="message-content">当前消息</div>
```

**CSS 类名特征：**
- `peer/reply` - 引用容器
- `peer-hover/reply:[--opacity:0.7]` - 鼠标悬停效果
- `peer-aria-disabled/reply:[--opacity:1]` - 禁用状态

---

## 5. 买入消息处理

**规则：** 针对买入消息，只需要消息组的时间信息

**识别特征：**

```python
# scraper/message_grouper.py
entry_keywords = ['call', 'put', 'calls', 'puts', '买入', 'buy', 'entry']

# 期权格式
pattern = r'\d+[cp]\b'  # 例如: "190c", "130p"

# 带价格格式
pattern = r'-\s*\$\d+'  # 例如: "- $130 CALLS"
```

**示例：**

```
✅ GILD - $130 CALLS 这周 1.5-1.60
✅ NVDA 190c 1/30 2-2.1 小仓位
✅ $EOSE call 本周 $18 0.5
```

**提取信息：**
- ✅ 股票代码：GILD, NVDA, EOSE
- ✅ 时间：Jan 22, 2026 10:41 PM
- ✅ 作者：xiaozhaolucky

---

## 6. 卖出/调整消息处理（复杂情况）

### 6.1 情况1：首条消息 + 有引用

**特征：**
- 是消息组首条（`has_message_above=false`）
- 有引用信息（`quoted_context` 不为空）

**处理策略：**

```python
# 1. 确认发送者和时间（从消息本身）
author = message.get('author')
timestamp = message.get('timestamp')

# 2. 从引用内容提取股票代码
quoted_context = message.get('quoted_context')
symbol = extract_symbol(quoted_context)  # 例如: "GILD - $130 CALLS"

# 3. 匹配对应的买入组
# 策略1: 引用内容匹配
for group in groups:
    if group.symbol == symbol and group.entry_message:
        if quoted_clean in entry_content:
            matched_group = group
```

**示例：**

```
消息：1.9附近出三分之一
引用：XxiaozhaoluckyGILD - $130 CALLS 这周 1.5-1.60
作者：xiaozhaolucky
时间：Jan 22, 2026 10:41 PM

→ 提取股票代码：GILD（从引用）
→ 匹配买入组：GILD_4b6cf055
```

### 6.2 情况2：非首条消息 + 有引用

**特征：**
- 不是消息组首条（`has_message_above=true`）
- 有引用信息

**处理策略：**

```python
# 1. 先找消息组首条消息（利用DOM关系）
if has_above and last_processed_message:
    author = last_processed_message.get('author')
    timestamp = last_processed_message.get('timestamp')

# 2. 再从引用信息确认股票代码
symbol = extract_symbol(quoted_context)

# 3. 匹配买入组
```

**示例：**

```
消息组：
├─ [首条] 小仓位 止损 在 1.3
│    引用：XxiaozhaoluckyGILD - $130 CALLS
│    作者：xiaozhaolucky
│    时间：10:41 PM
└─ [非首条] 2.23出三分之一
     引用：2.23出三分之一
     作者：(继承) xiaozhaolucky
     时间：(继承) 10:41 PM
     
→ 从首条消息的引用提取：GILD
→ 非首条消息继承时间和作者
```

### 6.3 情况3：有股票名称 + 无引用

**特征：**
- 消息内容包含股票代码
- 无引用信息（`quoted_context` 为空）

**处理策略：**

```python
# 1. 从消息内容提取股票代码
symbol = extract_symbol(message.get('content'))  # 例如: "NVDA 2.25 出三分之一"

# 2. 从历史消息中找最近的对应买入
# 策略2: 作者匹配
for group in groups:
    if (group.symbol == symbol and 
        group.entry_message and
        group.entry_message.get('author') == author):
        # 检查是否同一天
        if entry_date == date_part:
            matched_group = group
```

**示例：**

```
历史买入：NVDA 190c 1/30 2-2.1 (Jan 23, 12:07 AM, xiaozhaolucky)

当前消息：NVDA 2.25 出三分之一
作者：xiaozhaolucky
时间：Jan 23, 12:17 AM

→ 提取股票代码：NVDA（从消息内容）
→ 匹配条件：NVDA + 同作者 + 同一天
→ 匹配买入组：NVDA_3b07c620
```

### 6.4 情况4：无股票名称 + 无引用

**特征：**
- 消息内容无股票代码（例如："2.3附近都出"）
- 无引用信息

**处理策略（优先级）：**

```python
# 策略0: DOM层级关系优先
if has_above and last_processed_group_id:
    matched_group = groups[last_processed_group_id]

# 策略1: 时间上下文（前5条消息）
if not symbol:
    for j in range(max(0, i - 5), i):
        prev_symbol = extract_symbol(filtered_messages[j].get('content'))
        if prev_symbol:
            symbol = prev_symbol
            break

# 策略2: 作者上下文
if not symbol and author in last_symbol_by_author:
    symbol = last_symbol_by_author[author]
```

**示例：**

```
前一条消息：1.9附近出三分之一 (GILD组)
当前消息：2.3附近都出
DOM关系：has_message_above=true

→ 策略0生效：直接使用前一条消息的组（GILD_4b6cf055）
→ 继承股票代码：GILD
```

---

## 7. 股票代码提取规则

### 7.1 文本预处理

```python
# 1. 移除引用标记（只移除大写X）
text = re.sub(r'^[XＸ]+', '', text)

# 2. 移除时间标记
text = re.sub(r'\d{1,2}:\d{2}\s*[AP]M', '', text)

# 3. 移除作者名+时间格式
text = re.sub(r'[\w]+•\s*[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2}\s+[AP]M', '', text)

# 4. 在小写和大写字母间插入空格（关键！）
text = re.sub(r'([a-z])([A-Z]{2,})', r'\1 \2', text)
# "xiaozhaoluckyGILD" -> "xiaozhaolucky GILD"
```

### 7.2 匹配模式（优先级）

```python
patterns = [
    r'\$([A-Za-z]{1,5})\b',                    # $GILD
    r'\b([A-Za-z]{2,5})\s*-\s*\$',             # GILD - $130
    r'\b([A-Za-z]{2,5})\s+\d+[cp]',            # NVDA 190c
    r'\b([A-Za-z]{2,5})\s+call',               # GILD call
    r'\b([A-Za-z]{2,5})\s+put',                # GILD put
    r'\b([A-Za-z]{2,5})[\u4e00-\u9fa5]+call',  # amzn亚马逊call
    r'\b([A-Za-z]{2,5})价内',                   # gild价内
    r'\b([A-Za-z]{2,5})期权',                   # gild期权
    r'\b([A-Za-z]{2,5})\s+\d+\.?\d*\s*出',     # NVDA 2.25 出
    r'\b([A-Za-z]{2,5})剩下',                   # nvda剩下
]
```

### 7.3 排除词表

```python
exclude_words = {
    'CALL', 'PUT', 'CALLS', 'PUTS',  # 期权类型
    'TAIL',                           # 结尾标记
    'ALSO', 'FROM', 'WITH', 'THAT',  # 常见词
    'THIS', 'ABOUT', 'WHEN',
    'PM', 'AM'                        # 时间标记
}
```

---

## 8. 完整处理流程图

```
┌─────────────────────────┐
│   接收到消息            │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│ 1. 提取DOM属性          │
│  - has_message_above    │
│  - has_message_below    │
│  - quoted_context       │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│ 2. 继承作者和时间       │
│  (如果has_above=true)   │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│ 3. 提取股票代码         │
│  优先级:                │
│  a) 消息内容            │
│  b) 引用内容            │
│  c) DOM关系(前一条)     │
│  d) 时间上下文(前5条)   │
│  e) 作者上下文          │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│ 4. 分类消息类型         │
│  - entry (买入)         │
│  - exit (卖出)          │
│  - update (调整)        │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│ 5. 匹配或创建交易组     │
│  策略:                  │
│  a) DOM关系匹配         │
│  b) 引用内容匹配        │
│  c) 作者+日期匹配       │
│  d) 同标的+同天+同作者  │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│ 6. 按时间戳排序显示     │
└─────────────────────────┘
```

---

## 9. 测试用例

### 测试用例1：完整消息组（GILD）

```
输入：
├─ GILD - $130 CALLS 这周 1.5-1.60 (10:41 PM, xiaozhaolucky)
├─ 小仓位 止损 在 1.3 (引用上一条)
├─ 1.9附近出三分之一 (引用第一条)
├─ 2.23出三分之一
├─ 2.3附近都出
└─ gild价内溢价了 还有的也2.5-2.6都出 (11:10 PM)

期望输出：
GILD_4b6cf055 组：
├─ 10:41 PM 🟢 买入
├─ 10:41 PM 🟡 调整 (继承时间)
├─ 10:41 PM 🔴 卖出 (继承时间)
├─ 10:41 PM 🔴 卖出 (继承时间)
├─ 10:41 PM 🔴 卖出 (继承时间)
└─ 11:10 PM 🔴 卖出

✅ 测试通过
```

### 测试用例2：DOM层级关系（NVDA）

```
输入：
├─ NVDA 190c 1/30 2-2.1 小仓位 (12:07 AM)
├─ 止损在1.74 (引用上一条)
├─ NVDA 2.25 出三分之一 (12:17 AM)
├─ NVDA 2.32 出三分之一 (12:29 AM, has_below=true)
├─ 止损设置上移到2.16 (12:29 AM, has_above=true, 无股票代码)
├─ 2.45也在剩下减一半 (12:46 AM)
└─ 剩下看转弯往下时候都出 止损上移到2.25 (12:46 AM, has_above=true)

期望输出：
NVDA_3b07c620 组：
├─ 12:07 AM 🟢 买入
├─ 12:07 AM 🟡 调整
├─ 12:17 AM 🔴 卖出
├─ 12:29 AM 🔴 卖出
├─ 12:29 AM 🟡 调整 ← DOM关系识别
├─ 12:46 AM 🟡 调整
└─ 12:46 AM 🔴 卖出 ← DOM关系识别

✅ 测试通过
```

---

## 10. 已知问题和限制

### 10.1 时间格式

目前只支持：`"Jan 22, 2026 10:41 PM"` 格式

如果出现其他格式需要扩展 `parse_timestamp` 函数。

### 10.2 作者名混淆

如果作者名和股票代码连在一起（如 `xiaozhaoluckyGILD`），需要通过步骤4预处理插入空格。

### 10.3 特殊标记

- `Tail` - 结尾标记，需要过滤
- `X` - 引用标记，只移除大写X

---

## 11. 相关文件

| 文件 | 职责 |
|-----|------|
| `scraper/message_extractor.py` | 提取消息和DOM属性 |
| `scraper/message_grouper.py` | 消息分组和匹配逻辑 |
| `analyze_local_messages.py` | 本地HTML分析工具 |
| `doc/MESSAGE_CONTEXT.md` | 上下文传递机制 |
| `doc/MESSAGE_GROUPING.md` | 分组策略文档 |

---

## 更新历史

- 2026-02-02: 创建文档，整理完整解析规则
- v2.6.7: 利用DOM层级关系分组
- v2.6.8: 修复引用内容股票代码提取
- v2.6.9: 修复消息按时间排序
