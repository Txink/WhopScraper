# 本地HTML分析工具使用指南

## 📖 概述

本地HTML分析工具允许您分析已导出的HTML文件，无需重新连接网页、登录或加载数据。提供两种工具：

1. **analyze-html** - 分析页面结构，调试选择器
2. **analyze_local_messages.py** 🆕 - 提取消息内容，验证效果

## 🔧 工具对比

| 功能 | analyze-html | analyze_local_messages.py |
|------|--------------|--------------------------|
| **调用方式** | `python3 main.py --test analyze-html` | `python3 analyze_local_messages.py` |
| **主要用途** | 分析DOM结构、查找选择器 | 提取消息、验证分组效果 |
| **输出内容** | 元素路径、类名、属性 | 消息内容、交易组、统计 |
| **使用工具** | JavaScript DOM分析 | EnhancedMessageExtractor |
| **报告格式** | 结构分析报告 | 消息提取报告 |
| **适用场景** | 开发阶段：调试选择器 | 测试阶段：验证提取效果 |

## 🎯 使用场景

### 为什么需要本地HTML分析？

**问题1：重复导出耗时**
```
每次调整选择器都要：
1. 启动浏览器 (5秒)
2. 登录网页 (10秒)
3. 导航到页面 (3秒)
4. 加载历史消息 (30秒+)
5. 导出HTML (5秒)

总计：53秒+ 😫
```

**解决方案：**
```
首次导出后，后续调试只需：
1. 运行analyze-html (2秒)
2. 选择已有文件 (1秒)
3. 分析完成 (3秒)

总计：6秒 ⚡
```

**问题2：在线分析不稳定**
```
- 网络波动影响
- 需要保持登录状态
- 页面可能已更新
- 消息加载不一致
```

**解决方案：**
```
- 固定的HTML文件
- 离线工作
- 结果可复现
- 内容不变化
```

## 🚀 快速开始

### 工具1：analyze_local_messages.py（推荐）

**最简单的方式：**

```bash
# 直接运行，交互式选择文件
python3 analyze_local_messages.py

# 或指定文件
python3 analyze_local_messages.py debug/page_20260202_000748.html
```

**输出：**
- ✅ 消息提取结果
- ✅ 交易分组
- ✅ 统计信息
- ✅ 详细报告文件

**何时使用：**
- 想快速查看消息提取效果
- 验证选择器修改是否正确
- 查看交易消息分组结果
- 生成完整的分析报告

### 工具2：analyze-html（调试选择器）

**使用方式：**

```bash
python3 main.py --test analyze-html
```

**输出：**
- ✅ 页面DOM结构
- ✅ 可能的选择器
- ✅ 元素路径
- ✅ 类名和属性

**何时使用：**
- 选择器不工作，需要找到正确的选择器
- 页面结构已变化，需要了解新结构
- 想知道元素的类名和属性

### 完整工作流程

```bash
# Step 1: 首次导出完整HTML
python3 main.py --test export-dom

# 在浏览器中：
# 1. 滚动到页面最底部（加载所有历史消息）
# 2. 等待消息完全加载
# 3. 按回车键确认

# Step 2: 分析导出的HTML
python3 main.py --test analyze-html

# 输出：
📁 找到 1 个HTML文件:
   1. page_20260202_000748.html
      时间: 2026-02-02 00:07:48, 大小: 2.45 MB

请选择要分析的文件 (输入序号，默认=1): [直接按回车]

✅ 已选择: debug/page_20260202_000748.html
📖 正在读取HTML文件...
✅ 已读取 2,456,789 字符

🔍 正在分析HTML结构...
✅ 分析完成

📊 统计信息:
   总元素数: 5,848
   找到 2 种可能的消息容器
   找到 30 个包含交易关键字的元素

📄 详细分析报告已保存到:
   debug/local_analysis_20260202_001234.txt

# Step 3: 查看分析报告
cat debug/local_analysis_20260202_001234.txt
```

## 📊 分析报告格式

### 报告结构

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
   小仓位 止损 在 1.3
   
   示例HTML:
   <div class="group/message" data-message-id="post_1CXNbG1zAyv8MfM1oD7dEz" 
        data-is-own-message="false" 
        data-has-message-above="false" 
        data-has-message-below="true">
   ...

2. 选择器: [class*="message"]
   数量: 108
   类名: group/message
   ...

============================================================
包含交易关键字的元素
============================================================

