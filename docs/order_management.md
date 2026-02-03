# 订单管理功能文档

## 概述

长桥期权交易系统现已支持完整的订单管理功能，包括：
1. 订单撤销
2. 订单修改
3. 止盈止损设置
4. 消息上下文自动补全

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

## 6. 消息上下文自动补全

### 功能说明

消息上下文自动补全功能可以智能地利用历史消息信息，自动补全卖出（SELL）、修改（MODIFY）、清仓（CLOSE）指令中缺失的期权详细信息（如股票代码、行权价、到期日等）。

这对于处理简短的交易指令特别有用，例如：
- "止损在2.9" → 自动补全为 TSLA $440 CALL 2/9，止损价 $2.9
- "3.1出三分之一" → 自动补全为 TSLA $440 CALL 2/9，卖出价 $3.1，数量 1/3

### 补全触发条件

系统会在以下情况下尝试自动补全：

1. **SELL/CLOSE/MODIFY 指令**缺少以下任一信息：
   - 股票代码（ticker）
   - 行权价（strike）
   - 到期日（expiry）

2. **BUY 指令**不会触发补全（因为买入信息通常完整）

### 查找策略

系统采用两种查找策略，根据指令中是否包含股票代码自动选择：

#### 积极策略（有股票代码但缺细节）

当指令中包含股票代码但缺少行权价或到期日时，使用积极策略：

1. **查找同组历史消息**（history 字段）
   - 优先查找匹配股票代码的 BUY 指令
   - 如果找不到，忽略股票代码再次查找（宽松匹配）

2. **查找引用消息**（refer 字段）
   - 解析引用的消息内容
   - 同样先精确匹配，失败后宽松匹配

3. **查找前N条消息**（全局消息列表）
   - 向前查找最多N条消息（N由环境变量`CONTEXT_SEARCH_LIMIT`配置，默认5）
   - 查找匹配股票代码的 BUY 指令

#### 保守策略（无股票代码）

当指令中完全不包含股票代码时，使用保守策略：

1. **查找同组历史消息**（history 字段）
   - 查找最近的 BUY 指令

2. **查找引用消息**（refer 字段）
   - 解析引用的消息内容

3. **查找前N条消息**（全局消息列表）
   - 查找最近的任意 BUY 指令
   - N由环境变量`CONTEXT_SEARCH_LIMIT`配置，默认5
   - 作为兜底策略，当 history 和 refer 都没有找到时使用

### 使用示例

#### 示例1：同组历史消息补全

```
消息1: TSLA 440c 2/9 3.1
消息2: 止损在2.9
```

系统会从消息组的历史中找到 TSLA 买入信息，自动补全为：
```python
{
  "ticker": "TSLA",
  "strike": 440,
  "option_type": "CALL",
  "expiry": "2/9",
  "stop_loss_price": 2.9
}
```

#### 示例2：引用消息补全

```
引用: GILD - $130 CALLS 这周 1.5-1.60
内容: 小仓位 止损 在 1.3
```

系统会解析引用消息，补全为：
```python
{
  "ticker": "GILD",
  "strike": 130,
  "option_type": "CALL",
  "expiry": "1/23",
  "stop_loss_price": 1.3
}
```

#### 示例3：前序消息补全

```
消息1: NVDA 145c 2/7 2.5
消息2: AMD 180c 2/14 3.0
消息3: 市场反弹
消息4: 2.8出一半nvda
```

系统会在前5条消息中找到 NVDA 买入信息，补全为：
```python
{
  "ticker": "NVDA",
  "strike": 145,
  "expiry": "2/7",
  "price": 2.8,
  "sell_quantity": "1/2"
}
```

### 技术实现

补全功能由 `MessageContextResolver` 类实现，位于 `parser/message_context_resolver.py`。

在 `analyze_local_messages.py` 中自动启用，无需额外配置。

### 输出增强

解析结果会显示上下文补全信息：

```
#15 SELL - TSLA
  时间: Jan 23, 2026 12:51 AM
  期权代码: TSLA
  指令类型: SELL
  行权价: $440
  到期日: 2/9
  价格: $3.1
  卖出数量: 1/3
  🔗 上下文来源: history
  🔗 上下文消息: TSLA 440c 2/9 3.1
  原始消息: 3.1出三分之一tsla
```

上下文来源包括：
- `history` - 从同组历史消息补全
- `refer` - 从引用消息补全
- `前5条` - 从前序消息补全
- `无` - 未使用上下文（信息完整或无法补全）

### 统计信息

解析统计会显示上下文使用情况：

```
📊 解析统计
总消息数: 150 | 成功: 128 | 失败: 22 | 成功率: 85.3%
🔗 使用上下文补全: 45 (35.2% 的成功解析)
```

### 注意事项

1. **股票代码优先级**：如果消息中明确指定了股票代码，系统会保留该代码，即使与上下文不同
2. **只补全 BUY 指令**：系统只从 BUY（买入）指令中提取上下文，SELL/MODIFY 指令不作为上下文源
3. **时间戳支持**：系统会正确处理相对日期（如"本周"、"下周"），使用消息时间戳计算具体日期
4. **宽松匹配**：当精确匹配股票代码失败时，系统会尝试忽略股票代码进行宽松匹配（仅在积极策略中）

### 测试验证

完整的测试套件位于 `test_context_resolver.py`，包含以下测试用例：
- 有股票名但缺细节的补全
- 无股票名的补全
- 通过引用消息补全
- 前5条消息查找
- 实际消息场景测试

运行测试：
```bash
python3 test_context_resolver.py
```

## 相关文档

- [长桥 OpenAPI 官方文档](https://open.longportapp.com/docs)
- [期权链查询功能](./option_chain.md)
- [风险控制配置](./risk_control.md)
- [消息输出格式说明](./message_output_format.md)
