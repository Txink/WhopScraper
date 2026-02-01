# 🚀 快速上手指南

欢迎使用 Whop 消息抓取器！本指南将帮助您在 5 分钟内开始使用。

## 📋 前置要求

- Python 3.8+
- Playwright
- 稳定的网络连接

## ⚡ 三步快速开始

### 步骤 1: 安装依赖

```bash
# 进入项目目录
cd /Users/txink/Documents/code/playwright

# 安装 Python 依赖
pip3 install -r requirements.txt

# 安装 Playwright 浏览器
python3 -m playwright install chromium
```

### 步骤 2: 登录并保存 Cookie

```bash
# 运行登录助手
python3 whop_login.py
```

**操作**：
1. 浏览器会自动打开
2. 在浏览器中输入您的邮箱和密码
3. 完成登录后，返回终端按回车
4. Cookie 会自动保存到 `storage_state.json`

### 步骤 3: 开始抓取

**方式 A: 测试抓取（60 秒）**

```bash
python3 whop_scraper_simple.py \
  --url "https://whop.com/joined/stock-and-option/-gZyq1MzOZAWO98/app/" \
  --duration 60
```

**方式 B: 后台长期监控（推荐）**

```bash
# 使用一键启动脚本
./start_background_monitor.sh
```

选择 "1) screen 会话"，然后按提示操作即可。

## 🎯 常见使用场景

### 场景 1: 快速测试（临时使用）

```bash
# 测试 30 秒
python3 whop_scraper_simple.py \
  --url "https://whop.com/joined/stock-and-option/-gZyq1MzOZAWO98/app/" \
  --duration 30
```

### 场景 2: 后台监控（长期使用）

```bash
# 方法 A: 使用管理脚本（最简单）
./start_background_monitor.sh

# 方法 B: 使用 screen
screen -S whop
python3 whop_scraper_simple.py \
  --url "https://whop.com/joined/stock-and-option/-gZyq1MzOZAWO98/app/" \
  --duration 999999999 \
  --headless \
  --min-length 15 \
  --output messages.json
# 按 Ctrl+A, 然后按 D 分离
```

### 场景 3: 定时抓取（每天运行）

```bash
# 添加到 crontab
crontab -e

# 每天早上 9 点运行 8 小时
0 9 * * * cd /Users/txink/Documents/code/playwright && python3 whop_scraper_simple.py --url "https://whop.com/joined/stock-and-option/-gZyq1MzOZAWO98/app/" --duration 28800 --headless --output messages_$(date +\%Y\%m\%d).json >> logs/cron.log 2>&1
```

## 📊 管理和监控

### 查看运行状态

```bash
# 使用状态检查脚本
./check_status.sh

# 或手动查看
ps aux | grep whop_scraper_simple.py
screen -ls
tail -f logs/scraper*.log
```

### 停止监控

```bash
# 使用停止脚本
./stop_monitor.sh

# 或手动停止
kill $(pgrep -f whop_scraper_simple.py)
screen -X -S whop_monitor quit
```

### 查看抓取结果

```bash
# 查看日志
tail -50 logs/scraper_$(date +%Y%m%d)*.log

# 查看今日统计
grep "统计信息" logs/scraper_$(date +%Y%m%d)*.log -A 10

# 查看 JSON 输出
cat messages.json | jq '.'
```

## 🔧 核心功能

### 1. 智能去重

自动过滤重复消息：

```bash
python3 whop_scraper_simple.py --url "URL" --min-length 15
```

**效果**：
- 去重过滤：~50%
- 噪音过滤：~3%
- 去重效率：~49%

### 2. 自动滚动（可选）

如果页面需要滚动才能加载新消息：

```bash
python3 whop_scraper_simple.py --url "URL" --auto-scroll
```

### 3. 保存到文件

```bash
python3 whop_scraper_simple.py --url "URL" --output messages.json
```

输出格式：
```json
[
  {
    "id": "post_xxx",
    "text": "GILD - $130 CALLS 这周 1.5-1.60",
    "timestamp": "2026-01-30T22:17:20.123456"
  }
]
```

## ⚙️ 参数说明

| 参数 | 说明 | 默认值 | 示例 |
|------|------|--------|------|
| `--url` | 要抓取的页面 URL | 必填 | `--url "URL"` |
| `--duration` | 运行时长（秒） | 30 | `--duration 3600` |
| `--headless` | 后台运行（不显示浏览器） | 否 | `--headless` |
| `--min-length` | 最小消息长度（字符） | 10 | `--min-length 15` |
| `--output` | 保存到 JSON 文件 | 无 | `--output messages.json` |
| `--auto-scroll` | 启用自动滚动 | 否 | `--auto-scroll` |
| `--no-stats` | 不显示统计信息 | 否 | `--no-stats` |

## 🔐 Cookie 管理

### 测试 Cookie 是否有效

