# DOM导出和调试指南

## 📖 概述

当消息提取器无法正确识别页面元素时，可以使用DOM导出工具来分析页面结构，找到正确的选择器。

## 🎯 适用场景

### 何时使用

✅ **消息提取不正确**
- 作者信息未提取
- 时间戳缺失
- 消息内容重复
- 关联关系错误

✅ **页面结构变化**
- Whop更新了页面布局
- 选择器失效
- 需要适配新结构

✅ **开发新的提取逻辑**
- 需要了解页面结构
- 测试新的选择器
- 验证提取效果

## 🚀 快速开始

### 1. 导出页面DOM

```bash
python3 main.py --test export-dom
```

### 2. 查看输出文件

导出后会在 `debug/` 目录生成三个文件：

```
debug/
├── page_20260201_230500.html      # 完整HTML源代码
├── page_20260201_230500.png       # 页面截图
└── analysis_20260201_230500.txt   # 结构分析报告
```

### 3. 分析页面结构

#### 方法1: 使用浏览器开发者工具（推荐）

```bash
# 在浏览器中打开HTML文件
open debug/page_*.html
# 或者
google-chrome debug/page_*.html
```

**操作步骤：**
1. 按 `F12` 打开开发者工具
2. 点击"选择元素"工具（或按 `Ctrl+Shift+C`）
3. 点击页面上的消息元素
4. 查看右侧的元素面板，记录：
   - 元素的标签名（如 `<div>`）
   - `class` 属性
   - `id` 属性
   - `data-*` 属性

#### 方法2: 查看分析报告

```bash
# 查看自动生成的分析报告
cat debug/analysis_*.txt
```

**报告包含：**
- 所有可能的消息容器选择器
- 每个选择器匹配的元素数量
- 示例HTML和属性
- 包含交易关键字的元素路径

#### 方法3: 对照截图

```bash
# 打开截图
open debug/page_*.png
```

**用途：**
- 验证要提取的消息位置
- 确认元素的可见性
- 了解页面布局

## 📊 分析示例

### 分析报告示例

```
============================================================
页面结构分析
============================================================

URL: https://whop.com/joined/stock-and-option/-gZyq1MzOZAWO98/app/
标题: Stock and Option Trading
总元素数: 3,456

============================================================
可能的消息容器选择器
============================================================

1. 选择器: [class*="message"]
   数量: 42
   类名: message-container flex flex-col gap-2
   ID: 
   属性:
      data-message-id="post_1CXNbKK8oK74QriUZv3rmK"
      class="message-container flex flex-col gap-2"
      role="article"
   
   示例文本:
   xiaozhaolucky
   Jan 22, 2026 10:41 PM
   GILD - $130 CALLS 这周 1.5-160
   
   示例HTML:
   <div class="message-container flex flex-col gap-2" 
        data-message-id="post_1CXNbKK8oK74QriUZv3rmK" 
        role="article">
     <div class="message-header">
       <span class="author-name">xiaozhaolucky</span>
       <time datetime="2026-01-22T22:41:00">Jan 22, 2026 10:41 PM</time>
     </div>
     <div class="message-content">
       GILD - $130 CALLS 这周 1.5-160
     </div>
   </div>

2. 选择器: [role="article"]
   数量: 42
   类名: message-container flex flex-col gap-2
   ...
```

### 从报告中提取信息

根据上面的示例，我们可以得到：

**消息容器：**
- 选择器：`[role="article"]` 或 `[class*="message"]`
- 属性：`data-message-id`

**作者信息：**
- 父容器：`.message-header`
- 选择器：`.author-name`

**时间戳：**
- 父容器：`.message-header`
- 选择器：`time`
- 属性：`datetime`

**消息内容：**
- 选择器：`.message-content`

## 🔧 调整选择器

### 1. 打开消息提取器文件

```bash
vim scraper/message_extractor.py
# 或
code scraper/message_extractor.py
```

### 2. 找到选择器定义

在 `extract_message_groups()` 方法的JavaScript代码中找到选择器：

```javascript
// 查找所有消息容器
const messageSelectors = [
    '[class*="message"]',
    '[class*="Message"]',
    '[data-message]',
    'article',
    '[role="article"]'
];
```

