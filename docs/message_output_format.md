# 消息输出格式说明

## 📋 概述

`MessageGroup` 提供两种输出格式：
1. **简化格式** (`to_simple_dict()`) - 清晰、结构化的标准格式
2. **完整格式** (`to_dict()`) - 包含所有原始字段，用于高级处理

## 🎯 简化格式（推荐使用）

### 字段说明

```python
{
  "domID": "post_1CXNbG1zAyv8MfM1oD7dEz",     # DOM中的data-message-id
  "content": "小仓位 止损 在 1.3",            # 消息内容
  "timestamp": "Jan 22, 2026 10:41 PM",      # 发送时间
  "refer": "GILD - $130 CALLS 这周 1.5-1.60", # 引用的消息（可为null）
  "position": "first",                       # 消息位置
  "history": []                              # 同组历史消息
}
```

### 字段详解

#### `domID`
- **类型**: `string`
- **来源**: DOM属性 `data-message-id`
- **用途**: 消息的唯一标识符
- **稳定性**: ✅ **持久不变** - 即使页面刷新或重新进入，此ID保持不变
- **应用场景**:
  - 消息去重（避免重复处理同一消息）
  - 历史记录追踪（跨会话识别同一消息）
  - 增量更新（只处理新消息）
  - 消息引用匹配
- **示例**: `"post_1CXNbG1zAyv8MfM1oD7dEz"`

#### `content`
- **类型**: `string`
- **来源**: 消息气泡中的文本内容
- **说明**: 提取自 `<div class="bg-gray-3 rounded-[18px]">` 内的文本
- **示例**: `"小仓位 止损 在 1.3"`

#### `timestamp`
- **类型**: `string`
- **格式**: `月份 日期, 年份 时:分 AM/PM`
- **来源**: 从消息组的**第一条消息**头部提取
- **继承规则**: 
  - 第一条消息：从DOM直接提取
  - 中间/最后消息：继承第一条消息的时间戳
- **示例**: `"Jan 22, 2026 10:41 PM"`

#### `refer`
- **类型**: `string | null`
- **来源**: 引用区域 `<div class="peer/reply">` 中的文本（排除作者名）
- **说明**: 
  - 如果消息引用了其他消息，此字段包含被引用的消息内容
  - 如果没有引用，此字段为 `null`
  - **消息组继承规则**：同一消息组内所有消息共享相同的 `refer` 值
    - 首条消息：从DOM直接提取引用
    - 后续消息（middle、last）：继承首条消息的引用
- **提取细节**（v3.11修复）:
  - DOM中有多个 `span.fui-Text.truncate.fui-r-size-1`
  - 第一个span是作者名（包含 `fui-r-weight-medium`）→ 需要过滤
  - 第二个span是引用内容 → 需要提取
- **示例**: 
  - 有引用: `"GILD - $130 CALLS 这周 1.5-1.60"`
  - 无引用: `null`

#### `position`
- **类型**: `string`
- **取值**: `"single"` | `"first"` | `"middle"` | `"last"`
- **判断依据**: 

| `data-has-message-above` | `data-has-message-below` | `position` 值 |
|-------------------------|-------------------------|--------------|
| `false` | `false` | `"single"` |
| `false` | `true` | `"first"` |
| `true` | `true` | `"middle"` |
| `true` | `false` | `"last"` |

#### `history`
- **类型**: `array of strings`
- **内容**: 当前消息之前同组的所有消息内容（按时间顺序）
- **特点**:
  - 第一条消息（`position="first"` 或 `"single"`）: `history` 为 `[]`
  - 中间消息（`position="middle"`）: `history` 包含第一条到当前之前的所有消息
  - 最后一条消息（`position="last"`）: `history` 包含第一条到当前之前的所有消息
- **示例**:
  - 第一条: `history: []`
  - 第二条: `history: ["第一条消息"]`
  - 第三条: `history: ["第一条消息", "第二条消息"]`
- **提取方式**: 通过DOM结构向上遍历，找到所有同组（`data-has-message-above="true"`）的前序消息

## 📊 完整格式（高级使用）

### 字段说明

```python
{
  "group_id": "post_1CXNbG1zAyv8MfM1oD7dEz",      # 消息ID（同domID）
  "author": "xiaozhaolucky",                     # 作者
  "timestamp": "Jan 22, 2026 10:41 PM",          # 时间戳
  "primary_message": "小仓位 止损 在 1.3",        # 主消息
  "related_messages": [],                        # 关联消息列表
  "quoted_message": "",                          # 引用预览
  "quoted_context": "GILD - $130 CALLS...",      # 引用完整内容
  "has_message_above": false,                    # DOM属性
  "has_message_below": true,                     # DOM属性
  "has_attachment": false,                       # 是否有图片
  "image_url": "",                               # 图片URL
  "position": "first",                           # 位置
  "full_content": "[引用] GILD...\n小仓位..."    # 完整内容
}
```

### 额外字段说明

- `author`: 消息发送者（提取自用户名span）
- `related_messages`: 如果一个DOM容器包含多个消息，额外的消息存储在这里
- `has_attachment`: 是否包含图片附件
- `image_url`: 图片URL（如果有）
- `full_content`: 包含引用和所有消息的完整文本

## 💡 使用示例

### Python代码

