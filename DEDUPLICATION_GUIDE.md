# 智能去重功能指南

本文档介绍 Whop 消息抓取器的智能去重功能。

## 🎯 去重策略

### 三层去重机制

抓取器使用三层去重机制，确保消息的唯一性：

#### 1. 选择器优先级去重
- 使用优先级排序的选择器列表
- 优先使用最具体的选择器（如 `[id^="post_"]`）
- 找到消息后立即停止，避免重复提取

#### 2. 内容哈希去重
- 对每条消息的文本内容计算 MD5 哈希
- 即使消息 ID 不同，但内容相同也会被过滤
- 避免不同选择器提取到相同内容

#### 3. 消息 ID 去重
- 记录已见过的消息 ID
- 防止同一消息被重复处理
- 支持多种 ID 来源（data-message-id、id 属性、内容哈希）

## 📊 去重效果示例

### 抓取前（未去重）
```
总消息数: 101 条
- 包含重复内容
- 包含噪音消息（太短）
```

### 抓取后（已去重）
```
唯一消息: 50 条
去重过滤: 48 条
噪音过滤: 3 条
去重效率: 49.5%
```

## 🔧 使用方法

### 基本使用

```bash
# 默认去重配置
python3 whop_scraper_simple.py --url "https://whop.com/your-page/"
```

默认配置：
- 最小消息长度：10 字符
- 显示统计信息：是
- 去重模式：内容哈希 + ID 双重去重

### 自定义最小消息长度

```bash
# 过滤更多噪音（最小长度 20 字符）
python3 whop_scraper_simple.py --url "URL" --min-length 20

# 保留更多消息（最小长度 5 字符）
python3 whop_scraper_simple.py --url "URL" --min-length 5
```

**推荐设置**：
- 期权信号抓取：`--min-length 15`（过滤时间戳等短消息）
- 一般聊天消息：`--min-length 10`（默认值）
- 保留所有内容：`--min-length 1`

### 控制统计信息显示

```bash
# 显示详细统计（默认）
python3 whop_scraper_simple.py --url "URL"

# 简洁输出（不显示统计）
python3 whop_scraper_simple.py --url "URL" --no-stats
```

### 保存唯一消息到文件

```bash
# 保存为 JSON 格式
python3 whop_scraper_simple.py --url "URL" --output messages.json

# 保存并查看
python3 whop_scraper_simple.py --url "URL" --output messages.json
cat messages.json | jq '.'
```

输出格式：
```json
[
  {
    "id": "post_1CXNbEYnyqp6nMaetCZLtn",
    "text": "GILD - $130 CALLS 这周 1.5-1.60",
    "timestamp": "2026-01-30T22:17:20.123456"
  },
  {
    "id": "post_1CXNbG1zAyv8MfM1oD7dEz",
    "text": "小仓位 止损 在 1.3",
    "timestamp": "2026-01-30T22:17:21.234567"
  }
]
```

### 完整示例

```bash
# 所有功能组合
python3 whop_scraper_simple.py \
  --url "https://whop.com/your-page/" \
  --duration 300 \
  --headless \
  --min-length 15 \
  --output messages.json
```

这个命令会：
- ✅ 抓取 5 分钟（300 秒）
- ✅ 后台运行（无头模式）
- ✅ 过滤短于 15 字符的消息
- ✅ 保存唯一消息到 `messages.json`
- ✅ 显示去重统计信息

## 📈 统计信息解读

### 完整统计输出

```
============================================================
✅ 抓取完成！
============================================================
📊 统计信息：
   - 唯一消息：50 条
   - 去重过滤：48 条
   - 噪音过滤：3 条（< 10 字符）
   - 总处理数：101 条
   - 去重效率：49.5%
============================================================
💾 已保存 50 条唯一消息到: messages.json
============================================================
```

### 字段说明

| 字段 | 说明 |
|------|------|
| 唯一消息 | 最终提取的不重复消息数量 |
| 去重过滤 | 被过滤的重复消息数量 |
| 噪音过滤 | 被过滤的太短消息数量 |
| 总处理数 | 扫描到的所有消息数量 |
| 去重效率 | 唯一消息占总处理数的百分比 |

### 去重效率分析

**高效去重（效率 < 60%）**：
- 说明页面有大量重复内容
- 去重功能有效过滤了重复
- 推荐使用此配置

**低效去重（效率 > 90%）**：
- 说明页面内容大多唯一
- 可能需要调整选择器
- 或页面结构较简单

## 🔍 去重工作原理

### Python 端去重

```python
# 1. 提取消息时去重
messages_by_content = {}  # 内容哈希映射
for element in elements:
    content_hash = md5(text)
    if content_hash not in messages_by_content:
        messages_by_content[content_hash] = message

# 2. 处理消息时去重
seen_message_ids = set()
seen_message_hashes = set()

for msg in messages:
    content_hash = md5(msg['text'])
    if msg_id in seen_message_ids or content_hash in seen_message_hashes:
        continue  # 跳过重复
    
    seen_message_ids.add(msg_id)
    seen_message_hashes.add(content_hash)
```

### JavaScript 端去重

```javascript
// 在浏览器中执行去重
const seenContent = new Set();

for (const el of elements) {
    const text = el.innerText?.trim();
    
    // 内容去重
    if (seenContent.has(text)) continue;
    seenContent.add(text);
    
    messages.push({ id, text });
}
```