### 3. 根据分析结果更新选择器

**示例：根据上面的分析**

```javascript
// 更新后的选择器（按优先级排序）
const messageSelectors = [
    '[role="article"]',              // 最准确
    '[data-message-id]',             // 有唯一ID
    '[class*="message-container"]',  // 特定类名
    '[class*="message"]',            // 通用类名
];

// 作者选择器
const authorSelectors = [
    '.author-name',                  // 最准确
    '[class*="author"]',
    '[class*="username"]',
];

// 时间戳选择器  
const timestampSelectors = [
    'time[datetime]',                // 最准确
    'time',
    '[class*="timestamp"]',
];

// 内容选择器
const contentSelectors = [
    '.message-content',              // 最准确
    '[class*="content"]',
    '.prose',
];
```

### 4. 测试新的选择器

```bash
# 重新测试消息提取器
python3 main.py --test message-extractor
```

**验证输出：**
- 作者名称是否正确
- 时间戳是否准确
- 消息内容是否完整
- 关联关系是否正确

## 🎯 最佳实践

### 选择器优先级

1. **唯一属性** > **特定类名** > **通用类名**
   ```javascript
   // 好
   '[data-message-id]'
   '.message-content'
   
   // 一般
   '[class*="message"]'
   
   // 不推荐
   'div'
   ```

2. **具体的选择器** > **宽泛的选择器**
   ```javascript
   // 好
   'article[role="article"]'
   
   // 一般
   'article'
   ```

3. **语义化选择器** > **样式类选择器**
   ```javascript
   // 好
   'time[datetime]'
   '[role="article"]'
   
   // 一般
   '.flex.flex-col'
   ```

### 调试技巧

1. **逐步验证**
   - 先确保消息容器选择器正确
   - 再调整作者、时间等子元素选择器
   - 最后处理引用和关联关系

2. **使用浏览器控制台**
   ```javascript
   // 在浏览器控制台测试选择器
   document.querySelectorAll('[role="article"]').length
   document.querySelector('[role="article"]').innerText
   ```

3. **保留多个候选选择器**
   - 提供多个选择器作为备选
   - 按优先级尝试
   - 增加兼容性

4. **添加调试日志**
   ```javascript
   console.log('找到消息容器:', elements.length);
   console.log('第一个消息:', elements[0].innerText);
   ```

## 🐛 常见问题

### Q: 导出的HTML文件很大，浏览器打开很慢？

A: 
- 这是正常的，完整页面HTML通常1-5MB
- 可以使用文本编辑器（如VS Code）查看
- 搜索关键字快速定位（如 "GILD"）

### Q: 截图是空白的？

A: 
- 检查是否成功登录
- 确认页面是否完全加载（等待3秒）
- 尝试增加等待时间

### Q: 分析报告中找不到消息元素？

A: 
- 检查是否使用了正确的URL
- 确认页面是否有消息内容
- 尝试手动在浏览器中查看页面结构

### Q: 更新选择器后还是不行？

A: 
1. 重新导出DOM验证页面结构
2. 检查选择器语法是否正确
3. 在浏览器控制台测试选择器
4. 查看提取器的错误日志

## 📝 完整工作流程

```bash
# 1. 导出页面DOM
python3 main.py --test export-dom

# 2. 在浏览器中打开HTML
open debug/page_*.html

# 3. 使用开发者工具分析结构（F12）

# 4. 查看分析报告
cat debug/analysis_*.txt

# 5. 对照截图验证
open debug/page_*.png

# 6. 更新选择器
vim scraper/message_extractor.py

# 7. 测试新的选择器
python3 main.py --test message-extractor

# 8. 验证输出是否正确

# 9. 如果不正确，重复步骤1-8

# 10. 正确后，正常运行
python3 main.py
```

## 💡 提示

- 每次页面结构变化时重新导出DOM
- 保留旧的debug文件便于对比
- 定期清理debug目录避免占用空间
- 分享debug文件时注意隐私信息

## 📚 相关文档

- [消息上下文识别指南](MESSAGE_CONTEXT.md)
- [事件驱动监控指南](EVENT_DRIVEN_MONITOR.md)
- [故障排查](../TROUBLESHOOTING.md)
