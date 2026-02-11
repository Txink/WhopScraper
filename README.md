#: 期权信号抓取器 + 自动交易系统 v2.6.15

使用 Playwright 实时监控 Whop 页面，解析期权交易信号,并通过长桥证券 API 自动执行交易，包含完整的持仓管理和风险控制系统。

> 🚀 **v2.6.15 新特性**: 
> - **时间优先推断** - 优化symbol推断：时间上下文优先于引用内容，避免使用过时信息！
> - **扩大上下文窗口** - 从前5条扩大到前10条，捕获更多时间相关性！
> - **精准分组** - 修复NVDA消息被误分到GILD组，交易组减少3个错误分组！
> - **核心文档** - 新增 [MESSAGE_PARSING_RULES.md](./doc/MESSAGE_PARSING_RULES.md) 详细说明解析规则！

> 📁 **项目结构清晰**：所有文档位于 `doc/` 目录，所有测试位于 `test/` 目录

## 🎯 快速开始

### 方式 1: 简单抓取（推荐新手）

```bash
# 1. 安装依赖
pip3 install -r requirements.txt
python3 -m playwright install chromium

# 2. 登录并保存 Cookie
python3 whop_login.py

# 3. 开始抓取消息
python3 whop_scraper_simple.py --url "https://whop.com/your-page-url/"
```

📖 **详细指南**：[Whop 登录和抓取指南](./WHOP_LOGIN_GUIDE.md)

### 方式 2: 完整系统（包含自动交易）

```bash
# 1. 安装依赖
pip3 install -r requirements.txt
python3 -m playwright install chromium

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 填入凭据

# 3. 验证配置
python3 check_config.py

# 4. 运行测试
PYTHONPATH=. python3 test/test_longport_integration.py

# 5. 启动系统
python3 main.py
```

📖 **快速开始**：[新手上手指南](./GETTING_STARTED.md) ⭐ | [快速参考](./QUICK_REFERENCE.md)

📖 **详细指南**：[登录指南](./WHOP_LOGIN_GUIDE.md) | [后台监控](./BACKGROUND_MONITORING.md) | [去重功能](./DEDUPLICATION_GUIDE.md) | [自动滚动](./AUTO_SCROLL_GUIDE.md) | [事件驱动监控](./doc/EVENT_DRIVEN_MONITOR.md) ⭐ | [消息分组关联](./doc/MESSAGE_GROUPING.md) | [本地HTML分析](./doc/LOCAL_HTML_ANALYSIS.md) 🆕 | [消息上下文识别](./doc/MESSAGE_CONTEXT.md) | [DOM导出调试](./doc/DEBUG_DOM.md) 🔧 | [选择器优化](./doc/SELECTOR_OPTIMIZATION.md) 🎯 | [故障排查](./TROUBLESHOOTING.md)

📖 **消息提取重构**：[DOM结构指南](./docs/dom_structure_guide.md) 🏗️ | [输出格式说明](./docs/message_output_format.md) 📋 | [JSON导出指南](./docs/json_export_guide.md) 📤 | [本地分析工具](./docs/analyze_local_messages_guide.md) 🔍 | [重构总结](./docs/message_extraction_refactoring.md) 🎯 | [DOM分析](./docs/dom_analysis_summary.md) 🔬

📖 **完整系统**：[使用指南](./doc/USAGE_GUIDE.md) | [配置说明](./doc/CONFIGURATION.md) | [长桥集成](./doc/LONGPORT_INTEGRATION_GUIDE.md) | [订单管理](./docs/order_management.md) | [自动交易](./docs/auto_trading.md) 🤖 | [完整自动化流程](./docs/full_auto_trading_guide.md) 🚀 | [批量撤销订单](./README_CANCEL_ORDERS.md) | [启动清单](./doc/CHECKLIST.md)

📁 **项目资源**：[项目结构说明](./PROJECT_STRUCTURE.md) | [期权过期校验](./doc/OPTION_EXPIRY_CHECK.md) | [更新日志](./CHANGELOG.md) | [LLM 解析器指南](./docs/llm_parser_guide.md) 🤖 | [LLM 训练方案](./docs/llm_training_guide.md) 🎓 | [训练快速参考](./TRAINING_QUICK_REFERENCE.md) ⚡

## 功能特性

