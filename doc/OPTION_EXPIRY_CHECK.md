# 期权过期时间校验

## 功能概述

为了防止交易已经过期的期权合约，系统在期权代码转换阶段自动检查到期日期。如果期权已过期，系统将拒绝处理该指令，并记录警告日志。

## 工作原理

### 1. 校验时机

期权过期检查在 `convert_to_longport_symbol()` 函数中执行，该函数负责将期权信息转换为长桥期权代码格式。

### 2. 校验逻辑

```python
# 解析到期日
expiry_date = datetime(year, month, day)

# 检查是否过期（到期日的 23:59:59 与当前时间比较）
expiry_end_of_day = expiry_date.replace(hour=23, minute=59, second=59)
if now > expiry_end_of_day:
    raise ValueError(f"期权已过期: 到期日 {expiry_date} 早于当前日期 {now}")
```

### 3. 异常处理

在主程序的 `_handle_open_position()` 方法中捕获 `ValueError` 异常：

```python
try:
    symbol = convert_to_longport_symbol(
        ticker=instruction.ticker,
        option_type=instruction.option_type,
        strike=instruction.strike,
        expiry=instruction.expiry or "本周"
    )
except ValueError as e:
    logger.error(f"❌ 期权代码转换失败: {e}")
    logger.warning(f"⚠️  跳过开仓指令 - {instruction.raw_message}")
    return  # 直接返回，不执行后续下单操作
```

## 支持的日期格式

系统支持以下日期格式：

1. **月/日格式**：`1/31`、`01/31`
2. **完整日期**：`20260131`、`2026-01-31`
3. **中文表达**：`本周`（自动计算到本周五）

## 示例场景

### 场景 1: 已过期期权

```python
# 假设今天是 2026-01-30
message = "AAPL - $150 CALLS 1/29 $2.5"  # 昨天已过期

# 系统输出:
# ERROR - 期权代码转换失败: 期权已过期: 到期日 2026-01-29 早于当前日期 2026-01-30
# WARNING - ⚠️  跳过开仓指令 - AAPL - $150 CALLS 1/29 $2.5
# 不会执行下单操作
```

### 场景 2: 有效期权

```python
# 假设今天是 2026-01-30
message = "TSLA - $250 PUTS 2/6 $3.0"  # 未来日期

# 系统输出:
# INFO - 期权代码: TSLA260206P00250000.US
# INFO - 计划购买: 24 张 @ $3.0
# 继续执行下单操作
```

### 场景 3: 当天到期

```python
# 假设今天是 2026-01-30
message = "NVDA - $900 CALLS 1/30 $5.0"  # 今天到期

# 系统输出:
# INFO - 期权代码: NVDA260130C00900000.US
# 继续执行（今天到期的期权在 23:59:59 前仍然有效）
```

## 测试

运行测试验证功能：

```bash
# 基础测试
python3 test_option_expiry.py

# 集成测试
python3 test_expiry_integration.py
```

## 日志示例

### 正常情况（有效期权）
```
2026-01-30 20:00:00 - INFO - 🔵 处理开仓指令: AAPL CALL 150.0
2026-01-30 20:00:00 - INFO - 期权代码: AAPL260206C00150000.US
2026-01-30 20:00:00 - INFO - 计划购买: 24 张 @ $2.5
```

### 异常情况（已过期）
```
2026-01-30 20:00:00 - INFO - 🔵 处理开仓指令: AAPL CALL 150.0
2026-01-30 20:00:00 - ERROR - ❌ 期权代码转换失败: 期权已过期: 到期日 2026-01-29 早于当前日期 2026-01-30 20:00:00
2026-01-30 20:00:00 - WARNING - ⚠️  跳过开仓指令 - AAPL - $150 CALLS 1/29 $2.5
```

## 优势

1. **自动防护**：无需人工干预，系统自动拦截过期期权
2. **及时发现**：在下单前就发现问题，避免API调用失败
3. **清晰日志**：详细的错误信息帮助快速定位问题
4. **不影响其他**：只拒绝当前指令，不影响后续有效指令的处理

## 技术细节

### 时间比较

- 使用到期日的 `23:59:59` 作为截止时间
- 当前时间大于截止时间则判定为过期
- 今天到期的期权在当天内仍然有效

### 异常抛出

```python
raise ValueError(
    f"期权已过期: 到期日 {expiry_date.strftime('%Y-%m-%d')} "
    f"早于当前日期 {now.strftime('%Y-%m-%d %H:%M:%S')}"
)
```

### 错误处理流程

1. `convert_to_longport_symbol()` 抛出 `ValueError`
2. `_handle_open_position()` 捕获异常
3. 记录错误和警告日志
4. 直接返回，不执行后续的账户查询、数量计算、下单等操作

## 相关文件

- `broker/longport_broker.py` - 期权代码转换和过期检查
- `main.py` - 主程序异常处理
- `test_option_expiry.py` - 基础功能测试
- `test_expiry_integration.py` - 集成测试

## 更新日志

- **2026-01-30**: 初始实现，支持多种日期格式的过期检查
