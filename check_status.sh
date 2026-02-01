#!/bin/bash

# 查看 Whop 监控器状态

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PID_FILE="$SCRIPT_DIR/scraper.pid"
LOG_DIR="$SCRIPT_DIR/logs"

echo "=========================================="
echo "Whop 监控器状态"
echo "$(date)"
echo "=========================================="
echo ""

# 1. 检查进程状态
echo "📊 进程状态:"
echo "--------------------------------------"

if [ -f "$PID_FILE" ]; then
  PID=$(cat "$PID_FILE")
  if ps -p "$PID" > /dev/null 2>&1; then
    echo "✅ 状态: 运行中"
    echo "   PID: $PID"
    echo ""
    echo "   资源使用:"
    ps -p "$PID" -o %cpu,%mem,etime,command | tail -1
  else
    echo "❌ 状态: 未运行（PID 文件存在但进程不存在）"
    echo "   PID 文件: $PID_FILE"
  fi
else
  echo "⚠️  状态: 未找到 PID 文件"
fi

# 检查所有相关进程
ALL_PIDS=$(pgrep -f whop_scraper_simple.py 2>/dev/null)
if [ -n "$ALL_PIDS" ]; then
  echo ""
  echo "   所有相关进程:"
  ps -p $ALL_PIDS -o pid,%cpu,%mem,etime,command 2>/dev/null
fi

echo ""

# 2. Screen 会话
echo "🖥️  Screen 会话:"
echo "--------------------------------------"
if command -v screen &> /dev/null; then
  if screen -ls 2>/dev/null | grep -q whop; then
    screen -ls | grep whop
  else
    echo "未找到 screen 会话"
  fi
else
  echo "screen 未安装"
fi

echo ""

# 3. 最新日志
echo "📝 最新日志 (最后 10 行):"
echo "--------------------------------------"
LATEST_LOG=$(find "$LOG_DIR" -name "scraper_*.log" -type f 2>/dev/null | sort -r | head -1)
if [ -n "$LATEST_LOG" ]; then
  echo "日志文件: $LATEST_LOG"
  echo ""
  tail -10 "$LATEST_LOG" 2>/dev/null || echo "无法读取日志"
else
  echo "未找到日志文件"
fi

echo ""

# 4. 今日统计
echo "📈 今日统计:"
echo "--------------------------------------"
TODAY=$(date +%Y%m%d)
TODAY_LOGS=$(find "$LOG_DIR" -name "scraper_${TODAY}*.log" -type f 2>/dev/null)

if [ -n "$TODAY_LOGS" ]; then
  # 唯一消息数
  UNIQUE_MESSAGES=$(grep "唯一消息" $TODAY_LOGS 2>/dev/null | tail -1 | grep -o "[0-9]*" | head -1)
  echo "唯一消息: ${UNIQUE_MESSAGES:-0} 条"
  
  # 去重过滤数
  DUPLICATES=$(grep "去重过滤" $TODAY_LOGS 2>/dev/null | tail -1 | grep -o "[0-9]*" | head -1)
  if [ -n "$DUPLICATES" ] && [ "$DUPLICATES" -gt 0 ]; then
    echo "去重过滤: $DUPLICATES 条"
  fi
  
  # 最后一条消息时间
  LAST_MESSAGE=$(grep "\[.*\] 消息 #" $TODAY_LOGS 2>/dev/null | tail -1)
  if [ -n "$LAST_MESSAGE" ]; then
    echo "最后消息: $LAST_MESSAGE"
  fi
else
  echo "今日无数据"
fi

echo ""

# 5. 磁盘使用
echo "💾 磁盘使用:"
echo "--------------------------------------"
if [ -d "$LOG_DIR" ]; then
  echo "日志目录: $(du -sh "$LOG_DIR" 2>/dev/null | cut -f1)"
  echo "日志文件数: $(find "$LOG_DIR" -name "*.log" -type f 2>/dev/null | wc -l | tr -d ' ')"
fi

if [ -f "messages.json" ]; then
  echo "消息文件: $(du -sh messages.json 2>/dev/null | cut -f1)"
fi

echo ""

# 6. Cookie 状态
echo "🔐 Cookie 状态:"
echo "--------------------------------------"
if [ -f "storage_state.json" ]; then
  FILE_AGE=$((($(date +%s) - $(stat -f %m storage_state.json 2>/dev/null || stat -c %Y storage_state.json 2>/dev/null)) / 86400))
  echo "Cookie 文件年龄: $FILE_AGE 天"
  
  if [ $FILE_AGE -gt 7 ]; then
    echo "⚠️  警告: Cookie 可能过期，建议重新登录"
    echo "   运行: python3 whop_login.py"
  else
    echo "✅ Cookie 状态良好"
  fi
else
  echo "❌ 未找到 Cookie 文件"
  echo "   运行: python3 whop_login.py"
fi

echo ""
echo "=========================================="
echo "快速命令:"
echo "=========================================="
echo "  查看实时日志: tail -f $(find $LOG_DIR -name 'scraper_*.log' -type f 2>/dev/null | sort -r | head -1)"
echo "  停止监控: ./stop_monitor.sh"
echo "  重启监控: ./start_background_monitor.sh"
echo "  测试 Cookie: python3 whop_login.py --test"
echo "=========================================="