```python
from scraper.message_extractor import EnhancedMessageExtractor
from playwright.async_api import async_playwright

async def extract_messages():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        
        # 加载页面...
        
        # 提取消息
        extractor = EnhancedMessageExtractor(page)
        messages = await extractor.extract_message_groups()
        
        # 使用简化格式
        for msg in messages:
            simple = msg.to_simple_dict()
            print(f"ID: {simple['domID']}")
            print(f"内容: {simple['content']}")
            print(f"时间: {simple['timestamp']}")
            print(f"引用: {simple['refer']}")
            print(f"位置: {simple['position']}")
            print("-" * 40)
        
        await browser.close()
```

### 输出示例

```
ID: post_1CXNmCYpbYheKjRX4MLWLE
内容: nvda剩下部分也2.45附近出
时间: Jan 23, 2026 12:51 AM
引用: None
位置: single
历史: []
----------------------------------------
ID: post_1CXNbG1zAyv8MfM1oD7dEz
内容: 小仓位 止损 在 1.3
时间: Jan 22, 2026 10:41 PM
引用: GILD - $130 CALLS 这周 1.5-1.60
位置: first
历史: []
----------------------------------------
ID: post_1CXNbKK8oK74QriUZv3rmK
内容: 1.9附近出三分之一
时间: Jan 22, 2026 10:41 PM
引用: None
位置: middle
历史: ["小仓位 止损 在 1.3"]
----------------------------------------
ID: post_1CXNbUMakmSCcQD2NCbgn4
内容: 剩下看转弯往下时候都出 止损上移到2.25
时间: Jan 22, 2026 10:41 PM
引用: None
位置: last
历史: ["小仓位 止损 在 1.3", "1.9附近出三分之一"]
----------------------------------------
```

## 🔄 JSON输出

### 简化格式JSON

```python
import json

# 导出为JSON
messages_json = [msg.to_simple_dict() for msg in messages]
print(json.dumps(messages_json, ensure_ascii=False, indent=2))
```

输出：
```json
[
  {
    "domID": "post_1CXNmCYpbYheKjRX4MLWLE",
    "content": "nvda剩下部分也2.45附近出",
    "timestamp": "Jan 23, 2026 12:51 AM",
    "refer": null,
    "position": "single",
    "history": []
  },
  {
    "domID": "post_1CXNbG1zAyv8MfM1oD7dEz",
    "content": "小仓位 止损 在 1.3",
    "timestamp": "Jan 22, 2026 10:41 PM",
    "refer": "GILD - $130 CALLS 这周 1.5-1.60",
    "position": "first",
    "history": []
  },
  {
    "domID": "post_1CXNbKK8oK74QriUZv3rmK",
    "content": "1.9附近出三分之一",
    "timestamp": "Jan 22, 2026 10:41 PM",
    "refer": null,
    "position": "middle",
    "history": ["小仓位 止损 在 1.3"]
  }
]
```

## 🎯 使用场景

### 场景1：基本消息处理

使用 **简化格式**，快速访问核心信息：

```python
for msg in messages:
    data = msg.to_simple_dict()
    
    # 检查是否有引用
    if data['refer']:
        print(f"这条消息引用了: {data['refer']}")
    
    # 根据位置处理
    if data['position'] == 'first':
        # 这是消息组的开始，提取时间戳
        group_timestamp = data['timestamp']
```

### 场景2：消息组重组

根据 `position` 字段重组消息组：

```python
current_group = []
for msg in messages:
    data = msg.to_simple_dict()
    
    if data['position'] in ['single', 'first']:
        # 新消息组开始
        if current_group:
            process_group(current_group)
        current_group = [data]
    else:
        # 添加到当前组
        current_group.append(data)

# 处理最后一组
if current_group:
    process_group(current_group)
```

### 场景3：引用关系追踪

通过 `refer` 字段建立消息间的引用关系：

```python
# 建立消息内容到ID的映射
content_to_id = {
    msg.to_simple_dict()['content']: msg.to_simple_dict()['domID']
    for msg in messages
}

# 追踪引用
for msg in messages:
    data = msg.to_simple_dict()
    if data['refer']:
        # 查找被引用的消息ID
        referred_id = content_to_id.get(data['refer'])
        if referred_id:
            print(f"{data['domID']} 引用了 {referred_id}")
```

### 场景4：时间线重建

使用 `timestamp` 和 `position` 重建完整时间线：

```python
timeline = []
for msg in messages:
    data = msg.to_simple_dict()
    timeline.append({
        'time': data['timestamp'],
        'content': data['content'],
        'is_group_start': data['position'] in ['single', 'first']
    })

# 按时间排序
timeline.sort(key=lambda x: x['time'])
```

## 🔍 字段选择建议

### 使用简化格式的场景

- ✅ API返回数据
- ✅ 前端展示
- ✅ 数据分析
- ✅ 日志记录
- ✅ 数据导出

### 使用完整格式的场景

- ✅ 调试和诊断
- ✅ 深度数据处理
- ✅ 需要访问原始DOM属性
- ✅ 图片附件处理
- ✅ 复杂的消息关联分析

## 📚 相关文档

- `docs/dom_structure_guide.md` - DOM结构详解
- `docs/message_extraction_refactoring.md` - 提取逻辑说明
- `example_message_output.py` - 输出格式示例
