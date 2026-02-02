# analyze_local_messages.py

本地HTML消息提取分析工具 - 独立脚本

## 🎯 用途

分析已导出的HTML文件，提取消息内容并进行交易分组，无需启动浏览器连接网页。

## 🚀 快速使用

```bash
# 方式1：交互式选择（推荐）
python3 analyze_local_messages.py

# 方式2：指定文件
python3 analyze_local_messages.py debug/page_20260202_000748.html
```

## 📊 输出内容

1. **详细表格视图** - 每行一条消息，显示关联关系
2. **分组摘要视图** - 按交易组聚合，显示买卖流程
3. **原始消息详情** - 前10条消息的完整信息
4. **统计信息** - 完整度分析（作者、时间戳、引用）
5. **详细报告** - 保存到 `debug/message_analysis_*.txt`

## 💡 使用场景

### 场景1：验证消息提取效果

```bash
# 运行分析
python3 analyze_local_messages.py

# 查看统计信息
有作者信息: 94 (100.0%)  ✅
有时间戳: 94 (100.0%)    ✅
有引用内容: 42 (44.7%)   ✅
```

### 场景2：快速测试选择器修改

```bash
# 1. 修改选择器
vim scraper/message_extractor.py

# 2. 验证效果（无需重新导出HTML）
python3 analyze_local_messages.py
[按回车使用最新文件]

# 3. 查看改进
# 修改前：有作者信息: 50 (53.2%)
# 修改后：有作者信息: 94 (100.0%)  ✅
```

### 场景3：查看交易分组

```bash
python3 analyze_local_messages.py

# 输出示例：
【消息组 #1】
组ID: GILD_a1b2c3d4
交易标的: GILD
消息总数: 4

📈 【买入信号】
   GILD - $130 CALLS 这周 1.5-1.60
   
📉 【卖出操作】 (3条)
   1. 1.9附近出三分之一
      ⬅️ 对应买入: GILD - $130 CALLS 这周 1.5-1.60
   2. 2.23出三分之一
   3. 2.3附近都出
```

## 🔧 与其他工具的对比

| 工具 | 用途 | 输出 | 使用场景 |
|------|------|------|---------|
| `analyze_local_messages.py` | 提取消息 | 消息内容、分组 | 验证提取效果 |
| `python3 main.py --test analyze-html` | 分析结构 | DOM、选择器 | 调试选择器 |
| `python3 main.py --test message-extractor` | 在线测试 | 实时提取 | 最终验证 |

## 📋 输出示例

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

🔍 正在提取消息...
✅ 成功提取 94 条原始消息

🔄 正在分析消息关联关系...
✅ 识别出 8 个交易组

【方式1】详细表格视图
-------------------------------------------------------------------------------
消息组ID        标的     时间                 操作类型    消息内容
GILD_a1b2c3d4   GILD     Jan 22 10:41        🟢 买入    GILD - $130 CALLS...
GILD_a1b2c3d4   GILD     Jan 22 10:45        🔴 卖出    1.9附近出三分之一
...

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

## 📚 前置要求

### 需要HTML文件

```bash
# 首先导出HTML文件
python3 main.py --test export-dom

# 在浏览器中：
# 1. 滚动到底部加载所有消息
# 2. 按回车确认
```

### 已安装依赖

```bash
pip3 install playwright
python3 -m playwright install chromium
```

## 🔄 完整工作流程

```bash
# 1. 导出HTML（首次或需要更新数据时）
python3 main.py --test export-dom

# 2. 分析消息（快速验证）
python3 analyze_local_messages.py

# 3. 如果发现问题，分析DOM结构
python3 main.py --test analyze-html

# 4. 调整选择器
vim scraper/message_extractor.py

# 5. 重新分析验证（步骤2）
python3 analyze_local_messages.py

# 6. 重复4-5直到满意

# 7. 在线测试
python3 main.py --test message-extractor

# 8. 正常运行
python3 main.py
```

## 💡 优势

**快速迭代：**
- ✅ 无需登录网页（使用本地HTML）
- ✅ 无需加载消息（已经在HTML中）
- ✅ 快速启动（2-5秒）

**离线工作：**
- ✅ 不需要网络
- ✅ 可在任何环境运行
- ✅ 结果可复现

**详细报告：**
- ✅ 完整的消息内容
- ✅ 统计信息分析
- ✅ 保存为文件便于查看

## 🐛 故障排查

### 未找到HTML文件

```bash
❌ 未找到HTML文件

💡 提示: 请先运行以下命令导出HTML:
   python3 main.py --test export-dom
```

### 提取消息数为0

```
可能原因：
1. HTML文件不完整（文件太小）
2. 选择器不匹配
3. 页面结构已变化

解决方案：
1. 检查HTML文件大小（应 > 1MB）
2. 运行 analyze-html 查看页面结构
3. 重新导出HTML确保完整
```

### 统计信息不理想

```
有作者信息: 50 (53.2%)  ❌ 识别率低

解决方案：
1. 运行 analyze-html 查看作者元素结构
2. 调整 message_extractor.py 中的 authorSelectors
3. 重新运行此脚本验证
```

## 📖 详细文档

- [本地HTML分析指南](doc/LOCAL_HTML_ANALYSIS.md)
- [选择器优化指南](doc/SELECTOR_OPTIMIZATION.md)
- [消息分组说明](doc/MESSAGE_GROUPING.md)

## 🆘 获取帮助

遇到问题？

1. 查看 [故障排查文档](TROUBLESHOOTING.md)
2. 查看 [CHANGELOG](CHANGELOG.md#266)
3. 运行 `python3 main.py --test analyze-html` 分析DOM结构
