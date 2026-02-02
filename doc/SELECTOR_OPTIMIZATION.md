# 选择器优化指南

## 📖 概述

本文档详细说明了如何基于DOM分析结果优化消息提取器的选择器，提高提取准确性。

## 🎯 问题诊断

### 常见问题

1. **作者信息提取失败**
   - 症状：所有消息显示 "(未识别)"
   - 原因：选择器不匹配实际DOM结构

2. **时间戳识别错误**
   - 症状：所有消息显示 "(继承自上一条)"
   - 原因：时间戳元素选择器不正确

3. **消息内容重复**
   - 症状：同一消息被提取多次
   - 原因：选择器匹配到父子元素

4. **消息内容缺失**
   - 症状：只提取到部分内容
   - 原因：内容选择器嵌套层级不对

## 🔍 DOM分析流程

### 第一步：导出DOM

```bash
python3 main.py --test export-dom
```

这会生成三个文件：
- `debug/page_YYYYMMDD_HHMMSS.html` - 完整HTML
- `debug/page_YYYYMMDD_HHMMSS.png` - 页面截图
- `debug/analysis_YYYYMMDD_HHMMSS.txt` - 结构分析

### 第二步：查看分析报告

打开 `debug/analysis_*.txt`，重点关注：

```
============================================================
可能的消息容器选择器
============================================================

1. 选择器: [data-message-id]
   数量: 108
   类名: group/message
   ID: 
   属性:
      data-message-id="post_1CXNbKK8oK74QriUZv3rmK"
      data-is-own-message="false"
   
   示例文本:
   xiaozhaolucky
   GILD - $130 CALLS 这周 1.5-1.60
   ...
```

**从这个报告中提取关键信息：**
- ✅ 消息容器的选择器
- ✅ 元素数量(验证是否正确)
- ✅ 重要的类名和属性
- ✅ 示例文本结构

### 第三步：在浏览器中验证

```bash
# 用浏览器打开HTML文件
open debug/page_*.html
```

**使用开发者工具（F12）：**
1. 点击"选择元素"工具
2. 点击页面上的消息
3. 查看右侧元素面板
4. 记录：标签名、class、id、data-*属性

## 🔧 选择器优化策略

### 1. 消息容器选择器

#### 优先级原则

```javascript
const messageSelectors = [
    '[data-message-id]',          // 1. 唯一ID属性(最优先)
    '[class*="group/message"]',   // 2. 特定类名
    '[class*="message"]',         // 3. 通用类名
    '[role="article"]'            // 4. 语义化属性(兜底)
];
```

#### 实际案例：Whop页面

**DOM结构：**
```html
<div class="group/message" 
     data-message-id="post_1CXNbG1zAyv8MfM1oD7dEz"
     data-is-own-message="false">
```

**最佳选择器：**
```javascript
'[data-message-id]'  // 每条消息都有唯一ID
```

**为什么不用 `class="group/message"`？**
- 类名包含斜杠，需要转义：`.group\\/message`
- 不如属性选择器简洁
- 属性选择器更稳定

### 2. 作者信息选择器

#### 挑战

作者信息可能：
- 没有专门的HTML标签包装
- 直接作为文本节点存在
- 与时间戳、消息内容混在一起

#### 解决方案

**多策略提取：**

```javascript
// 策略1: 从特定类名提取
const authorSelectors = [
    '[class*="fui-Text"][class*="truncate"]',  // Whop作者类名
    '[class*="author"]',
    '[class*="username"]'
];

// 策略2: 从文本节点查找
const walker = document.createTreeWalker(
    msgEl,
    NodeFilter.SHOW_TEXT
);
while (node = walker.nextNode()) {
    const text = node.textContent.trim();
    // 应用过滤规则...
}
```

