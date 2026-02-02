# Whop聊天页面DOM结构指南

## 📋 概述

本文档详细说明了Whop聊天页面的DOM结构特征，用于指导消息提取和解析逻辑。

## 🏗️ 核心结构

### 消息容器

每条消息都包裹在 `class="group/message"` 的 div 下：

```html
<div class="group/message" 
     data-message-id="post_1CXNbG1zAyv8MfM1oD7dEz"
     data-is-own-message="false"
     data-has-message-above="false"
     data-has-message-below="true">
  <!-- 消息内容 -->
</div>
```

**关键属性**：
- `data-message-id`: 消息唯一标识符
  - ✅ **稳定不变**：即使页面刷新或重新进入，此ID保持不变
  - 可用于消息追踪、去重、历史记录匹配
  - 格式：`post_` + 唯一字符串（如 `post_1CXNbG1zAyv8MfM1oD7dEz`）
- `data-is-own-message`: 是否是当前用户发送的消息
- `data-has-message-above`: 是否与上一条消息在同一组
- `data-has-message-below`: 是否有下一条同组消息

## 📊 消息组边界识别

通过 `data-has-message-above` 和 `data-has-message-below` 两个属性的组合，可以精确判断消息在组中的位置：

### 1. 单条消息组

```
data-has-message-above="false"
data-has-message-below="false"
```

**特征**：
- 消息组只有一条消息
- 有完整的头部（头像、用户名、时间戳）
- 消息气泡独立显示

**示例**：
```html
<div class="group/message" 
     data-has-message-above="false"
     data-has-message-below="false">
  <span class="fui-AvatarRoot">...</span>
  <span>xiaozhaolucky</span>
  <span>Jan 23, 2026 12:51 AM</span>
  <div class="bg-gray-3 rounded-[18px]">
    <p>nvda剩下部分也2.45附近出</p>
  </div>
</div>
```

### 2. 消息组第一条

```
data-has-message-above="false"
data-has-message-below="true"
```

**特征**：
- 消息组有多条消息，这是第一条
- 有完整的头部信息
- 下方还有同组消息

**示例**：
```html
<div class="group/message" 
     data-has-message-above="false"
     data-has-message-below="true">
  <span class="fui-AvatarRoot">...</span>
  <span>xiaozhaolucky</span>
  <span>Jan 23, 2026 12:46 AM</span>
  <div class="bg-gray-3 rounded-[18px] rounded-bl-lg">
    <p>2.45也在剩下减一半</p>
  </div>
</div>
```

**注意**：消息气泡的圆角可能不同（如 `rounded-bl-lg`）

### 3. 消息组中间消息

```
data-has-message-above="true"
data-has-message-below="true"
```

**特征**：
- 消息组有多条消息，这是中间的某条
- **没有头部信息**（用户名、时间戳隐藏）
- 上下都有同组消息

**示例**：
```html
<div class="group/message" 
     data-has-message-above="true"
     data-has-message-below="true">
  <!-- 没有头像、用户名、时间戳 -->
  <div class="bg-gray-3 rounded-[18px] rounded-bl-lg rounded-tl-lg">
    <p>1.9附近出三分之一</p>
  </div>
</div>
```

**关键**：中间消息需要从消息组的第一条继承时间戳和作者信息！

### 4. 消息组最后一条

```
data-has-message-above="true"
data-has-message-below="false"
```

**特征**：
- 消息组有多条消息，这是最后一条
- 可能有头像（显示在最后一条）
- 没有完整头部，但可能有时间戳

**示例**：
```html
<div class="group/message" 
     data-has-message-above="true"
     data-has-message-below="false">
  <span class="fui-AvatarRoot">...</span>  <!-- 头像可能在最后一条 -->
  <div class="bg-gray-3 rounded-[18px] rounded-tl-lg">
    <p>剩下看转弯往下时候都出 止损上移到2.25</p>
  </div>
  <span class="text-gray-11 text-0">由 267阅读</span>
</div>
```

## 📝 消息组头部信息

### 用户名

**DOM路径**：
```html
<span role="button" 
      class="truncate cursor-pointer hover:underline fui-HoverCardTrigger"
      tabindex="0">
  xiaozhaolucky
</span>
```

**选择器**：
- 最精确：`span[role="button"].truncate.fui-HoverCardTrigger`
- 备用：`[class*="fui-Text"][class*="truncate"]`

### 时间戳