1. 关键字: GILD
   文本: GILD - $130 CALLS 这周 1.5-1.60
   路径:
      <SPAN class='fui-Text truncate fui-r-size-1' id=''>
         <DIV class='flex items-center gap-1.5 truncate' id=''>
            <DIV class='peer/reply relative mb-1.5 max-w-4/5' id=''>
               <DIV class='relative flex w-full max-w-full flex-col gap-1 items-start' id=''>
                  <DIV class='flex max-w-[min(80%,600px)] flex-col gap-1 pl-11' id=''>

2. 关键字: 止损
   文本: 小仓位 止损 在 1.3
   路径:
   ...
```

### 如何使用报告

**1. 确定消息容器选择器**

从"可能的消息容器选择器"部分：

```
选择器: [data-message-id]
数量: 108  ← 这个数字应该等于实际消息数

如果数量正确，这个选择器就是好的选择。
```

**2. 查看元素路径**

从"包含交易关键字的元素"部分：

```
路径:
   <DIV class='bg-gray-3 rounded-[18px]' ...>  ← 消息气泡
      <DIV class='text-[15px] whitespace-pre-wrap' ...>  ← 文本容器
         <P>  ← 段落
```

**3. 提取有用的类名**

从示例HTML中提取：
```
class="group/message"           → 消息容器
class="bg-gray-3 rounded-[18px]"  → 消息气泡
class="fui-Text truncate"       → 作者名
class="whitespace-pre-wrap"     → 消息文本
```

## 🔧 实际应用案例

### 案例1：调试作者信息提取

**问题：** 作者信息总是显示"(未识别)"

**Step 1: 查看报告中的消息示例**

```
示例文本:
xiaozhaolucky
GILD - $130 CALLS 这周 1.5-1.60
```

**发现：** 作者名 `xiaozhaolucky` 在消息文本的第一行

**Step 2: 查看元素路径**

```
路径:
   <SPAN class='fui-Text truncate fui-r-size-1'>
      <DIV class='flex items-center gap-1.5 truncate'>
```

**发现：** 作者名在 `<SPAN class='fui-Text truncate'>` 中

**Step 3: 调整选择器**

编辑 `scraper/message_extractor.py`：

```python
# 旧选择器
const authorSelectors = [
    '[class*="author"]',  # 找不到
    '[class*="username"]'
];

# 新选择器
const authorSelectors = [
    '[class*="fui-Text"][class*="truncate"]',  # ✅ 正确
    '[class*="author"]'
];
```

**Step 4: 验证（无需重新导出）**

```bash
python3 main.py --test analyze-html
# 使用同一个HTML文件
# 查看是否能识别作者
```

### 案例2：找到消息内容选择器

**问题：** 消息内容提取不完整

**Step 1: 查看报告中的路径**

```
关键字: GILD
文本: GILD - $130 CALLS 这周 1.5-1.60
路径:
   <DIV class='bg-gray-3 rounded-[18px] px-3 py-1.5'>
      <DIV class='text-[15px] whitespace-pre-wrap'>
         <P>
```

**Step 2: 识别消息气泡**

```
class="bg-gray-3 rounded-[18px]"  ← 这是消息气泡的特征
```

**Step 3: 更新选择器**

```python
const contentSelectors = [
    '[class*="bg-gray-3"][class*="rounded"]',  # ✅ 消息气泡
    '[class*="whitespace-pre-wrap"]',          # ✅ 文本容器
    'p'                                         # ✅ 段落
];
```

### 案例3：对比不同版本的选择器效果

**场景：** 修改了选择器，想对比效果

**方法1：使用相同HTML分析**

```bash
# 修改前分析
python3 main.py --test analyze-html
选择: 1
# 保存输出: before.txt

# 修改 message_extractor.py

# 修改后分析
python3 main.py --test analyze-html
选择: 1
# 保存输出: after.txt

# 对比结果
diff before.txt after.txt
```

**方法2：对比不同时间点的HTML**

```bash
# 分析旧HTML
python3 main.py --test analyze-html
选择: 2  # 旧文件

# 分析新HTML
python3 main.py --test analyze-html
选择: 1  # 新文件

# 查看页面结构是否有变化
```

## 💡 高级技巧

### 技巧1：快速查找选择器

**使用浏览器开发者工具：**

```bash
# 1. 在浏览器中打开导出的HTML
open debug/page_20260202_000748.html

