# 完整自动交易流程指南

## 概述

本指南介绍如何使用完整的自动化交易流程：从监听网页消息到自动下单的端到端方案。

## 工作流程

```
1. 监听Whop页面 → 2. 提取消息 → 3. 解析指令 → 4. 自动下单 → 5. 持仓管理
     (main.py)       (scraper)     (parser)     (AutoTrader)   (PositionManager)
```

## 快速开始

### 方式1: 监听网页实时自动交易

#### 第1步：配置环境变量

在 `.env` 文件中配置：

```bash
# ============ Whop 登录配置 ============
WHOP_EMAIL=your_email@example.com
WHOP_PASSWORD=your_password
WHOP_OPTION_PAGES=https://whop.com/your-page-url/

# ============ 长桥交易配置 ============
LONGPORT_APP_KEY=your_app_key
LONGPORT_APP_SECRET=your_app_secret
LONGPORT_ACCESS_TOKEN=your_access_token
LONGPORT_MODE=paper  # paper=模拟账户, real=真实账户
LONGPORT_AUTO_TRADE=true  # 启用自动交易
LONGPORT_DRY_RUN=false    # false=实际执行, true=仅模拟

# ============ 自动交易配置 ============
MAX_OPTION_TOTAL_PRICE=10000      # 单个期权总价上限
REQUIRE_CONFIRMATION=false         # 是否需要控制台确认
PRICE_DEVIATION_TOLERANCE=5        # 价格偏差容忍度
POSITION_SIZE_SMALL=1              # 小仓位数量
POSITION_SIZE_MEDIUM=2             # 中仓位数量
POSITION_SIZE_LARGE=5              # 大仓位数量
```

#### 第2步：启动系统

```bash
# 正常运行（监控并自动交易）
python3 main.py
```

#### 第3步：系统自动工作

系统启动后会：
1. ✅ 自动登录Whop页面
2. ✅ 实时监听新消息
3. ✅ 解析交易指令
4. ✅ 自动执行下单
5. ✅ 管理持仓和风险

### 方式2: 从本地HTML文件自动交易

#### 第1步：导出网页HTML

```bash
# 导出当前页面HTML
python3 main.py --test export-dom
```

#### 第2步：从HTML自动交易

```bash
# Dry Run模式（仅模拟，不实际下单）
python3 auto_trade_from_messages.py debug/page_20260203_xxx.html

# 真实交易模式（需要确认）
python3 auto_trade_from_messages.py debug/page_20260203_xxx.html --real

# 真实交易模式（跳过确认，谨慎！）
python3 auto_trade_from_messages.py debug/page_20260203_xxx.html --real --no-confirm
```

## 详细工作流程

### 1. 消息监听（main.py）

```python
# main.py 启动后会：
# 1. 初始化浏览器
browser = BrowserManager(headless=True)

# 2. 登录Whop页面
await browser.login(email, password)

# 3. 创建消息监控器
monitor = MutationObserverMonitor(page)

# 4. 设置新消息回调
monitor.on_new_instruction(self._handle_instruction)

# 5. 开始监听
await monitor.start()
```

### 2. 消息提取（scraper）

```python
# 使用EnhancedMessageExtractor提取消息
extractor = EnhancedMessageExtractor(page)
raw_groups = await extractor.extract_message_groups()

# 输出格式：
{
    "domID": "msg-123",
    "timestamp": "Jan 23, 2026 12:51 AM",
    "content": "AAPL 250c 2/7 5.0",
    "position": "single",
    "refer": None,
    "history": []
}
```

### 3. 指令解析（parser）

```python
# 使用OptionParser + MessageContextResolver解析
resolver = MessageContextResolver(all_messages)
result = resolver.resolve_instruction(message)

if result:
    instruction, context_source, context_message = result
    # instruction: OptionInstruction对象
    # instruction_type: BUY, SELL, CLOSE, MODIFY
```

### 4. 自动下单（AutoTrader）

