# 更新日志

## [2.6.15] - 2026-02-02

### 🎯 优化symbol推断优先级

**问题：** 12:46 AM的NVDA消息被错误分配到GILD组

**示例：**
```
错误：
12:29 AM  NVDA_3b07c620  NVDA  🟡 调整  止损设置上移到2.16
12:46 AM  GILD_007b7ab5  GILD  🟡 调整  2.45也在剩下减一半      ← 错！应该是NVDA
12:46 AM  GILD_007b7ab5  GILD  🔴 卖出  剩下看转弯往下...        ← 错！应该是NVDA
12:51 AM  NVDA_3b07c620  NVDA  🔴 卖出  nvda剩下部分也2.45附近出

正确：
12:29 AM  NVDA_3b07c620  NVDA  🟡 调整  止损设置上移到2.16
12:46 AM  NVDA_3b07c620  NVDA  🟡 调整  2.45也在剩下减一半      ← 正确！
12:46 AM  NVDA_3b07c620  NVDA  🔴 卖出  剩下看转弯往下...        ← 正确！
12:51 AM  NVDA_3b07c620  NVDA  🔴 卖出  nvda剩下部分也2.45附近出
```

**根本原因：**

旧的symbol推断优先级：
```python
1. 消息内容
2. 引用内容  ← 优先级太高！
3. DOM关系
4. 时间上下文（前5条）
5. 作者上下文
```

问题：
- ❌ 引用内容可能是很久之前的消息（比如引用了GILD的买入消息）
- ❌ 时间上下文窗口太小（只看前5条）
- ❌ 没有考虑时间因素，导致推断出过时的symbol

**解决方案：**

调整symbol推断优先级，**时间上下文优先于引用内容**：

```python
新的优先级：
1. 消息内容          # 最准确
2. DOM关系           # 同一消息组
3. 时间上下文（前10条） # 最近的讨论  ← 提高优先级！
4. 引用内容          # 可能过时    ← 降低优先级！
5. 作者上下文        # 兜底方案
```

**关键改进：**

```python
# 1. 扩大时间上下文窗口：5 → 10
context_window = 10

# 2. 从最近往前查找（确保找到最新的symbol）
for j in range(i - 1, max(0, i - context_window) - 1, -1):
    prev_symbol = extract_symbol(filtered_messages[j])
    if prev_symbol:
        symbol = prev_symbol  # 使用最近的symbol
        break

# 3. 时间上下文在引用内容之前执行
```

**修改文件：**
- `scraper/message_grouper.py` - `group_messages()` 方法

**效果统计：**

修复前：
- 识别 34 个交易组
- NVDA_3b07c620: 5条消息
- GILD_007b7ab5: 2条消息（错误）

修复后：
- 识别 31 个交易组  ← 减少3个错误分组
- NVDA_3b07c620: 7条消息  ← 完整
- 无 GILD_007b7ab5 组

**完整的NVDA组：**
```
12:07 AM  🟢 买入  NVDA 190c 1/30 2-2.1 小仓位
12:17 AM  🔴 卖出  NVDA 2.25 出三分之一
12:29 AM  🔴 卖出  NVDA 2.32 出三分之一
12:29 AM  🟡 调整  止损设置上移到2.16
12:46 AM  🟡 调整  2.45也在剩下减一半          ← 修复！
12:46 AM  🔴 卖出  剩下看转弯往下时候都出...    ← 修复！
12:51 AM  🔴 卖出  nvda剩下部分也2.45附近出
```

**额外修复：**

#### 1. XOM 识别修复

**问题：** `"$XOM"` 被识别为 `"OM"`

**原因：** 正则 `\bX([A-Z]{2,5})\b` 把所有 `XABC` 格式都转换为 `ABC`，包括真实的股票代码 `XOM`

**解决方案：**
```python
# 只在没有 $ 符号前缀时才移除 X
if '$X' not in text:
    text_cleaned = re.sub(r'\bX([A-Z]{2,5})\b', r'\1', text_cleaned)
```

**效果：**
- ✅ `$XOM` → `XOM`（正确）
- ✅ `XAPLD` → `APLD`（正确）

#### 2. CMCSA 识别修复

**问题：** `"0.92出三分之一cmcsa期权"` 被识别为 `LYFT`

**原因：** 正则模式 `\b([A-Za-z]{2,5})期权` 无法匹配 "三分之一cmcsa" 这种中文+英文的格式

**解决方案：**

添加新的高优先级模式：
```python
r'[\u4e00-\u9fa5]+([A-Za-z]{2,5})期权',  # "三分之一cmcsa期权"
```

**效果：**
- ✅ "0.92出三分之一cmcsa期权" → `CMCSA`（正确）
- ✅ "0.93也出三分之一cmcsa期权" → `CMCSA`（正确）

---

## [2.6.14] - 2026-02-02

### 🧹 过滤元数据和纯图片消息

**问题：** 阅读量、时间戳等元数据被当作消息内容显示

**根本原因：**

从DOM结构分析，用户发送了一张图片：
```html
<!-- 图片attachment -->
<div data-attachment-id="file_37q4tZRW3QPU4">
  <img src="https://...whop.com/.../image.png" />
</div>
<!-- 阅读量统计 -->
<span>由 223阅读</span>
```

提取器没有提取到图片，只提取到了阅读量统计 `"由 223阅读"`，导致这条纯图片消息被当作文本消息显示。

**示例：**
```
错误：
RKLB  🟡 调整  由 223阅读              ← 实际上是一张图片
RKLB  🟡 调整  •Wednesday 11:04 PM    ← 纯时间戳
```

**修复内容：**

#### 1. ✅ 过滤纯图片消息（核心修复）

检测并过滤只包含图片/附件而没有文本内容的消息：

```javascript
// 检查是否包含附件
const hasAttachment = msgEl.querySelector('[data-attachment-id]') || 
                     msgEl.querySelector('img[src*="whop.com"]');

// 检查是否只有阅读量信息
const isOnlyReadCount = group.primary_message && 
                       group.primary_message.match(/^(由\s*)?\d+\s*阅读$/);

// 如果只有附件和阅读量，没有实质内容，则跳过
const isImageOnlyMessage = hasAttachment && 
                          (isOnlyReadCount || !group.primary_message);

if (isImageOnlyMessage) {
    // 跳过此消息组
}
```

#### 2. ✅ 过滤元数据

- ✅ "由 223阅读" - 阅读量统计
- ✅ "223阅读" - 阅读量简写
- ✅ "Edited" / "编辑" - 编辑标记
- ✅ "Reply" / "回复" - 回复标记
- ✅ "删除" / "已编辑" - 操作标记

#### 3. ⚠️ 部分过滤的元数据

- ⚠️ "•Wednesday 11:04 PM" - 纯时间戳
  - 已添加多层过滤机制
  - 需要进一步优化 Unicode 字符处理

**实现策略：**

**源头过滤**（`message_extractor.py`）：
```javascript
// 过滤阅读量
!text.match(/^由\s*\d+\s*阅读$/) &&
!text.match(/^\d+\s*阅读$/) &&

// 过滤时间戳元数据
!text.match(/^•.*\d{1,2}:\d{2}\s+[AP]M$/) &&

// 过滤操作标记
text !== 'Edited' && text !== 'Reply' && text !== '编辑' &&

// 过滤纯元数据消息组
const isPureMetadata = weekdays.some(day => text.includes(day)) && 
                       text.includes('PM/AM') && 
                       text.length < 30;
```

**处理阶段过滤**（`message_grouper.py`）：
```python
# 过滤纯元数据消息
is_timestamp_only = has_weekday and has_time and len(words) <= 4
if is_timestamp_only or is_read_count:
    continue
```

**输出阶段过滤**（`_print_message_immediately`）：
```python
# 过滤纯元数据
if content in ['Edited', 'Reply', '编辑', '回复']:
    return
```

**修改文件：**
- `scraper/message_extractor.py` - 3处过滤逻辑
- `scraper/message_grouper.py` - 2处过滤逻辑

**效果统计：**

修复前：
- 提取 99 条原始消息
- 识别 32 个交易组

修复后：
- 提取 92 条原始消息（✅ 过滤掉 7 条纯图片/元数据消息）
- 识别 34 个交易组

**已知问题：**
- 时间戳类型的元数据（包含星期名称）过滤还需要进一步优化
- 可能涉及 Unicode 字符或特殊空格的处理

---

## [2.6.13] - 2026-02-02

### 🐛 修复头像fallback文本污染问题

**问题：** `XAPLD` 被错误识别为独立的股票代码，而不是 `APLD`

**示例：**
```
错误：
XAPLD_fd3268fc  (11:03 PM) 买入  ← 错误的组
APLD_9633f8df   (11:05 PM) 调整  ← 另一个组

正确：
APLD_9633f8df   (11:03 PM) 买入  ← 同一组
APLD_9633f8df   (11:05 PM) 调整  ← 同一组
```

**根本原因：**

从DOM结构分析，`X` 和 `APLD` 相隔很远：

```html
<!-- 第5279行：头像fallback（隐藏） -->
<span class="fui-AvatarFallback hidden" style="display: none;">X</span>

<!-- 第5294行：消息内容（相隔15行） -->
<p>APLD - $40 CALLS下周的 $1.28</p>
```

但提取逻辑使用 `innerText` 时，可能把隐藏的头像文本也提取了，导致 `X` 和 `APLD` 被拼接成 `XAPLD`。

**双层修复方案：**

#### 1. 源头修复（`message_extractor.py`）

在提取阶段就排除头像元素：

```javascript
// 跳过头像相关元素
if (el.closest('[class*="fui-Avatar"]') || 
    el.closest('[class*="avatar"]') ||
    el.classList.contains('hidden') ||
    window.getComputedStyle(el).display === 'none') {
    continue;
}

// 过滤单独的 "X"
if (text !== 'X' && ...) {
    texts.push(text);
}

// 备用方案：先移除头像元素再提取
const clonedEl = msgEl.cloneNode(true);
const avatarEls = clonedEl.querySelectorAll('[class*="fui-Avatar"], .hidden');
avatarEls.forEach(el => el.remove());
```

#### 2. 保险修复（`message_grouper.py`）

即使提取阶段漏掉了，分析阶段也能纠正：

```python
# 新增步骤2：移除 X + 大写字母组合
text_cleaned = re.sub(r'\bX([A-Z]{2,5})\b', r'\1', text_cleaned)
# "XAPLD" -> "APLD"
# "XGILD" -> "GILD"
```

**修改文件：**
- `scraper/message_extractor.py` - 内容提取逻辑（源头修复）
- `scraper/message_grouper.py` - `_extract_symbol()` 方法（保险修复）

**测试结果：**
```
之前：
XAPLD_fd3268fc (11:03 PM) 🟢 买入
APLD_9633f8df  (11:05 PM) 🟡 调整

现在：
APLD_9633f8df  (11:03 PM) 🟢 买入  ← 正确归组
APLD_9633f8df  (11:05 PM) 🟡 调整
APLD_9633f8df  (11:05 PM) 🔴 卖出
APLD_9633f8df  (11:05 PM) 🔴 卖出
APLD_9633f8df  (11:05 PM) 🔴 卖出
```

---

## [2.6.12] - 2026-02-02

### 🚀 架构重构 - 流式处理（Stream Processing）

**核心思想转变：从"批处理"到"流式处理"**

#### 之前的架构（批处理，错误）：

```python
# 1. 先收集所有消息到groups
groups = {}
for message in all_messages:
    analyze_and_add_to_group(message, groups)

# 2. 最后统一输出（按组输出，时间错乱）
for group in groups:
    print_group(group)
```

