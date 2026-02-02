# analyze_local_messages.py 使用指南

## 📋 概述

`analyze_local_messages.py` 是一个本地HTML消息分析脚本，用于直接分析本地HTML文件，提取和展示消息内容。

**最新更新**: 现已支持新的消息提取格式，包括 `history`、`position` 等字段。

## 🚀 快速使用

### 方式1：交互式选择

```bash
python3 analyze_local_messages.py
```

脚本会列出 `debug/` 目录下所有HTML文件，让你选择要分析的文件。

### 方式2：指定文件

```bash
python3 analyze_local_messages.py debug/page_20260202_000748.html
```

## 📊 输出格式

### 新格式输出

脚本现在使用新的简化格式输出消息，包含以下字段：

```json
{
  "domID": "post_1CXNbKK8oK74QriUZv3rmK",
  "content": "1.9附近出三分之一",
  "timestamp": "Jan 22, 2026 10:41 PM",
  "refer": null,
  "position": "middle",
  "history": [
    "GILD - $130 CALLS 这周 1.5-1.60",
    "小仓位 止损 在 1.3"
  ]
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `domID` | string | DOM中的data-message-id（✅ 稳定不变，可用于消息去重） |
| `content` | string | **完整消息内容**（包含引用+主消息+关联消息） |
| `timestamp` | string | 发送时间 |
| `refer` | string\|null | 引用的消息（快速访问） |
| `position` | string | 消息位置 (single/first/middle/last) |
| `history` | array | 同组历史消息列表 |

**注意**：`content` 字段包含完整内容，适合用于消息分析和解析。

## 📈 输出内容

### 1. 原始消息详情（前10条）

展示前10条消息的新格式输出，包括：
- 基本信息（domID、position、timestamp、content）
- 引用信息（refer）
- 历史消息（history）
- 完整JSON格式（前3条）

**示例输出**：
```
【原始消息详情】（前10条 - 新格式）
================================================================================

1. 消息 #1
   ----------------------------------------------------------------------------
   domID:     post_1CXNmCYpbYheKjRX4MLWLE
   position:  single
   timestamp: Jan 23, 2026 12:51 AM
   content:   nvda剩下部分也2.45附近出
   history:   []
   ----------------------------------------------------------------------------

   📋 JSON格式:
   {
     "domID": "post_1CXNmCYpbYheKjRX4MLWLE",
     "content": "nvda剩下部分也2.45附近出",
     "timestamp": "Jan 23, 2026 12:51 AM",
     "refer": null,
     "position": "single",
     "history": []
   }
```

### 2. 统计信息（增强版）

新增统计包括：
- **消息位置分布**: single/first/middle/last的数量和占比
- **history字段统计**: 有历史消息的数量和平均历史条数

**示例输出**：
```
📊 统计信息（基于新格式）
================================================================================
原始消息数: 150
交易组数: 45

消息位置分布:
  single  :  30 (20.0%)
  first   :  40 (26.7%)
  middle  :  50 (33.3%)
  last    :  30 (20.0%)

history字段统计:
  有历史消息: 80 (53.3%)
  平均历史条数: 2.3
================================================================================
```

### 3. 指令解析

继续提供期权指令解析功能，转化为Broker可用指令。

### 4. 交易组聚合

使用 `MessageGrouper` 进行流式处理，按时间顺序聚合相关消息。

## 📝 详细报告

脚本会自动生成详细报告文件，保存在 `debug/message_analysis_YYYYMMDD_HHMMSS.txt`。

### 报告内容

1. **统计信息** - 包含新格式统计
2. **详细表格视图** - 交易组表格
3. **分组摘要视图** - 交易组摘要
4. **所有原始消息（新格式）** - 每条消息的：
   - 新格式字段（domID、position、timestamp、content、refer、history）
   - 完整JSON格式
   - 旧格式对比（用于参考）

## 💡 使用技巧

### 1. 专注于新格式

如果只关心新格式输出，可以直接查看前10条消息的详情。

### 2. 对比新旧格式

在详细报告中，每条消息都包含新旧格式对比，方便理解字段映射。

### 3. 追踪消息历史

使用 `history` 字段快速了解消息的上下文：

```python
# 在报告中查找
if simple_data['history']:
    print(f"历史消息数: {len(simple_data['history'])}")
    for i, hist_msg in enumerate(simple_data['history'], 1):
        print(f"  {i}. {hist_msg}")
```

### 4. 分析消息组结构

使用 `position` 字段理解消息组结构：

```
position="first"  → 消息组开始，有完整头部信息
position="middle" → 消息组中间，继承时间戳
position="last"   → 消息组结束
position="single" → 独立消息
```

## 🔍 调试和优化

### 查看详细输出

```bash
# 显示解析输出
SHOW_PARSER_OUTPUT=true python3 analyze_local_messages.py

# 隐藏解析输出
SHOW_PARSER_OUTPUT=false python3 analyze_local_messages.py
```

### 如果提取不准确

1. 查看原始消息详情，检查字段是否正确
2. 查看 `docs/dom_structure_guide.md` 了解DOM结构
3. 检查 `scraper/message_extractor.py` 中的选择器
4. 运行 `test_refactoring.py` 验证核心功能

## 📚 相关文档

- `docs/message_output_format.md` - 输出格式详细说明
- `docs/dom_structure_guide.md` - DOM结构指南
- `HISTORY_FIELD_GUIDE.md` - history字段使用指南
- `CHANGELOG.md` - 版本变更记录

## 🎯 完整示例

```bash
# 1. 分析最新的HTML文件
python3 analyze_local_messages.py

# 2. 选择文件（输入1）
请选择要分析的文件 (输入序号，默认=1): 1

# 3. 查看输出
# - 前10条消息详情（新格式）
# - 统计信息（包含新字段统计）
# - 交易组聚合
# - 指令解析

# 4. 查看详细报告
cat debug/message_analysis_20260202_131530.txt
```

## ✨ 新功能亮点

### 1. history字段展示

每条消息都显示其历史上下文：
```
history:   [2 条历史消息]
  1. GILD - $130 CALLS 这周 1.5-1.60
  2. 小仓位 止损 在 1.3
```

### 2. position字段

清晰标识消息在组中的位置：
```
position:  middle  # 中间消息，需要历史上下文
```

### 3. JSON格式预览

前3条消息直接展示完整JSON格式，便于理解结构。

### 4. 统计增强

新增消息位置分布和history字段统计，更全面地了解消息结构。

## 🎊 总结

更新后的 `analyze_local_messages.py` 完全支持新的消息提取格式，提供更清晰、更结构化的输出，便于理解消息组关系和上下文。