**DOM结构**：
```html
<span class="text-1 text-gray-10 inline-flex items-center gap-1">
  <span>xiaozhaolucky</span>
  <div class="flex shrink-0 items-center gap-1">
    <span>•</span>
    <span>Jan 23, 2026 12:46 AM</span>
  </div>
</span>
```

**选择器**：
- 容器：`.inline-flex.items-center.gap-1`
- 时间戳：匹配格式 `Jan 23, 2026 12:46 AM`

**格式**：`月份 日期, 年份 时:分 AM/PM`

### 头像

**DOM结构**：
```html
<span class="fui-AvatarRoot size-8 fui-r-size-3 fui-shape-circle">
  <span class="fui-AvatarFallback fui-one-letter hidden">X</span>
  <img alt="头像" class="fui-AvatarImage" src="...">
</span>
```

**位置**：
- 单条消息：在消息顶部
- 多条消息：在第一条或最后一条

**选择器**：
- `.fui-AvatarRoot`
- `.fui-AvatarImage`

## 🔗 引用消息

### DOM结构

```html
<div class="peer/reply relative mb-1.5 max-w-4/5 space-x-1.5 outline-none select-none cursor-pointer hover:opacity-70"
     role="button" tabindex="-1" aria-disabled="false">
  <!-- 引用连接线 -->
  <div class="absolute top-1/2 -bottom-2.5 right-full -left-[29px]">
    <div class="border-gray-5 absolute z-[1] aspect-square h-full rounded-tl-lg border-t-2 border-l-2"></div>
  </div>
  
  <!-- 引用内容 -->
  <div class="flex items-center gap-1.5 truncate">
    <span class="fui-AvatarRoot size-5">...</span>
    <span class="fui-Text truncate">GILD - $130 CALLS 这周 1.5-1.60</span>
  </div>
</div>
```

### 提取规则

**容器选择器**：
- 最精确：`.peer\\/reply` （需要转义斜杠）
- 备用：`[class*="peer/reply"]`

**引用文本选择器**（关键！）：
- **精确路径**：`.peer\\/reply [class*="fui-Text"][class*="truncate"]`
- 这个 span 包含被引用消息的预览文本

**示例提取**：
```javascript
const quoteEl = msgEl.querySelector('.peer\\/reply');
if (quoteEl) {
  const quoteTextSpan = quoteEl.querySelector('[class*="fui-Text"][class*="truncate"]');
  const quoteText = quoteTextSpan.textContent.trim();
  // 输出: "GILD - $130 CALLS 这周 1.5-1.60"
}
```

### 引用的视觉特征

- 左侧有圆角边框线连接到上方消息
- 包含被引用消息的头像缩略图
- 引用文本被截断显示（truncate）

## 💬 消息气泡

### DOM结构

```html
<div class="bg-gray-3 rounded-[18px] px-3 py-1.5 text-[15px]">
  <div class="text-[15px] whitespace-pre-wrap">
    <p>消息内容<br></p>
  </div>
  <svg fill="none" height="16" width="16">
    <title>Tail</title>
    <!-- SVG尾巴图形 -->
  </svg>
</div>
```

### 关键类名

- `bg-gray-3` - 背景色（灰色）
- `rounded-[18px]` - 圆角半径
- `whitespace-pre-wrap` - 保留换行和空格
- `px-3 py-1.5` - 内边距

### 圆角变化

根据消息在组中的位置，圆角可能不同：

- **单条/第一条**：`rounded-bl-lg`（左下角大圆角）
- **中间消息**：`rounded-bl-lg rounded-tl-lg`（左侧都是大圆角）
- **最后一条**：`rounded-tl-lg`（左上角大圆角）

这样形成视觉上连续的消息组效果。

## 📷 图片消息

### DOM结构

```html
<div class="group/message" data-has-message-above="false">
  <!-- 图片容器 -->
  <img src="https://img-v2-prod.whop.com/..." 
       alt="图片" 
       loading="lazy"
       class="...">
  
  <!-- 或带data-attachment-id属性 -->
  <div data-attachment-id="xxx">
    <img src="..." />
  </div>
  
  <!-- 阅读量（可能是唯一文本） -->
  <span class="text-gray-11 text-0">由 223阅读</span>
</div>
```

### 检测方法

```javascript
const hasAttachment = 
  msgEl.querySelector('[data-attachment-id]') || 
  msgEl.querySelector('img[src*="whop.com"]') ||
  msgEl.querySelector('[class*="attachment"]');
```

### 过滤规则

**纯图片消息**（应忽略）：
- 有图片附件
- 主消息只有阅读量或为空
- 没有实质文本内容