问题：
- ❌ 按"组"输出，导致时间顺序混乱
- ❌ 不同组的消息不会交错显示
- ❌ 不符合真实场景

#### 现在的架构（流式处理，正确）：

```python
# 按时间顺序逐条处理（模拟真实监控）
for message in messages_ordered_by_time:
    # 1. 分析消息，生成groupId
    symbol = extract_symbol(message)
    msg_type = classify_type(message)
    group_id = generate_group_id(symbol, timestamp)
    
    # 2. 立即输出到表格
    print_to_table(message, group_id, symbol, msg_type)
    
    # 3. 记录到对应group（用于后续查询）
    groups[group_id].add(message, msg_type)
```

优势：
- ✅ 每条消息独立处理，立即输出
- ✅ 严格按时间顺序，不同组正确交错
- ✅ 符合真实场景：消息按时间到达

#### 实际效果对比：

**之前（按组输出）：**
```
AMZN 10:57 PM 买入
AMZN 10:57 PM 调整
AMZN 11:35 PM 卖出   ← 最晚
IREN 10:57 PM 买入   ← 但10:57显示在11:35后（错！）
IREN 10:58 PM 调整
```

**现在（流式输出）：**
```
AMZN 10:57 PM 买入
AMZN 10:57 PM 调整
IREN 10:57 PM 买入   ← 同时间的消息正确交错
IREN 10:58 PM 调整
IREN 11:03 PM 调整
AMZN 11:35 PM 卖出   ← 最晚的消息在最后（对！）
```

#### 实现细节：

1. **添加 `stream_output` 参数**
   ```python
   def group_messages(self, messages: List[Dict], stream_output: bool = False)
   ```

2. **消息按时间排序**
   ```python
   if stream_output:
       filtered_messages = sorted(messages, key=parse_timestamp)
   ```

3. **新增 `_print_message_immediately()` 方法**
   - 每条消息处理完立即输出
   - 固定宽度表格格式：时间(22) | 分组ID(20) | 股票(8) | 操作(10) | 内容(55)

4. **输出示例：**
   ```
   时间                     分组ID                 股票       操作         内容
   Jan 22, 2026 10:41 PM  GILD_4b6cf055        GILD     🟢 买入       GILD - $130 CALLS 这周 1.5-1.60
   Jan 22, 2026 10:41 PM  GILD_4b6cf055        GILD     🟡 调整       小仓位 止损 在 1.3
   Jan 22, 2026 10:41 PM  EOSE_4183c31e        EOSE     🟢 买入       $EOSE call 本周 $18 0.5
   Jan 22, 2026 10:44 PM  EOSE_4183c31e        EOSE     🔴 卖出       0.75出三分之一
   Jan 22, 2026 11:10 PM  GILD_4b6cf055        GILD     🔴 卖出       gild价内溢价了 还有的也2.5-2.6都出
   ```

#### 修改文件：

- `scraper/message_grouper.py`
  - 新增 `stream_output` 参数
  - 新增 `_print_message_immediately()` 方法
  - 在消息处理时立即输出
- `analyze_local_messages.py`
  - 启用 `stream_output=True`
  - 移除旧的 `format_as_rich_panels()` 调用

#### 影响：

- ✅ 符合真实监控场景的时间线
- ✅ 便于理解消息的因果关系
- ✅ 更直观地展示交易流程
- ✅ 保持向后兼容（`stream_output=False` 时使用旧逻辑）

---

## [2.6.11] - 2026-02-02

### 🔧 重构消息输出逻辑 - 按时间顺序显示

**问题：** 消息按"组"输出，导致时间顺序混乱

**示例：**
```
错误的输出顺序（按组）：
- AMZN_81b77ae3 (10:57 PM) 🟢 买入
- AMZN_81b77ae3 (10:57 PM) 🟡 调整  
- AMZN_81b77ae3 (11:35 PM) 🔴 卖出   ← 这条最晚
- IREN_314d412f (10:57 PM) 🟢 买入   ← 但IREN 10:57显示在11:35之后
- IREN_314d412f (10:58 PM) 🟡 调整

正确的输出顺序（按时间）：
- AMZN_81b77ae3 (10:57 PM) 🟢 买入
- AMZN_81b77ae3 (10:57 PM) 🟡 调整
- IREN_314d412f (10:57 PM) 🟢 买入  ← 同一时间的IREN消息
- IREN_314d412f (10:58 PM) 🟡 调整  ← 时间连续
- ...
- AMZN_81b77ae3 (11:35 PM) 🔴 卖出  ← 最晚的消息在最后
```

**根本原因：**

旧逻辑是"按组输出"：
```python
for group in groups:  # 按组遍历
    for message in group.messages:  # 输出组内消息
        print(message)
```

但真实场景是"消息按时间顺序到达"，不同组的消息会交错出现。

**解决方案：**

重写 `format_as_rich_panels()` 函数：

```python
# 1. 从所有组中收集所有消息
all_messages = []
for group in groups:
    for msg in [entry, exits, updates]:
        all_messages.append({
            'message': msg,
            'group_id': group.group_id,
            'symbol': group.symbol,
            'type': msg_type
        })

# 2. 按时间戳排序所有消息
all_messages.sort(key=lambda x: parse_timestamp(x['message']['timestamp']))

# 3. 按时间顺序输出每条消息
for msg_item in all_messages:
    print(f"{msg_item['group_id']} - {msg_item['message']['content']}")
```

**修改文件：**
- `scraper/message_grouper.py` - `format_as_rich_panels()` 函数

**效果：**
- ✅ 消息严格按时间顺序输出
- ✅ 不同组的消息正确交错显示
- ✅ 每条消息显示它所属的分组ID
- ✅ 符合真实场景：消息按时间顺序到达和处理

**影响：**
- 输出格式不变，只是顺序正确了
- 更符合真实监控场景的时间线
- 便于理解消息的因果关系

---

## [2.6.10] - 2026-02-02

### 📝 新增核心文档 - 消息解析规则

**新增文档：** `doc/MESSAGE_PARSING_RULES.md`

**内容：**

根据实际使用经验，整理完整的消息解析规则和实现策略：

1. **消息排序规则** - 按时间先后排列
2. **消息组概念** - 首条有作者时间，其余继承
3. **引用消息识别** - peer/reply DOM标记
4. **DOM结构分析** - has_message_above/below属性
5. **买入消息处理** - 只需时间信息
6. **卖出/调整消息** - 4种复杂情况的处理策略
7. **股票代码提取** - 预处理和匹配模式
8. **完整处理流程图** - 从接收到显示的完整流程
9. **测试用例** - GILD和NVDA的完整案例
10. **已知问题** - 限制和注意事项

**文档价值：**

- ✅ 记录核心解析逻辑，便于后续维护
- ✅ 解释为什么需要DOM层级关系
- ✅ 说明作者名和股票代码的处理
- ✅ 提供完整的测试用例验证

**更新README：**

在 `📚 文档导航` 部分添加链接：
- [MESSAGE_PARSING_RULES.md](./doc/MESSAGE_PARSING_RULES.md) - 消息解析规则（**核心逻辑**）

---

## [2.6.9] - 2026-02-02

### 🐛 修复消息显示顺序错误 - 按时间排序

**问题：**

用户反馈消息显示顺序不对：

```
11:10 PM 的消息显示在了 10:41 PM 消息的前面 ❌
```

**根本原因：**

`format_as_rich_panels` 函数中消息是按ID排序，而不是按时间排序：

```python
# 第628行 - 原代码
all_messages.sort(key=lambda x: x['id'])  # 按消息ID字母顺序排序 ❌

# 但函数注释说：
# "按时间顺序展示所有操作" ⚠️ 注释与实现不符！
```

**解决方案：**

修改排序逻辑，按时间戳解析并排序：

```python
def parse_timestamp(ts):
    """解析时间戳用于排序"""
    if not ts:
        return float('inf')  # 没有时间戳的放最后
    try:
        # 解析 "Jan 22, 2026 10:41 PM" 格式
        from datetime import datetime
        return datetime.strptime(ts, '%b %d, %Y %I:%M %p')
    except:
        return ts  # 解析失败，使用原始字符串

# 按时间戳+消息ID排序
all_messages.sort(key=lambda x: (parse_timestamp(x['timestamp']), x['id']))
```

**测试结果：**

```
GILD_4b6cf055 交易组（按时间顺序）：
├─ 10:41 PM - 买入、调整、3次卖出
└─ 11:10 PM - gild价内溢价了 还有的也2.5-2.6都出 ✅ 正确排在最后
```

**影响范围：**
- `scraper/message_grouper.py`：修改`format_as_rich_panels`排序逻辑

---

## [2.6.8] - 2026-02-02

### 🐛 修复引用内容中股票代码提取失败

**问题：**

GILD消息组缺失多条消息，这些消息被错误归类到AMZN组：

```
✗ 小仓位 止损 在 1.3
✗ 1.9附近出三分之一
✗ 2.23出三分之一
✗ 2.3附近都出
```

这些消息明确引用了GILD买入消息，但未能正确匹配到GILD组。

**根本原因：**

引用内容格式：`"XxiaozhaoluckyGILD - $130 CALLS"`

问题：
1. 作者名 `xiaozhaolucky` 和股票代码 `GILD` 之间**没有空格**
2. 正则表达式的 `\b`（单词边界）无法匹配连在一起的文本
3. `_extract_symbol` 无法从引用内容中提取出GILD

**解决方案：**

在 `_extract_symbol` 的预处理步骤中增强文本清理：

**修复1: 只移除引用标记X，保留作者名**

```python
# 原代码（有bug）：
text_cleaned = re.sub(r'^[XxＸｘ]+', '', text)
# 问题："Xxiaozhaolucky" -> "iaozhaolucky" ❌ 作者名首字母x被误删！

# 修复后：
text_cleaned = re.sub(r'^[XＸ]+', '', text)  # 只移除大写X
# 效果："Xxiaozhaolucky" -> "xiaozhaolucky" ✅ 保留完整作者名
```

**修复2: 处理作者名和股票代码连在一起的情况**

```python
# 3. 移除作者名+时间格式
text_cleaned = re.sub(
    r'[\w]+•\s*[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2}\s+[AP]M', 
    '', 
    text_cleaned
)

# 4. 在小写字母和大写字母之间插入空格
#    处理作者名+股票代码无空格的情况
#    例如："xiaozhaoluckyGILD" -> "xiaozhaolucky GILD"
text_cleaned = re.sub(r'([a-z])([A-Z]{2,})', r'\1 \2', text_cleaned)
```

**关键点：**
- `xiaozhaolucky` 是**作者名**（13个字母）
- 股票代码模式限制 `{2,5}` 个字母
- 作者名不会被误识别为股票代码 ✅

**处理效果：**

```
输入: "XxiaozhaoluckyGILD - $130 CALLS"
步骤1: 移除X -> "xiaozhaoluckyGILD - $130 CALLS"
步骤4: 插入空格 -> "xiaozhaolucky GILD - $130 CALLS"
提取: "GILD" ✅
```

**测试结果：**

```
✅ 小仓位 止损 在 1.3 -> GILD_4b6cf055
✅ 1.9附近出三分之一 -> GILD_4b6cf055
✅ 2.23出三分之一 -> GILD_4b6cf055
✅ 2.3附近都出 -> GILD_4b6cf055
```

所有消息正确归类到GILD组！

**影响范围：**
- `scraper/message_grouper.py`：增强`_extract_symbol`预处理逻辑

---

## [2.6.7] - 2026-02-02

### 🐛 修复消息分组错误 - 利用DOM层级关系

**问题：**

用户反馈部分消息被错误归类到其他交易组：

