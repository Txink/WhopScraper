# Parser层数据模型规范

## 📋 指令类型（InstructionType）

| 类型 | 说明 | 示例 |
|------|------|------|
| `BUY` | 买入 | 买入AAPL期权 |
| `SELL` | 卖出（部分） | 卖出持仓的1/3 |
| `CLOSE` | 清仓（全部卖出） | 全部卖出 |
| `MODIFY` | 修改止损/止盈 | 止损提高到$1.5 |
| `UNKNOWN` | 未识别 | - |

## 📦 数据模型（OptionInstruction）

### 通用字段
```python
timestamp: str           # 时间戳
raw_message: str        # 原始消息文本
instruction_type: str   # 指令类型（BUY/SELL/CLOSE/MODIFY）
ticker: str            # 期权代码（如 AAPL）
option_type: str       # 期权类型（CALL/PUT）
strike: float          # 行权价
expiry: str           # 到期日（如 "1/31", "2/20"）
message_id: str       # 消息唯一标识
```

### 买入指令（BUY）
```python
# 价格信息（支持单价或价格区间）
price: float                # 单价（如果是区间则为中间值）
price_range: [float, float] # 价格区间 [min, max]（可选）

# 示例1：单价
price = 1.5
price_range = None

# 示例2：价格区间 0.8-0.85
price = 0.825              # 中间值
price_range = [0.8, 0.85]  # 区间

# 仓位信息
position_size: str  # "小仓位", "中仓位", "大仓位"（由broker层决定具体数量）
```

### 卖出指令（SELL）
```python
# 价格信息（支持单价或价格区间）
price: float                # 单价（如果是区间则为中间值）
price_range: [float, float] # 价格区间 [min, max]（可选）

# 卖出数量
sell_quantity: str  # 支持以下格式：
                    # - "100"     具体股数
                    # - "1/3"     最初买入仓位的1/3
                    # - "1/2"     最初买入仓位的1/2
                    # - "2/3"     最初买入仓位的2/3
                    # - "30%"     最初买入仓位的30%
                    # 注意：比例是相对于最初买入仓位，不是当前持仓

# 示例
instruction_type = "SELL"
price = 1.75
sell_quantity = "1/3"  # 卖出最初买入仓位的1/3
```

### 清仓指令（CLOSE）
```python
# 价格信息（支持单价或价格区间）
price: float                # 单价（如果是区间则为中间值）
price_range: [float, float] # 价格区间 [min, max]（可选）

# 清仓指令不需要sell_quantity字段（隐含为100%）

# 示例
instruction_type = "CLOSE"
price = 2.3
price_range = None
```

### 修改指令（MODIFY）
```python
# 止损价格（支持单价或价格区间）
stop_loss_price: float           # 止损单价
stop_loss_range: [float, float]  # 止损价格区间 [min, max]（可选）

# 止盈价格（支持单价或价格区间）
take_profit_price: float          # 止盈单价
take_profit_range: [float, float] # 止盈价格区间 [min, max]（可选）

# 示例1：设置止损
instruction_type = "MODIFY"
stop_loss_price = 1.05
stop_loss_range = None

# 示例2：设置止损区间
instruction_type = "MODIFY"
stop_loss_price = 1.025         # 中间值
stop_loss_range = [1.0, 1.05]  # 区间
```

## 📊 解析示例

### 1. 买入指令
```
原始消息: "CMCSA 30c 2/20 0.83-0.85 小仓位日内交易"

解析结果:
{
  "instruction_type": "BUY",
  "ticker": "CMCSA",
  "option_type": "CALL",
  "strike": 30.0,
  "expiry": "2/20",
  "price": 0.84,              # 区间中间值
  "price_range": [0.83, 0.85], # 具体区间
  "position_size": "小仓位"
}
```

### 2. 卖出指令（部分）
```
原始消息: "1.75出三分之一"

解析结果:
{
  "instruction_type": "SELL",
  "price": 1.75,
  "price_range": None,
  "sell_quantity": "1/3"  # 最初买入仓位的1/3
}
```

### 3. 卖出指令（百分比）
```
原始消息: "2.45也在剩下减一半"

解析结果:
{
  "instruction_type": "SELL",
  "price": 2.45,
  "price_range": None,
  "sell_quantity": "1/2"  # 最初买入仓位的1/2
}
```

### 4. 清仓指令
```
原始消息: "2.3附近都出"

解析结果:
{
  "instruction_type": "CLOSE",
  "price": 2.3,
  "price_range": None
}
```

### 5. 修改指令（止损）
```
原始消息: "止损提高到1.5"

解析结果:
{
  "instruction_type": "MODIFY",
  "stop_loss_price": 1.5,
  "stop_loss_range": None
}
```

## 🔄 Parser与Broker层职责分工

### Parser层职责
- ✅ 解析消息文本，提取结构化数据
- ✅ 识别指令类型（买入/卖出/清仓/修改）
- ✅ 提取期权信息（ticker, strike, expiry, option_type）
- ✅ 解析价格（单价或区间）
- ✅ 解析卖出数量格式（比例、百分比、具体数量）
- ✅ 转换相对日期为具体日期

### Broker层职责
- ⚠️ 根据position_size确定具体买入数量
- ⚠️ 根据sell_quantity计算具体卖出数量（相对于最初买入仓位）
- ⚠️ 获取当前市场价格
- ⚠️ 验证价格是否在可接受范围内
- ⚠️ 选择价格区间内的最优价格
- ⚠️ 执行实际交易
- ⚠️ 管理持仓信息

## 📈 当前解析统计

- **总消息数**: 91条
- **成功解析**: 64条
- **解析失败**: 27条
- **成功率**: 70.3%

## ✅ 已支持的消息格式

### 买入格式
- `LYFT 19.5c 1/23 0.58-0.62 小仓位` ✅
- `CMCSA 30c 2/20 0.83-0.85 小仓位` ✅
- `MSFT 480c 1/23 2.70 日内小仓位` ✅
- `$EOSE call 本周 $18 0.5` ✅
- `IREN $58 calls 1月23 1.10` ✅

### 卖出格式
- `1.75出三分之一` → SELL, quantity=1/3 ✅
- `2.6出一半` → SELL, quantity=1/2 ✅
- `0.92出剩下的` → CLOSE ✅
- `2.3附近都出` → CLOSE ✅
- `2.45也在剩下减一半` → SELL, quantity=1/2 ✅
- `4.75 amd全出` → CLOSE ✅

### 修改格式
- `止损 0.95` → MODIFY, stop_loss=0.95 ✅
- `止损提高到1.5` → MODIFY, stop_loss=1.5 ✅
- `止损设置上移到2.16` → MODIFY, stop_loss=2.16 ✅