**有内容的图片消息**（应保留）：
- 有图片附件
- 有实质文本内容
- 提取图片URL和文本

## 🏷️ 元数据标记

### 阅读量

```html
<span class="text-gray-11 text-0 h-[15px] px-0.5">由 268阅读</span>
```

**特征**：
- `text-gray-11 text-0` 类名组合
- 格式：`由 XXX阅读` 或 `XXX阅读`
- 正则：`/^(由\s*)?\d+\s*阅读$/`

### 尾巴标记

```html
<svg>
  <title>Tail</title>
  <!-- SVG图形 -->
</svg>
```

**处理**：需要过滤掉 "Tail" 文本

### 编辑标记

```html
<span>已编辑</span>
<!-- 或 -->
<span>Edited</span>
```

**处理**：识别并过滤

## 🔍 选择器优先级

### 消息容器

1. `.group\\/message[data-message-id]` - 最精确
2. `[data-message-id]` - 次优
3. `.group\\/message` - 备用

### 用户名

1. `span[role="button"].truncate.fui-HoverCardTrigger` - 最精确
2. `[class*="fui-Text"][class*="truncate"]` - 备用

### 时间戳

1. `.inline-flex.items-center.gap-1` + 正则匹配 - 最精确
2. 正则在整个元素文本中搜索 - 备用

### 消息内容

1. `.bg-gray-3[class*="rounded"]` - 消息气泡
2. `[class*="whitespace-pre-wrap"]` - 文本容器
3. `p` - 段落标签

### 引用消息

1. `.peer\\/reply [class*="fui-Text"][class*="truncate"]` - 最精确
2. `.peer\\/reply` 整体文本 - 备用

## 📐 提取逻辑流程

### 1. 识别消息组边界

```javascript
const hasAbove = msgEl.getAttribute('data-has-message-above');
const hasBelow = msgEl.getAttribute('data-has-message-below');

if (hasAbove === 'false') {
  // 新消息组开始
  // 提取完整头部信息
  extractAuthor();
  extractTimestamp();
  extractAvatar();
} else {
  // 继承上一条消息的头部信息
  inheritFromPreviousMessage();
}
```

### 2. 提取引用

```javascript
const quoteEl = msgEl.querySelector('.peer\\/reply');
if (quoteEl) {
  // 精确提取引用文本
  const quoteTextSpan = quoteEl.querySelector('[class*="fui-Text"][class*="truncate"]');
  const quoteText = quoteTextSpan ? quoteTextSpan.textContent : quoteEl.textContent;
}
```

### 3. 提取消息内容

```javascript
// 从消息气泡提取
const bubbles = msgEl.querySelectorAll('.bg-gray-3[class*="rounded"]');
for (const bubble of bubbles) {
  // 跳过引用区域
  if (bubble.closest('.peer\\/reply')) continue;
  
  // 提取文本
  const text = bubble.innerText.trim();
  // 过滤元数据
  if (!shouldFilter(text)) {
    messages.push(text);
  }
}
```

### 4. 过滤元数据

```javascript
function shouldFilter(text) {
  // 阅读量
  if (/^(由\s*)?\d+\s*阅读$/.test(text)) return true;
  
  // 编辑标记
  if (text === '已编辑' || text === 'Edited') return true;
  
  // Tail标记
  if (text === 'Tail') return true;
  
  // 时间戳行
  if (/^•.*\d{1,2}:\d{2}\s+[AP]M$/.test(text)) return true;
  
  return false;
}
```

## 🎯 最佳实践

1. **始终使用最精确的选择器**
   - 优先使用组合选择器（如 `.peer\\/reply [class*="fui-Text"]`）
   - 避免过于宽泛的选择器

2. **利用DOM属性判断位置**
   - `data-has-message-above/below` 是最可靠的边界判断
   - 不要仅依赖CSS类名

3. **实现继承机制**
   - 消息组的第一条提取完整信息
   - 后续消息继承时间戳和作者

4. **分层过滤**
   - 先过滤DOM层级（跳过引用区域、头像区域）
   - 再过滤文本内容（元数据模式匹配）

5. **容错处理**
   - 提供备用选择器
   - 实现降级提取策略
   - 记录无法提取的情况

## 📚 参考实现

完整实现参见：
- `scraper/message_filter.py` - 过滤规则和DOM辅助类
- `scraper/message_extractor.py` - 消息提取逻辑
- `scraper/quote_matcher.py` - 引用匹配算法