```
消息#63 (12:29 AM): "止损设置上移到2.16"  
消息#65 (12:46 AM): "剩下看转弯往下时候都出 止损上移到2.25"

这两条消息应该属于NVDA交易组，但被错误识别为EOSE/GILD
```

**根本原因：**

1. 这些消息本身不包含股票代码（如NVDA）
2. "Tail"被错误识别为作者名（实际是结尾标记字符）
3. 没有利用DOM结构中的消息组层级关系

**解决方案：**

#### 1. 过滤"Tail"标记

在 `scraper/message_extractor.py` 中：

```javascript
// 过滤掉结尾标记
if (text && 
    text !== 'Tail' &&  // 排除结尾标记
    !text.includes('PM') && 
    ...
) {
    group.author = text;
}

// 清理引用内容和消息内容中的Tail标记
quoteText = quoteText.replace(/Tail$/g, '').trim();
```

#### 2. 提取DOM层级关系属性

Whop页面使用 `data-has-message-above` 和 `data-has-message-below` 属性标记消息组关系：

```javascript
// 提取消息组关系属性
group.has_message_above = msgEl.getAttribute('data-has-message-above') === 'true';
group.has_message_below = msgEl.getAttribute('data-has-message-below') === 'true';
```

DOM特征分析：
```
消息#62 (NVDA 2.32 出三分之一):
  - data-has-message-above=false
  - data-has-message-below=true  ← 有后续消息

消息#63 (止损设置上移到2.16):
  - data-has-message-above=true  ← 与前一条消息同组！
  - data-has-message-below=false
```

#### 3. 优先使用DOM层级关系分组

在 `scraper/message_grouper.py` 中添加策略0（最高优先级）：

```python
# 策略0: DOM层级关系优先
if has_above and last_processed_message:
    prev_symbol = self._extract_symbol(last_processed_message.get('content', ''))
    if prev_symbol:
        symbol = prev_symbol

# 匹配组时优先使用DOM关系
if has_above and last_processed_group_id and last_processed_group_id in self.groups:
    matched_group = self.groups[last_processed_group_id]
```

#### 4. 继承作者和时间戳

```python
# 如果消息有上一条相关消息（has_message_above=true），继承上一条消息的作者和时间戳
if group.has_message_above and last_timestamp_group:
    if not group.author:
        group.author = last_timestamp_group.author
    if not group.timestamp:
        group.timestamp = last_timestamp_group.timestamp
```

**测试结果：**

```
✅ "止损设置上移到2.16" 正确归类到 NVDA_3b07c620
✅ "剩下看转弯往下时候都出 止损上移到2.25" 正确归类到 NVDA_3b07c620
✅ 作者正确识别为 "xiaozhaolucky"（不再是"Tail"）
✅ 时间戳正确继承为 "Jan 23, 2026 12:29 AM"
```

**影响范围：**
- `scraper/message_extractor.py`：提取DOM属性，过滤Tail标记
- `scraper/message_grouper.py`：利用DOM层级关系分组
- `analyze_local_messages.py`：传递DOM属性

---

## [2.6.6] - 2026-02-02

### 🔧 改进DOM导出与本地HTML分析工具

**🆕 新增独立分析脚本：** `analyze_local_messages.py`

**用户反馈：**
- export-dom 可能无法导出完整页面信息（历史消息未加载）
- 需要手动确认页面加载完成后再导出
- 需要支持分析已导出的本地HTML文件

#### 新增功能

**1. DOM导出增加用户确认步骤**

**问题：**
```
原来的export-dom自动导出，可能只导出了部分消息：
1. 页面初始只加载最近的消息
2. 需要滚动到底部才能加载历史消息
3. 自动导出时可能历史消息还未加载
```

**解决方案：**

修改 `export_page_dom()` 函数，添加用户确认步骤：

```python
# 1. 打开浏览器窗口（非无头模式）
# 2. 导航到页面
# 3. 等待初始加载（3秒）
# 4. 显示提示信息
print("⚠️  重要提示")
print("浏览器窗口已打开，请在浏览器中执行以下操作：")
print("1. 📜 滚动页面到最底部，加载所有历史消息")
print("2. ⏳ 等待所有消息完全加载")
print("3. ✅ 确认页面内容完整")
print("完成后按 [回车] 键继续导出...")

# 5. 等待用户输入
input()

# 6. 开始导出
```

**优势：**
- ✅ 用户可以手动加载所有历史消息
- ✅ 确保导出的HTML包含完整数据
- ✅ 可以验证页面内容是否正确
- ✅ 灵活控制导出时机

**2. 新增本地HTML分析工具** 🆕

**功能：** `analyze_local_html()`

**用途：**
- 分析已导出的本地HTML文件
- 不需要启动浏览器连接网页
- 可以反复分析同一个HTML文件
- 快速验证选择器修改效果

**使用流程：**

```bash
# 1. 运行本地HTML分析
python3 main.py --test analyze-html

# 2. 程序自动扫描debug目录
📁 找到 3 个HTML文件:
   1. page_20260202_000748.html
      时间: 2026-02-02 00:07:48, 大小: 2.45 MB
   2. page_20260201_230555.html
      时间: 2026-02-01 23:05:55, 大小: 2.12 MB
   3. page_20260201_220430.html
      时间: 2026-02-01 22:04:30, 大小: 1.98 MB

# 3. 选择要分析的文件
请选择要分析的文件 (输入序号，默认=1): 1

# 4. 自动分析并生成报告
✅ 已选择: debug/page_20260202_000748.html
📖 正在读取HTML文件...
✅ 已读取 2,456,789 字符
🔍 正在分析HTML结构...
✅ 分析完成

# 5. 查看结果
📊 统计信息:
   总元素数: 5,848
   找到 2 种可能的消息容器
   找到 30 个包含交易关键字的元素

📄 详细分析报告已保存到:
   debug/local_analysis_20260202_001234.txt
```

**分析内容：**

```
============================================================
本地HTML结构分析
============================================================

源文件: debug/page_20260202_000748.html
总元素数: 5,848

============================================================
可能的消息容器选择器
============================================================

1. 选择器: [data-message-id]
   数量: 108
   类名: group/message
   ID: 
   
   示例文本:
   xiaozhaolucky
   GILD - $130 CALLS 这周 1.5-1.60
   ...
   
   示例HTML:
   <div class="group/message" data-message-id="post_1CXN...">
   ...

============================================================
包含交易关键字的元素
============================================================

1. 关键字: GILD
   文本: GILD - $130 CALLS 这周 1.5-1.60
   路径:
      <SPAN class='fui-Text truncate'>
         <DIV class='flex items-center'>
            ...
```

**技术实现：**

```python
# 1. 扫描debug目录
html_files = glob("debug/page_*.html")
html_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)

# 2. 用户选择文件
choice = input("请选择要分析的文件: ")

# 3. 读取HTML
with open(html_file, 'r', encoding='utf-8') as f:
    html_content = f.read()

# 4. 使用playwright分析
from playwright.async_api import async_playwright

async with async_playwright() as p:
    browser = await p.chromium.launch(headless=True)
    page = await browser.new_page()
    
    # 加载HTML内容
    await page.set_content(html_content)
    
    # JavaScript分析
    analysis_data = await page.evaluate(js_analysis)
    
    # 生成报告
    ...
```

**优势：**

**快速迭代：**
- ✅ 无需重新登录
- ✅ 无需加载网页
- ✅ 分析速度快（本地文件）
- ✅ 可反复测试

**离线工作：**
- ✅ 不需要网络连接
- ✅ 不消耗API配额
- ✅ 可在任何环境运行

**便于调试：**
- ✅ 固定的HTML内容
- ✅ 可对比不同时间点的HTML
- ✅ 可分享HTML文件协作调试

**3. 新增独立分析脚本** 🆕

**文件：** `analyze_local_messages.py`

**功能：**
- 独立的命令行脚本
- 直接运行，无需通过main.py
- 使用实际的EnhancedMessageExtractor提取消息
- 使用MessageGrouper进行交易分组
- 生成完整的分析报告

**使用方法：**

```bash
# 方式1: 交互式选择文件
python3 analyze_local_messages.py

# 方式2: 直接指定文件
python3 analyze_local_messages.py debug/page_20260202_000748.html

# 方式3: 使用通配符
python3 analyze_local_messages.py debug/page_*.html
```

**输出内容：**

```
================================================================================
本地HTML消息提取分析工具
================================================================================

📁 找到 1 个HTML文件:
   1. page_20260202_000748.html
      时间: 2026-02-02 00:07:48, 大小: 2.45 MB

请选择要分析的文件 (输入序号，默认=1): [回车]

✅ 已选择: debug/page_20260202_000748.html
📖 正在读取HTML文件...
✅ 已读取 2,456,789 字符

🚀 正在启动Playwright...
✅ Playwright已启动

📝 正在加载HTML内容...
✅ HTML内容已加载

🔍 正在提取消息...
✅ 成功提取 94 条原始消息

🔄 正在分析消息关联关系...
✅ 识别出 8 个交易组

【方式1】详细表格视图
-------------------------------------------------------------------------------
消息组ID        标的     时间                 操作类型    消息内容
-------------------------------------------------------------------------------
GILD_a1b2c3d4   GILD     Jan 22 10:41        🟢 买入    GILD - $130 CALLS...
GILD_a1b2c3d4   GILD     Jan 22 10:45        🔴 卖出    1.9附近出三分之一
GILD_a1b2c3d4   GILD     Jan 22 10:50        🔴 卖出    2.23出三分之一
...

【方式2】分组摘要视图
-------------------------------------------------------------------------------
【消息组 #1】
组ID: GILD_a1b2c3d4
交易标的: GILD
消息总数: 4

📈 【买入信号】
   GILD - $130 CALLS 这周 1.5-1.60
   
📉 【卖出操作】 (3条)
   1. 1.9附近出三分之一
      ⬅️ 对应买入: GILD - $130 CALLS...
...

【原始消息详情】（前10条）
-------------------------------------------------------------------------------

📊 统计信息
-------------------------------------------------------------------------------
原始消息数: 94
交易组数: 8
有作者信息: 94 (100.0%)
有时间戳: 94 (100.0%)
有引用内容: 42 (44.7%)

💾 正在保存详细报告...
✅ 详细报告已保存到: debug/message_analysis_20260202_002345.txt
```

**生成的报告文件：**

```
debug/message_analysis_20260202_002345.txt

包含：
- 统计信息（消息数、交易组数、完整度）
- 详细表格视图
- 分组摘要视图
- 所有原始消息的完整内容
```

**与analyze-html的区别：**

| 功能 | analyze-html | analyze_local_messages.py |
|------|--------------|--------------------------|
| **用途** | 分析页面结构 | 提取和分组消息 |
| **输出** | DOM结构、选择器 | 交易消息、分组关系 |
| **工具** | 结构分析 | EnhancedMessageExtractor |
| **报告** | 元素路径、类名 | 消息内容、交易流程 |
| **使用场景** | 调试选择器 | 验证提取效果 |

**优势：**

**独立运行：**
- ✅ 不依赖main.py
- ✅ 可以快速运行
- ✅ 支持命令行参数

**完整提取：**
- ✅ 使用实际的提取器
- ✅ 完整的消息分组
- ✅ 统计信息详细

**便于验证：**
- ✅ 快速测试选择器修改
- ✅ 查看实际提取效果
- ✅ 生成详细报告文件

#### 使用场景

**场景1：首次导出完整数据**

```bash
# Step 1: 导出完整HTML
python3 main.py --test export-dom

# 浏览器打开后：
# 1. 滚动到页面最底部
# 2. 等待所有历史消息加载
# 3. 按回车键确认

# Step 2: 分析导出的HTML
python3 main.py --test analyze-html
# 选择刚才导出的文件（通常是选项1）

# Step 3: 查看分析报告
cat debug/local_analysis_*.txt
```

