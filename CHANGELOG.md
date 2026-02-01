# 更新日志

## [2.2.0] - 2026-02-01

### 新增功能

#### 期权链查询
- ✅ `get_option_expiry_dates()` - 获取期权到期日列表
- ✅ `get_option_chain_info()` - 获取指定到期日的期权链（行权价、期权代码）
- ✅ `get_option_quote()` - 获取期权实时报价

#### 订单管理
- ✅ `cancel_order()` - 撤销订单
- ✅ `replace_order()` - 修改订单（价格、数量）
- ✅ 订单支持止盈止损参数：
  - `trigger_price` - 固定止损触发价
  - `trailing_percent` - 跟踪止损百分比
  - `trailing_amount` - 跟踪止损金额

### 功能增强

#### submit_option_order() 方法增强
新增参数：
```python
submit_option_order(
    symbol,
    side,
    quantity,
    price=None,
    order_type="LIMIT",
    remark="",
    trigger_price=None,        # ⭐ 新增
    trailing_percent=None,     # ⭐ 新增
    trailing_amount=None       # ⭐ 新增
)
```

### 测试
- ✅ `test/broker/test_order_management.py` - 订单管理功能完整测试
- ✅ `test/broker/test_longport_integration.py` - 更新集成测试，包含期权链查询

### 文档
- ✅ `docs/order_management.md` - 订单管理功能完整文档
- ✅ `README.md` - 更新功能特性说明
- ✅ `CHANGELOG.md` - 本更新日志

### 错误修复
- 🐛 修复期权代码转换中的日期解析问题
- 🐛 修复期权链查询 API 属性名问题（price vs strike_price）
- 🐛 修复订单撤销返回值处理

### 已验证功能
所有功能已在模拟账户中测试通过：
- ✅ 期权链查询（26个到期日，41个行权价）
- ✅ 期权实时报价（最新价、开盘、最高、最低、成交量）
- ✅ 带止损的订单提交
- ✅ 跟踪止损订单
- ✅ 订单修改
- ✅ 订单撤销
- ✅ 订单状态查询

---

## [2.1.0] - 2026-01-XX

### 新增功能
- ✅ Cookie 持久化
- ✅ 智能去重（内容哈希 + 消息ID）
- ✅ 自动滚动支持
- ✅ 后台监控工具
- ✅ 长桥证券集成
- ✅ 风险控制模块
- ✅ 持仓管理系统

---

## 使用指南

### 快速测试新功能

#### 1. 测试期权链查询

```bash
cd /Users/txink/Documents/code/playwright
PYTHONPATH=$(pwd) python3 test/broker/test_longport_integration.py
```

查看输出中的"测试 5: 期权链查询"部分。

#### 2. 测试订单管理

```bash
PYTHONPATH=$(pwd) python3 test/broker/test_order_management.py
```

此测试会演示：
- 带止损的订单提交
- 跟踪止损订单
- 订单修改
- 订单撤销

#### 3. 使用新功能

```python
from broker import LongPortBroker, load_longport_config

# 初始化
config = load_longport_config()
broker = LongPortBroker(config)

# 1. 查询期权链
expiry_dates = broker.get_option_expiry_dates("AAPL.US")
option_chain = broker.get_option_chain_info("AAPL.US", expiry_dates[1])

# 2. 提交带止损的订单
order = broker.submit_option_order(
    symbol=option_chain["call_symbols"][20],
    side="BUY",
    quantity=2,
    price=5.0,
    trigger_price=3.0,  # 止损价 $3
    remark="带止损的买入订单"
)

# 3. 修改订单
broker.replace_order(
    order_id=order['order_id'],
    quantity=3,
    price=4.5
)

# 4. 撤销订单
broker.cancel_order(order['order_id'])
```

### 详细文档

- 📖 [订单管理完整文档](./docs/order_management.md)
- 📖 [长桥集成指南](./doc/LONGPORT_INTEGRATION_GUIDE.md)
- 📖 [配置说明](./doc/CONFIGURATION.md)

---

## 贡献者

感谢所有贡献者的付出！

---

## 许可证

MIT License