# 2. 按F12打开开发者工具

# 3. 使用控制台测试选择器
document.querySelectorAll('[data-message-id]').length
// 输出: 108

document.querySelector('[data-message-id]').innerText
// 输出: "xiaozhaolucky\nGILD - $130 CALLS..."

# 4. 找到正确的选择器后，更新代码
```

### 技巧2：提取关键元素的完整HTML

**修改分析工具输出更多信息：**

```python
# 在 main.py 的 analyze_local_html() 中
# 修改 sample_html 的长度限制

# 旧代码
sample_html: sample.outerHTML.substring(0, 500)

# 新代码（输出更多）
sample_html: sample.outerHTML.substring(0, 2000)
```

### 技巧3：导出特定元素的结构

**使用浏览器控制台：**

```javascript
// 导出第一个消息的完整HTML
const msg = document.querySelector('[data-message-id]');
console.log(msg.outerHTML);

// 导出所有消息的类名
const messages = document.querySelectorAll('[data-message-id]');
messages.forEach((msg, i) => {
    console.log(`消息${i}: ${msg.className}`);
});
```

## 📋 常见问题

### Q1: HTML文件很大，分析很慢？

A: 
- 正常情况：2-5MB的HTML文件分析需要3-5秒
- 如果超过10秒，可能是：
  - HTML包含大量图片（base64编码）
  - 重复分析同一文件（应该缓存结果）
- 解决方案：
  - 分析前清理不必要的元素
  - 只保留消息相关的部分

### Q2: 找不到HTML文件？

A: 
```bash
# 检查debug目录
ls -lh debug/

# 如果为空，先导出
python3 main.py --test export-dom

# 如果文件存在但工具找不到
# 检查文件名格式是否为: page_YYYYMMDD_HHMMSS.html
```

### Q3: 分析报告的选择器数量为0？

A: 可能的原因：
1. HTML文件不完整（太小）
2. 页面结构已变化
3. 选择器列表需要更新

解决方案：
```bash
# 1. 检查文件大小
ls -lh debug/page_*.html

# 2. 如果<500KB，重新导出
python3 main.py --test export-dom

# 3. 确保滚动加载了所有消息
```

### Q4: 如何知道HTML是否包含完整数据？

A: 检查方法：
```bash
# 1. 查看文件大小
ls -lh debug/page_*.html
# 完整的应该 > 1MB

# 2. 在浏览器中打开
open debug/page_*.html
# 目测消息数量

# 3. 查看分析报告
cat debug/local_analysis_*.txt | grep "数量:"
# 消息数量应该符合预期
```

## 🔄 工作流程最佳实践

### 推荐流程

```
1. 首次导出（获取baseline）
   python3 main.py --test export-dom
   ↓
2. 本地分析（理解结构）
   python3 main.py --test analyze-html
   ↓
3. 调整选择器
   vim scraper/message_extractor.py
   ↓
4. 本地验证（快速迭代）
   python3 main.py --test analyze-html
   ↓
5. 提取测试
   python3 main.py --test message-extractor
   ↓
6. 如果失败，返回步骤3
   ↓
7. 成功后正常运行
   python3 main.py
```

### 何时重新导出HTML

**需要重新导出的情况：**
- ✅ 页面结构已更新（Whop更新了UI）
- ✅ 需要更多历史消息
- ✅ 现有HTML文件损坏
- ✅ 需要对比不同时间点的数据

**不需要重新导出的情况：**
- ❌ 只是调整选择器
- ❌ 修改提取逻辑
- ❌ 测试不同的分析方法
- ❌ 验证代码修改

## 🎯 analyze_local_messages.py 详细说明

### 功能特点

**1. 独立运行**

```bash
# 不需要通过main.py
# 不需要--test参数
# 直接运行即可
python3 analyze_local_messages.py
```

**2. 交互式选择**

```
📁 找到 3 个HTML文件:
   1. page_20260202_000748.html
      时间: 2026-02-02 00:07:48, 大小: 2.45 MB
   2. page_20260201_230555.html
      时间: 2026-02-01 23:05:55, 大小: 2.12 MB
   3. page_20260201_220430.html
      时间: 2026-02-01 22:04:30, 大小: 1.98 MB