**场景2：调整选择器后验证**

```bash
# 1. 修改 scraper/message_extractor.py 中的选择器
vim scraper/message_extractor.py

# 2. 使用已有的HTML验证（无需重新导出）
python3 main.py --test analyze-html

# 3. 查看分析结果是否符合预期
# 4. 如果不满意，继续调整选择器
# 5. 重复步骤1-3
```

**场景3：对比不同时间点的页面结构**

```bash
# 分析旧的HTML文件
python3 main.py --test analyze-html
选择: 2  # 选择较旧的文件

# 分析新的HTML文件
python3 main.py --test analyze-html
选择: 1  # 选择最新的文件

# 对比两份分析报告
diff debug/local_analysis_20260201_*.txt \
     debug/local_analysis_20260202_*.txt
```

#### 文件命名规则

**导出的文件：**
```
debug/
├── page_20260202_000748.html      # 页面HTML
├── page_20260202_000748.png       # 页面截图
├── analysis_20260202_000748.txt   # 在线分析报告
└── local_analysis_20260202_001234.txt  # 本地分析报告
```

**命名格式：**
- `page_YYYYMMDD_HHMMSS.html` - 页面HTML
- `analysis_YYYYMMDD_HHMMSS.txt` - 在线分析（export-dom）
- `local_analysis_YYYYMMDD_HHMMSS.txt` - 本地分析（analyze-html）

#### 注意事项

**1. HTML文件大小**
- 完整页面HTML通常1-5 MB
- 如果文件过小（<500KB），可能未加载完整
- 建议滚动加载更多消息后再导出

**2. 分析报告限制**
- 只显示前30个包含关键字的元素
- 避免报告过大影响阅读
- 如需完整数据，可修改代码中的限制

**3. 文件管理**
- 定期清理debug目录
- 保留重要的HTML文件作为baseline
- 使用git忽略debug目录（已配置）

#### 命令对比

| 命令 | 功能 | 是否需要网络 | 是否需要登录 | 用途 |
|------|------|-------------|-------------|------|
| `export-dom` | 导出实时页面 | ✅ 需要 | ✅ 需要 | 获取最新数据 |
| `analyze-html` | 分析本地HTML | ❌ 不需要 | ❌ 不需要 | 快速调试选择器 |

#### 工作流程优化

**推荐流程：**

```
1. export-dom (首次/获取新数据)
   ↓
2. analyze-html (快速分析)
   ↓
3. 调整选择器
   ↓
4. analyze-html (验证修改)
   ↓
5. message-extractor (测试提取)
   ↓
6. 正常运行
```

---

## [2.6.5] - 2026-02-01

### 🎯 消息分组与表格展示 - 智能识别交易关联关系

**新增功能：交易消息组聚合**

针对用户反馈的问题：
1. **多条卖出消息无法识别属于同一交易**
   - 问题：`1.9附近出三分之一`、`2.23出三分之一`、`2.3附近都出` 被识别为独立消息
   - 期望：它们应该归属于同一个交易（GILD $130 CALLS）

2. **卖出消息缺少买入信息关联**
   - 问题：看到卖出消息，不知道对应哪笔买入
   - 期望：显示买入-卖出的对应关系

3. **消息展示格式不直观**
   - 问题：列表格式难以查看关联关系
   - 期望：表格形式展示，清晰显示消息组

#### 核心功能

**1. 创建消息分组器模块** 🆕

**文件：** `scraper/message_grouper.py`

**类结构：**

```python
class TradeMessageGroup:
    """交易消息组 - 一组相关的交易消息"""
    - group_id: 消息组ID
    - symbol: 交易标的（GILD, NVDA等）
    - entry_message: 买入消息
    - exit_messages: 卖出消息列表
    - update_messages: 更新消息（止损调整等）

class MessageGrouper:
    """消息分组器 - 将消息按交易组聚合"""
    - group_messages(): 主要分组逻辑
    - _extract_symbol(): 提取交易标的
    - _classify_message(): 分类消息类型
    - _generate_group_id(): 生成唯一组ID
```

**2. 智能消息分类**

**分类规则：**

```python
# 买入消息
entry_keywords = ['call', 'put', 'calls', 'puts', '买入', 'buy']

# 卖出消息
exit_keywords = ['出', '卖', 'sell', 'exit', '平仓']

# 更新消息
update_keywords = ['止损', '上移', '调整', 'stop loss', 'trailing']
```

**分类优先级：** 卖出 > 更新 > 买入

**3. 交易标的提取**

**支持的格式：**

```python
'$GILD'              # $符号格式
'GILD - $130'        # 标的-价格格式
'GILD call'          # 标的+期权类型
'NVDA put'           # 标的+期权类型
```

**正则表达式：**
```python
r'\$([A-Z]{1,5})\b'           # $GILD
r'\b([A-Z]{2,5})\s*-\s*\$'    # GILD - $130
r'\b([A-Z]{2,5})\s+call'      # GILD call
r'\b([A-Z]{2,5})\s+put'       # GILD put
```

**4. 消息组ID生成**

**生成逻辑：**
```python
key = f"{symbol}_{author}_{date}"
hash = md5(key).hexdigest()[:8]
group_id = f"{symbol}_{hash}"

# 示例: GILD_a1b2c3d4
```

**优势：**
- ✅ 同一标的、同一作者、同一天的交易归为一组
- ✅ 短hash便于识别和引用
- ✅ 包含symbol便于快速识别

**5. 关联识别**

**匹配规则：**

```python
# 卖出消息匹配买入消息的条件：
1. 同一交易标的（symbol）
2. 同一作者（author）
3. 同一天（date）
4. 引用内容包含买入消息
```

**关联流程：**
```
卖出消息
  ↓
提取引用中的symbol
  ↓
查找匹配的买入组
  ↓
添加到该组的exit_messages
```

**6. 表格展示格式**

**方式1：详细表格视图**

```
消息组ID        标的     时间                 操作类型    消息内容                                       关联买入
-------------------------------------------------------------------------------
GILD_a1b2c3d4   GILD     Jan 22, 2026 10:41  🟢 买入    GILD - $130 CALLS 这周 1.5-1.60            -
GILD_a1b2c3d4   GILD     Jan 22, 2026 10:45  🔴 卖出    1.9附近出三分之一                          GILD - $130 CALLS 这周 1.5-1.60
GILD_a1b2c3d4   GILD     Jan 22, 2026 10:50  🔴 卖出    2.23出三分之一                             GILD - $130 CALLS 这周 1.5-1.60
GILD_a1b2c3d4   GILD     Jan 22, 2026 10:55  🔴 卖出    2.3附近都出                                GILD - $130 CALLS 这周 1.5-1.60
GILD_a1b2c3d4   GILD     Jan 22, 2026 11:00  🟡 调整    止损上移到2.0                              -
```

**特点：**
- ✅ 类似数据库表格式
- ✅ 每行一条消息
- ✅ 卖出消息显示对应的买入信息
- ✅ 使用emoji标识操作类型

**方式2：分组摘要视图**

```
============================================================
交易消息组汇总表
============================================================

【消息组 #1】
组ID: GILD_a1b2c3d4
交易标的: GILD
消息总数: 5
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

🔄 【止损/调整】 (1条)
   1. 止损上移到2.0
      时间: Jan 22, 2026 11:00 PM
------------------------------------------------------------
```

**特点：**
- ✅ 分组聚合展示
- ✅ 清晰的买入-卖出关联
- ✅ 统计信息一目了然
- ✅ 使用emoji增强可读性

**7. 集成到测试命令**

**修改文件：** `main.py` (第909-955行)

**新的输出流程：**
```
1. 提取原始消息 → EnhancedMessageExtractor
2. 转换为字典格式
3. 消息分组聚合 → MessageGrouper
4. 表格格式展示 → format_as_detailed_table / format_as_table
5. 显示原始消息示例（前5条）
```

#### 使用方法

```bash
# 运行消息提取器测试
python3 main.py --test message-extractor

# 输出内容：
# 1. 详细表格视图 - 数据库表格式
# 2. 分组摘要视图 - 聚合展示
# 3. 原始消息示例 - 前5条详情
```

#### 技术亮点

**1. 引用关系识别**
```python
# 从引用中提取symbol
quoted_symbol = self._get_quoted_symbol(message)

# 匹配买入组
for group in self.groups.values():
    if group.symbol == quoted_symbol and \
       group.entry_message and \
       group.entry_message['author'] == author:
        # 找到匹配的组
```

**2. 智能过滤**
```python
# 优先判断卖出（避免误判）
if any(keyword in content for keyword in exit_keywords):
    return 'exit'

# 再判断更新
if any(keyword in content for keyword in update_keywords):
    return 'update'
```

**3. 去重处理**
```python
# 避免重复创建组
if group_id not in self.groups:
    self.groups[group_id] = TradeMessageGroup(group_id, symbol)
```

#### 预期效果

**优化前（v2.6.4）：**
```
1. 消息组 ID: post_1CXNbKK8oK74QriUZv3rmK
   主消息: 1.9附近出三分之一...

2. 消息组 ID: post_1CXNbLQCCswh8gHbnddMin
   主消息: 2.23出三分之一...

3. 消息组 ID: post_1CXNbPCCiZcSYj6bhdCmUX
   主消息: 2.3附近都出...

❌ 问题：无法看出它们属于同一笔交易
```

**优化后（v2.6.5）：**
```
消息组ID: GILD_a1b2c3d4
交易标的: GILD

📈 买入: GILD - $130 CALLS 这周 1.5-1.60

📉 卖出 (3条):
   1. 1.9附近出三分之一  ⬅️ 对应买入: GILD - $130 CALLS
   2. 2.23出三分之一     ⬅️ 对应买入: GILD - $130 CALLS
   3. 2.3附近都出        ⬅️ 对应买入: GILD - $130 CALLS

✅ 优势：清晰展示交易全貌和关联关系
```

#### 文档更新

- 创建 `doc/MESSAGE_GROUPING.md` - 消息分组详细指南
- 更新 `README.md` - 添加新功能说明

#### 注意事项

**1. 分组依赖准确的symbol提取**
- 如果symbol提取失败，消息可能被单独分组
- 需要确保消息中包含清晰的交易标的

**2. 关联依赖引用信息**
- 卖出消息应该引用买入消息
- 如果没有引用，通过同一天、同一作者、同一标的匹配

**3. 同一天多笔交易**
- 同一标的、同一天可能有多笔交易
- 使用时间顺序和引用关系区分

---

## [2.6.4] - 2026-02-01

### 🎯 消息提取器优化 - 基于DOM分析的精确调整

**问题诊断：**

通过DOM导出工具分析发现v2.6.2的消息提取器存在以下问题：
1. **作者信息提取失败** - 所有消息显示"(未识别)"
2. **时间戳识别错误** - 所有消息显示"(继承自上一条)"
3. **消息内容重复** - 同一消息被提取多次

**根本原因：**

选择器与Whop页面实际DOM结构不匹配：
- 消息容器使用 `class="group/message"` 和 `data-message-id` 属性
- 作者信息不是标准HTML标签,而是文本节点
- 时间戳格式为 "Jan 22, 2026 10:41 PM"
- 消息内容嵌套在 `bg-gray-3 rounded-[18px]` 样式的div中

#### 调整内容

**1. 优化消息容器选择器**

```javascript
// 旧选择器(不准确)
'[class*="message"]'

// 新选择器(精确)
'[data-message-id]',          // 最准确:有唯一ID
'.group\\/message',           // Whop使用的类名
'[class*="group/message"]'    // 包含group/message
```

