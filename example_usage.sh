#!/bin/bash
# Whop 抓取器使用示例
# 这是一个示例脚本，展示如何使用 Whop 登录和抓取工具

set -e  # 遇到错误时退出

echo "=================================================="
echo "Whop 抓取器 - 快速开始示例"
echo "=================================================="
echo ""

# 检查是否安装了依赖
echo "步骤 1/4: 检查依赖..."
if ! command -v python3 &> /dev/null; then
    echo "❌ 错误: 未找到 python3"
    echo "请先安装 Python 3.8 或更高版本"
    exit 1
fi

echo "✅ Python 已安装: $(python3 --version)"
echo ""

# 检查是否安装了 Playwright
echo "步骤 2/4: 检查 Playwright..."
if python3 -c "import playwright" 2>/dev/null; then
    echo "✅ Playwright 已安装"
else
    echo "⚠️  Playwright 未安装"
    echo "正在安装依赖..."
    pip3 install -r requirements.txt
    python3 -m playwright install chromium
    echo "✅ 依赖安装完成"
fi
echo ""

# 检查 Cookie 文件
echo "步骤 3/4: 检查登录状态..."
if [ -f "storage_state.json" ]; then
    echo "✅ 找到已保存的登录状态 (storage_state.json)"
    echo ""
    echo "选项:"
    echo "  1) 使用现有 Cookie 继续"
    echo "  2) 重新登录（覆盖现有 Cookie）"
    echo "  3) 测试现有 Cookie 是否有效"
    echo ""
    read -p "请选择 [1/2/3]: " choice
    
    case $choice in
        1)
            echo "使用现有 Cookie"
            ;;
        2)
            echo "重新登录..."
            python3 whop_login.py
            ;;
        3)
            echo "测试 Cookie..."
            python3 whop_login.py --test
            exit 0
            ;;
        *)
            echo "使用现有 Cookie"
            ;;
    esac
else
    echo "⚠️  未找到登录状态文件"
    echo "现在将打开浏览器进行登录..."
    echo ""
    python3 whop_login.py
fi
echo ""

# 开始抓取
echo "步骤 4/4: 开始抓取消息..."
echo ""
read -p "请输入要抓取的 Whop 页面 URL: " target_url

if [ -z "$target_url" ]; then
    echo "❌ URL 不能为空"
    exit 1
fi

read -p "监控时长（秒，默认 30）: " duration
duration=${duration:-30}

read -p "是否使用无头模式？[y/N]: " headless_choice

if [[ "$headless_choice" =~ ^[Yy]$ ]]; then
    headless_flag="--headless"
else
    headless_flag=""
fi

echo ""
echo "=================================================="
echo "开始抓取..."
echo "  URL: $target_url"
echo "  时长: $duration 秒"
echo "  模式: $([ -z "$headless_flag" ] && echo "有头模式（可见浏览器）" || echo "无头模式（后台运行）")"
echo "=================================================="
echo ""

python3 whop_scraper_simple.py \
    --url "$target_url" \
    --duration "$duration" \
    $headless_flag

echo ""
echo "=================================================="
echo "✅ 完成！"
echo "=================================================="
echo ""
echo "提示:"
echo "  - 要重新登录: python3 whop_login.py"
echo "  - 要测试登录: python3 whop_login.py --test"
echo "  - 查看详细文档: cat WHOP_LOGIN_GUIDE.md"
echo ""
