# history 字段使用指南

## 📋 概述

`history` 字段用于存储当前消息之前同组的所有消息内容，便于追踪消息上下文和补充信息。

## 🎯 字段定义

```typescript
{
  domID: string;
  content: string;
  timestamp: string;
  refer: string | null;
  position: "single" | "first" | "middle" | "last";
  history: string[];  // ← 新增字段
}
```

### 字段特性

- **类型**: `array of strings`
- **内容**: 当前消息之前同组的所有消息文本
- **顺序**: 按时间顺序排列（第一条消息在数组第一个）
- **规则**:
  - `position="single"` 或 `"first"`: `history = []`
  - `position="middle"`: `history` 包含第一条到当前消息之前的所有消息
  - `position="last"`: `history` 包含第一条到当前消息之前的所有消息

## 📊 示例说明

### 场景：一个4条消息的消息组

#### 原始消息序列

```
1. GILD - $130 CALLS 这周 1.5-1.60        (first)
2. 小仓位 止损 在 1.3                     (middle)
3. 1.9附近出三分之一                      (middle)
4. 剩下看转弯往下时候都出 止损上移到2.25    (last)
```

#### 每条消息的 history

**消息 #1 (first)**
```json
{
  "content": "GILD - $130 CALLS 这周 1.5-1.60",
  "position": "first",
  "history": []  // 第一条消息，没有历史
}
```

**消息 #2 (middle)**
```json
{
  "content": "小仓位 止损 在 1.3",
  "position": "middle",
  "history": [
    "GILD - $130 CALLS 这周 1.5-1.60"  // 包含第1条
  ]
}
```

**消息 #3 (middle)**
```json
{
  "content": "1.9附近出三分之一",
  "position": "middle",
  "history": [
    "GILD - $130 CALLS 这周 1.5-1.60",  // 第1条
    "小仓位 止损 在 1.3"                 // 第2条
  ]
}
```

**消息 #4 (last)**
```json
{
  "content": "剩下看转弯往下时候都出 止损上移到2.25",
  "position": "last",
  "history": [
    "GILD - $130 CALLS 这周 1.5-1.60",  // 第1条
    "小仓位 止损 在 1.3",                // 第2条
    "1.9附近出三分之一"                  // 第3条
  ]
}
```

## 💻 使用场景

### 场景1：完整上下文展示

```python
def display_with_context(message):
    data = message.to_simple_dict()
    
    if data['history']:
        print("📜 上下文历史:")
        for i, prev_msg in enumerate(data['history'], 1):
            print(f"  {i}. {prev_msg}")
        print()
    
    print(f"💬 当前消息: {data['content']}")
    print(f"⏰ 时间: {data['timestamp']}")
    print(f"📍 位置: {data['position']}")
```

输出示例：
```
📜 上下文历史:
  1. GILD - $130 CALLS 这周 1.5-1.60
  2. 小仓位 止损 在 1.3

💬 当前消息: 1.9附近出三分之一
⏰ 时间: Jan 22, 2026 10:41 PM
📍 位置: middle
```

### 场景2：查找买入信息

```python
def find_entry_info(message):
    """从当前消息或历史消息中查找买入信息"""
    data = message.to_simple_dict()
    
    # 1. 先检查当前消息
    if 'CALL' in data['content'] or 'PUT' in data['content']:
        return extract_option_info(data['content'])
    
    # 2. 再检查引用消息
    if data['refer']:
        if 'CALL' in data['refer'] or 'PUT' in data['refer']:
            return extract_option_info(data['refer'])
    
    # 3. 最后检查历史消息
    for prev_msg in data['history']:
        if 'CALL' in prev_msg or 'PUT' in prev_msg:
            return extract_option_info(prev_msg)
    
    return None
```

### 场景3：判断消息类型

```python
def classify_message(message):
    """根据历史判断消息类型"""
    data = message.to_simple_dict()
    
    if not data['history']:
        # 第一条消息，通常是开仓
        return "ENTRY"
    else:
        content = data['content']
        if '止损' in content:
            return "STOP_LOSS"
        elif '出' in content and ('附近' in content or '分之' in content):
            return "TAKE_PROFIT"
        elif '转弯' in content or '上移' in content:
            return "UPDATE"
        else:
            return "UNKNOWN"
```

### 场景4：重建消息组

```python
def reconstruct_group(last_message):
    """从最后一条消息重建完整消息组"""
    data = last_message.to_simple_dict()
    
    # 完整消息组 = 历史 + 当前
    full_group = data['history'] + [data['content']]
    
    print(f"消息组完整内容 ({len(full_group)} 条):")
    for i, msg in enumerate(full_group, 1):
        print(f"  {i}. {msg}")
    
    return full_group
```

## 🔧 提取实现

### DOM结构遍历

```javascript
// JavaScript 提取逻辑
const getGroupHistory = (currentMsgEl) => {
    const history = [];
    let prevEl = currentMsgEl.previousElementSibling;
    
    // 向上遍历，找到同组的所有前序消息
    while (prevEl && prevEl.matches('[class*="group/message"]')) {
        const hasAbove = prevEl.getAttribute('data-has-message-above');
        
        // 提取消息内容
        const content = extractMessageContent(prevEl);
        if (content) {
            history.unshift(content);  // 添加到数组前面，保持顺序
        }
        
        // 如果这条消息的 has_message_above 为 false，说明是消息组的第一条，停止
        if (hasAbove === 'false') {
            break;
        }
        
        prevEl = prevEl.previousElementSibling;
    }
    
    return history;
};
```

### Python 使用

```python
from scraper.message_extractor import EnhancedMessageExtractor

async def extract_with_history():
    extractor = EnhancedMessageExtractor(page)
    messages = await extractor.extract_message_groups()
    
    for msg in messages:
        data = msg.to_simple_dict()
        
        print(f"消息: {data['content']}")
        print(f"位置: {data['position']}")
        
        if data['history']:
            print(f"历史消息数: {len(data['history'])}")
            for i, prev in enumerate(data['history'], 1):
                print(f"  {i}. {prev}")
        
        print("-" * 40)
```

## 🎯 优势

### 1. 完整上下文
- 无需手动关联消息
- 自动追踪同组消息的完整历史

### 2. 信息补全
- 子消息可以从历史中查找买入信息
- 从历史中推断期权名称、到期时间等

### 3. 消息分组
- 便于理解消息之间的关联关系
- 自动建立消息组的完整视图

### 4. 简化处理
- 减少手动查找前序消息的代码
- 提高消息解析的准确性

## 📚 相关文档

- `docs/message_output_format.md` - 完整输出格式说明
- `docs/dom_structure_guide.md` - DOM结构详解
- `CHANGELOG.md` - v3.4 版本变更记录

## ✅ 验证测试

```bash
# 运行测试
python3 test_refactoring.py

# 查看示例
python3 example_message_output.py
```

## 🎊 总结

`history` 字段提供了一种简单、高效的方式来追踪消息上下文，使得消息解析和处理变得更加准确和便捷。通过DOM结构自动提取，确保了历史消息的完整性和准确性。