**过滤规则：**
```javascript
if (text && 
    text.length > 2 && 
    text.length < 30 &&          // 作者名不会太长
    !text.includes('•') &&        // 排除符号
    !text.includes('$') &&        // 排除交易内容
    !/\d/.test(text)) {          // 排除包含数字的文本
    // 这可能是作者名
}
```

### 3. 时间戳选择器

#### 时间戳格式

常见格式：
- `Jan 22, 2026 10:41 PM` (英文)
- `1月22日 10:41` (中文)
- `2026-01-22 10:41` (ISO)

#### 提取策略

**优先级：**
```javascript
const timestampSelectors = [
    'time',                        // 1. HTML5语义化标签
    '[datetime]',                  // 2. datetime属性
    '[class*="timestamp"]',        // 3. timestamp类名
    '[class*="time"]'              // 4. time类名
];
```

**正则表达式兜底：**
```javascript
const timePatterns = [
    /[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2}\s+[AP]M/,
    /\d{1,2}月\d{1,2}日\s+\d{1,2}:\d{2}/,
    /\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}/
];

for (const pattern of timePatterns) {
    const match = allText.match(pattern);
    if (match) {
        timestamp = match[0];
        break;
    }
}
```

### 4. 消息内容选择器

#### Whop页面结构

消息内容嵌套在多层div中：

```html
<div class="bg-gray-3 rounded-[18px] px-3 py-1.5">
  <div class="relative flex max-w-full">
    <div class="flex max-w-full flex-col gap-1">
      <p>GILD - $130 CALLS 这周 1.5-1.60</p>
      <p>小仓位 止损 在 1.3</p>
    </div>
  </div>
</div>
```

#### 最佳策略

**查找所有段落：**
```javascript
const contentSelectors = [
    '[class*="bg-gray-3"][class*="rounded"]',  // 消息气泡
    '[class*="whitespace-pre-wrap"]',          // 文本容器
    'p'                                         // 段落标签
];

// 查找所有匹配的元素
const contentElements = msgEl.querySelectorAll(selector);
```

**提取并过滤：**
```javascript
const texts = [];
for (const el of contentElements) {
    const text = el.innerText.trim();
    
    // 过滤元数据
    if (text && 
        text.length > 1 && 
        text !== '•' &&
        text !== author &&
        text !== timestamp) {
        texts.push(text);
    }
}

// 去重
const uniqueTexts = [...new Set(texts)];
```

### 5. 引用消息选择器

#### Whop引用结构

```html
<div class="peer/reply relative mb-1.5 ...">
  <div class="border-t border-l ...">
    <!-- 引用的原始消息 -->
  </div>
</div>
```

#### 选择器

```javascript
const quoteSelectors = [
    '[class*="peer/reply"]',       // Whop特定样式
    '[class*="reply"]',
    '[class*="quote"]',
    '[class*="border-t"]'          // 引用可能有边框
];
```

**长度验证：**
```javascript
if (quoteText.length > 5 && quoteText.length < 500) {
    // 只保留合理长度的引用
    quoted_message = quoteText.substring(0, 200);
}
```

## 📊 优化效果对比

### 优化前 (v2.6.2)

```
1. 消息组 ID: post_1CXNbKK8oK74QriUZv3rmK
   作者: (未识别)
   时间: (继承自上一条)
   主消息: 1.9附近出三分之一...
   引用内容: 1.9附近出三分之一...

   完整内容:
      [引用] 1.9附近出三分之一
      1.9附近出三分之一        # 重复!
```

### 优化后 (v2.6.4)

```
1. 消息组 ID: post_1CXNbKK8oK74QriUZv3rmK
   作者: xiaozhaolucky       # ✅ 正确识别
   时间: Jan 22, 2026 10:41 PM  # ✅ 准确提取
   主消息: GILD - $130 CALLS 这周 1.5-1.60
   
   完整内容:
      GILD - $130 CALLS 这周 1.5-1.60
      小仓位 止损 在 1.3      # ✅ 无重复
```