### 信号监控
- ✅ 自动登录 Whop 平台
- ✅ **Cookie 持久化**（登录一次，长期使用）
- ✅ **消息上下文识别** 🆕 (v2.6.2)
  - 智能识别连续消息的关联关系
  - 自动组合开仓+止损+止盈消息
  - 识别引用/回复的消息内容
  - 提供完整的交易决策上下文
- ✅ **智能解析期权交易指令**
  - 规则解析器（快速、确定性）
  - **LLM 解析器**（智能、泛化性强）🆕
  - 混合解析器（规则 + LLM，最佳实践）
  - **LoRA 微调训练**（最高准确率）🎓 新增
- ✅ **期权过期时间校验**（自动拦截已过期期权）
- ✅ 自动样本收集与管理
- ✅ JSON 格式输出，方便对接券商 API

### 交易执行
- ✅ 长桥证券 API 集成（支持模拟/真实账户切换）
- ✅ 风险控制和 Dry Run 模式
- ✅ **期权交易**
  - 期权链查询（获取到期日、行权价、实时报价）
  - 期权订单提交（submit_option_order）
  - 期权代码自动转换
- ✅ **正股交易** ⭐ 新增
  - 正股实时报价查询（get_stock_quote）
  - 正股订单提交（submit_stock_order）
  - 支持限价单和市价单
  - 市价单智能风险检查
  - **卖出持仓检查** 🔒 (v2.5.2)
    - 自动验证持仓数量
    - 防止超量卖出
    - 无持仓时拒绝卖出
- ✅ **订单管理**
  - 订单撤销（cancel_order）
  - 订单修改（replace_order）
  - 批量撤销订单工具（cancel_all_orders.py）⭐
  - 止盈止损设置（trigger_price, trailing_percent）
  - 跟踪止损（trailing_amount）
- ✅ **完整的订单生命周期管理**
- ✅ **彩色表格输出** ⭐
  - BUY (买入) - 绿色 ✅
  - SELL (卖出) - 红色 ❌
  - **CANCEL (撤销) - 浅灰色边框** ⚫ (v2.5.4)
  - **失败订单 - 红色边框** 🔴 (v2.5.3)
  - 修改项黄色高亮（如 `1 → 2`）
  - 自动格式化止盈止损策略

## 🔧 工具说明

### 后台监控管理工具

项目提供了完整的后台监控管理工具：

#### 1. `start_background_monitor.sh` - 一键启动后台监控

交互式启动脚本，支持多种运行模式。

```bash
# 一键启动（交互式配置）
./start_background_monitor.sh

# 或者快速启动（使用默认 URL）
./start_background_monitor.sh "https://whop.com/your-page/"
```

提供三种运行模式：
- **Screen 会话**（推荐）：可随时查看，支持重连
- **nohup 后台**：简单临时使用
- **无限循环**：自动重启，最稳定

#### 2. `check_status.sh` - 查看运行状态

```bash
# 查看详细状态
./check_status.sh
```

显示信息：
- 进程状态和资源使用
- Screen 会话
- 最新日志
- 今日统计
- Cookie 状态

#### 3. `stop_monitor.sh` - 停止监控

```bash
# 停止所有监控进程
./stop_monitor.sh
```

支持：
- PID 文件方式停止
- 批量停止所有进程
- 停止 Screen 会话

### 登录和 Cookie 管理工具

项目提供了两个简单易用的工具，帮助您快速开始使用：

#### 1. `whop_login.py` - 登录助手

用于保存和测试 Whop 登录状态（Cookie）。

```bash
# 登录并保存 Cookie
python3 whop_login.py

# 测试 Cookie 是否有效
python3 whop_login.py --test

# 查看所有选项
python3 whop_login.py --help
```

#### 2. `whop_scraper_simple.py` - 智能消息抓取器（支持去重）

使用保存的 Cookie 自动登录并抓取页面消息，支持智能去重和噪音过滤。