```bash
python3 whop_login.py --test
```

### Cookie 过期了怎么办？

```bash
# 重新登录
python3 whop_login.py
```

**建议**：每周测试一次 Cookie 状态

## 📚 完整文档

### 入门文档
- [快速参考](./QUICK_REFERENCE.md) - 常用命令速查
- [登录指南](./WHOP_LOGIN_GUIDE.md) - Cookie 管理详解
- **本文档** - 快速上手指南

### 高级文档
- [去重功能指南](./DEDUPLICATION_GUIDE.md) - 去重机制详解
- [自动滚动指南](./AUTO_SCROLL_GUIDE.md) - 懒加载支持
- [后台监控指南](./BACKGROUND_MONITORING.md) - 长期运行方案
- [故障排查](./TROUBLESHOOTING.md) - 常见问题解决

### 完整系统
- [项目 README](./README.md) - 完整项目说明
- [使用指南](./doc/USAGE_GUIDE.md) - 详细使用教程
- [配置说明](./doc/CONFIGURATION.md) - 环境变量配置
- [长桥集成](./doc/LONGPORT_INTEGRATION_GUIDE.md) - 自动交易

## 💡 最佳实践

### 1. 首次使用

```bash
# 1. 登录
python3 whop_login.py

# 2. 短时间测试
python3 whop_scraper_simple.py --url "URL" --duration 60

# 3. 检查结果
# 如果能正常抓取消息，说明配置成功

# 4. 启动长期监控
./start_background_monitor.sh
```

### 2. 日常维护

```bash
# 每天检查状态
./check_status.sh

# 每周测试 Cookie
python3 whop_login.py --test

# 查看日志
tail -f logs/scraper_*.log
```

### 3. 问题排查

```bash
# 1. 检查进程状态
./check_status.sh

# 2. 查看错误日志
grep -i "error\|exception" logs/scraper_*.log

# 3. 测试 Cookie
python3 whop_login.py --test

# 4. 如果 Cookie 过期，重新登录
python3 whop_login.py

# 5. 重启监控
./stop_monitor.sh
./start_background_monitor.sh
```

## 🎓 学习路径

### 新手（刚开始使用）
1. ✅ 按照"三步快速开始"操作
2. ✅ 阅读 [快速参考](./QUICK_REFERENCE.md)
3. ✅ 尝试不同的参数组合

### 进阶（熟悉基本操作）
1. ✅ 阅读 [去重功能指南](./DEDUPLICATION_GUIDE.md)
2. ✅ 阅读 [后台监控指南](./BACKGROUND_MONITORING.md)
3. ✅ 设置自动化任务（crontab）

### 高级（需要自定义）
1. ✅ 阅读 [故障排查](./TROUBLESHOOTING.md)
2. ✅ 修改脚本参数和选择器
3. ✅ 集成到其他系统

## ❓ 常见问题

### Q1: 如何让脚本一直运行？

**A**: 使用管理脚本：

```bash
./start_background_monitor.sh
```

选择 "1) screen 会话" 或 "3) 无限循环"。

### Q2: 如何查看抓取了多少消息？

**A**: 查看状态：

```bash
./check_status.sh
```

或查看日志：

```bash
grep "唯一消息" logs/scraper_*.log | tail -1
```

### Q3: Cookie 多久会过期？

**A**: 通常 7-30 天。建议：

```bash
# 每周测试一次
python3 whop_login.py --test
```

### Q4: 如何在服务器上运行？

**A**: 使用 nohup 或 systemd 服务，参考 [后台监控指南](./BACKGROUND_MONITORING.md)。

### Q5: 抓取的消息保存在哪里？

**A**: 
- 屏幕输出：终端或日志文件
- JSON 文件：使用 `--output` 参数指定
- 完整日志：`logs/` 目录

## 🆘 获取帮助

1. **查看帮助信息**：
   ```bash
   python3 whop_scraper_simple.py --help
   python3 whop_login.py --help
   ```

2. **查看文档**：
   - 项目根目录的 `*.md` 文件
   - `doc/` 目录的详细文档

3. **故障排查**：
   - 查看 [TROUBLESHOOTING.md](./TROUBLESHOOTING.md)

4. **提交 Issue**：
   - 提供完整的错误信息
   - 说明使用的命令
   - 附上相关日志

## 🎉 完成！

现在您已经掌握了基本使用方法，可以：

- ✅ 登录并保存 Cookie
- ✅ 抓取 Whop 页面消息
- ✅ 在后台长期运行
- ✅ 查看和管理监控状态

**下一步**：
- 查看 [快速参考](./QUICK_REFERENCE.md) 了解更多命令
- 阅读 [后台监控指南](./BACKGROUND_MONITORING.md) 了解高级用法
- 探索 [完整项目功能](./README.md)（包含自动交易）

祝使用愉快！🚀
