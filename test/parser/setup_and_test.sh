#!/bin/bash

# LLM 解析器测试 - 一键安装和测试脚本

set -e  # 遇到错误立即退出

echo "╔════════════════════════════════════════════════════════════╗"
echo "║     LLM 交易指令解析器测试 - 自动安装脚本                  ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# 项目根目录
PROJECT_ROOT="/Users/txink/Documents/code/playwright"
cd "$PROJECT_ROOT"

# 1. 检查 Homebrew
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第 1 步: 检查 Homebrew"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if ! command -v brew &> /dev/null; then
    echo -e "${RED}❌ Homebrew 未安装${NC}"
    echo "请先安装 Homebrew: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    exit 1
else
    echo -e "${GREEN}✅ Homebrew 已安装${NC}"
fi
echo ""

# 2. 检查并安装 Ollama
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第 2 步: 安装 Ollama"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if ! command -v ollama &> /dev/null; then
    echo -e "${YELLOW}📦 正在安装 Ollama...${NC}"
    brew install ollama
    echo -e "${GREEN}✅ Ollama 安装完成${NC}"
else
    echo -e "${GREEN}✅ Ollama 已安装${NC}"
    ollama --version
fi
echo ""

# 3. 启动 Ollama 服务
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第 3 步: 启动 Ollama 服务"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 检查是否已经运行
if pgrep -x "ollama" > /dev/null; then
    echo -e "${GREEN}✅ Ollama 服务已在运行${NC}"
else
    echo -e "${YELLOW}🔥 启动 Ollama 服务（后台运行）...${NC}"
    
    # 创建日志目录
    mkdir -p /tmp/ollama_logs
    
    # 后台启动
    nohup ollama serve > /tmp/ollama_logs/ollama.log 2>&1 &
    
    # 等待服务启动
    echo "⏳ 等待服务启动..."
    sleep 3
    
    # 验证服务
    if pgrep -x "ollama" > /dev/null; then
        echo -e "${GREEN}✅ Ollama 服务启动成功${NC}"
        echo "   日志位置: /tmp/ollama_logs/ollama.log"
    else
        echo -e "${RED}❌ Ollama 服务启动失败${NC}"
        echo "请手动运行: ollama serve"
        exit 1
    fi
fi
echo ""

# 4. 下载模型
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第 4 步: 下载测试模型"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

MODEL="qwen2.5:1.5b"

# 检查模型是否已存在
if ollama list | grep -q "$MODEL"; then
    echo -e "${GREEN}✅ 模型 $MODEL 已存在${NC}"
else
    echo -e "${YELLOW}📥 正在下载模型 $MODEL (约 900MB)...${NC}"
    echo "   这可能需要几分钟，请耐心等待..."
    
    ollama pull "$MODEL"
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✅ 模型下载完成${NC}"
    else
        echo -e "${RED}❌ 模型下载失败${NC}"
        exit 1
    fi
fi

# 显示已安装的模型
echo ""
echo "已安装的模型:"
ollama list
echo ""

# 5. 安装 Python 依赖
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第 5 步: 安装 Python 依赖"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python3 未安装${NC}"
    exit 1
fi

echo "Python 版本: $(python3 --version)"

# 检查 pip3
if ! command -v pip3 &> /dev/null; then
    echo -e "${RED}❌ pip3 未安装${NC}"
    exit 1
fi

# 安装 ollama Python 包
echo -e "${YELLOW}📦 安装 ollama Python 包...${NC}"
pip3 install ollama --quiet

if pip3 show ollama &> /dev/null; then
    echo -e "${GREEN}✅ ollama Python 包已安装${NC}"
    pip3 show ollama | grep Version
else
    echo -e "${RED}❌ ollama Python 包安装失败${NC}"
    exit 1
fi
echo ""

# 6. 运行测试
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第 6 步: 运行测试"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo -e "${YELLOW}🧪 开始测试 Qwen2.5 1.5B 解析能力...${NC}"
echo ""

# 运行测试脚本
python3 test/parser/test_llm_parser.py

# 7. 完成
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}✅ 测试完成！${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "下一步:"
echo "  1. 查看上方测试结果和建议"
echo "  2. 如需测试其他模型，运行:"
echo "     ollama pull qwen2.5:3b"
echo "     ollama pull qwen2.5:7b"
echo "  3. 停止 Ollama 服务:"
echo "     pkill ollama"
echo ""
