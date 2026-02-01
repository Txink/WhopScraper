# 快速参考指南

## 🚀 快速开始（三步）

```bash
# 1. 安装依赖
pip3 install -r requirements.txt && python3 -m playwright install chromium

# 2. 登录并保存 Cookie
python3 whop_login.py

# 3. 开始抓取
python3 whop_scraper_simple.py --url "你的 Whop 页面 URL"
```

## 📋 常用命令

### 后台监控（一直运行）

```bash
# 🚀 方法 1: 一键启动（推荐，最简单）
./start_background_monitor.sh
# 交互式配置，支持多种运行模式

# 📊 查看运行状态
./check_status.sh

# 🛑 停止监控
./stop_monitor.sh

# ============================================

# 方法 2: 使用 screen（手动）
screen -S whop
python3 whop_scraper_simple.py --url "URL" --duration 999999999 --headless --min-length 15 --output messages.json
# 按 Ctrl+A, 然后按 D 分离

# 重新连接
screen -r whop

# 方法 3: 使用 nohup
nohup python3 whop_scraper_simple.py --url "URL" --duration 86400 --headless --min-length 15 --output messages.json > scraper.log 2>&1 &
# 查看日志: tail -f scraper.log

# 方法 4: 自动重启
nohup bash -c 'while true; do python3 whop_scraper_simple.py --url "URL" --duration 86400 --headless --min-length 15 --output messages.json; sleep 10; done' > scraper.log 2>&1 &
```

📖 **详细说明**：[后台监控完整指南](./BACKGROUND_MONITORING.md)

### 登录管理

```bash
# 首次登录 / 重新登录
python3 whop_login.py

# 测试登录状态
python3 whop_login.py --test

# 使用自定义 Cookie 文件
python3 whop_login.py --storage "my_cookies.json"
```

### 消息抓取（支持智能去重）

```bash
# 基本抓取（30 秒，自动去重）
python3 whop_scraper_simple.py --url "URL"

# 自定义时长
python3 whop_scraper_simple.py --url "URL" --duration 60

# 后台运行（无头模式）
python3 whop_scraper_simple.py --url "URL" --headless

# 过滤噪音（最小消息长度）
python3 whop_scraper_simple.py --url "URL" --min-length 15

# 保存到文件
python3 whop_scraper_simple.py --url "URL" --output messages.json

# 简洁输出（不显示统计）
python3 whop_scraper_simple.py --url "URL" --no-stats

# 启用自动滚动（懒加载页面）
python3 whop_scraper_simple.py --url "URL" --auto-scroll

# 自定义滚动间隔
python3 whop_scraper_simple.py --url "URL" --auto-scroll --scroll-interval 10

# 完整示例
python3 whop_scraper_simple.py --url "URL" --duration 300 --headless --auto-scroll --min-length 15 --output messages.json

# 使用自定义 Cookie
python3 whop_scraper_simple.py --url "URL" --storage "my_cookies.json"
```

### 完整系统

```bash
# 配置环境变量
cp .env.example .env && nano .env

# 验证配置
python3 check_config.py

# 启动完整系统（监控 + 解析 + 自动交易）
python3 main.py
```

## 🔧 故障排查

| 问题 | 解决方法 |
|------|---------|
| Cookie 过期 | `python3 whop_login.py` |
| 找不到消息 | 去掉 `--headless`，观察浏览器 |
| 安装失败 | `pip3 install --upgrade pip && pip3 install -r requirements.txt` |
| 浏览器未安装 | `python3 -m playwright install chromium` |

## 📁 重要文件

| 文件 | 用途 | 是否提交 Git |
|------|------|-------------|
| `storage_state.json` | 保存的登录 Cookie | ❌ 否 |
| `.env` | 环境变量配置 | ❌ 否 |
| `.env.example` | 配置模板 | ✅ 是 |
| `whop_login.py` | 登录助手脚本 | ✅ 是 |
| `whop_scraper_simple.py` | 简单抓取器 | ✅ 是 |
| `main.py` | 完整系统主程序 | ✅ 是 |

## 🎯 使用场景

### 场景 1: 只需要抓取消息

```bash
python3 whop_login.py
python3 whop_scraper_simple.py --url "URL" --duration 300
```

### 场景 2: 自动交易（完整功能）

```bash
cp .env.example .env
# 编辑 .env 填入凭据
python3 check_config.py
python3 main.py
```

### 场景 3: 多账号管理

```bash
# 账号 1
python3 whop_login.py --storage "account1.json"
python3 whop_scraper_simple.py --url "URL" --storage "account1.json"

# 账号 2
python3 whop_login.py --storage "account2.json"
python3 whop_scraper_simple.py --url "URL" --storage "account2.json"
```

### 场景 4: 定时自动抓取

```bash
# 添加到 crontab
crontab -e

# 每小时执行一次（抓取 5 分钟）
0 * * * * cd /path/to/playwright && python3 whop_scraper_simple.py --url "URL" --duration 300 --headless >> /path/to/logs/scraper.log 2>&1
```

## 📚 详细文档

- [Whop 登录指南](./WHOP_LOGIN_GUIDE.md) - 登录和抓取详细教程
- [项目 README](./README.md) - 完整项目说明
- [配置文档](./doc/CONFIGURATION.md) - 环境变量配置
- [使用指南](./doc/USAGE_GUIDE.md) - 完整使用教程

## 💡 提示

1. **首次使用**：建议使用非无头模式，观察浏览器行为
2. **定期测试**：定期运行 `python3 whop_login.py --test` 检查 Cookie 状态
3. **安全第一**：不要分享 `storage_state.json` 和 `.env` 文件
4. **调试技巧**：遇到问题时去掉 `--headless` 参数查看浏览器
5. **日志记录**：使用 `> log.txt 2>&1` 重定向输出到文件

## ⚡ 一键运行

使用交互式脚本：

```bash
# 运行交互式配置和抓取脚本
./example_usage.sh
```

这个脚本会引导您完成：
1. 检查依赖
2. 登录或测试 Cookie
3. 配置抓取参数
4. 开始抓取

## 🆘 获取帮助

```bash
# 查看命令帮助
python3 whop_login.py --help
python3 whop_scraper_simple.py --help

# 查看完整文档
cat WHOP_LOGIN_GUIDE.md

# 查看项目结构
cat PROJECT_STRUCTURE.md
```

## 📞 支持

- 📖 文档：查看 `doc/` 目录中的各类文档
- 💬 问题：提交 GitHub Issue
- 📝 示例：参考 `samples/` 目录中的示例
