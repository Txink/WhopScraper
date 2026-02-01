#!/bin/bash

# Whop 后台监控启动脚本
# 使用方法: ./start_background_monitor.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 配置
DEFAULT_URL="https://whop.com/joined/stock-and-option/-gZyq1MzOZAWO98/app/"
LOG_DIR="$SCRIPT_DIR/logs"
PID_FILE="$SCRIPT_DIR/scraper.pid"
OUTPUT_FILE="messages_$(date +%Y%m%d).json"

# 创建日志目录
mkdir -p "$LOG_DIR"

echo "=========================================="
echo "Whop 后台监控启动器"
echo "=========================================="
echo ""

# 检查是否已经运行
if [ -f "$PID_FILE" ]; then
  OLD_PID=$(cat "$PID_FILE")
  if ps -p "$OLD_PID" > /dev/null 2>&1; then
    echo "⚠️  监控器已在运行中"
    echo "   PID: $OLD_PID"
    echo ""
    read -p "是否停止旧进程并重新启动？[y/N]: " RESTART
    if [[ "$RESTART" =~ ^[Yy]$ ]]; then
      echo "停止旧进程..."
      kill "$OLD_PID" 2>/dev/null || true
      sleep 2
    else
      echo "保持旧进程运行，退出"
      exit 0
    fi
  fi
fi

# 获取 URL（如果没有提供则使用默认值）
if [ -n "$1" ]; then
  URL="$1"
else
  echo "URL (按回车使用默认值):"
  echo "  $DEFAULT_URL"
  read -p "> " INPUT_URL
  URL="${INPUT_URL:-$DEFAULT_URL}"
fi

# 获取运行时长
echo ""
echo "运行时长（秒）:"
echo "  1) 24 小时 (86400)"
echo "  2) 7 天 (604800)"
echo "  3) 永久运行 (999999999)"
echo "  4) 自定义"
read -p "选择 [1-4, 默认 3]: " DURATION_CHOICE

case $DURATION_CHOICE in
  1) DURATION=86400 ;;
  2) DURATION=604800 ;;
  3) DURATION=999999999 ;;
  4) 
    read -p "输入秒数: " DURATION
    DURATION="${DURATION:-999999999}"
    ;;
  *) DURATION=999999999 ;;
esac

# 获取最小消息长度
echo ""
read -p "最小消息长度（字符，默认 15）: " MIN_LENGTH
MIN_LENGTH="${MIN_LENGTH:-15}"

# 是否启用自动滚动
echo ""
read -p "启用自动滚动？[y/N]: " AUTO_SCROLL
if [[ "$AUTO_SCROLL" =~ ^[Yy]$ ]]; then
  AUTO_SCROLL_FLAG="--auto-scroll"
  read -p "滚动间隔（秒，默认 5）: " SCROLL_INTERVAL
  SCROLL_INTERVAL="${SCROLL_INTERVAL:-5}"
  AUTO_SCROLL_FLAG="$AUTO_SCROLL_FLAG --scroll-interval $SCROLL_INTERVAL"
else
  AUTO_SCROLL_FLAG=""
fi

# 选择运行模式
echo ""
echo "=========================================="
echo "选择运行模式:"
echo "=========================================="
echo "  1) screen 会话（推荐，可随时查看）"
echo "  2) nohup 后台（简单，适合临时使用）"
echo "  3) 无限循环（自动重启，最稳定）"
echo ""
read -p "选择 [1-3, 默认 1]: " MODE_CHOICE

LOG_FILE="$LOG_DIR/scraper_$(date +%Y%m%d_%H%M%S).log"

case $MODE_CHOICE in
  1)
    # Screen 模式
    echo ""
    echo "=========================================="
    echo "启动 screen 会话..."
    echo "=========================================="
    echo "命令:"
    echo "  screen -S whop_monitor"
    echo ""
    echo "在 screen 中运行:"
    CMD="python3 whop_scraper_simple.py --url \"$URL\" --duration $DURATION --headless --min-length $MIN_LENGTH $AUTO_SCROLL_FLAG --output \"$OUTPUT_FILE\""
    echo "  $CMD"
    echo ""
    echo "操作提示:"
    echo "  - 分离会话: Ctrl+A, 然后按 D"
    echo "  - 重新连接: screen -r whop_monitor"
    echo "  - 停止监控: 在会话中按 Ctrl+C"
    echo ""
    read -p "按回车启动 screen 会话..." 
    
    # 创建临时脚本
    TEMP_SCRIPT=$(mktemp)
    echo "$CMD" > "$TEMP_SCRIPT"
    chmod +x "$TEMP_SCRIPT"
    
    screen -S whop_monitor bash -c "$CMD"
    
    rm -f "$TEMP_SCRIPT"
    ;;
    
  2)
    # Nohup 模式
    echo ""
    echo "=========================================="
    echo "启动 nohup 后台进程..."
    echo "=========================================="
    
    nohup python3 whop_scraper_simple.py \
      --url "$URL" \
      --duration "$DURATION" \
      --headless \
      --min-length "$MIN_LENGTH" \
      $AUTO_SCROLL_FLAG \
      --output "$OUTPUT_FILE" \
      > "$LOG_FILE" 2>&1 &
    
    PID=$!
    echo $PID > "$PID_FILE"
    
    echo "✅ 后台进程已启动"
    echo "   PID: $PID"
    echo "   日志: $LOG_FILE"
    echo ""
    echo "管理命令:"
    echo "  查看日志: tail -f $LOG_FILE"
    echo "  停止进程: kill $PID"
    echo "  查看进程: ps -p $PID"
    echo ""
    ;;
    
  3)
    # 无限循环模式
    echo ""
    echo "=========================================="
    echo "启动无限循环模式..."
    echo "=========================================="
    
    FOREVER_SCRIPT=$(mktemp)
    cat > "$FOREVER_SCRIPT" << EOF
#!/bin/bash
cd "$SCRIPT_DIR"
while true; do
  echo "\$(date): 启动新的监控周期" >> "$LOG_DIR/forever.log"
  python3 whop_scraper_simple.py \
    --url "$URL" \
    --duration $DURATION \
    --headless \
    --min-length $MIN_LENGTH \
    $AUTO_SCROLL_FLAG \
    --output "$OUTPUT_FILE" \
    >> "$LOG_FILE" 2>&1
  echo "\$(date): 监控周期结束，10 秒后重启..." >> "$LOG_DIR/forever.log"
  sleep 10
done
EOF
    chmod +x "$FOREVER_SCRIPT"
    
    nohup bash "$FOREVER_SCRIPT" > "$LOG_DIR/forever_main.log" 2>&1 &
    
    PID=$!
    echo $PID > "$PID_FILE"
    
    echo "✅ 无限循环模式已启动"
    echo "   PID: $PID"
    echo "   主日志: $LOG_DIR/forever_main.log"
    echo "   循环日志: $LOG_DIR/forever.log"
    echo "   监控日志: $LOG_FILE"
    echo ""
    echo "管理命令:"
    echo "  查看主日志: tail -f $LOG_DIR/forever_main.log"
    echo "  查看监控日志: tail -f $LOG_FILE"
    echo "  停止所有: kill $PID"
    echo ""
    
    rm -f "$FOREVER_SCRIPT"
    ;;
    
  *)
    echo "无效选择，退出"
    exit 1
    ;;
esac

echo "=========================================="
echo "✅ 启动完成！"
echo "=========================================="