**修改文件：** `scraper/message_extractor.py` (第101-125行)

**优势：**
- ✅ 按优先级尝试多个选择器
- ✅ 添加日志输出便于调试
- ✅ 避免匹配到无关元素

**2. 增强作者信息提取**

```javascript
// 新增智能提取策略
1. 尝试从特定类名提取 (fui-Text)
2. 过滤时间、日期、符号等无关文本
3. 从文本节点中查找符合规则的作者名
```

**修改文件：** `scraper/message_extractor.py` (第134-204行)

**过滤规则：**
- ✅ 长度2-50字符
- ✅ 不包含 PM/AM、日期、数字
- ✅ 不包含交易符号($、•)
- ✅ 不匹配时间格式

**3. 改进时间戳提取**

```javascript
// 优先级顺序
1. <time> 标签 (HTML5语义化)
2. [datetime] 属性
3. 正则表达式匹配

// 支持的时间格式
- "Jan 22, 2026 10:41 PM"  // 英文格式
- "1月22日 10:41"          // 中文格式
- "2026-01-22 10:41"       // ISO格式
- "10:41 PM"               // 简短格式
```

**修改文件：** `scraper/message_extractor.py` (第206-251行)

**优势：**
- ✅ 多种格式支持
- ✅ 优先使用语义化标签
- ✅ 正则表达式兜底

**4. 精确消息内容提取**

```javascript
// 针对Whop页面结构
const contentSelectors = [
    '[class*="bg-gray-3"][class*="rounded"]',  // Whop消息气泡
    '[class*="whitespace-pre-wrap"]',          // 消息文本容器
    'p',                                        // 段落标签
    '[class*="prose"]'                         // 通用内容类
];

// 智能过滤
1. 排除元数据(作者、时间、符号)
2. 去重(避免重复提取)
3. 只保留有效内容
```

**修改文件：** `scraper/message_extractor.py` (第288-342行)

**过滤逻辑：**
- ✅ 排除作者和时间戳
- ✅ 排除单字符符号(•)
- ✅ 排除日期时间格式
- ✅ 使用Set去重

**5. 优化引用识别**

```javascript
// 新增Whop特定选择器
'[class*="peer/reply"]',       // Whop引用样式
'[class*="border-t"]'          // 引用边框样式

// 添加长度验证
if (quoteText.length > 5 && quoteText.length < 500) {
    // 只保留合理长度的引用
}
```

**修改文件：** `scraper/message_extractor.py` (第253-274行)

#### 技术细节

**转义斜杠：**
```javascript
'.group\\/message'  // 需要转义斜杠
```

**去重策略：**
```javascript
const uniqueTexts = [...new Set(texts)];  // ES6 Set去重
```

**调试输出：**
```javascript
console.log(`✅ 使用选择器: ${selector}, 找到 ${messageElements.length} 个消息`);
```

#### 预期改进

**提取准确性：**
- ✅ 作者信息正确识别
- ✅ 时间戳准确提取
- ✅ 消息内容不重复
- ✅ 引用关系正确关联

**提取效率：**
- ✅ 减少无效匹配
- ✅ 优先级选择器减少尝试次数
- ✅ 去重减少冗余数据

**调试体验：**
- ✅ 控制台输出选择器使用情况
- ✅ 便于定位提取问题
- ✅ 支持DOM导出工具分析

#### 测试方法

```bash
# 1. 重新测试消息提取器
python3 main.py --test message-extractor

# 2. 查看提取结果
# 检查输出中的:
# - 作者名称是否正确
# - 时间戳是否准确
# - 消息内容是否完整
# - 是否有重复消息

# 3. 如果还有问题,重新导出DOM
python3 main.py --test export-dom

# 4. 根据新的DOM分析继续调整
```

#### 文档更新

- 更新 `doc/MESSAGE_CONTEXT.md` 添加Whop页面结构说明
- 更新 `doc/DEBUG_DOM.md` 添加选择器调整案例

---

## [2.6.3] - 2026-02-01

### 🔧 DOM导出工具 - 调试页面结构

**新增功能：导出页面DOM和截图用于本地分析**

#### 问题背景

v2.6.2 的消息提取器在实际测试中发现：
- 作者信息未正确提取
- 时间戳识别失败
- 消息重复和关联错误

**根本原因：**
- 页面选择器与实际结构不匹配
- 需要查看实际的DOM结构来调整选择器

#### 解决方案

**新增 `export_page_dom()` 函数**

自动导出三个关键文件：

1. **完整HTML** (`debug/page_YYYYMMDD_HHMMSS.html`)
   - 页面的完整HTML源代码
   - 可在浏览器中打开查看结构
   - 使用开发者工具检查元素

2. **页面截图** (`debug/page_YYYYMMDD_HHMMSS.png`)
   - 完整页面截图（full page）
   - 对照实际显示效果
   - 验证元素位置和可见性

3. **结构分析** (`debug/analysis_YYYYMMDD_HHMMSS.txt`)
   - 自动分析可能的消息容器
   - 列出各种选择器的匹配情况
   - 显示包含交易关键字的元素路径
   - 提供样本HTML和属性信息

#### 使用方法

```bash
# 导出页面DOM和截图
python3 main.py --test export-dom
```

**输出示例：**
```
============================================================
导出页面DOM和截图
============================================================

✅ 配置验证通过
🚀 正在启动浏览器...
✅ 浏览器已启动
✅ 已登录
✅ 页面导航成功

📝 正在导出HTML到: debug/page_20260201_230500.html
✅ HTML已保存 (1,234,567 字符)

📸 正在截图到: debug/page_20260201_230500.png
✅ 截图已保存

🔍 正在分析页面结构...
✅ 分析已保存

============================================================
导出完成！
============================================================

📁 输出文件:
   1. HTML: debug/page_20260201_230500.html
   2. 截图: debug/page_20260201_230500.png
   3. 分析: debug/analysis_20260201_230500.txt

💡 下一步:
   1. 打开 HTML 查看页面结构
   2. 查看截图对照实际显示
   3. 阅读分析了解可用的选择器
   4. 根据分析结果调整 message_extractor.py
```

#### 分析文件内容

**analysis_YYYYMMDD_HHMMSS.txt** 包含：

```
============================================================
页面结构分析
============================================================

URL: https://whop.com/joined/...
标题: Stock and Option Trading
总元素数: 3,456

============================================================
可能的消息容器选择器
============================================================

1. 选择器: [class*="message"]
   数量: 42
   类名: message-container flex flex-col
   ID: msg-12345
   属性:
      data-message-id="post_1CXNbKK8..."
      class="message-container flex flex-col"
   
   示例文本:
   GILD - $130 CALLS 这周 1.5-160
   
   示例HTML:
   <div class="message-container" data-message-id="...">
   ...

2. 选择器: [role="article"]
   数量: 38
   ...

============================================================
包含交易关键字的元素
============================================================

1. 关键字: GILD
   文本: GILD - $130 CALLS 这周 1.5-160
   路径:
      <DIV class='prose' id=''>
         <P class='text-content' id=''>
            <SPAN class='' id=''>
   ...
```

#### 调试流程

1. **运行导出命令**
   ```bash
   python3 main.py --test export-dom
   ```

2. **查看HTML文件**
   - 在浏览器中打开 `debug/page_*.html`
   - 使用开发者工具（F12）检查消息元素
   - 找到实际的类名、ID、属性

3. **对照截图**
   - 打开 `debug/page_*.png`
   - 确认要提取的消息位置
   - 验证元素的可见性

4. **阅读分析报告**
   - 打开 `debug/analysis_*.txt`
   - 查看所有可能的选择器
   - 选择最合适的选择器

5. **调整选择器**
   - 编辑 `scraper/message_extractor.py`
   - 更新 `messageSelectors`、`authorSelectors` 等
   - 重新测试提取效果

#### 优势

**快速定位问题：**
- ✅ 无需猜测页面结构
- ✅ 直接查看实际DOM
- ✅ 对照截图验证

**高效调试：**
- ✅ 本地分析，不需要反复登录
- ✅ 完整的结构信息
- ✅ 自动生成选择器建议

**便于协作：**
- ✅ 可分享debug文件
- ✅ 便于问题报告
- ✅ 帮助改进选择器

#### 注意事项

1. **隐私保护**
   - debug文件包含实际页面内容
   - 不要提交到公开仓库
   - .gitignore 已添加 debug/ 目录

2. **文件大小**
   - HTML文件可能较大（1-5MB）
   - 截图文件通常 500KB-2MB
   - 定期清理debug目录

3. **非无头模式**
   - 导出时使用非无头模式（headless=False）
   - 可以看到浏览器操作过程
   - 确保正确加载和截图

---

## [2.6.2] - 2026-02-01

### 🚀 增强的消息提取器 - 识别上下文和引用关系

**重大改进：智能识别消息的关联和引用**

#### 1. **消息关联识别**
   
   **问题场景：**
   - Whop 页面中，连续消息的第一条有时间戳
   - 后续关联消息没有时间戳，但属于同一个交易信号
   - 例如：开仓消息 → 止损消息 → 多个止盈消息

   **解决方案：**
   - ✅ 识别有时间戳的消息作为消息组起点
   - ✅ 将无时间戳的后续消息关联到同一组
   - ✅ 自动继承作者和时间戳信息
   - ✅ 保持完整的交易上下文

#### 2. **引用消息识别**
   
   **问题场景：**
   - 止损/止盈消息通常引用原始的开仓消息
   - 需要知道引用的是哪个标的和价格

   **解决方案：**
   - ✅ 识别消息的引用关系
   - ✅ 提取被引用消息的内容
   - ✅ 将引用内容添加到消息上下文
   - ✅ 提供完整的交易决策信息

#### 3. **新增 EnhancedMessageExtractor 类**

**主要功能：**
```python
# 消息组结构
class MessageGroup:
    - group_id: 消息组ID
    - author: 作者
    - timestamp: 时间戳
    - primary_message: 主消息
    - related_messages: 关联消息列表
    - quoted_message: 引用的消息预览
    - quoted_context: 引用的完整上下文
```

**提取能力：**
- 📊 识别消息元数据（作者、时间、ID）
- 🔗 识别消息组和关联关系
- 💬 识别引用/回复关系
- 📝 提供完整上下文内容

#### 4. **集成到监控系统**

**monitor.py 更新：**
- ✅ 导入 `EnhancedMessageExtractor`
- ✅ `scan_once()` 优先使用增强提取器
- ✅ 保留原始提取方法作为备用
- ✅ 自动降级处理异常情况

#### 5. **新增测试命令**

```bash
# 测试增强的消息提取器
python3 main.py --test message-extractor

# 查看提取的消息组、关联关系和引用内容
```

**测试输出示例：**
```
📨 消息组详情:
============================================================

1. 消息组 ID: msg-12345
   作者: xiaozhaolucky
   时间: Jan 22, 2026 10:41 PM
   主消息: GILD - $130 CALLS 这周 1.5-160
   关联消息数: 0
   
   完整内容:
      GILD - $130 CALLS 这周 1.5-160
------------------------------------------------------------

2. 消息组 ID: msg-12346
   作者: xiaozhaolucky
   时间: Jan 22, 2026 10:41 PM (继承)
   主消息: 小仓位 止损 在 1.3
   关联消息数: 3
      1. 1.9附近出三分之一
      2. 2.23出三分之一
      3. 2.3附近都出
   引用内容: GILD - $130 CALLS ...
   
   完整内容:
      [引用] GILD - $130 CALLS 这周 1.5-160
      小仓位 止损 在 1.3
      1.9附近出三分之一
      2.23出三分之一
      2.3附近都出
```

#### 6. **优势**