请选择要分析的文件 (输入序号，默认=1): 
```

**3. 完整的消息提取**

使用实际的提取器：
- `EnhancedMessageExtractor` - 提取消息
- `MessageGrouper` - 分组交易
- 完整的统计信息

**4. 多种展示格式**

输出包含：
```
1. 详细表格视图 - 每行一条消息
2. 分组摘要视图 - 按交易组聚合
3. 原始消息详情 - 前10条完整信息
4. 统计信息 - 完整度分析
```

**5. 生成详细报告**

```
debug/message_analysis_20260202_002345.txt

包含所有原始消息的完整内容：
- 消息ID
- 作者
- 时间戳
- 主消息
- 关联消息
- 引用内容
- 完整内容（合并后）
```

### 使用示例

**场景1：快速查看提取效果**

```bash
# 运行脚本
python3 analyze_local_messages.py

# 选择最新文件（按回车）
[回车]

# 查看输出
# - 提取了多少消息
# - 识别了多少交易组
# - 有多少消息有作者/时间戳
```

**场景2：验证选择器修改**

```bash
# 1. 修改选择器
vim scraper/message_extractor.py

# 2. 快速验证（使用同一个HTML文件）
python3 analyze_local_messages.py
[回车]

# 3. 对比统计信息
# 修改前：有作者信息: 50 (53.2%)
# 修改后：有作者信息: 94 (100.0%)  ✅ 改进了！
```

**场景3：生成报告分享**

```bash
# 运行分析
python3 analyze_local_messages.py

# 获得报告文件
✅ 详细报告已保存到: debug/message_analysis_20260202_002345.txt

# 分享报告
cat debug/message_analysis_20260202_002345.txt
```

**场景4：指定特定文件**

```bash
# 分析特定的HTML文件
python3 analyze_local_messages.py debug/page_20260201_230555.html

# 使用通配符分析最新文件
python3 analyze_local_messages.py $(ls -t debug/page_*.html | head -1)
```

### 输出解读

**统计信息：**

```
📊 统计信息
-------------------------------------------------------------------------------
原始消息数: 94          # 总共提取了94条消息
交易组数: 8             # 识别出8个交易组

有作者信息: 94 (100.0%)  # 所有消息都识别了作者 ✅
有时间戳: 94 (100.0%)    # 所有消息都提取了时间戳 ✅
有引用内容: 42 (44.7%)   # 42条消息包含引用 ✅
```

**完整度分析：**

| 指标 | 理想值 | 说明 |
|------|--------|------|
| 有作者信息 | 100% | 应该能识别所有消息的作者 |
| 有时间戳 | 90%+ | 大部分消息应该有时间戳 |
| 有引用内容 | 30-50% | 卖出消息通常引用买入 |

**如果统计不理想：**

```bash
# 如果作者信息识别率低（<80%）
# → 检查作者选择器
# → 查看 analyze-html 的分析报告
# → 调整 message_extractor.py 中的 authorSelectors

# 如果时间戳识别率低（<80%）
# → 检查时间戳选择器
# → 查看时间戳格式是否正确
# → 调整 timestampSelectors

# 如果消息数量异常
# → 检查消息容器选择器
# → 可能匹配到了非消息元素
```

### 命令行参数

```bash
# 无参数 - 交互式选择
python3 analyze_local_messages.py

# 指定文件路径
python3 analyze_local_messages.py <HTML文件路径>

# 示例
python3 analyze_local_messages.py debug/page_20260202_000748.html
```

### 与其他工具的配合

**工作流程：**

```
1. export-dom
   ↓ 导出HTML文件
2. analyze_local_messages.py  ← 快速查看提取效果
   ↓ 发现问题
3. analyze-html  ← 分析DOM结构
   ↓ 找到正确选择器
4. 修改 message_extractor.py
   ↓
5. analyze_local_messages.py  ← 验证修改
   ↓ 重复4-5直到满意
6. message-extractor  ← 在线测试
   ↓
7. 正常运行
```

**工具选择：**

- 想看提取效果 → `analyze_local_messages.py`
- 选择器不工作 → `analyze-html`
- 在线测试 → `message-extractor`

## 📚 相关文档

- [DOM导出调试](DEBUG_DOM.md) - DOM导出工具详细说明
- [选择器优化](SELECTOR_OPTIMIZATION.md) - 如何优化选择器
- [消息上下文识别](MESSAGE_CONTEXT.md) - 消息提取原理
- [CHANGELOG v2.6.6](../CHANGELOG.md#266) - 版本更新日志
