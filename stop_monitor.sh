#!/bin/bash

# 停止 Whop 监控器

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PID_FILE="$SCRIPT_DIR/scraper.pid"

echo "=========================================="
echo "停止 Whop 监控器"
echo "=========================================="
echo ""

# 方法 1: 使用 PID 文件
if [ -f "$PID_FILE" ]; then
  PID=$(cat "$PID_FILE")
  if ps -p "$PID" > /dev/null 2>&1; then
    echo "找到进程 PID: $PID"
    read -p "确认停止？[y/N]: " CONFIRM
    if [[ "$CONFIRM" =~ ^[Yy]$ ]]; then
      kill "$PID"
      echo "✅ 已发送停止信号"
      sleep 2
      
      # 检查是否还在运行
      if ps -p "$PID" > /dev/null 2>&1; then
        echo "⚠️  进程仍在运行，尝试强制停止..."
        kill -9 "$PID"
        sleep 1
        if ps -p "$PID" > /dev/null 2>&1; then
          echo "❌ 无法停止进程"
        else
          echo "✅ 进程已强制停止"
          rm -f "$PID_FILE"
        fi
      else
        echo "✅ 进程已停止"
        rm -f "$PID_FILE"
      fi
    else
      echo "取消操作"
    fi
  else
    echo "⚠️  PID 文件存在但进程未运行"
    rm -f "$PID_FILE"
  fi
else
  echo "⚠️  未找到 PID 文件"
  echo ""
fi

# 方法 2: 查找所有相关进程
echo ""
echo "查找所有 whop_scraper_simple.py 进程..."
PIDS=$(pgrep -f whop_scraper_simple.py)

if [ -n "$PIDS" ]; then
  echo "找到以下进程:"
  ps -p $PIDS -o pid,etime,command
  echo ""
  read -p "是否停止所有进程？[y/N]: " CONFIRM_ALL
  if [[ "$CONFIRM_ALL" =~ ^[Yy]$ ]]; then
    pkill -f whop_scraper_simple.py
    sleep 2
    
    # 验证
    REMAINING=$(pgrep -f whop_scraper_simple.py)
    if [ -n "$REMAINING" ]; then
      echo "⚠️  仍有进程运行，尝试强制停止..."
      pkill -9 -f whop_scraper_simple.py
      echo "✅ 已强制停止所有进程"
    else
      echo "✅ 所有进程已停止"
    fi
  fi
else
  echo "未找到运行中的进程"
fi

# 方法 3: Screen 会话
echo ""
echo "查找 screen 会话..."
if screen -ls | grep -q whop; then
  echo "找到 screen 会话:"
  screen -ls | grep whop
  echo ""
  echo "停止 screen 会话:"
  echo "  方法 1: screen -r whop_monitor  (重新连接后按 Ctrl+C)"
  echo "  方法 2: screen -X -S whop_monitor quit  (直接结束会话)"
  echo ""
  read -p "是否直接结束 screen 会话？[y/N]: " KILL_SCREEN
  if [[ "$KILL_SCREEN" =~ ^[Yy]$ ]]; then
    screen -X -S whop_monitor quit 2>/dev/null && echo "✅ Screen 会话已结束" || echo "❌ 未能结束 screen 会话"
  fi
else
  echo "未找到 screen 会话"
fi

echo ""
echo "=========================================="
echo "操作完成"
echo "=========================================="