**解析准确性提升：**
- ✅ 完整的交易上下文（买入 + 止损 + 止盈）
- ✅ 正确关联相关消息
- ✅ 减少歧义和误解析

**用户体验改进：**
- ✅ 清晰的消息组织结构
- ✅ 可追溯的交易决策过程
- ✅ 便于验证和调试

**系统健壮性：**
- ✅ 自动降级到原始提取方法
- ✅ 异常处理和错误恢复
- ✅ 向后兼容

**使用建议：**
- 首次使用建议运行测试命令查看提取效果
- 如遇到兼容性问题会自动降级
- 可通过日志查看提取过程

---

## [2.6.1] - 2026-02-01

### 🔧 Cookie 存储路径优化 + 测试模式修复

**改进内容：**

1. **统一 Cookie 存储位置**
   - Cookie 文件从根目录移动到 `.auth/` 目录
   - 新路径：`.auth/whop_state.json`
   - 自动创建 `.auth/` 目录

2. **修改的文件：**
   - ✅ `.env`: 更新 `STORAGE_STATE_PATH` 为 `.auth/whop_state.json`
   - ✅ `whop_login.py`: 
     - 默认存储路径改为 `.auth/whop_state.json`
     - 保存前自动创建目录
     - 导入 `os` 和 `pathlib.Path`
   - ✅ `.gitignore`: 添加 `.auth/` 目录忽略规则

3. **自动迁移：**
   - 已存在的 `storage_state.json` 已移动到 `.auth/whop_state.json`

4. **测试模式修复：**
   - 🐛 修复 `test_whop_scraper` 中的无效 `display_mode="simple"`
   - ✅ 改为 `display_mode="raw"` 只显示原始消息
   - ✅ 修复 `output_file=None` 导致的崩溃
   - ✅ 使用临时文件替代 None

**使用说明：**
```bash
# 重新登录（如需要）
python3 whop/whop_login.py

# Cookie 将保存到 .auth/whop_state.json

# 测试页面抓取（只显示原始消息）
python3 main.py --test whop-scraper
```

---

## [2.6.0] - 2026-02-01

### 🚀 事件驱动监控 + 定时状态报告

**重大改进：从轮询模式升级为事件驱动监控**

#### 1. **事件驱动监控 (MutationObserverMonitor)**
   
   **核心改进：**
   - ✅ 使用 `MutationObserver` API 监听 DOM 变化
   - ✅ 只在消息更新时才触发处理逻辑
   - ✅ 大幅降低 CPU 占用和不必要的 API 调用
   - ✅ 实时响应，消息出现即刻处理

   **技术实现：**
   - 在页面注入 MutationObserver 监听器
   - 监听指定容器的子元素变化
   - 新消息添加到队列，定期检查并处理
   - 支持多种容器选择器自动探测

#### 2. **定时状态报告**
   
   **新增功能：**
   - ⏰ 定时输出监控器运行状态
   - 📊 显示处理消息数、解析指令数
   - 🕐 显示运行时长和空闲时间
   - ⚠️ 显示错误次数和去重缓存大小

   **状态信息包括：**
   ```
   📊 监控器运行状态
   ========================================
   运行状态:       ✅ 运行中
   处理消息数:     42
   解析指令数:     15
   错误次数:       0
   去重缓存:       42 条
   运行时长:       1:23:45
   空闲时间:       12 秒
   ========================================
   ```

#### 3. **新增配置选项**
   
   **`.env` 新增配置：**
   ```bash
   MONITOR_MODE=event              # 监控模式: event=事件驱动, poll=轮询模式
   CHECK_INTERVAL=0.5              # 事件驱动模式检查间隔（秒）
   STATUS_REPORT_INTERVAL=60       # 状态报告间隔（秒）
   ```

   **Config 新增属性：**
   - `MONITOR_MODE`: 选择监控模式
   - `CHECK_INTERVAL`: 事件驱动模式的检查间隔
   - `STATUS_REPORT_INTERVAL`: 状态报告间隔

#### 4. **优化风险控制器**
   
   **问题修复：**
   - 🐛 修复了 `market_value` KeyError 错误
   - ✅ 使用实时报价 API 获取期权价格
   - ✅ 添加降级方案（实时报价 → 成本价）
   - ✅ 无持仓时跳过风险检查，避免不必要的 API 调用

   **日志优化：**
   - 无持仓时使用 DEBUG 级别日志
   - 减少日志噪音，只显示重要信息

#### 5. **命令行参数支持**
   
   **新增测试模式：**
   ```bash
   # 测试解析器
   python3 main.py --test parser
   
   # 测试 Whop 页面抓取

   python3 main.py --test whop-scraper
   
   # 测试交易接口
   python3 main.py --test broker
   
   # 测试配置文件
   python3 main.py --test config
   ```

#### 6. **自动创建日志目录**
   
   **问题修复：**
   - 🐛 修复了 `logs` 目录不存在导致的 FileNotFoundError
   - ✅ 程序启动时自动创建 `logs` 目录

**使用建议：**
- 推荐使用 `event` 模式以获得最佳性能
- 可根据需要调整 `STATUS_REPORT_INTERVAL` 来控制状态报告频率
- 如遇到兼容性问题，可切换回 `poll` 模式

---

## [2.5.4] - 2026-02-01

### 🎨 取消订单表格样式优化

**优化内容：**
将取消订单表格的边框颜色优化为极浅灰色：

1. **视觉优化**
   - 取消订单表格使用极浅灰色边框（`dim white`）
   - 非常柔和的视觉效果，不突兀
   - 区别于失败订单的醒目红色边框
   - "CANCEL"操作文字仍保持黄色高亮

2. **颜色语义**
   - 🔴 红色边框：失败订单（严重错误，需关注）
   - ⚪ 极浅灰边框：取消订单（中性操作，已处理）
   - 🟢 绿色边框：卖出成功（正常操作）
   - 🔵 蓝色边框：买入成功（正常操作）

**优化效果：**
- ✅ 取消订单样式极其柔和，不占据视觉焦点
- ✅ 与失败订单有明确区分（失败=红色醒目，取消=浅灰低调）
- ✅ 视觉层次清晰，重要程度一目了然

---

## [2.5.3] - 2026-02-01

### 🎨 失败订单红色边框表格展示

**新增功能：**
为卖出失败的订单添加红色边框表格展示：

1. **失败订单表格**
   - 新增 `print_order_failed_table()` 函数
   - 使用红色边框突出显示失败订单
   - 标题显示"❌ 订单失败"
   - "失败原因"行使用红色粗体高亮

2. **异常处理优化**
   - `submit_stock_order()`: 捕获 ValueError 异常并展示失败表格
   - `submit_option_order()`: 同样添加失败表格展示
   - 失败订单表格在异常抛出前显示

3. **显示内容**
   - 期权/股票代码
   - 操作方向（SELL 红色，BUY 绿色）
   - 数量和价格
   - 总价
   - 失败原因（红色粗体）
   - 账户模式
   - 备注

**优化效果：**
- ✅ 失败订单一目了然，红色边框醒目
- ✅ 失败原因高亮显示
- ✅ 保持与成功订单相同的表格风格

---

## [2.5.2] - 2026-02-01

### 🔒 卖出持仓检查功能

**新增功能：**
为正股和期权卖出操作添加持仓数量验证：

1. **持仓检查逻辑**
   - 新增 `_check_position_for_sell()` 方法
   - 卖出前自动查询当前持仓
   - 验证股票/期权是否有持仓
   - 验证可用持仓数量是否足够

2. **卖出订单优化**
   - `submit_stock_order()`: 卖出时先检查持仓，无持仓或数量不足则拒绝订单
   - `submit_option_order()`: 同样添加持仓检查
   - 买入操作继续进行风险检查
   - 卖出操作跳过风险检查（因为卖出不需要资金）

3. **错误提示优化**
   - 无持仓时明确提示"没有持仓"
   - 持仓不足时提示"可用持仓仅 X 股/张"
   - 使用彩色警告信息提示用户

4. **测试用例**
   - 新增 `test_sell_without_position()`: 测试卖出无持仓股票
   - 新增 `test_sell_exceed_position()`: 测试卖出超过持仓数量
   - 两个测试用例会临时关闭 Dry Run 模式以验证持仓检查逻辑

**技术细节：**
- 持仓检查使用 `available_quantity` 字段（可用数量）
- Dry Run 模式下仍会跳过持仓检查（用于测试）
- 持仓检查失败抛出 `ValueError` 异常

**验证结果：**
✅ 持仓检查功能验证通过
- 无持仓时无法卖出
- 超过可用持仓数量时无法卖出
- 正常持仓范围内可以成功卖出

---

## [2.5.1] - 2026-02-01

### 📊 表格显示优化

**优化内容：**
优化正股报价和持仓信息的表格显示：

1. **新增股票报价表格函数**
   - 新增 `print_stock_quotes_table()` 函数
   - 表格化显示股票报价信息（代码、最新价、涨跌幅、开盘、最高、最低、成交量、成交额）
   - 涨跌幅使用彩色显示（绿色上涨🟢，红色下跌🔴）
   - 成交额使用百万（M）单位简化显示

2. **持仓表格优化**
   - 移除"可用数量"列，避免表格内容被截断
   - 扩展列宽，显示更完整的信息
   - 列标题改为"代码/期权"，更通用（支持正股和期权）
   - 自动判断期权/正股计算市值（期权×100，正股×1）
   - 简化市场列显示，移除 "Market." 前缀（如 "HK" 而不是 "Market.HK"）

3. **测试文件优化**
   - `test_stock_integration.py` 使用表格显示股票报价
   - 单股票和多股票报价都使用统一的表格格式
   - 额外显示涨跌额和涨跌幅信息

**优化效果：**
- ✅ 股票报价一目了然，彩色标识涨跌
- ✅ 持仓信息显示更完整，无截断
- ✅ 表格样式统一美观

---

## [2.5.0] - 2026-02-01

### 🚀 正股交易API支持

**新增功能：**
为长桥券商集成添加完整的正股交易API支持：

1. **正股报价查询**
   - `get_stock_quote()`: 获取单个或多个股票的实时报价
   - 支持涨跌幅计算、成交量、成交额等详细信息
   - 自动处理市场后缀（.US、.HK）

2. **正股订单提交**
   - `submit_stock_order()`: 提交正股买卖订单
   - 支持限价单（LIMIT）和市价单（MARKET）
   - 支持止盈止损参数（trigger_price、trailing_percent、trailing_amount）
   - 市价单使用实时报价进行风险检查

3. **风险控制优化**
   - 市价单自动获取当前价格用于风险检查
   - 风险检查失败时提供详细的错误信息
   - 支持模拟账户和真实账户的风险控制

4. **集成测试**
   - 新增 `test/broker/test_stock_integration.py` 正股API集成测试
   - 涵盖8个测试场景：配置加载、账户查询、报价查询、订单提交、持仓查询等
   - 美观的表格化输出和测试总结

**技术细节：**
- 正股订单数量以股数计算（期权以合约数计算）
- 正股订单金额 = 价格 × 数量（期权订单金额 = 价格 × 数量 × 100）
- 支持 Dry Run 模式进行安全测试

**验证结果：**
✅ 所有正股API接口验证通过
- 多股票报价查询（AAPL、TSLA、NVDA、MSFT、GOOGL）
- 单股票详细报价
- 限价单提交
- 市价单提交
- 订单和持仓查询

---

## [2.4.11] - 2026-02-01

### 📊 订单汇总表格优化

**优化内容：**
优化 `print_orders_summary_table` 函数的显示格式：

1. **移除策略列**：当日订单不需要显示策略信息，简化表格
2. **扩展状态列**：将状态列宽度从12扩展到20，完整显示订单状态
3. **简化状态显示**：移除 "OrderStatus." 前缀，直接显示状态名称（如 "Canceled", "NewOrder"）

