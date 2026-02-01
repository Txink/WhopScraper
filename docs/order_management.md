# 订单管理功能文档

## 概述

长桥期权交易系统现已支持完整的订单管理功能，包括：
1. 订单撤销
2. 订单修改
3. 止盈止损设置

## 功能详解

### 1. 订单提交（增强版）

现在 `submit_option_order` 方法支持止盈止损参数：

```python
order = broker.submit_option_order(
    symbol="AAPL260202C252500.US",
    side="BUY",
    quantity=1,
    price=5.0,
    order_type="LIMIT",
    trigger_price=3.0,          # 止损触发价（可选）
    trailing_percent=5.0,       # 跟踪止损百分比（可选）
    trailing_amount=1.0,        # 跟踪止损金额（可选）
    remark="订单备注"
)
```

#### 参数说明

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `symbol` | str | ✅ | 期权代码 |
| `side` | str | ✅ | 买卖方向（BUY/SELL） |
| `quantity` | int | ✅ | 合约数量 |
| `price` | float | ❌ | 限价单价格（市价单传 None） |
| `order_type` | str | ❌ | 订单类型（LIMIT/MARKET），默认 LIMIT |
| `remark` | str | ❌ | 订单备注 |
| `trigger_price` | float | ❌ | 触发价格（条件单止损） |
| `trailing_percent` | float | ❌ | 跟踪止损百分比（如 5 表示 5%） |
| `trailing_amount` | float | ❌ | 跟踪止损金额 |

#### 止盈止损说明

**1. 固定止损（trigger_price）**
- 当市场价格触及设定的触发价格时，订单被触发
- 适用场景：设置固定的止损点位

```python
# 示例：买入价 $5，止损价 $3
order = broker.submit_option_order(
    symbol="AAPL260202C252500.US",
    side="BUY",
    quantity=1,
    price=5.0,
    trigger_price=3.0  # 价格跌到 $3 时止损
)
```

**2. 跟踪止损（trailing_percent / trailing_amount）**
- 跟踪市场价格变动，自动调整止损点位
- 适用场景：锁定利润，控制回撤

```python
# 示例：跟踪止损 5%
order = broker.submit_option_order(
    symbol="AAPL260202C252500.US",
    side="BUY",
    quantity=1,
    price=5.0,
    trailing_percent=5.0  # 从最高价回撤 5% 时止损
)
```

### 2. 订单撤销

撤销未成交或部分成交的订单。

```python
result = broker.cancel_order(order_id="1202576179308015616")
```

#### 返回值

```python
{
    "order_id": "1202576179308015616",
    "status": "cancelled",
    "cancelled_at": "2026-02-01T19:28:27.287",
    "mode": "paper"  # paper（模拟）或 real（真实）
}
```

#### 注意事项

- 只能撤销未成交或部分成交的订单
- 已成交的订单无法撤销
- 撤销操作不可逆

### 3. 订单修改

修改未成交订单的价格和数量。

```python
result = broker.replace_order(
    order_id="1202576179308015616",
    quantity=2,              # 新数量
    price=4.50,              # 新价格
    trigger_price=2.5,       # 新的止损触发价（可选）
    trailing_percent=10.0,   # 新的跟踪止损百分比（可选）
    remark="修改后的订单"
)
```

#### 参数说明

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `order_id` | str | ✅ | 要修改的订单ID |
| `quantity` | int | ✅ | 新的数量 |
| `price` | float | ❌ | 新的价格（限价单） |
| `trigger_price` | float | ❌ | 新的触发价格 |
| `trailing_percent` | float | ❌ | 新的跟踪止损百分比 |
| `trailing_amount` | float | ❌ | 新的跟踪止损金额 |
| `remark` | str | ❌ | 新的订单备注 |

#### 返回值

```python
{
    "order_id": "1202576179308015616",
    "quantity": 2,
    "price": 4.5,
    "status": "replaced",
    "replaced_at": "2026-02-01T19:28:25.053",
    "mode": "paper"
}
```

#### 注意事项

- 只能修改未成交或部分成交的订单
- 修改会取消原订单并创建新订单
- 新订单的排队优先级会重新计算

## 完整使用示例

### 示例1：带固定止损的买入订单

```python
from broker import LongPortBroker, load_longport_config

# 初始化
config = load_longport_config()
broker = LongPortBroker(config)

# 提交带止损的订单
order = broker.submit_option_order(
    symbol="AAPL260207C250000.US",
    side="BUY",
    quantity=2,
    price=5.0,
    trigger_price=3.0,  # 止损价 $3
    remark="买入 AAPL Call，止损 $3"
)

print(f"订单ID: {order['order_id']}")
```

### 示例2：带跟踪止损的买入订单

```python
# 提交跟踪止损订单
order = broker.submit_option_order(
    symbol="AAPL260207C250000.US",
    side="BUY",
    quantity=2,
    price=5.0,
    trailing_percent=10.0,  # 跟踪止损 10%
    remark="买入 AAPL Call，跟踪止损 10%"
)

print(f"订单ID: {order['order_id']}")
```

