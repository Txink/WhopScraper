# 期权 Symbol 格式修复

## 问题描述

买入 GOLD 期权时订单提交失败，错误信息：
```
OpenApiException: GOLD260220C060000.US security not found
```

## 根本原因

**Strike price 格式错误**：生成的 symbol 使用了 **6 位** strike code，而 LongPort API 要求 **5 位**。

### 错误格式（修复前）
```python
strike_code = f"{int(strike * 1000):06d}"  # 6位，例如：060000
symbol = "GOLD260220C060000.US"  # ❌ 错误
```

### 正确格式（修复后）
```python
strike_code = f"{int(strike * 1000):05d}"  # 5位，例如：60000
symbol = "GOLD260220C60000.US"   # ✅ 正确
```

## 示例对比

| Strike Price | 错误格式 (6位) | 正确格式 (5位) |
|-------------|---------------|---------------|
| $60.0 | `060000` | `60000` |
| $17.5 | `017500` | `17500` |
| $150.0 | `150000` | `150000` |

## 验证

### 从 LongPort API 查询期权链
```bash
GOLD 2026-02-20 Call 期权：
- GOLD260220C17500.US  ← $17.5 strike (5位)
- GOLD260220C60000.US  ← $60.0 strike (5位)
- GOLD260220C150000.US ← $150.0 strike (6位，但没有前导0)
```

### 测试结果
- ❌ 修复前：`GOLD260220C060000.US` → 无法获取报价（返回空列表）
- ✅ 修复后：`GOLD260220C60000.US` → 成功获取报价（$2.60）

## 修复的文件

1. **`models/instruction.py`**
   - `generate_option_symbol()` 方法
   - Strike 格式：`:06d` → `:05d`

2. **`broker/longport_broker.py`**
   - `convert_to_longport_symbol()` 函数
   - Strike 格式：`:06d` → `:05d`
   - 更新注释和文档

3. **`analyze_local_messages.py`**
   - Symbol 生成逻辑
   - Strike 格式：`:06d` → `:05d`

4. **`doc/LONGPORT_INTEGRATION_GUIDE.md`**
   - 更新代码示例

## 影响范围

此修复影响所有期权合约的 symbol 生成，包括：
- 买入订单
- 卖出订单
- 持仓查询
- 市场报价查询

## 后续建议

1. ✅ 添加单元测试验证 symbol 格式
2. ✅ 在提交订单前验证 symbol 是否能获取报价（已在 `auto_trader.py` 中实现）
3. 考虑添加 symbol 格式验证函数

## 测试命令

```bash
# 测试 symbol 生成
python3 -c "
from models.instruction import OptionInstruction
symbol = OptionInstruction.generate_option_symbol(
    ticker='GOLD', option_type='CALL', strike=60.0, 
    expiry='2/20', timestamp='2026-02-05 23:51:00.070'
)
print(f'Generated: {symbol}')
print(f'Expected:  GOLD260220C60000.US')
print(f'Match: {symbol == \"GOLD260220C60000.US\"} ✅' if symbol == 'GOLD260220C60000.US' else 'Match: False ❌')
"

# 测试报价查询
python3 -c "
from broker import load_longport_config, LongPortBroker
config = load_longport_config()
broker = LongPortBroker(config)
quotes = broker.get_option_quote(['GOLD260220C60000.US'])
print(f'✅ 成功获取报价' if quotes else '❌ 无法获取报价')
"
```

## 修复日期
2026-02-06