**优化效果：**
- ✅ 表格更简洁，信息更清晰
- ✅ 订单状态一目了然（不再被截断为 "OrderStatus…"）
- ✅ 可以快速识别已撤销、已成交等订单状态

---

## [2.4.10] - 2026-02-01

### 🛠️ 批量撤销订单工具

**新增功能：**
创建 `cancel_all_orders.py` 批量撤销今日订单的工具脚本：

1. **订单查询**：自动获取并显示今日所有订单
2. **智能过滤**：自动识别可撤销的订单（排除已完成、已撤销等状态）
3. **安全确认**：撤销前需要用户手动确认
4. **批量撤销**：逐个撤销订单并显示详细进度
5. **结果汇总**：统计成功、失败、跳过的订单数量

**可撤销的订单状态：**
- `NotReported` - 待报
- `ReplacedNotReported` - 待报修改
- `PendingReplace` - 修改待报
- `NewOrder` - 已报
- `PartiallyFilled` - 部分成交
- `RejectedCancel` - 撤销已拒绝

**使用文档：**
- 新增 `README_CANCEL_ORDERS.md` 详细使用说明

---

## [2.4.9] - 2026-02-01

### 📊 集成测试表格化显示优化

**优化内容：**
修改 `test_longport_integration.py` 测试文件，使用表格化函数替代日志输出：

1. **账户信息**：使用 `print_account_info_table()` 显示账户余额
2. **当日订单**：使用 `print_orders_summary_table()` 显示所有订单（移除10个订单的限制）
3. **持仓信息**：使用 `print_positions_table()` 显示当前持仓

**修改前（日志输出）：**
```
2026-02-01 21:08:01,510 - __main__ - INFO - 账户模式: paper
2026-02-01 21:08:01,510 - __main__ - INFO - 总资金: 766,793.34 HKD
2026-02-01 21:08:01,510 - __main__ - INFO - 可用资金: 116,751.85 HKD
```

**修改后（表格显示）：**
```
                 账户余额信息                  
┏━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┓
┃ 项目                 ┃                 金额 ┃
┣━━━━━━━━━━━━━━━━━━━━━━╋━━━━━━━━━━━━━━━━━━━━━━┫
┃ 总资产               ┃          $766,793.34 ┃
┃ 可用资金             ┃          $116,499.71 ┃
┃ 持仓市值             ┃                $0.00 ┃
┃ 冻结资金             ┃          $650,293.63 ┃
┃ 币种                 ┃                  HKD ┃
┃ 账户模式             ┃          🧪 模拟账户 ┃
┗━━━━━━━━━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━━━━━━━━━┛
```

**优势：**
- ✅ 信息展示更直观清晰
- ✅ 统一使用表格格式，提升专业性
- ✅ 与其他订单相关的显示保持一致
- ✅ 便于快速识别关键信息

---

## [2.4.8] - 2026-02-01

### 📋 订单表格格式统一

**优化内容：**
- 统一所有订单表格格式为标准的两列格式（字段-值）
- `print_order_table()` 从简化的单列格式改为标准两列格式
- 与 `print_order_search_table()` 保持完全一致的显示风格

**修改前（订单提交 - 简化格式）：**
```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ AAPL 260202 $252.5 CALL          ┃
┃ ──────────────────────────────── ┃
┃ BUY × 1 @ $5.00 = $500.00        ┃
┃ 策略: 止损: $3.00                ┃
┃ #1202...6 | submitted | 🧪 模拟  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```

**修改后（订单提交 - 标准格式）：**
```
                  AAPL 260202 $252.5 CALL                  
┏━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ 订单ID       ┃ 1202601196670431232                      ┃
┃ 期权         ┃ AAPL 260202 $252.5 CALL                  ┃
┃ 操作方向     ┃ BUY                                      ┃
┃ 数量         ┃ 1                                        ┃
┃ 价格         ┃ $5.00                                    ┃
┃ 总价         ┃ $500.00                                  ┃
┃ 策略         ┃ 止损: $3.00                              ┃
┃ 状态         ┃ submitted                                ┃
┃ 账户模式     ┃ 🧪 模拟账户                              ┃
┃ 备注         ┃ Test order with stop loss                ┃
┗━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```

**优势：**
- ✅ 格式统一：所有订单表格使用相同的两列格式
- ✅ 信息完整：显示完整的字段名和值
- ✅ 易于阅读：字段名左对齐，值右对齐，一目了然
- ✅ 专业性强：符合专业交易系统的展示规范

---

## [2.4.7] - 2026-02-01

### 🎨 边框样式增强优化

**优化内容：**

1. **边框加粗**：所有表格使用 `box.HEAVY` 样式，边框更粗更醒目
2. **撤销订单边框改色**：从灰色改为红色，警示性更强
3. **简化表头**：修改订单和撤销订单表格去除"字段/值"表头行，更简洁

**边框颜色规范：**
- **购买订单（BUY）**：🔵 蓝色粗体边框 `bold blue`
- **售卖订单（SELL）**：🟢 绿色粗体边框 `bold green`
- **修改订单（MODIFY）**：🟡 黄色粗体边框 `bold yellow`
- **撤销订单（CANCEL）**：🔴 红色粗体边框 `bold red`

**效果对比：**
```
修改前（细边框）：
┌────────────────┐
│ 订单信息       │
└────────────────┘

修改后（粗边框）：
┏━━━━━━━━━━━━━━━━┓
┃ 订单信息       ┃
┗━━━━━━━━━━━━━━━━┛
```

**修改订单表格（去除表头）：**
```
修改前：
┏━━━━━━┳━━━━━━┳━━━━━━┓
┃ 字段 ┃ 原值 ┃ 新值 ┃  ← 表头行
┡━━━━━━╇━━━━━━╇━━━━━━┩
│ 数量 │ 1    │ 1 → 3│
└──────┴──────┴──────┘

修改后：
┏━━━━━━┳━━━━━━┳━━━━━━┓
┃ 数量 ┃ 1    ┃ 1 → 3┃  ← 直接显示内容
┗━━━━━━┻━━━━━━┻━━━━━━┛
```

**优势：**
- ✅ 粗边框更醒目，视觉冲击力更强
- ✅ 红色边框警示撤销操作，降低误操作风险
- ✅ 去除冗余表头，表格更简洁高效
- ✅ 统一的粗线样式，提升专业性

---

## [2.4.6] - 2026-02-01

### 🎨 订单表格彩色边框优化

**优化内容：**
为不同类型的订单表格添加彩色粗体边框，增强视觉识别度：

- **购买订单（BUY）**：蓝色粗体边框 `bold blue`
- **售卖订单（SELL）**：绿色粗体边框 `bold green`
- **修改订单（MODIFY）**：黄色粗体边框 `bold yellow`
- **撤销订单（CANCEL）**：灰色粗体边框 `bold bright_black`

**修改的函数：**
- `print_order_table()` - 订单提交表（蓝色/绿色边框）
- `print_order_search_table()` - 订单查询表（蓝色/绿色边框）
- `print_order_modify_table()` - 订单修改表（黄色边框）
- `print_order_cancel_table()` - 订单撤销表（灰色边框）

**效果展示：**
```
购买订单：
╔════════════════════════════╗  ← 蓝色粗体边框
║ AAPL 260207 $250 CALL      ║
║ BUY × 2 @ $5.00            ║
╚════════════════════════════╝

售卖订单：
╔════════════════════════════╗  ← 绿色粗体边框
║ TSLA 260214 $250 PUT       ║
║ SELL × 1 @ $4.50           ║
╚════════════════════════════╝

修改订单：
╔════════════════════════════╗  ← 黄色粗体边框
║ 订单修改详情               ║
╚════════════════════════════╝

撤销订单：
╔════════════════════════════╗  ← 灰色粗体边框
║ 订单撤销信息               ║
╚════════════════════════════╝
```

**优势：**
- ✅ 视觉区分度更高：不同操作类型一目了然
- ✅ 快速识别：通过颜色快速判断订单类型
- ✅ 专业美观：提升界面的专业性和美观度
- ✅ 减少误操作：颜色提醒降低操作失误风险

---

## [2.4.5] - 2026-02-01

### 🐛 修复 Decimal 类型错误

**问题描述：**
在计算订单总价时，由于 `price` 和 `quantity` 可能是 `Decimal` 类型，与 `int` 类型的乘数相乘时会抛出类型错误：
```
unsupported operand type(s) for *: 'float' and 'decimal.Decimal'
```

**修复内容：**
- 在 `format_total_value()` 函数中，将 `price` 和 `quantity` 强制转换为 `float` 类型
- 在 `print_order_modify_table()` 中的总价计算，同样进行类型转换
- 在简洁视图的总价计算中添加类型转换

**修复代码：**
```python
# 修复前
total = price * quantity * multiplier

# 修复后
total = float(price) * float(quantity) * multiplier
```

**影响范围：**
- ✅ 订单提交显示
- ✅ 订单查询显示
- ✅ 订单修改对比
- ✅ 订单撤销显示
- ✅ 订单列表汇总

---

## [2.4.4] - 2026-02-01

### 💰 订单价格和总价分离显示优化

**优化内容：**
- 将价格信息拆分为两个独立字段：**价格**（单价）和 **总价**（合约总价值）
- 新增 `format_total_value()` 函数，计算并格式化总价（单价 × 数量 × 100）
- 总价在所有表格中默认显示为**蓝色粗体**，提升可读性
- 订单修改表中，总价变更时显示为**黄色粗体**高亮

**效果对比：**
```
修改前：
│ 价格         │ $5.00 x 100 = $500.00                    │

修改后：
│ 价格         │ $5.00                                    │
│ 总价         │ $1000.00                                 │ ← 蓝色显示
```

**订单修改表对比：**
```
┃ 字段         ┃ 原值                 ┃ 新值                 ┃
┃ 价格         ┃ $5.00                ┃ $5.00 → $4.50        ┃
┃ 总价         ┃ $500.00              ┃ $500.00 → $1350.00   ┃ ← 黄色高亮
```

**订单列表汇总新增总价列：**
```
┃ 期权                 ┃ 方向 ┃ 数量 ┃ 价格   ┃ 总价      ┃ 策略      ┃
┃ AAPL 260207 $250 CALL┃ BUY  ┃ 2    ┃ $5.00  ┃ $1000.00  ┃ 止损: ... ┃
```

**优势：**
- ✅ 信息更清晰：价格和总价分离展示，一目了然
- ✅ 视觉突出：总价使用蓝色粗体，一眼看到合约价值
- ✅ 变更明显：修改表中总价变更黄色高亮，快速识别影响
- ✅ 专业性强：符合金融交易界面的专业展示习惯

---

## [2.4.3] - 2026-02-01

### 💰 订单价格显示优化

**优化内容：**
- 所有订单表格的价格栏现在显示完整的计算公式：`单价 x 合约乘数 = 总价值`
- 新增 `format_price()` 函数统一处理价格格式化
- 自动显示期权合约乘数（标准为 100）和每份合约的总价值

**效果对比：**
```
修改前：
│ 价格         │ $5.00                                    │

修改后：
│ 价格         │ $5.00 x 100 = $500.00                    │
```

**修改对比表格：**
```
┃ 字段         ┃ 原值                 ┃ 新值                 ┃
┃ 价格         ┃ $5.00 x 100 =        ┃ $5.00 x 100 =        ┃
┃              ┃ $500.00              ┃ $500.00 → $4.50 x    ┃
┃              ┃                      ┃ 100 = $450.00        ┃
```