```python
# 创建AutoTrader
trader = AutoTrader(broker)

# 执行指令
result = trader.execute_instruction(instruction)

# 根据指令类型执行：
# - BUY: 计算数量 → 检查余额 → 提交买入订单
# - SELL: 检查持仓 → 计算卖出比例 → 提交卖出订单
# - CLOSE: 检查持仓 → 卖出全部
# - MODIFY: 检查持仓 → 检查止盈止损触发 → 执行或修改
```

### 5. 持仓管理（PositionManager）

```python
# 买入后自动创建持仓
position = create_position_from_order(
    symbol=symbol,
    ticker=ticker,
    quantity=quantity,
    avg_cost=price
)
position_manager.add_position(position)

# 卖出后自动更新持仓
position_manager.update_position(
    symbol=symbol,
    quantity=new_quantity
)
```

## 配置说明

### 安全模式层级

从最安全到最危险：

#### 级别1: Dry Run + 模拟账户（最安全，推荐新手）

```bash
LONGPORT_MODE=paper
LONGPORT_DRY_RUN=true
REQUIRE_CONFIRMATION=true
```

- ✅ 所有操作仅打印，不实际执行
- ✅ 使用模拟账户数据
- ✅ 每次操作需要确认
- 📝 适合：学习和测试

#### 级别2: 模拟账户 + 确认模式

```bash
LONGPORT_MODE=paper
LONGPORT_DRY_RUN=false
REQUIRE_CONFIRMATION=true
```

- ⚠️ 实际提交到模拟账户
- ✅ 不会产生真实交易
- ✅ 每次操作需要确认
- 📝 适合：验证策略

#### 级别3: 真实账户 + 确认模式（谨慎使用）

```bash
LONGPORT_MODE=real
LONGPORT_DRY_RUN=false
LONGPORT_AUTO_TRADE=true
REQUIRE_CONFIRMATION=true
```

- ⚠️ 真实交易
- ⚠️ 实际资金
- ✅ 每次操作需要确认
- 📝 适合：小额实盘

#### 级别4: 真实账户 + 自动模式（极度危险！）

```bash
LONGPORT_MODE=real
LONGPORT_DRY_RUN=false
LONGPORT_AUTO_TRADE=true
REQUIRE_CONFIRMATION=false
```

- 🚫 全自动真实交易
- 🚫 无需确认
- 🚫 极高风险
- 📝 适合：经验丰富且已充分测试

### 风险控制配置

```bash
# 单个期权总价上限（防止单笔过大）
MAX_OPTION_TOTAL_PRICE=10000

# 价格偏差容忍度（防止价格波动过大时交易）
PRICE_DEVIATION_TOLERANCE=5

# 仓位大小控制
POSITION_SIZE_SMALL=1    # 小仓位：1张合约
POSITION_SIZE_MEDIUM=2   # 中仓位：2张合约
POSITION_SIZE_LARGE=5    # 大仓位：5张合约
```

## 监控和调试

### 查看日志

```bash
# 实时查看日志
tail -f logs/trading.log

# 查看最近100行
tail -100 logs/trading.log
```

### 检查持仓

```python
# 在Python中查看
from broker import LongPortBroker, load_longport_config

config = load_longport_config()
broker = LongPortBroker(config)

# 显示账户信息
broker.show_account_info()

# 显示持仓
broker.show_positions()

# 显示当日订单
broker.show_today_orders()
```

### 常见问题排查

#### 1. 消息无法解析

**症状**：监听到消息但无法解析成指令

**排查**：
```bash
# 查看parser输出
SHOW_PARSER_OUTPUT=true python3 main.py
```

**解决**：
- 检查消息格式是否匹配
- 更新parser的正则表达式
- 查看 `parser/option_parser.py`

#### 2. 订单无法提交

**症状**：指令解析成功但下单失败

**排查**：
```bash
# 检查配置
python3 check_config.py

# 测试broker连接
python3 main.py --test broker
```

**解决**：
- 检查长桥API凭据
- 确认账户余额
- 查看 `LONGPORT_AUTO_TRADE` 是否启用

#### 3. 持仓不同步

**症状**：订单成功但持仓管理器没有记录

**排查**：
```bash
# 查看持仓文件
cat data/positions.json
```