```bash
# 基本抓取（监控 30 秒，自动去重）
python3 whop_scraper_simple.py --url "https://whop.com/your-page-url/"

# 监控更长时间（如 60 秒）
python3 whop_scraper_simple.py --url "https://whop.com/your-page-url/" --duration 60

# 使用无头模式（后台运行）
python3 whop_scraper_simple.py --url "https://whop.com/your-page-url/" --headless

# 过滤更多噪音（最小消息长度 15 字符）
python3 whop_scraper_simple.py --url "URL" --min-length 15

# 保存唯一消息到文件
python3 whop_scraper_simple.py --url "URL" --output messages.json

# 启用自动滚动（适用于懒加载页面）
python3 whop_scraper_simple.py --url "URL" --auto-scroll

# 完整示例（所有功能）
python3 whop_scraper_simple.py --url "URL" --duration 300 --headless --auto-scroll --min-length 15 --output messages.json

# 查看所有选项
python3 whop_scraper_simple.py --help
```

**核心功能**：
- ✅ 内容哈希去重（避免不同 ID 的相同内容）
- ✅ 消息 ID 去重（防止重复处理）
- ✅ 噪音过滤（过滤太短的消息）
- ✅ 统计信息（显示去重效率）
- ✅ 保存到文件（JSON 格式）
- ✅ **自动滚动**（支持懒加载/无限滚动页面）

📖 详细说明：
- [去重功能指南](./DEDUPLICATION_GUIDE.md)
- [自动滚动指南](./AUTO_SCROLL_GUIDE.md)

📖 **详细教程**：请参考 [Whop 登录和抓取指南](./WHOP_LOGIN_GUIDE.md)

**使用场景**：
- 🎯 **新手入门**：快速验证 Cookie 功能
- 🧪 **功能测试**：测试 Whop 登录和消息提取
- 🚀 **简单抓取**：只需要抓取消息，不需要自动交易
- 📊 **数据收集**：收集消息样本用于后续分析

**完整系统 vs 简单工具**：
- 简单工具：快速上手，专注于消息抓取
- 完整系统（`main.py`）：包含期权解析、风险控制、自动交易等完整功能

## 安装依赖

```bash
# 安装 Python 依赖
pip3 install -r requirements.txt

# 安装 Playwright 浏览器
python3 -m playwright install chromium
```

## 配置

> 💡 **统一配置管理**：所有配置项都在 `.env` 文件中设置，无需修改代码。

### 配置步骤

1. 复制配置模板：
```bash
cp .env.example .env
```

2. 编辑 `.env` 文件，填入你的凭据。

3. 验证配置：
```bash
python3 check_config.py
```

此工具会检查：
- ✅ 配置文件是否存在
- ✅ 必填项是否已设置
- ✅ 配置类型是否正确
- ✅ 风险参数是否合理
- ✅ 交易模式组合提示

### 配置分类

#### Whop 平台配置
```env
# 必填：登录凭据
WHOP_EMAIL=your_email@example.com
WHOP_PASSWORD=your_password

# 可选：页面 URL
# TARGET_URL=https://whop.com/joined/stock-and-option/-9vfxZgBNgXykNt/app/
# LOGIN_URL=https://whop.com/login/

# 可选：浏览器设置
HEADLESS=false          # 是否无头模式运行
SLOW_MO=0               # 浏览器操作延迟（毫秒）

# 可选：监控设置
POLL_INTERVAL=2.0       # 轮询间隔（秒）
```

#### 长桥证券配置
```env
# 必填：账户模式
LONGPORT_MODE=paper     # paper=模拟账户, real=真实账户

# 必填：API 凭据（根据账户模式填写对应的配置）
LONGPORT_PAPER_APP_KEY=your_paper_app_key
LONGPORT_PAPER_APP_SECRET=your_paper_app_secret
LONGPORT_PAPER_ACCESS_TOKEN=your_paper_access_token

# 可选：风险控制
LONGPORT_MAX_POSITION_RATIO=0.20  # 单仓位上限（20%）
LONGPORT_MAX_DAILY_LOSS=0.05      # 单日止损（5%）
LONGPORT_MIN_ORDER_AMOUNT=100     # 最小下单金额（$100）

# 可选：交易模式
LONGPORT_AUTO_TRADE=false   # 是否启用自动交易
LONGPORT_DRY_RUN=true       # 是否启用模拟模式（不实际下单）
```

### 配置文件说明

| 文件 | 说明 | 是否提交到 Git |
|------|------|---------------|
| `.env.example` | 配置模板，包含所有配置项及说明 | ✅ 是 |
| `.env` | 实际配置，包含真实凭据 | ❌ 否（已在 .gitignore 中）|
| `config.py` | 配置加载模块 | ✅ 是 |