**优势：**
- 用户一眼就能看到每份合约的实际价值
- 避免手动计算单价 × 100
- 提升专业性和可读性

---

## [2.4.2] - 2026-02-01

### 📊 订单表格标题统一优化

**优化内容：**
- 统一所有单订单表格标题使用期权语义化名称
- `print_order_table()` 和 `print_order_search_table()` 现在与 `print_order_cancel_table()` 和 `print_order_modify_table()` 保持一致的标题格式
- 标题显示格式：`AAPL 260207 $250 CALL` 而不是通用的 "订单详情" 或 "订单查询"

**效果对比：**
```
修改前：
                         订单详情                          
┌──────────────┬──────────────────────────────────────────┐
│ 订单ID       │ 1202595745459367936                      │
│ 期权         │ AAPL 260202 $252.5 CALL                  │
...

修改后：
                   AAPL 260202 $252.5 CALL                   
┌──────────────┬──────────────────────────────────────────┐
│ 订单ID       │ 1202595745459367936                      │
│ 期权         │ AAPL 260202 $252.5 CALL                  │
...
```

**优势：**
- 提升表格的可读性和专业性
- 用户一眼就能识别是哪个期权的订单
- 所有订单相关表格格式保持一致

---

## [2.4.1] - 2026-02-01

### 📊 订单表格格式优化

#### 单个订单表格改为垂直两列格式

**修改的函数：**
- `print_order_table()` - 订单详情表
- `print_order_search_table()` - 订单查询表
- `print_order_cancel_table()` - 订单撤销表
- `print_order_modify_table()` - 订单修改表
- `print_account_info_table()` - 账户信息表

**新格式特性：**
```
                买入订单详情                
┏━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ 字段         ┃ 值                        ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│              │   AAPL 260207 $250 CALL   │ ← 表格内第一行显示语义化期权名称
├──────────────┼───────────────────────────┤
│ 订单ID       │ 1202580174474850304       │
├──────────────┼───────────────────────────┤
│ 期权名称     │ AAPL260207C250000.US      │ ← 仍显示原始代码
├──────────────┼───────────────────────────┤
│ 操作方向     │ BUY                       │
...
```

**期权代码解析增强：**
- 支持 6 位价格格式：`AAPL260207C250000.US`
- 支持 8 位价格格式：`AAPL260207C00250000.US`
- 语义化输出格式：`TICKER YYMMDD $PRICE CALL/PUT`
- 示例：`AAPL260207C250000.US` → `AAPL 260207 $250 CALL`
- 语义化名称显示在表格内第一行，居中对齐

**表格样式改进：**
- 启用行分隔线（`show_lines=True`），视觉更清晰
- 语义化期权名称采用青色粗体（`bold cyan`），醒目突出

**保持不变：**
- ✅ 订单列表汇总（`print_orders_summary_table()`）仍为横向多列格式
- ✅ 持仓信息列表（`print_positions_table()`）仍为横向多列格式

**影响范围：**
- 订单提交、查询、修改、撤销的输出格式
- 账户信息展示

---

## [2.4.0] - 2026-02-01

### 新增功能 - SEARCH 查询操作标识 🔍

#### 订单查询操作
- ✅ **新增 SEARCH 操作类型**
  - 专门用于标识订单查询操作
  - 使用蓝色（bold blue）标识
  - 与 BUY/SELL/CANCEL 并列的操作类型

- ✅ **订单查询专用表格**
  - 新增 `print_order_search_table()` 函数
  - **操作类型**：显示 SEARCH（蓝色）
  - **订单方向**：显示原始的 BUY/SELL（保持原色）
  - **已成交数量**：显示 executed_quantity
  - **提交时间**：显示 submitted_at

- ✅ **完整的操作类型体系**
  ```
  BUY    (买入) → 绿色 ✅
  SELL   (卖出) → 红色 ❌
  SEARCH (查询) → 蓝色 🔍  ⭐ 新增
  CANCEL (撤销) → 黄色 ⚠️
  ```

#### 显示效果

**查询订单时的输出：**
```
✅ 找到订单
                     订单查询                     
┏━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ 字段         ┃ 值                              ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 订单ID       │ 1202583663460507648             │
│ 期权名称     │ AAPL260202C252500.US            │
│ 操作类型     │ SEARCH                          │ ← 蓝色
│ 订单方向     │ BUY                             │ ← 绿色
│ 数量         │ 2                               │
│ 已成交       │ 0                               │
│ 价格         │ $4.50                           │
│ 策略         │ -                               │
│ 状态         │ OrderStatus.ReplacedNotReported │
│ 提交时间     │ 2026-02-01T19:58:08             │
│ 账户模式     │ 🧪 模拟账户                     │
└──────────────┴─────────────────────────────────┘
```

### 技术实现

- 修改 `broker/order_formatter.py`:
  - `format_side()` 函数添加 SEARCH 支持
  - 新增 `print_order_search_table()` 函数

- 修改 `test/broker/test_order_management.py`:
  - `test_get_order_detail()` 使用新的查询表格

- 更新 `demo_order_format.py`:
  - 新增场景 3：订单查询（SEARCH - 蓝色）
  - 更新场景编号
  - 更新说明文档

### 文档更新

- 新增 `SEARCH_OPERATION_UPDATE.md` - SEARCH 操作详细说明
- 更新演示脚本的颜色说明

### 设计理念

**清晰的语义区分：**
- **操作类型（SEARCH）**：表示"当前操作是查询"
- **订单方向（BUY/SELL）**：表示"订单本身的方向"

这样设计可以：
1. 清晰区分"查询动作"和"订单属性"
2. 保持信息完整性
3. 视觉层次分明

---

## [2.3.0] - 2026-02-01

### 新增功能 - 彩色表格输出 ⭐

#### 订单格式化输出
- ✅ **彩色表格展示订单信息**
  - BUY (买入) - 绿色粗体 ✅
  - SELL (卖出) - 红色粗体 ❌
  - CANCEL (撤销) - 黄色粗体 ⚠️
  
- ✅ **订单详情表**
  - 订单ID
  - 期权名称
  - 操作方向（彩色标识）
  - 数量
  - 价格
  - 策略（止盈止损规则）
  - 状态
  - 账户模式

- ✅ **订单修改对比表** (优化)
  - **只显示有变更的字段**（更简洁）
  - 修改项用箭头表示（如 `1 → 2`）
  - 新值列黄色高亮
  - 底部显示修改统计（如 `共修改 2 个字段`）
  - 订单ID和期权名称始终显示

- ✅ **订单撤销表**
  - 黄色 CANCEL 标识
  - 显示被撤销的订单详情
  - 撤销时间

- ✅ **订单列表汇总表**
  - 紧凑的多订单展示
  - 每个订单一行
  - 彩色方向标识

- ✅ **策略自动格式化**
  - 固定止损: `止损: $3.00`
  - 跟踪止损: `跟踪止损: 5.0%`
  - 跟踪金额: `跟踪金额: $2.00`
  - 组合显示

### 技术实现

- 新增模块: `broker/order_formatter.py`
- 集成到: `broker/longport_broker.py`
- 依赖: `rich>=13.0.0`

### 文档

- ✅ `docs/order_format_guide.md` - 格式化输出完整指南
- ✅ `demo_order_format.py` - 演示脚本

### 示例输出

```
✅ 订单提交成功
                 订单详情                  
┏━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┓
┃ 字段         ┃ 值                   ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━┩
│ 订单ID       │ 1202580174474850304  │
│ 期权名称     │ AAPL260207C250000.US │
│ 操作方向     │ BUY                  │ (绿色)
│ 数量         │ 2                    │
│ 价格         │ $5.00                │
│ 策略         │ 止损: $3.00          │
│ 状态         │ submitted            │
│ 账户模式     │ 🧪 模拟账户          │
└──────────────┴──────────────────────┘
```

---

## [2.2.0] - 2026-02-01

### 新增功能

#### 期权链查询
- ✅ `get_option_expiry_dates()` - 获取期权到期日列表
- ✅ `get_option_chain_info()` - 获取指定到期日的期权链（行权价、期权代码）
- ✅ `get_option_quote()` - 获取期权实时报价

#### 订单管理
- ✅ `cancel_order()` - 撤销订单
- ✅ `replace_order()` - 修改订单（价格、数量）
- ✅ 订单支持止盈止损参数：
  - `trigger_price` - 固定止损触发价
  - `trailing_percent` - 跟踪止损百分比
  - `trailing_amount` - 跟踪止损金额

### 功能增强

#### submit_option_order() 方法增强
新增参数：
```python
submit_option_order(
    symbol,
    side,
    quantity,
    price=None,
    order_type="LIMIT",
    remark="",
    trigger_price=None,        # ⭐ 新增
    trailing_percent=None,     # ⭐ 新增
    trailing_amount=None       # ⭐ 新增
)
```

### 测试
- ✅ `test/broker/test_order_management.py` - 订单管理功能完整测试
- ✅ `test/broker/test_longport_integration.py` - 更新集成测试，包含期权链查询

### 文档
- ✅ `docs/order_management.md` - 订单管理功能完整文档
- ✅ `README.md` - 更新功能特性说明
- ✅ `CHANGELOG.md` - 本更新日志

### 错误修复
- 🐛 修复期权代码转换中的日期解析问题
- 🐛 修复期权链查询 API 属性名问题（price vs strike_price）
- 🐛 修复订单撤销返回值处理

### 已验证功能
所有功能已在模拟账户中测试通过：
- ✅ 期权链查询（26个到期日，41个行权价）
- ✅ 期权实时报价（最新价、开盘、最高、最低、成交量）
- ✅ 带止损的订单提交
- ✅ 跟踪止损订单
- ✅ 订单修改
- ✅ 订单撤销
- ✅ 订单状态查询

---

## [2.1.0] - 2026-01-XX

### 新增功能
- ✅ Cookie 持久化
- ✅ 智能去重（内容哈希 + 消息ID）
- ✅ 自动滚动支持
- ✅ 后台监控工具
- ✅ 长桥证券集成
- ✅ 风险控制模块
- ✅ 持仓管理系统

---

## 使用指南

### 快速测试新功能

#### 1. 测试期权链查询

```bash
cd /Users/txink/Documents/code/playwright
PYTHONPATH=$(pwd) python3 test/broker/test_longport_integration.py
```

查看输出中的"测试 5: 期权链查询"部分。

#### 2. 测试订单管理

```bash
PYTHONPATH=$(pwd) python3 test/broker/test_order_management.py
```

此测试会演示：
- 带止损的订单提交
- 跟踪止损订单
- 订单修改
- 订单撤销

#### 3. 使用新功能

```python
from broker import LongPortBroker, load_longport_config

# 初始化
config = load_longport_config()
broker = LongPortBroker(config)

# 1. 查询期权链
expiry_dates = broker.get_option_expiry_dates("AAPL.US")
option_chain = broker.get_option_chain_info("AAPL.US", expiry_dates[1])

# 2. 提交带止损的订单
order = broker.submit_option_order(
    symbol=option_chain["call_symbols"][20],
    side="BUY",
    quantity=2,
    price=5.0,
    trigger_price=3.0,  # 止损价 $3
    remark="带止损的买入订单"
)

# 3. 修改订单
broker.replace_order(
    order_id=order['order_id'],
    quantity=3,
    price=4.5
)

# 4. 撤销订单
broker.cancel_order(order['order_id'])
```

### 详细文档

- 📖 [订单管理完整文档](./docs/order_management.md)
- 📖 [长桥集成指南](./doc/LONGPORT_INTEGRATION_GUIDE.md)
- 📖 [配置说明](./doc/CONFIGURATION.md)

---

## 贡献者

感谢所有贡献者的付出！

---

## 许可证

MIT License