## 💡 高级技巧

### 1. 动态调整最小长度

根据实际消息情况调整：

```bash
# 先用默认值抓取
python3 whop_scraper_simple.py --url "URL" --duration 60

# 查看统计，如果噪音过滤数量多，增加最小长度
python3 whop_scraper_simple.py --url "URL" --min-length 20

# 查看统计，如果唯一消息太少，减少最小长度
python3 whop_scraper_simple.py --url "URL" --min-length 5
```

### 2. 对比去重效果

```bash
# 抓取同一页面两次，对比结果
python3 whop_scraper_simple.py --url "URL" --output run1.json
python3 whop_scraper_simple.py --url "URL" --output run2.json

# 使用 jq 对比
jq '.[] | .text' run1.json | sort > run1_sorted.txt
jq '.[] | .text' run2.json | sort > run2_sorted.txt
diff run1_sorted.txt run2_sorted.txt
```

### 3. 批量处理多个页面

```bash
# 创建脚本
cat > scrape_all.sh << 'EOF'
#!/bin/bash
URLS=(
  "https://whop.com/page1"
  "https://whop.com/page2"
  "https://whop.com/page3"
)

for i in "${!URLS[@]}"; do
  echo "抓取页面 $((i+1))..."
  python3 whop_scraper_simple.py \
    --url "${URLS[$i]}" \
    --duration 60 \
    --headless \
    --output "messages_page$((i+1)).json"
done

echo "全部完成！"
EOF

chmod +x scrape_all.sh
./scrape_all.sh
```

### 4. 实时监控去重效率

```bash
# 使用 watch 实时查看统计
watch -n 5 'tail -20 scraper.log | grep -A 5 "统计信息"'

# 或者使用后台运行并实时查看
python3 whop_scraper_simple.py --url "URL" --duration 3600 \
  > scraper.log 2>&1 &

tail -f scraper.log
```

## 🐛 故障排查

### 问题 1: 唯一消息数量为 0

**可能原因**：
- 最小长度设置过高
- 页面选择器不匹配
- Cookie 过期

**解决方法**：
```bash
# 1. 降低最小长度
python3 whop_scraper_simple.py --url "URL" --min-length 1

# 2. 使用非无头模式观察
python3 whop_scraper_simple.py --url "URL"

# 3. 重新登录
python3 whop_login.py
```

### 问题 2: 去重效率过低（< 30%）

**可能原因**：
- 页面结构复杂，重复提取
- 选择器不够精确

**解决方法**：
- 已在代码中优化，使用优先级选择器
- 如仍有问题，查看 `TROUBLESHOOTING.md`

### 问题 3: 噪音过滤太多

**现象**：噪音过滤数量远大于唯一消息

**解决方法**：
```bash
# 降低最小长度
python3 whop_scraper_simple.py --url "URL" --min-length 5
```

### 问题 4: 保存文件失败

**可能原因**：
- 文件路径不存在
- 权限不足

**解决方法**：
```bash
# 确保目录存在
mkdir -p output
python3 whop_scraper_simple.py --url "URL" --output output/messages.json

# 检查权限
chmod 755 output
```

## 📚 相关文档

- [快速参考](./QUICK_REFERENCE.md) - 常用命令速查
- [登录指南](./WHOP_LOGIN_GUIDE.md) - Cookie 管理
- [故障排查](./TROUBLESHOOTING.md) - 问题解决
- [项目 README](./README.md) - 完整项目文档

## 🎓 最佳实践

### 推荐配置

**日常监控**：
```bash
python3 whop_scraper_simple.py \
  --url "URL" \
  --duration 300 \
  --headless \
  --min-length 10 \
  --output messages_$(date +%Y%m%d_%H%M%S).json
```

**首次测试**：
```bash
# 不使用无头模式，观察浏览器
python3 whop_scraper_simple.py \
  --url "URL" \
  --duration 60 \
  --min-length 10
```

**生产环境**：
```bash
# 长时间运行，保存日志
nohup python3 whop_scraper_simple.py \
  --url "URL" \
  --duration 3600 \
  --headless \
  --min-length 15 \
  --output messages.json \
  > scraper.log 2>&1 &
```

### 性能优化

1. **选择合适的监控时长**：
   - 短时测试：30-60 秒
   - 日常监控：300-600 秒
   - 长期监控：1800-3600 秒

2. **调整最小长度**：
   - 过滤更多噪音：15-20 字符
   - 平衡过滤：10 字符（默认）
   - 保留更多内容：5 字符

3. **使用无头模式**：
   - 生产环境：始终使用 `--headless`
   - 开发调试：不使用 `--headless`

## 🔄 更新日志

### v2.0 - 智能去重版本
- ✅ 添加内容哈希去重
- ✅ 添加噪音过滤（最小长度）
- ✅ 添加去重统计信息
- ✅ 添加消息保存功能
- ✅ 优化选择器优先级
- ✅ 改进 JavaScript 提取逻辑

### v1.0 - 基础版本
- ✅ 基本消息提取
- ✅ 简单 ID 去重
- ✅ Cookie 管理

## 💬 反馈

如有问题或建议，请查阅：
- [故障排查指南](./TROUBLESHOOTING.md)
- [快速参考](./QUICK_REFERENCE.md)
- 提交 GitHub Issue
