# 手动安装指南（macOS）

由于 Homebrew 安装可能遇到问题，请按以下步骤手动安装：

## 方法 1: 直接下载安装（推荐）

### 1. 下载 Ollama

访问官网下载 macOS 版本：
```
https://ollama.ai/download/mac
```

或者使用命令行下载：
```bash
# 下载 Ollama.app
curl -L https://ollama.ai/download/Ollama-darwin.zip -o /tmp/Ollama.zip

# 解压到应用程序文件夹
unzip /tmp/Ollama.zip -d /Applications/

# 添加到 PATH
sudo ln -s /Applications/Ollama.app/Contents/Resources/ollama /usr/local/bin/ollama
```

### 2. 启动 Ollama

```bash
# 打开 Ollama 应用
open /Applications/Ollama.app

# 或者命令行启动
ollama serve &
```

### 3. 下载模型

```bash
# 下载 Qwen2.5 1.5B (最快，约900MB)
ollama pull qwen2.5:1.5b

# 验证安装
ollama list
```

### 4. 安装 Python 依赖

```bash
cd /Users/txink/Documents/code/playwright

# 安装 ollama Python 包
python3 -m pip install ollama
```

### 5. 运行测试

```bash
python3 test/parser/test_llm_parser.py
```

---

## 方法 2: 使用 Docker（如果有 Docker）

```bash
# 启动 Ollama 容器
docker run -d -v ollama:/root/.ollama -p 11434:11434 --name ollama ollama/ollama

# 下载模型
docker exec -it ollama ollama pull qwen2.5:1.5b

# 安装 Python 依赖
python3 -m pip install ollama

# 运行测试
python3 test/parser/test_llm_parser.py
```

---

## 方法 3: 修复 Homebrew 安装

如果仍想使用 Homebrew，尝试：

```bash
# 更新 Homebrew
brew update

# 清理缓存
brew cleanup

# 尝试安装
brew install --cask ollama

# 如果还是失败，卸载后重装
brew uninstall ollama
brew install --cask ollama
```

---

## 快速测试（无需安装）

如果只是想快速测试 LLM 的解析能力，可以使用在线 API：

### 使用 OpenAI API

```python
# 安装依赖
pip3 install openai

# 修改测试脚本使用 OpenAI
# 编辑 test/parser/test_llm_parser.py
# 将 ollama.chat 替换为 openai.chat.completions.create
```

### 使用阿里云通义千问 API

```python
# 安装依赖
pip3 install dashscope

# 使用通义千问 API
# 参考: https://help.aliyun.com/zh/dashscope/
```

---

## 故障排查

### 问题 1: "ollama: command not found"

检查 PATH：
```bash
which ollama

# 如果找不到，手动添加
export PATH="/Applications/Ollama.app/Contents/Resources:$PATH"

# 或添加到 ~/.zshrc
echo 'export PATH="/Applications/Ollama.app/Contents/Resources:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### 问题 2: "Connection refused"

确保 Ollama 服务在运行：
```bash
# 检查进程
ps aux | grep ollama

# 重启服务
pkill ollama
ollama serve &
```

### 问题 3: Python 包安装失败

尝试使用不同的安装方式：
```bash
# 方法 1: pip3
pip3 install ollama

# 方法 2: python3 -m pip
python3 -m pip install ollama

# 方法 3: 使用虚拟环境
python3 -m venv venv
source venv/bin/activate
pip install ollama
```

---

## 验证安装

运行以下命令验证所有组件是否正常：

```bash
# 1. 检查 Ollama
ollama --version

# 2. 检查服务
curl http://localhost:11434/api/tags

# 3. 检查模型
ollama list

# 4. 测试模型
ollama run qwen2.5:1.5b "你好"

# 5. 检查 Python 包
python3 -c "import ollama; print(ollama.__version__)"
```

全部通过后，运行测试：
```bash
python3 test/parser/test_llm_parser.py
```