**解决**：
- 检查 `data/` 目录权限
- 查看日志中的持仓同步信息

## 测试流程

### 1. 配置测试

```bash
python3 main.py --test config
```

### 2. Broker测试

```bash
python3 main.py --test broker
```

### 3. 消息提取测试

```bash
python3 main.py --test whop-scraper
```

### 4. AutoTrader测试

```bash
PYTHONPATH=. python3 test/broker/test_auto_trader.py
```

### 5. 完整流程测试

```bash
# 使用本地HTML测试
python3 auto_trade_from_messages.py debug/page_xxx.html
```

## 最佳实践

### 1. 逐步启用

```bash
# 第1周：Dry Run模式熟悉系统
LONGPORT_DRY_RUN=true
LONGPORT_MODE=paper

# 第2周：模拟账户测试
LONGPORT_DRY_RUN=false
LONGPORT_MODE=paper
REQUIRE_CONFIRMATION=true

# 第3周：小额真实账户
LONGPORT_MODE=real
MAX_OPTION_TOTAL_PRICE=1000  # 限制每笔1000美元
REQUIRE_CONFIRMATION=true

# 稳定后：逐步放开
MAX_OPTION_TOTAL_PRICE=5000
REQUIRE_CONFIRMATION=false  # 可选
```

### 2. 监控策略

```python
# 定期检查系统状态
import schedule

def check_system_health():
    broker.show_account_info()
    broker.show_positions()
    broker.show_today_orders()

# 每小时检查一次
schedule.every().hour.do(check_system_health)
```

### 3. 风险控制

```bash
# 设置合理的上限
MAX_OPTION_TOTAL_PRICE=10000  # 单笔最多10000美元
POSITION_SIZE_LARGE=5         # 大仓位最多5张

# 启用确认模式
REQUIRE_CONFIRMATION=true

# 使用价格偏差保护
PRICE_DEVIATION_TOLERANCE=5  # 价格偏差超过5%时警告
```

## 演示脚本

### 1. 自动交易功能演示

```bash
python3 demo_auto_trading.py
```

### 2. 完整流程演示

```bash
# 1. 导出HTML
python3 main.py --test export-dom

# 2. 分析消息
python3 analyze_local_messages.py debug/page_xxx.html

# 3. 自动交易（Dry Run）
python3 auto_trade_from_messages.py debug/page_xxx.html
```

## 故障恢复

### 系统崩溃后恢复

```bash
# 1. 检查持仓数据
cat data/positions.json

# 2. 检查订单历史
python3 -c "
from broker import LongPortBroker, load_longport_config
broker = LongPortBroker(load_longport_config())
broker.show_today_orders()
"

# 3. 手动同步持仓（如果需要）
# 编辑 data/positions.json
```

### 紧急停止

```bash
# 方法1: Ctrl+C 停止（推荐）
# 系统会自动清理资源

# 方法2: 强制停止
pkill -f "python3 main.py"

# 方法3: 禁用自动交易
# 编辑 .env
LONGPORT_AUTO_TRADE=false
```

## 性能优化

### 1. 减少CPU使用

```bash
# 使用事件驱动监控
MONITOR_MODE=event

# 增加轮询间隔
POLL_INTERVAL=5
```

### 2. 减少内存使用

```bash
# 禁用样本收集
ENABLE_SAMPLE_COLLECTION=false

# 禁用Parser输出
SHOW_PARSER_OUTPUT=false
```

## 相关文档

- [自动交易功能](./auto_trading.md) - AutoTrader详细文档
- [订单管理](./order_management.md) - 订单提交、修改、撤销
- [消息解析指南](./analyze_local_messages_guide.md) - Parser使用指南
- [风险控制](../doc/RISK_CONTROL.md) - 风险控制配置

## 更新日志

### 2026-02-03
- ✅ 创建完整自动交易流程文档
- ✅ 集成AutoTrader到main.py
- ✅ 支持BUY, SELL, CLOSE, MODIFY指令
- ✅ 提供多种安全模式配置
- ✅ 完整的测试和故障排查指南
