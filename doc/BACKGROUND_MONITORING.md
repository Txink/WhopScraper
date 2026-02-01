# 后台监控完整指南

本指南介绍如何让 Whop 抓取器在后台持续运行。

## 📋 目录

- [方法 1: nohup 后台运行](#方法-1-nohup-后台运行)
- [方法 2: screen/tmux 会话](#方法-2-screentmux-会话)
- [方法 3: 系统服务](#方法-3-系统服务-推荐)
- [方法 4: crontab 定时重启](#方法-4-crontab-定时重启)
- [方法 5: 无限循环模式](#方法-5-无限循环模式)
- [监控和管理](#监控和管理)

## 🚀 方法 1: nohup 后台运行

最简单的方法，适合临时使用。

### 基本用法

```bash
# 启动后台监控（长时间运行）
nohup python3 whop_scraper_simple.py \
  --url "https://whop.com/joined/stock-and-option/-gZyq1MzOZAWO98/app/" \
  --duration 86400 \
  --headless \
  --min-length 15 \
  --output messages.json \
  > scraper.log 2>&1 &

# 记录进程 ID
echo $! > scraper.pid
```

**说明**：
- `nohup`：让进程在后台持续运行，即使关闭终端
- `--duration 86400`：运行 24 小时（86400 秒）
- `> scraper.log 2>&1`：将输出重定向到日志文件
- `&`：在后台运行
- `echo $!`：保存进程 ID

### 查看运行状态

```bash
# 查看日志（实时）
tail -f scraper.log

# 查看最新的 50 行
tail -50 scraper.log

# 搜索特定内容
grep "消息 #" scraper.log | tail -20

# 查看统计信息
grep "统计信息" scraper.log -A 10
```

### 停止进程

```bash
# 使用保存的 PID
kill $(cat scraper.pid)

# 或者查找进程
ps aux | grep whop_scraper_simple.py

# 强制停止
kill -9 <PID>
```

### 自动重启脚本

```bash
# 创建自动重启脚本
cat > start_monitor.sh << 'EOF'
#!/bin/bash

LOG_FILE="scraper_$(date +%Y%m%d_%H%M%S).log"
PID_FILE="scraper.pid"

echo "启动 Whop 监控器..."

while true; do
  echo "$(date): 启动新的监控周期" >> "$LOG_FILE"
  
  nohup python3 whop_scraper_simple.py \
    --url "https://whop.com/joined/stock-and-option/-gZyq1MzOZAWO98/app/" \
    --duration 86400 \
    --headless \
    --min-length 15 \
    --output messages_$(date +%Y%m%d).json \
    >> "$LOG_FILE" 2>&1 &
  
  echo $! > "$PID_FILE"
  PID=$(cat "$PID_FILE")
  
  echo "进程已启动，PID: $PID"
  
  # 等待进程结束
  wait $PID
  
  echo "$(date): 监控周期结束，5 秒后重启..." >> "$LOG_FILE"
  sleep 5
done
EOF

chmod +x start_monitor.sh

# 启动
nohup ./start_monitor.sh > monitor.log 2>&1 &
```

## 🖥️ 方法 2: screen/tmux 会话

适合需要随时查看和操作的场景。

### 使用 screen

```bash
# 安装 screen（如果未安装）
# macOS
brew install screen

# Ubuntu/Debian
sudo apt install screen

# 创建新的 screen 会话
screen -S whop_monitor

# 在 screen 中运行抓取器
python3 whop_scraper_simple.py \
  --url "https://whop.com/joined/stock-and-option/-gZyq1MzOZAWO98/app/" \
  --duration 999999999 \
  --headless \
  --min-length 15 \
  --output messages.json

# 分离会话（保持后台运行）
# 按 Ctrl+A，然后按 D

# 重新连接会话
screen -r whop_monitor

# 列出所有会话
screen -ls

# 结束会话
# 在会话中输入: exit
```

### 使用 tmux（推荐）

```bash
# 安装 tmux（如果未安装）
# macOS
brew install tmux

# Ubuntu/Debian
sudo apt install tmux

# 创建新的 tmux 会话
tmux new -s whop_monitor

# 在 tmux 中运行抓取器
python3 whop_scraper_simple.py \
  --url "https://whop.com/joined/stock-and-option/-gZyq1MzOZAWO98/app/" \
  --duration 999999999 \
  --headless \
  --min-length 15 \
  --output messages.json

# 分离会话（保持后台运行）
# 按 Ctrl+B，然后按 D

# 重新连接会话
tmux attach -t whop_monitor

# 列出所有会话
tmux ls

# 结束会话
tmux kill-session -t whop_monitor
```

**tmux 优势**：
- ✅ 更现代，功能更强大
- ✅ 可以分割窗口查看多个任务
- ✅ 更好的会话管理
- ✅ 支持鼠标操作

## ⚙️ 方法 3: 系统服务（推荐）

最专业的方法，适合生产环境长期运行。

### macOS (launchd)

```bash
# 创建服务配置文件
cat > ~/Library/LaunchAgents/com.whop.monitor.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.whop.monitor</string>
    
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/python3</string>
        <string>/Users/txink/Documents/code/playwright/whop_scraper_simple.py</string>
        <string>--url</string>
        <string>https://whop.com/joined/stock-and-option/-gZyq1MzOZAWO98/app/</string>
        <string>--duration</string>
        <string>999999999</string>
        <string>--headless</string>
        <string>--min-length</string>
        <string>15</string>
        <string>--output</string>
        <string>/Users/txink/Documents/code/playwright/messages.json</string>
    </array>
    
    <key>WorkingDirectory</key>
    <string>/Users/txink/Documents/code/playwright</string>
    
    <key>StandardOutPath</key>
    <string>/Users/txink/Documents/code/playwright/logs/scraper.log</string>
    
    <key>StandardErrorPath</key>
    <string>/Users/txink/Documents/code/playwright/logs/scraper_error.log</string>
    
    <key>RunAtLoad</key>
    <true/>
    
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
EOF

# 创建日志目录
mkdir -p /Users/txink/Documents/code/playwright/logs

# 加载服务
launchctl load ~/Library/LaunchAgents/com.whop.monitor.plist

# 启动服务
launchctl start com.whop.monitor

# 查看服务状态
launchctl list | grep whop

# 停止服务
launchctl stop com.whop.monitor

# 卸载服务
launchctl unload ~/Library/LaunchAgents/com.whop.monitor.plist
```

### Linux (systemd)

```bash
# 创建服务文件
sudo cat > /etc/systemd/system/whop-monitor.service << 'EOF'
[Unit]
Description=Whop Message Monitor
After=network.target

[Service]
Type=simple
User=txink
WorkingDirectory=/home/txink/playwright
ExecStart=/usr/bin/python3 /home/txink/playwright/whop_scraper_simple.py \
  --url "https://whop.com/joined/stock-and-option/-gZyq1MzOZAWO98/app/" \
  --duration 999999999 \
  --headless \
  --min-length 15 \
  --output /home/txink/playwright/messages.json

Restart=always
RestartSec=10

StandardOutput=append:/home/txink/playwright/logs/scraper.log
StandardError=append:/home/txink/playwright/logs/scraper_error.log

[Install]
WantedBy=multi-user.target
EOF

# 创建日志目录
mkdir -p /home/txink/playwright/logs

# 重载 systemd
sudo systemctl daemon-reload

# 启动服务
sudo systemctl start whop-monitor

# 设置开机自启
sudo systemctl enable whop-monitor

# 查看服务状态
sudo systemctl status whop-monitor

# 查看日志
sudo journalctl -u whop-monitor -f

# 停止服务
sudo systemctl stop whop-monitor

# 重启服务
sudo systemctl restart whop-monitor
```

## 🔄 方法 4: crontab 定时重启

适合需要定期重启的场景（如每天重启一次）。

### 每天自动重启

```bash
# 编辑 crontab
crontab -e

# 添加以下内容（每天凌晨 2 点重启）
# 先停止旧进程
0 2 * * * pkill -f whop_scraper_simple.py

# 5 分钟后启动新进程
5 2 * * * cd /Users/txink/Documents/code/playwright && nohup python3 whop_scraper_simple.py --url "https://whop.com/joined/stock-and-option/-gZyq1MzOZAWO98/app/" --duration 86400 --headless --min-length 15 --output messages_$(date +\%Y\%m\%d).json > logs/scraper_$(date +\%Y\%m\%d).log 2>&1 &

# 或者使用更完整的脚本
5 2 * * * /Users/txink/Documents/code/playwright/start_monitor.sh
```

### 每小时检查并重启（如果停止）

```bash
# 创建检查脚本
cat > check_and_restart.sh << 'EOF'
#!/bin/bash

SCRIPT_PATH="/Users/txink/Documents/code/playwright"
LOG_DIR="$SCRIPT_PATH/logs"
PID_FILE="$SCRIPT_PATH/scraper.pid"

cd "$SCRIPT_PATH"

# 检查进程是否运行
if [ -f "$PID_FILE" ]; then
  PID=$(cat "$PID_FILE")
  if ps -p $PID > /dev/null; then
    echo "$(date): 进程正在运行，PID: $PID"
    exit 0
  fi
fi

# 进程未运行，启动新的
echo "$(date): 进程未运行，启动新的监控..." >> "$LOG_DIR/restart.log"

nohup python3 whop_scraper_simple.py \
  --url "https://whop.com/joined/stock-and-option/-gZyq1MzOZAWO98/app/" \
  --duration 86400 \
  --headless \
  --min-length 15 \
  --output messages_$(date +%Y%m%d).json \
  >> "$LOG_DIR/scraper_$(date +%Y%m%d).log" 2>&1 &

echo $! > "$PID_FILE"
echo "$(date): 新进程已启动，PID: $(cat $PID_FILE)" >> "$LOG_DIR/restart.log"
EOF

chmod +x check_and_restart.sh

# 添加到 crontab（每小时检查一次）
crontab -e

# 添加这行
0 * * * * /Users/txink/Documents/code/playwright/check_and_restart.sh
```

## 🔁 方法 5: 无限循环模式

创建一个持续运行的脚本，自动处理错误和重启。

```bash
cat > monitor_forever.sh << 'EOF'
#!/bin/bash

SCRIPT_PATH="/Users/txink/Documents/code/playwright"
LOG_DIR="$SCRIPT_PATH/logs"
URL="https://whop.com/joined/stock-and-option/-gZyq1MzOZAWO98/app/"

cd "$SCRIPT_PATH"
mkdir -p "$LOG_DIR"

echo "========================================" >> "$LOG_DIR/forever.log"
echo "启动永久监控模式: $(date)" >> "$LOG_DIR/forever.log"
echo "========================================" >> "$LOG_DIR/forever.log"

while true; do
  TIMESTAMP=$(date +%Y%m%d_%H%M%S)
  LOG_FILE="$LOG_DIR/scraper_$TIMESTAMP.log"
  OUTPUT_FILE="messages_$(date +%Y%m%d).json"
  
  echo "$(date): 启动新的监控周期" >> "$LOG_DIR/forever.log"
  
  # 运行抓取器（24 小时）
  python3 whop_scraper_simple.py \
    --url "$URL" \
    --duration 86400 \
    --headless \
    --min-length 15 \
    --output "$OUTPUT_FILE" \
    >> "$LOG_FILE" 2>&1
  
  EXIT_CODE=$?
  
  if [ $EXIT_CODE -ne 0 ]; then
    echo "$(date): 进程异常退出，代码: $EXIT_CODE" >> "$LOG_DIR/forever.log"
  else
    echo "$(date): 进程正常结束" >> "$LOG_DIR/forever.log"
  fi
  
  # 等待 10 秒后重启
  echo "$(date): 10 秒后重启..." >> "$LOG_DIR/forever.log"
  sleep 10
done
EOF

chmod +x monitor_forever.sh

# 启动（在 screen/tmux 中）
screen -S whop_forever
./monitor_forever.sh

# 或者使用 nohup
nohup ./monitor_forever.sh > logs/forever_main.log 2>&1 &
```

## 📊 监控和管理

### 查看运行状态

```bash
# 方法 1: 查看进程
ps aux | grep whop_scraper_simple.py

# 方法 2: 查看日志
tail -f logs/scraper.log

# 方法 3: 查看最新消息
tail -20 logs/scraper.log | grep "消息 #"

# 方法 4: 统计抓取数量
grep "唯一消息" logs/scraper.log | tail -1
```

### 监控脚本

```bash
cat > monitor_status.sh << 'EOF'
#!/bin/bash

echo "======================================"
echo "Whop 监控器状态"
echo "======================================"
echo ""

# 检查进程
if pgrep -f whop_scraper_simple.py > /dev/null; then
  echo "✅ 进程状态: 运行中"
  PID=$(pgrep -f whop_scraper_simple.py)
  echo "   PID: $PID"
  
  # CPU 和内存使用
  ps -p $PID -o %cpu,%mem,etime
else
  echo "❌ 进程状态: 未运行"
fi

echo ""
echo "最新日志（最后 10 行）:"
echo "--------------------------------------"
tail -10 logs/scraper.log 2>/dev/null || echo "无日志文件"

echo ""
echo "今日抓取统计:"
echo "--------------------------------------"
TODAY=$(date +%Y%m%d)
LOG_FILE="logs/scraper_$TODAY.log"
if [ -f "$LOG_FILE" ]; then
  UNIQUE=$(grep "唯一消息" "$LOG_FILE" | tail -1 | grep -o "[0-9]*" | head -1)
  echo "唯一消息: ${UNIQUE:-0} 条"
else
  echo "今日无日志"
fi

echo ""
echo "======================================"
EOF

chmod +x monitor_status.sh

# 使用
./monitor_status.sh
```

### 自动报告脚本

```bash
cat > daily_report.sh << 'EOF'
#!/bin/bash

REPORT_FILE="reports/daily_report_$(date +%Y%m%d).txt"
mkdir -p reports

{
  echo "=========================================="
  echo "Whop 监控日报 - $(date +%Y年%m月%d日)"
  echo "=========================================="
  echo ""
  
  # 统计信息
  LOG_FILE="logs/scraper_$(date +%Y%m%d).log"
  if [ -f "$LOG_FILE" ]; then
    echo "📊 今日统计:"
    grep "统计信息" "$LOG_FILE" -A 6 | tail -1
    echo ""
    
    echo "📝 抓取样本（最近 5 条）:"
    grep "消息 #" "$LOG_FILE" | tail -5
    echo ""
  fi
  
  # 系统资源
  echo "💻 系统资源:"
  if pgrep -f whop_scraper_simple.py > /dev/null; then
    PID=$(pgrep -f whop_scraper_simple.py)
    ps -p $PID -o %cpu,%mem,etime
  fi
  
  echo ""
  echo "=========================================="
} > "$REPORT_FILE"

# 发送报告（可选：通过邮件或其他方式）
cat "$REPORT_FILE"
EOF

chmod +x daily_report.sh

# 添加到 crontab（每天晚上 11 点生成报告）
# 0 23 * * * /Users/txink/Documents/code/playwright/daily_report.sh
```

## 🛡️ 最佳实践

### 1. 日志管理

```bash
# 创建日志轮转脚本
cat > rotate_logs.sh << 'EOF'
#!/bin/bash

LOG_DIR="logs"
ARCHIVE_DIR="logs/archive"
DAYS_TO_KEEP=7

mkdir -p "$ARCHIVE_DIR"

# 归档旧日志
find "$LOG_DIR" -name "*.log" -mtime +$DAYS_TO_KEEP -exec mv {} "$ARCHIVE_DIR/" \;

# 压缩归档日志
find "$ARCHIVE_DIR" -name "*.log" ! -name "*.gz" -exec gzip {} \;

# 删除超过 30 天的归档
find "$ARCHIVE_DIR" -name "*.gz" -mtime +30 -delete

echo "$(date): 日志轮转完成" >> "$LOG_DIR/rotation.log"
EOF

chmod +x rotate_logs.sh

# 每天凌晨 1 点执行
# 0 1 * * * /Users/txink/Documents/code/playwright/rotate_logs.sh
```

### 2. 错误告警

```bash
# 创建告警脚本
cat > check_errors.sh << 'EOF'
#!/bin/bash

LOG_FILE="logs/scraper_$(date +%Y%m%d).log"
ERROR_COUNT=$(grep -i "error\|failed\|exception" "$LOG_FILE" 2>/dev/null | wc -l)

if [ $ERROR_COUNT -gt 10 ]; then
  echo "$(date): 警告 - 检测到 $ERROR_COUNT 个错误" >> logs/alerts.log
  
  # 发送通知（示例：使用 macOS 通知）
  osascript -e "display notification \"检测到 $ERROR_COUNT 个错误\" with title \"Whop 监控警告\""
  
  # 或者发送邮件、Slack 消息等
fi
EOF

chmod +x check_errors.sh

# 每小时检查一次
# 0 * * * * /Users/txink/Documents/code/playwright/check_errors.sh
```

### 3. Cookie 定期更新

```bash
# 每周自动更新 Cookie
# 0 3 * * 0 cd /Users/txink/Documents/code/playwright && python3 whop_login.py --test || python3 whop_login.py
```

## 📝 推荐配置

### 场景 1: 个人使用（简单）

```bash
# 使用 screen/tmux
screen -S whop_monitor
python3 whop_scraper_simple.py \
  --url "URL" \
  --duration 999999999 \
  --headless \
  --min-length 15 \
  --output messages.json

# Ctrl+A, D 分离
```

### 场景 2: 开发测试

```bash
# 使用 nohup + 自动重启
nohup ./monitor_forever.sh > logs/forever.log 2>&1 &
```

### 场景 3: 生产环境（推荐）

```bash
# 使用系统服务（macOS launchd 或 Linux systemd）
# 见上文"方法 3"
```

## 🆘 故障排查

### 问题 1: 进程意外停止

```bash
# 查看日志
tail -100 logs/scraper.log | grep -i "error\|exception"

# 使用自动重启脚本
./monitor_forever.sh
```

### 问题 2: Cookie 过期

```bash
# 测试并更新
python3 whop_login.py --test || python3 whop_login.py
```

### 问题 3: 内存占用过高

```bash
# 定期重启（使用 crontab）
# 每天凌晨 2 点重启
```

## 📚 相关文档

- [快速参考](./QUICK_REFERENCE.md)
- [去重指南](./DEDUPLICATION_GUIDE.md)
- [自动滚动指南](./AUTO_SCROLL_GUIDE.md)
- [故障排查](./TROUBLESHOOTING.md)

## 🎯 快速开始

**最简单的方法**（立即开始）：

```bash
# 在 screen 中运行
screen -S whop
python3 whop_scraper_simple.py \
  --url "https://whop.com/joined/stock-and-option/-gZyq1MzOZAWO98/app/" \
  --duration 999999999 \
  --headless \
  --min-length 15 \
  --output messages.json

# 按 Ctrl+A, 然后按 D 分离
# 关闭终端也会继续运行
```

有任何问题，请查阅其他文档或提交 Issue！