## 🎯 调试技巧

### 1. 添加控制台日志

```javascript
console.log(`✅ 使用选择器: ${selector}, 找到 ${messageElements.length} 个消息`);
console.log(`作者: "${group.author}"`);
console.log(`时间: "${group.timestamp}"`);
console.log(`内容: "${group.primary_message}"`);
```

### 2. 保存示例HTML

```javascript
group.element_html = msgEl.outerHTML.substring(0, 500);
```

在Python端打印：
```python
for group in message_groups:
    print(f"示例HTML: {group.element_html}")
```

### 3. 浏览器控制台测试

```javascript
// 测试选择器
document.querySelectorAll('[data-message-id]').length

// 查看第一个消息的完整结构
console.dir(document.querySelector('[data-message-id]'))

// 查看所有文本节点
const walker = document.createTreeWalker(
    document.querySelector('[data-message-id]'),
    NodeFilter.SHOW_TEXT
);
let node;
while (node = walker.nextNode()) {
    console.log(node.textContent.trim());
}
```

## 📝 完整工作流程

```bash
# 1. 发现问题
python3 main.py --test message-extractor
# 输出: 作者 (未识别), 时间 (继承自上一条)

# 2. 导出DOM分析
python3 main.py --test export-dom

# 3. 查看分析报告
cat debug/analysis_*.txt

# 4. 在浏览器中验证
open debug/page_*.html
# 使用F12开发者工具查看元素

# 5. 调整选择器
vim scraper/message_extractor.py
# 根据DOM结构更新选择器

# 6. 测试验证
python3 main.py --test message-extractor
# 检查输出是否正确

# 7. 如果还有问题,重复2-6步骤
```

## 💡 最佳实践

### 1. 选择器健壮性

**好的选择器：**
```javascript
'[data-message-id]'              // ✅ 使用数据属性
'time[datetime]'                  // ✅ 组合选择器
'[class*="message"]'              // ✅ 属性包含匹配
```

**不好的选择器：**
```javascript
'.message-1234567'                // ❌ 包含动态ID
'div > div > div > p'            // ❌ 过度依赖结构
'div:nth-child(3)'               // ❌ 依赖顺序
```

### 2. 多重保护

```javascript
// 提供多个候选选择器
const selectors = [
    'best-selector',      // 最准确
    'good-selector',      // 备用
    'fallback-selector'   // 兜底
];

for (const selector of selectors) {
    const elements = document.querySelectorAll(selector);
    if (elements.length > 0) break;  // 找到就停止
}
```

### 3. 内容验证

```javascript
// 验证提取的内容是否合理
if (text && 
    text.length > minLength && 
    text.length < maxLength &&
    !isMetadata(text)) {
    // 内容有效
}
```

### 4. 去重处理

```javascript
// 使用Set自动去重
const uniqueTexts = [...new Set(texts)];
```

## 🐛 常见问题

### Q: 选择器找不到任何元素？

A: 
1. 检查选择器语法是否正确
2. 验证页面是否完全加载
3. 使用浏览器控制台测试选择器
4. 检查元素是否在iframe中

### Q: 提取的内容包含大量无关文本？

A: 
1. 使用更精确的选择器
2. 添加过滤规则
3. 排除元数据元素

### Q: 同一内容被提取多次？

A: 
1. 检查是否匹配到父子元素
2. 使用 `querySelector` 而不是 `querySelectorAll`
3. 添加去重逻辑

### Q: 页面结构经常变化怎么办？

A: 
1. 使用数据属性而不是样式类
2. 提供多个候选选择器
3. 定期运行DOM导出工具验证

## 📚 相关文档

- [DOM导出和调试指南](DEBUG_DOM.md)
- [消息上下文识别指南](MESSAGE_CONTEXT.md)
- [故障排查](../TROUBLESHOOTING.md)
- [CHANGELOG v2.6.4](../CHANGELOG.md#264)