> ⚠️ **安全提示**：`.env` 文件包含敏感信息，已自动添加到 `.gitignore`，不会提交到版本控制系统。

## 使用方法

### 启动系统

### 完整模式（监控 + 自动交易）

```bash
python3 main.py
```

程序会：
1. 自动登录 Whop
2. 初始化长桥交易接口
3. 启动持仓管理和风险控制
4. 开始实时监控新消息
5. 自动解析并执行交易
6. 自动管理止损止盈

### 仅监控模式

如果只想监控信号而不交易，设置：

```bash
# 在 .env 中
LONGPORT_AUTO_TRADE=false
```

然后运行：

```bash
python3 main.py
```

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

**⚠️ 期权过期校验**：系统会自动检查期权到期日，如果期权已过期（到期日早于当前日期），将自动拦截并跳过该指令，不会执行下单操作。

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

### 长桥证券集成（推荐）

本项目已集成长桥（LongPort）OpenAPI，支持：
- ✅ 模拟账户和真实账户自动切换
- ✅ 期权自动下单
- ✅ 风险控制和 Dry Run 模式
- ✅ 完整的测试流程

**查看完整接入指南**：[LONGPORT_INTEGRATION_GUIDE.md](./doc/LONGPORT_INTEGRATION_GUIDE.md)

快速开始：

```bash
# 1. 配置环境变量（在 .env 中）
LONGPORT_MODE=paper  # 使用模拟账户
LONGPORT_PAPER_APP_KEY=your_key
LONGPORT_PAPER_APP_SECRET=your_secret
LONGPORT_PAPER_ACCESS_TOKEN=your_token

# 2. 运行测试
PYTHONPATH=. python3 test/test_longport_integration.py

# 3. 启动自动交易
python3 main.py
```

### 其他券商 API

如果使用其他券商，在 `main.py` 的 `_on_instruction` 方法中添加你的 API 调用逻辑：

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

## 测试

### 快速运行所有测试

使用提供的脚本一键运行所有测试：

```bash
./run_all_tests.sh
```

### 单独运行测试

```bash
# 配置加载测试（验证 .env 配置）
PYTHONPATH=. python3 test/test_config.py

# 长桥 API 集成测试
PYTHONPATH=. python3 test/test_longport_integration.py

# 期权过期校验测试
PYTHONPATH=. python3 test/test_option_expiry.py

# 期权过期集成测试
PYTHONPATH=. python3 test/test_expiry_integration.py

# 持仓管理测试
PYTHONPATH=. python3 test/test_position_management.py

```

📝 更多测试信息，请参考 [test/README.md](./test/README.md)

## 项目结构

```
playwright/
├── config.py              # 配置模块
├── main.py                # 主程序入口
├── requirements.txt       # Python 依赖
├── .env                   # 环境变量（需自行创建）
├── .env.example           # 环境变量模板
├── CHANGELOG.md           # 更新日志
├── README.md              # 项目说明
├── check_config.py        # 配置检查工具
├── run_all_tests.sh       # 测试运行脚本
│
├── doc/                   # 📁 文档目录
│   ├── README.md          # 文档导航
│   ├── USAGE_GUIDE.md     # 完整使用指南
│   ├── CONFIGURATION.md   # 配置说明文档
│   ├── SETUP_WIZARD.md    # 分步设置向导
│   ├── QUICKSTART_LONGPORT.md  # 快速开始
│   ├── LONGPORT_INTEGRATION_GUIDE.md  # 长桥 API 集成
│   ├── CHECKLIST.md       # 启动检查清单
│   ├── PROJECT_STATUS.md  # 项目状态报告
│   └── OPTION_EXPIRY_CHECK.md  # 期权过期校验文档
│
├── test/                  # 🧪 测试目录
│   ├── README.md          # 测试说明
│   ├── test_longport_integration.py  # 长桥 API 测试
│   ├── test_option_expiry.py         # 期权过期测试
│   ├── test_expiry_integration.py    # 期权过期集成测试
│   └── test_position_management.py   # 持仓管理测试
│
├── broker/                # 券商接口模块
│   ├── __init__.py
│   ├── config_loader.py   # 配置加载器
│   ├── longport_broker.py # 长桥交易接口
│   ├── position_manager.py  # 持仓管理
│
├── scraper/               # 页面抓取模块
│   ├── browser.py         # Playwright 浏览器管理
│   └── monitor.py         # 实时监控逻辑
│
├── parser/                # 解析模块
│   └── option_parser.py   # 期权指令正则解析器
│
├── models/                # 数据模型
│   └── instruction.py     # 指令数据模型
│
├── data/                  # 数据目录
│   └── positions.json     # 持仓数据
│
├── logs/                  # 日志目录
│   └── trading.log        # 交易日志
│
└── output/                # 输出目录
    └── signals.json       # 解析后的信号输出
```

