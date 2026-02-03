动交易快速启动指南

## 5分钟上手自动交易

### 第1步：配置环境（2分钟）

编辑 `.env` 文件：

```bash
# ============ Whop 登录 ============
WHOP_EMAIL=your_email@example.com
WHOP_PASSWORD=your_password
WHOP_OPTION_PAGES=https://whop.com/your-page/

# ============ 长桥API ============
LONGPORT_APP_KEY=your_key
LONGPORT_APP_SECRET=your_secret
LONGPORT_ACCESS_TOKEN=your_token

# ============ 安全设置（新手推荐）============
LONGPORT_MODE=paper              # 模拟账户
LONGPORT_DRY_RUN=true           # 仅模拟，不实际执行
LONGPORT_AUTO_TRADE=true        # 启用自动交易
REQUIRE_CONFIRMATION=true       # 需要确认

# ============ 交易限制 ============
MAX_OPTION_TOTAL_PRICE=5000     # 单笔最多5000美元
POSITION_SIZE_SMALL=1           # 小仓位1张
POSITION_SIZE_MEDIUM=2          # 中仓位2张
POSITION_SIZE_LARGE=5           # 大仓位5张
```

### 第2步：测试配置（1分钟）

```bash
# 验证配置
python3 check_config.py

# 测试broker连接
python3 main.py --test broker
```

### 第3步：启动系统（2分钟）

```bash
# 启动自动交易系统
python3 main.py
```

系统会：
- ✅ 自动登录Whop
- ✅ 监听新消息
- ✅ 解析交易指令
- ✅ 自动下单（根据配置）

## 工作原理

```
监听消息 → 解析指令 → 自动下单
```

### 支持的指令格式

| 指令类型 | 示例消息 | 解析结果 |
|---------|---------|---------|
| **买入** | `AAPL 250c 2/7 5.0 小仓位` | BUY 1张 AAPL $250 CALL |
| **卖出** | `AAPL 6.0出1/3` | SELL 1/3持仓 @ $6.0 |
| **清仓** | `TSLA 7.0清仓` | CLOSE 全部持仓 @ $7.0 |
| **止损** | `止损在2.9` | MODIFY 止损价$2.9 |

## 安全模式

### 🔰 新手模式（最安全）

```bash
LONGPORT_MODE=paper
LONGPORT_DRY_RUN=true
REQUIRE_CONFIRMATION=true
```

- ✅ 所有操作仅打印
- ✅ 模拟账户
- ✅ 需要确认

### 🔶 测试模式

```bash
LONGPORT_MODE=paper
LONGPORT_DRY_RUN=false
REQUIRE_CONFIRMATION=true
```

- ⚠️ 提交到模拟账户
- ✅ 不涉及真实资金
- ✅ 需要确认

### 🔴 实盘模式（谨慎！）

```bash
LONGPORT_MODE=real
LONGPORT_DRY_RUN=false
REQUIRE_CONFIRMATION=true
```

- 🚫 真实资金
- 🚫 实际交易
- ✅ 需要确认

## 常用命令

```bash
# 正常运行
python3 main.py

# 导出HTML（用于离线测试）
python3 main.py --test export-dom

# 从HTML自动交易
python3 auto_trade_from_messages.py debug/page_xxx.html

# 查看演示
python3 demo_auto_trading.py

# 运行测试
python3 test/broker/test_auto_trader.py
```

## 查看结果

### 实时日志

```bash
tail -f logs/trading.log
```

### 持仓查询

```python
from broker import LongPortBroker, load_longport_config

broker = LongPortBroker(load_longport_config())
broker.show_account_info()
broker.show_positions()
broker.show_today_orders()
```

## 停止系统

```bash
# 方法1：按 Ctrl+C（推荐）
# 系统会自动清理资源

# 方法2：禁用自动交易
# 编辑 .env
LONGPORT_AUTO_TRADE=false
```

## 故障排查

### 问题1：无法解析消息

```bash
# 查看parser输出
SHOW_PARSER_OUTPUT=true python3 main.py
```

### 问题2：无法下单

```bash
# 检查配置
python3 check_config.py

# 检查是否启用自动交易
grep LONGPORT_AUTO_TRADE .env
```

### 问题3：提示余额不足

```bash
# 检查配置的上限是否过高
grep MAX_OPTION_TOTAL_PRICE .env

# 降低上限
MAX_OPTION_TOTAL_PRICE=1000
```

## 进阶使用

### 自定义仓位大小

```bash
# 根据你的风险承受能力调整
POSITION_SIZE_SMALL=1    # 保守：1张
POSITION_SIZE_MEDIUM=3   # 适中：3张
POSITION_SIZE_LARGE=10   # 激进：10张
```

### 价格保护

```bash
# 价格偏差超过5%时警告
PRICE_DEVIATION_TOLERANCE=5
```

### 批量处理历史消息

```bash
# 1. 导出HTML
python3 main.py --test export-dom

# 2. 批量处理
python3 auto_trade_from_messages.py debug/page_xxx.html
```

## 完整文档

- 📖 [完整自动化流程指南](./docs/full_auto_trading_guide.md)
- 📖 [AutoTrader详细文档](./docs/auto_trading.md)
- 📖 [订单管理](./docs/order_management.md)
- 📖 [配置说明](./doc/CONFIGURATION.md)

## 免责声明

⚠️ **重要提示**：

- 本系统为学习和研究目的开发
- 使用真实账户前请充分测试
- 交易有风险，投资需谨慎
- 作者不对任何交易损失负责

## 支持

遇到问题？

1. 查看 [故障排查文档](./TROUBLESHOOTING.md)
2. 查看日志 `logs/trading.log`
3. 提交 Issue

---

**祝交易顺利！** 🚀
