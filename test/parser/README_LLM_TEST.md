# LLM 解析器测试指南

## 第一步：安装 Ollama

### macOS 安装方法

```bash
# 使用 Homebrew 安装
brew install ollama

# 或者直接下载安装包
# 访问 https://ollama.ai 下载
```

### 启动 Ollama 服务

```bash
# 方式1: 直接启动（前台运行）
ollama serve

# 方式2: 后台运行（推荐）
nohup ollama serve > /dev/null 2>&1 &
```

### 下载测试模型

```bash
# Qwen2.5 1.5B (最快，约900MB)
ollama pull qwen2.5:1.5b

# 可选：其他模型
ollama pull qwen2.5:3b    # 更准确，约2GB
ollama pull qwen2.5:7b    # 最准确，约4.7GB
```

## 第二步：安装 Python 依赖

```bash
# 进入项目目录
cd /Users/txink/Documents/code/playwright

# 安装 ollama Python 客户端
pip3 install ollama

# 或使用 poetry（如果项目使用 poetry）
poetry add ollama
```

## 第三步：运行测试

```bash
# 确保 Ollama 服务已启动
ollama list  # 检查模型列表

# 运行测试脚本
python3 test/parser/test_llm_parser.py
```

## 测试场景说明

测试脚本包含 8 个测试用例，覆盖：

1. **简单指令**: `tsla 0.17 卖出 1/3`
2. **复杂指令**: `2.53出三分之一 hon 止损剩下提高到2.3`
3. **上下文依赖**: `0.17 卖出 1/3` (需要从历史消息获取ticker)
4. **止损指令**: `止损提高到1.5`
5. **清仓指令**: `2.3都出 msft`
6. **买入指令**: `BA 240c 2/13 1.25 小仓位`
7. **中文表达**: `一点七五出三分之一`
8. **反向止损**: `2.5止损`

## 预期结果

### 性能指标

- **响应时间**: 目标 < 1秒
- **准确率**: 目标 > 80%
- **成功率**: 目标 > 90%

### M1 Pro 预期性能

| 模型 | 平均响应时间 | 预期准确率 |
|------|-------------|-----------|
| qwen2.5:1.5b | 0.6-1.0秒 | 70-85% |
| qwen2.5:3b | 1.0-1.5秒 | 80-90% |
| qwen2.5:7b | 2.0-3.0秒 | 90-95% |

## 快速安装脚本

如果想一键安装，可以运行：

```bash
# 创建安装脚本
cat > /tmp/setup_llm_test.sh << 'EOF'
#!/bin/bash

echo "🚀 开始安装 LLM 测试环境..."

# 1. 检查并安装 Ollama
if ! command -v ollama &> /dev/null; then
    echo "📦 安装 Ollama..."
    brew install ollama
else
    echo "✅ Ollama 已安装"
fi

# 2. 启动 Ollama 服务（后台）
echo "🔥 启动 Ollama 服务..."
pkill ollama 2>/dev/null
nohup ollama serve > /tmp/ollama.log 2>&1 &
sleep 2

# 3. 下载模型
echo "📥 下载 Qwen2.5 1.5B 模型..."
ollama pull qwen2.5:1.5b

# 4. 安装 Python 依赖
echo "📦 安装 Python 依赖..."
pip3 install ollama

echo ""
echo "✅ 安装完成！"
echo ""
echo "运行测试："
echo "  python3 test/parser/test_llm_parser.py"
echo ""
EOF

chmod +x /tmp/setup_llm_test.sh
/tmp/setup_llm_test.sh
```

## 故障排查

### 问题1: "ollama: command not found"

```bash
# 检查是否安装
brew list | grep ollama

# 重新安装
brew install ollama
```

### 问题2: "Error: Failed to connect to Ollama"

```bash
# 检查服务是否运行
ps aux | grep ollama

# 重启服务
ollama serve
```

### 问题3: "Model not found"

```bash
# 查看已安装模型
ollama list

# 重新下载
ollama pull qwen2.5:1.5b
```

### 问题4: 响应太慢

```bash
# 使用更小的模型
ollama pull qwen2.5:1.5b

# 或者升级到 MLX 版本（Mac专用，更快）
pip3 install mlx-lm
```

## 下一步

测试完成后，查看测试报告中的建议：

- 如果**准确率高但速度慢**: 考虑混合方案（正则 + LLM兜底）
- 如果**速度快但准确率低**: 优化提示词或使用更大模型
- 如果**两者都不理想**: 继续使用现有正则解析器
- 如果**两者都优秀**: 可以考虑切换到纯 LLM 方案
