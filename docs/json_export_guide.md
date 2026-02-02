# JSON格式消息导出指南

## 📋 概述

`analyze_local_messages.py` 支持自动导出 JSON 格式的消息记录，方便进行数据分析、存储和集成。

## 🚀 快速使用

### 基本用法（自动导出JSON）

```bash
python3 analyze_local_messages.py debug/page_20260202_000748.html
```

**输出**：
```
✅ 成功提取 98 条原始消息

📤 正在导出JSON文件...
✅ JSON文件已导出: debug/page_20260202_000748_messages_20260202_220944.json
   文件大小: 24.50 KB
   消息数量: 98
```

### 禁用JSON导出

```bash
python3 analyze_local_messages.py debug/page_20260202_000748.html --no-json
```

## 📊 JSON数据结构

### 顶层结构

```json
{
  "metadata": { ... },    // 元数据信息
  "messages": [ ... ]     // 消息数组
}
```

### metadata 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `source_file` | string | 源HTML文件路径 |
| `export_time` | string | 导出时间（ISO 8601格式） |
| `total_messages` | number | 总消息数量 |
| `extractor_version` | string | 提取器版本号 |

**示例**：
```json
{
  "source_file": "debug/page_20260202_000748.html",
  "export_time": "2026-02-02T22:09:44.244804",
  "total_messages": 98,
  "extractor_version": "3.9"
}
```

### messages 字段

消息数组，每条消息包含以下字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `domID` | string | DOM中的data-message-id（稳定不变） |
| `content` | string | 消息内容 |
| `timestamp` | string | 发送时间 |
| `refer` | string\|null | 引用的消息（如果有） |
| `position` | string | 消息位置（single/first/middle/last） |
| `history` | array | 同组历史消息列表 |

**完整示例**：
```json
{
  "domID": "post_1CXLiGzeRPCu7g71itNmSd",
  "content": "2.75出剩下一半",
  "timestamp": "Jan 21, 2026 10:51 PM",
  "refer": null,
  "position": "last",
  "history": [
    "SPY - $680 CALLS 今天 $2.3",
    "小仓位 止损在1.8",
    "2.6出一半"
  ]
}
```

## 💻 使用场景

### 1. Python数据分析

```python
import json
import pandas as pd

# 读取JSON文件
with open('debug/page_20260202_000748_messages_20260202_220944.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# 转换为DataFrame
df = pd.DataFrame(data['messages'])

# 分析
print(f"总消息数: {len(df)}")
print(f"\n按position统计:")
print(df['position'].value_counts())

# 查找包含特定关键词的消息
spy_msgs = df[df['content'].str.contains('SPY', na=False)]
print(f"\nSPY相关消息: {len(spy_msgs)} 条")
```

### 2. JavaScript处理

```javascript
// Node.js
const fs = require('fs');

// 读取JSON文件
const data = JSON.parse(
  fs.readFileSync('debug/page_20260202_000748_messages_20260202_220944.json', 'utf-8')
);

console.log(`总消息数: ${data.metadata.total_messages}`);

// 过滤有history的消息
const withHistory = data.messages.filter(msg => msg.history.length > 0);
console.log(`有history的消息: ${withHistory.length} 条`);

// 按position分组
const grouped = data.messages.reduce((acc, msg) => {
  acc[msg.position] = (acc[msg.position] || 0) + 1;
  return acc;
}, {});
console.log('按position统计:', grouped);
```

### 3. 数据库导入

```python
import json
import sqlite3

# 读取JSON
with open('messages.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# 连接数据库
conn = sqlite3.connect('messages.db')
cursor = conn.cursor()

# 创建表
cursor.execute('''
CREATE TABLE IF NOT EXISTS messages (
    domID TEXT PRIMARY KEY,
    content TEXT,
    timestamp TEXT,
    refer TEXT,
    position TEXT,
    history TEXT
)
''')

# 插入数据
for msg in data['messages']:
    cursor.execute('''
    INSERT OR REPLACE INTO messages VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        msg['domID'],
        msg['content'],
        msg['timestamp'],
        msg['refer'],
        msg['position'],
        json.dumps(msg['history'])
    ))

conn.commit()
conn.close()
```

### 4. 批量处理

```bash
# 批量处理所有HTML文件
for html in debug/*.html; do
    echo "处理: $html"
    python3 analyze_local_messages.py "$html"
done

# 合并所有JSON文件
python3 << EOF
import json
import glob

all_messages = []
for json_file in glob.glob('debug/*_messages_*.json'):
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        all_messages.extend(data['messages'])

# 去重（基于domID）
unique_messages = {msg['domID']: msg for msg in all_messages}

output = {
    "metadata": {
        "total_messages": len(unique_messages),
        "source": "merged from multiple files"
    },
    "messages": list(unique_messages.values())
}

with open('debug/all_messages_merged.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"合并完成: {len(unique_messages)} 条消息")
EOF
```

## 📝 文件命名规则

**格式**：`{原文件名}_messages_{时间戳}.json`

**示例**：
- 源文件：`page_20260202_000748.html`
- JSON文件：`page_20260202_000748_messages_20260202_220944.json`

**时间戳格式**：`YYYYMMDD_HHMMSS`

## 🎯 最佳实践

### 1. 增量更新

利用 `domID` 的稳定性进行增量更新：

```python
import json

# 读取现有数据
existing_ids = set()
try:
    with open('messages.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
        existing_ids = {msg['domID'] for msg in data['messages']}
except FileNotFoundError:
    pass

# 读取新数据
with open('new_messages.json', 'r', encoding='utf-8') as f:
    new_data = json.load(f)

# 只保留新消息
new_messages = [
    msg for msg in new_data['messages']
    if msg['domID'] not in existing_ids
]

print(f"新增消息: {len(new_messages)} 条")
```

### 2. 数据验证

```python
def validate_message(msg):
    """验证消息数据完整性"""
    required_fields = ['domID', 'content', 'timestamp', 'position', 'history']
    
    for field in required_fields:
        if field not in msg:
            return False, f"缺少字段: {field}"
    
    if msg['position'] not in ['single', 'first', 'middle', 'last']:
        return False, f"无效的position值: {msg['position']}"
    
    if not isinstance(msg['history'], list):
        return False, "history必须是数组"
    
    return True, "OK"

# 使用
with open('messages.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

for msg in data['messages']:
    valid, reason = validate_message(msg)
    if not valid:
        print(f"⚠️ 消息 {msg['domID']}: {reason}")
```

### 3. 性能优化

对于大文件，使用流式处理：

```python
import ijson  # pip install ijson

# 流式读取大JSON文件
with open('large_messages.json', 'rb') as f:
    # 只处理符合条件的消息
    for msg in ijson.items(f, 'messages.item'):
        if 'SPY' in msg['content']:
            print(msg['domID'], msg['content'])
```

## 🔍 故障排除

### JSON文件未生成

**可能原因**：
1. 使用了 `--no-json` 参数
2. 没有提取到任何消息
3. 目标目录没有写入权限

**解决方法**：
```bash
# 检查是否有消息提取
python3 analyze_local_messages.py debug/page.html 2>&1 | grep "成功提取"

# 检查目录权限
ls -ld debug/
```

### JSON格式错误

**验证JSON格式**：
```bash
# 使用jq验证
jq . debug/messages.json

# 或使用Python
python3 -m json.tool debug/messages.json
```

## 📚 相关文档

- [消息输出格式说明](message_output_format.md)
- [analyze_local_messages使用指南](analyze_local_messages_guide.md)
- [DOM结构指南](dom_structure_guide.md)