### 示例3：修改订单

```python
# 修改价格和数量
result = broker.replace_order(
    order_id=order['order_id'],
    quantity=3,        # 从 2 张改为 3 张
    price=4.5,         # 从 $5 改为 $4.5
    remark="调整价格和数量"
)

print(f"订单修改成功: 新数量 {result['quantity']}, 新价格 ${result['price']}")
```

### 示例4：撤销订单

```python
# 撤销订单
result = broker.cancel_order(order['order_id'])
print(f"订单已撤销: {result['order_id']}")
```

### 示例5：完整的交易流程

```python
from broker import LongPortBroker, load_longport_config
import time

# 1. 初始化
config = load_longport_config()
broker = LongPortBroker(config)

# 2. 获取期权链，选择合适的期权
expiry_dates = broker.get_option_expiry_dates("AAPL.US")
option_chain = broker.get_option_chain_info("AAPL.US", expiry_dates[1])

# 选择接近平值的期权
mid_idx = len(option_chain["strike_prices"]) // 2
symbol = option_chain["call_symbols"][mid_idx]
strike = option_chain["strike_prices"][mid_idx]

print(f"选择期权: {symbol}, 行权价: ${strike:.2f}")

# 3. 提交带止损的订单
order = broker.submit_option_order(
    symbol=symbol,
    side="BUY",
    quantity=2,
    price=5.0,
    trigger_price=3.0,  # 止损价
    remark="带止损的买入订单"
)

print(f"订单提交成功: {order['order_id']}")

# 4. 等待一段时间后检查订单状态
time.sleep(2)
orders = broker.get_today_orders()
target_order = next((o for o in orders if o['order_id'] == order['order_id']), None)

if target_order:
    print(f"订单状态: {target_order['status']}")
    
    # 5. 如果订单未成交，可以修改价格
    if target_order['status'] not in ['filled', 'cancelled']:
        result = broker.replace_order(
            order_id=order['order_id'],
            quantity=2,
            price=4.8,  # 调整价格
            remark="价格调整"
        )
        print(f"订单已修改: 新价格 ${result['price']}")
        
        # 6. 或者直接撤销
        # result = broker.cancel_order(order['order_id'])
        # print(f"订单已撤销")
```

## 风险控制

系统集成了风险控制模块，所有订单都会经过风险检查：

1. **最小下单金额检查**：默认 $100
2. **单仓位上限检查**：默认不超过总资金的 20%
3. **每日止损检查**：默认不超过总资金的 20%

风险参数可在 `.env` 文件中配置：

```bash
LONGPORT_MAX_POSITION_RATIO=0.20  # 单仓位上限 20%
LONGPORT_MAX_DAILY_LOSS=0.20      # 每日止损 20%
LONGPORT_MIN_ORDER_AMOUNT=100     # 最小下单金额 $100
```

## 测试

运行订单管理功能测试：

```bash
cd /Users/txink/Documents/code/playwright
PYTHONPATH=$(pwd) python3 test/broker/test_order_management.py
```

测试包括：
- ✅ 带止损价格的限价订单
- ✅ 跟踪止损订单
- ✅ 订单修改（价格和数量）
- ✅ 订单撤销
- ✅ 订单详情查询

## 常见问题

### Q1: 订单修改失败怎么办？

**A**: 订单修改失败可能是因为：
- 订单已成交
- 订单已被撤销
- 修改参数不合法

建议先查询订单状态，确认订单处于可修改状态。

### Q2: 止损订单什么时候触发？

**A**: 
- **固定止损**：当市场价格达到或穿过触发价格时触发
- **跟踪止损**：当价格从最高点回撤指定百分比或金额时触发

### Q3: 可以同时设置多个止损吗？

**A**: 不建议同时设置 `trigger_price` 和 `trailing_percent`，选择其中一种即可。

### Q4: 撤销订单后可以恢复吗？

**A**: 不可以。订单撤销操作不可逆，需要重新下单。

### Q5: 模拟账户和真实账户的区别？

**A**: 
- **模拟账户**（Paper Trading）：用于测试，不会产生真实交易
- **真实账户**：会产生真实交易，需谨慎操作

通过 `.env` 文件中的 `LONGPORT_MODE` 配置切换：
```bash
LONGPORT_MODE=paper  # 模拟账户
LONGPORT_MODE=real   # 真实账户
```

## 更新日志

### 2026-02-01
- ✅ 新增订单撤销功能 `cancel_order()`
- ✅ 新增订单修改功能 `replace_order()`
- ✅ 订单支持止损价格 `trigger_price`
- ✅ 订单支持跟踪止损 `trailing_percent` / `trailing_amount`
- ✅ 完整的测试套件验证

## 相关文档

- [长桥 OpenAPI 官方文档](https://open.longportapp.com/docs)
- [期权链查询功能](./option_chain.md)
- [风险控制配置](./risk_control.md)