## 注意事项

1. **登录安全**：`.env` 文件包含敏感信息，已添加到 `.gitignore`，不会提交到版本控制
2. **网络稳定**：确保网络连接稳定，程序会自动重连
3. **期权过期**：系统会自动拦截已过期的期权指令，确保不会交易失效合约

## 常见问题

### 1. 登录失败

- 检查 `.env` 文件中的邮箱和密码是否正确
- 尝试手动登录一次，确认账号可用
- 查看是否需要验证码（程序目前不支持验证码）

### 2. 找不到消息

- Whop 页面结构可能变化，需要更新 `monitor.py` 中的选择器
- 尝试在有头模式下运行（`HEADLESS=false`），检查页面是否正常加载

### 3. 解析错误

- 根据日志或输出改进 `parser/option_parser.py` 中的正则表达式
- 提交 Issue 反馈新的消息格式

## 项目状态

### 已完成功能 ✅

- ✅ 信号监控和解析
- ✅ 长桥证券 API 集成
- ✅ 自动期权下单
- ✅ 持仓管理系统
- ✅ 自动止损止盈
- ✅ 移动止损
- ✅ 风险控制系统
- ✅ 模拟/真实账户切换
- ✅ Dry Run 模式
- ✅ 完整测试套件
- ✅ 详细文档

查看：[项目状态详情](./doc/PROJECT_STATUS.md)

### 📚 文档导航

所有文档位于 `doc/` 目录：

| 文档 | 说明 |
|------|------|
| [WHOP_LOGIN_GUIDE.md](./WHOP_LOGIN_GUIDE.md) | 🔑 Whop 登录和抓取指南（**推荐新手**） |
| [USAGE_GUIDE.md](./doc/USAGE_GUIDE.md) | 📖 完整使用指南 |
| [CONFIGURATION.md](./doc/CONFIGURATION.md) | ⚙️ 配置说明文档 |
| [SETUP_WIZARD.md](./doc/SETUP_WIZARD.md) | 🧙 分步设置向导 |
| [QUICKSTART_LONGPORT.md](./doc/QUICKSTART_LONGPORT.md) | ⚡ 5分钟快速开始 |
| [LONGPORT_INTEGRATION_GUIDE.md](./doc/LONGPORT_INTEGRATION_GUIDE.md) | 🔧 长桥 API 集成指南 |
| [MESSAGE_PARSING_RULES.md](./doc/MESSAGE_PARSING_RULES.md) | 📝 消息解析规则（**核心逻辑**） |
| [MESSAGE_CONTEXT.md](./doc/MESSAGE_CONTEXT.md) | 🔗 消息上下文传递机制 |
| [MESSAGE_GROUPING.md](./doc/MESSAGE_GROUPING.md) | 📦 消息分组策略 |
| [CHECKLIST.md](./doc/CHECKLIST.md) | ✅ 启动检查清单 |
| [OPTION_EXPIRY_CHECK.md](./doc/OPTION_EXPIRY_CHECK.md) | ⏰ 期权过期校验说明 |
| [PROJECT_STATUS.md](./doc/PROJECT_STATUS.md) | 📊 项目状态报告 |

### 🧪 测试文件

所有测试文件位于 `test/` 目录：

| 测试文件 | 说明 |
|---------|------|
| [test_config.py](./test/test_config.py) | 配置加载验证测试 |
| [test_longport_integration.py](./test/test_longport_integration.py) | 长桥 API 集成测试 |
| [test_option_expiry.py](./test/test_option_expiry.py) | 期权过期时间校验测试 |
| [test_expiry_integration.py](./test/test_expiry_integration.py) | 期权过期集成测试 |
| [test_position_management.py](./test/test_position_management.py) | 持仓管理测试 |

## 许可证

MIT
