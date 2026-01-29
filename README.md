# 期权信号抓取器

使用 Playwright 实时监控 Whop 页面，解析期权交易信号并转换为 JSON 格式的标准化指令。

## 功能特性

- ✅ 自动登录 Whop 平台
- ✅ 实时监控页面新消息
- ✅ 智能解析期权交易指令
- ✅ 自动样本收集与管理
- ✅ JSON 格式输出，方便对接券商 API

## 安装依赖

```bash
# 安装 Python 依赖
pip3 install -r requirements.txt

# 安装 Playwright 浏览器
python3 -m playwright install chromium
```

## 配置

1. 复制配置模板：
```bash
cp .env.example .env
```

2. 编辑 `.env` 文件，填入你的凭据：
```env
WHOP_EMAIL=your_email@example.com
WHOP_PASSWORD=your_password

# 可选配置
HEADLESS=false          # 是否无头模式运行
POLL_INTERVAL=2.0       # 轮询间隔（秒）
```

## 使用方法

### 启动监控

```bash
python3 main.py
```

程序会：
1. 自动登录 Whop
2. 导航到目标页面
3. 开始实时监控新消息
4. 自动解析并保存指令到 `output/signals.json`

### 测试解析器

```bash
python3 main.py --test
```

## 支持的指令格式

### 1. 开仓指令

| 示例 | 解析结果 |
|------|---------|
| `INTC - $48 CALLS 本周 $1.2` | 股票: INTC, 行权价: 48, 类型: CALL, 价格: 1.2 |
| `AAPL $150 PUTS 1/31 $2.5` | 股票: AAPL, 行权价: 150, 类型: PUT, 到期: 1/31, 价格: 2.5 |
| `TSLA - 250 CALL $3.0 小仓位` | 股票: TSLA, 行权价: 250, 类型: CALL, 价格: 3.0, 仓位: 小仓位 |

### 2. 止损指令

| 示例 | 解析结果 |
|------|---------|
| `止损 0.95` | 止损价: 0.95 |
| `止损提高到1.5` | 调整止损至: 1.5 |

### 3. 止盈/出货指令

| 示例 | 解析结果 |
|------|---------|
| `1.75出三分之一` | 价格: 1.75, 比例: 1/3 |
| `1.65附近出剩下三分之二` | 价格: 1.65, 比例: 2/3 |
| `2.0 出一半` | 价格: 2.0, 比例: 1/2 |

## 样本管理

程序会自动收集所有消息样本，方便后续改进解析规则。

### 查看样本统计

```bash
python3 -m samples.sample_manager report
```

输出示例：
```
样本统计报告
============================================================
总样本数: 25
成功解析: 20 (80.0%)
未能解析: 5 (20.0%)

按分类统计:
  - 开仓指令: 8
  - 止损指令: 5
  - 止盈指令: 7
  - 未识别: 5
============================================================
```

### 查看所有样本

```bash
# 查看所有样本
python3 -m samples.sample_manager list

# 查看特定分类的样本
python3 -m samples.sample_manager list "开仓指令"

# 只查看未解析的样本
python3 -m samples.sample_manager list --unparsed
```

### 手动添加样本

```bash
python3 -m samples.sample_manager add "NVDA 900 CALL $5.0" "开仓指令" "测试样本"
```

### 导出样本

```bash
# 导出所有开仓指令样本
python3 -m samples.sample_manager export "开仓指令" samples_open.txt
```

### 使用样本改进正则

1. 查看未能解析的样本：
```bash
python3 -m samples.sample_manager list --unparsed
```

2. 在 `parser/option_parser.py` 中添加新的正则模式

3. 重新运行测试验证：
```bash
python3 main.py --test
```

## 输出格式

解析后的指令保存在 `output/signals.json`，格式如下：

```json
[
  {
    "timestamp": "2026-01-28T10:00:00",
    "raw_message": "INTC - $48 CALLS 本周 $1.2",
    "instruction_type": "OPEN",
    "ticker": "INTC",
    "option_type": "CALL",
    "strike": 48.0,
    "expiry": "本周",
    "price": 1.2,
    "position_size": "小仓位",
    "message_id": "abc123"
  }
]
```

## 对接券商 API

在 `main.py` 的 `_on_instruction` 方法中添加你的券商 API 调用逻辑：

```python
def _on_instruction(self, instruction: OptionInstruction):
    if instruction.instruction_type == "OPEN":
        # 开仓
        broker_api.open_position(
            ticker=instruction.ticker,
            option_type=instruction.option_type,
            strike=instruction.strike,
            price=instruction.price
        )
    elif instruction.instruction_type == "STOP_LOSS":
        # 设置止损
        broker_api.set_stop_loss(instruction.price)
    # ...
```

## 项目结构

```
playwright/
├── config.py              # 配置模块
├── main.py                # 主程序入口
├── requirements.txt       # Python 依赖
├── .env                   # 环境变量（需自行创建）
├── .env.example           # 环境变量模板
├── scraper/
│   ├── browser.py         # Playwright 浏览器管理
│   └── monitor.py         # 实时监控逻辑
├── parser/
│   └── option_parser.py   # 期权指令正则解析器
├── models/
│   └── instruction.py     # 指令数据模型
├── samples/
│   ├── sample_manager.py  # 样本管理器
│   ├── samples.json       # 样本数据库
│   └── initial_samples.json  # 初始样本示例
└── output/
    └── signals.json       # 解析后的信号输出
```

## 注意事项

1. **登录安全**：`.env` 文件包含敏感信息，已添加到 `.gitignore`，不会提交到版本控制
2. **网络稳定**：确保网络连接稳定，程序会自动重连
3. **样本隐私**：样本中可能包含交易信号，注意保护隐私

## 常见问题

### 1. 登录失败

- 检查 `.env` 文件中的邮箱和密码是否正确
- 尝试手动登录一次，确认账号可用
- 查看是否需要验证码（程序目前不支持验证码）

### 2. 找不到消息

- Whop 页面结构可能变化，需要更新 `monitor.py` 中的选择器
- 尝试在有头模式下运行（`HEADLESS=false`），检查页面是否正常加载

### 3. 解析错误

- 查看未解析样本：`python3 -m samples.sample_manager list --unparsed`
- 根据样本改进 `parser/option_parser.py` 中的正则表达式
- 提交 Issue 反馈新的消息格式

## 许可证

MIT
