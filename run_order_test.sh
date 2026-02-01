#!/bin/bash
# 订单管理功能测试快捷脚本

cd "$(dirname "$0")"
echo "📍 当前目录: $(pwd)"
echo ""

echo "🧪 运行订单管理功能测试..."
echo "============================================================"
PYTHONPATH=. python3 test/broker/test_order_management.py

echo ""
echo "✅ 测试完成！"
