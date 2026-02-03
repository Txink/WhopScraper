# 自动交易功能文档

## 概述

自动交易模块（`AutoTrader`）将消息parser处理后的期权交易指令自动转化为broker接口调用，实现完全自动化的下单流程。

## 功能特性

- ✅ 自动买入：根据账户余额和配置上限智能计算买入数量
- ✅ 自动卖出：支持按比例卖出（相对初始买入量）
- ✅ 自动清仓：一键清空持仓
- ✅ 止盈止损：自动检测并执行止盈止损条件
- ✅ 风险控制：总价上限、余额检查、持仓验证
- ✅ 确认模式：可选的控制台确认机制
- ✅ 批量执行：支持批量处理多条指令

## 架构设计

```
消息 → Parser → OptionInstruction → AutoTrader → LongPortBroker → 交易所
```

### 核心模块

- `broker/auto_trader.py` - 自动交易执行器
- `models/instruction.py` - 指令数据模型
- `parser/option_parser.py` - 消息解析器
- `broker/longport_broker.py` - 长桥交易接口

## 交易规则

### 1. 买入规则

#### 总价上限计算

```python
# 1. 获取配置的总价上限（从环境变量）
max_configured = MAX_OPTION_TOTAL_PRICE  # 默认 $10,000

# 2. 获取账户可用余额
available_cash = broker.get_account_balance()['available_cash']

# 3. 取两者较小值作为实际上限
max_total_price = min(max_configured, available_cash)
```

#### 数量计算

```python
# 单张合约价格（期权每张=100股）
single_contract_price = price * 100

# 最大可买数量
max_quantity = int(max_total_price / single_contract_price)

# 根据仓位大小调整
if position_size == "小仓位":
    quantity = min(POSITION_SIZE_SMALL, max_quantity)
elif position_size == "中仓位":
    quantity = min(POSITION_SIZE_MEDIUM, max_quantity)
elif position_size == "大仓位":
    quantity = min(POSITION_SIZE_LARGE, max_quantity)
else:
    quantity = min(1, max_quantity)  # 默认1张
```

#### 确认模式

如果启用确认模式（`REQUIRE_CONFIRMATION=true`），系统会：
1. 显示订单详情
2. 等待控制台输入
3. 只有输入 `yes` 或 `y` 才会下单

### 2. 卖出规则

#### 比例计算（相对初始买入量）

```python
# 1. 查询历史买入订单，计算总买入量
total_buy_quantity = sum(已成交的买入订单数量)

# 2. 根据卖出比例计算
if sell_quantity == "1/3":
    quantity = int(total_buy_quantity * 1 / 3)
elif sell_quantity == "30%":
    quantity = int(total_buy_quantity * 0.30)
else:
    quantity = int(sell_quantity)  # 具体数量

# 3. 检查持仓限制
if quantity > available_quantity:
    quantity = available_quantity
```

#### 持仓检查

卖出前必须检查持仓：
- 无持仓 → 跳过
- 持仓不足 → 调整为可用数量
- 持仓充足 → 按计划卖出

### 3. 清仓规则

```python
# 1. 检查持仓
if not has_position(symbol):
    skip()  # 跳过，无持仓

# 2. 获取可用数量
available_quantity = get_available_quantity(symbol)

# 3. 全部卖出
sell(symbol, quantity=available_quantity)
```

### 4. 修改规则（止盈止损）

#### 检查流程

```python
# 1. 检查持仓
if not has_position(symbol):
    skip()  # 跳过

# 2. 获取当前价格
current_price = get_market_price(symbol)

# 3. 检查止损条件
if stop_loss_price and current_price <= stop_loss_price:
    close_immediately()  # 立即清仓

# 4. 检查止盈条件
if take_profit_price and current_price >= take_profit_price:
    close_immediately()  # 立即清仓

# 5. 如果未触发，修改未成交订单
if not triggered:
    modify_pending_orders()
```

## 配置说明

### 环境变量配置

在 `.env` 文件中配置：

```bash
# 单个期权总价上限（美元）
MAX_OPTION_TOTAL_PRICE=10000

# 是否需要控制台确认
REQUIRE_CONFIRMATION=false

# 价格偏差容忍度（百分比）
PRICE_DEVIATION_TOLERANCE=5

# 仓位大小配置（合约数量）
POSITION_SIZE_SMALL=1
POSITION_SIZE_MEDIUM=2
POSITION_SIZE_LARGE=5
```

### 配置项说明

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `MAX_OPTION_TOTAL_PRICE` | float | 10000 | 单个期权总价上限（美元） |
| `REQUIRE_CONFIRMATION` | bool | false | 是否需要控制台确认 |
| `PRICE_DEVIATION_TOLERANCE` | float | 5 | 价格偏差容忍度（百分比） |
| `POSITION_SIZE_SMALL` | int | 1 | 小仓位数量（合约） |
| `POSITION_SIZE_MEDIUM` | int | 2 | 中仓位数量（合约） |
| `POSITION_SIZE_LARGE` | int | 5 | 大仓位数量（合约） |

## 使用示例

### 示例1：执行单条买入指令

```python
from broker import LongPortBroker, load_longport_config, AutoTrader
from models.instruction import OptionInstruction, InstructionType

# 1. 初始化
config = load_longport_config()
broker = LongPortBroker(config)
trader = AutoTrader(broker)

# 2. 创建买入指令
instruction = OptionInstruction(
    instruction_type=InstructionType.BUY.value,
    ticker="AAPL",
    option_type="CALL",
    strike=250.0,
    expiry="2/7",
    price=5.0,
    position_size="小仓位",
    raw_message="AAPL 250c 2/7 5.0 小仓位"
)

# 3. 执行指令
result = trader.execute_instruction(instruction)
print(result)
```

### 示例2：执行卖出指令（卖出1/3）

```python
# 创建卖出指令
instruction = OptionInstruction(
    instruction_type=InstructionType.SELL.value,
    ticker="AAPL",
    option_type="CALL",
    strike=250.0,
    expiry="2/7",
    price=6.0,
    sell_quantity="1/3",  # 卖出1/3
    raw_message="AAPL 250c 2/7 6.0出1/3"
)

# 执行
result = trader.execute_instruction(instruction)
```

### 示例3：执行清仓指令

```python
# 创建清仓指令
instruction = OptionInstruction(
    instruction_type=InstructionType.CLOSE.value,
    ticker="AAPL",
    option_type="CALL",
    strike=250.0,
    expiry="2/7",
    price=7.0,
    raw_message="AAPL 250c 2/7 7.0清仓"
)

# 执行
result = trader.execute_instruction(instruction)
```

### 示例4：执行止盈止损指令

```python
# 创建修改指令
instruction = OptionInstruction(
    instruction_type=InstructionType.MODIFY.value,
    ticker="AAPL",
    option_type="CALL",
    strike=250.0,
    expiry="2/7",
    stop_loss_price=3.0,      # 止损价
    take_profit_price=10.0,   # 止盈价
    raw_message="AAPL 250c 2/7 止损3.0 止盈10.0"
)

# 执行
result = trader.execute_instruction(instruction)
```

### 示例5：批量执行指令

```python
# 创建多个指令
instructions = [
    OptionInstruction(
        instruction_type=InstructionType.BUY.value,
        ticker="AAPL",
        option_type="CALL",
        strike=250.0,
        expiry="2/7",
        price=5.0,
        position_size="小仓位",
        raw_message="AAPL 250c 2/7 5.0"
    ),
    OptionInstruction(
        instruction_type=InstructionType.BUY.value,
        ticker="TSLA",
        option_type="CALL",
        strike=440.0,
        expiry="2/9",
        price=3.1,
        position_size="中仓位",
        raw_message="TSLA 440c 2/9 3.1"
    )
]

# 批量执行
results = trader.execute_batch_instructions(instructions)

# 统计结果
success_count = sum(1 for r in results if r is not None)
print(f"成功: {success_count}/{len(instructions)}")
```

## 完整工作流

### 从消息到下单的完整流程

```python
import asyncio
from broker import LongPortBroker, load_longport_config, AutoTrader
from parser.option_parser import OptionParser
from parser.message_context_resolver import MessageContextResolver

async def auto_trade_from_messages(html_file: str):
    """从HTML消息文件自动交易"""
    
    # 1. 提取消息
    from scraper.message_extractor import EnhancedMessageExtractor
    from playwright.async_api import async_playwright
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        with open(html_file, 'r', encoding='utf-8') as f:
            html_content = f.read()
        await page.set_content(html_content)
        
        extractor = EnhancedMessageExtractor(page)
        raw_groups = await extractor.extract_message_groups()
        await browser.close()
    
    # 2. 解析消息
    all_messages = [group.to_simple_dict() for group in raw_groups]
    resolver = MessageContextResolver(all_messages)
    
    instructions = []
    for msg in all_messages:
        result = resolver.resolve_instruction(msg)
        if result:
            instruction, _, _ = result
            if instruction:
                instructions.append(instruction)
    
    print(f"成功解析 {len(instructions)} 条指令")
    
    # 3. 初始化交易器
    config = load_longport_config()
    broker = LongPortBroker(config)
    trader = AutoTrader(broker)
    
    # 4. 批量执行
    results = trader.execute_batch_instructions(instructions)
    
    # 5. 统计结果
    success_count = sum(1 for r in results if r is not None)
    print(f"执行完成: 成功 {success_count}/{len(instructions)}")

# 运行
asyncio.run(auto_trade_from_messages("debug/page_20260203_xxx.html"))
```

## 演示脚本

运行演示脚本查看各种交易场景：

```bash
python3 demo_auto_trading.py
```

演示包括：
1. 买入指令
2. 卖出指令（按比例）
3. 清仓指令
4. 修改指令（止盈止损）
5. 批量执行指令

## 风险控制

### 内置风险检查

1. **总价上限检查**
   - 单个期权总价不超过配置上限
   - 不超过账户可用余额

2. **持仓检查**
   - 卖出前检查是否有持仓
   - 卖出数量不超过可用持仓

3. **价格偏差检查**
   - 对比市场价格和目标价格
   - 偏差超过容忍度时给出警告

4. **确认机制**
   - 可选的控制台确认
   - 防止误操作

### 建议配置

#### 保守配置（适合新手）

```bash
MAX_OPTION_TOTAL_PRICE=5000          # 每个期权最多投入$5000
REQUIRE_CONFIRMATION=true             # 启用确认
PRICE_DEVIATION_TOLERANCE=3           # 价格偏差容忍度3%
POSITION_SIZE_SMALL=1                 # 小仓位1张
POSITION_SIZE_MEDIUM=1                # 中仓位1张
POSITION_SIZE_LARGE=2                 # 大仓位2张
```

#### 激进配置（适合有经验的交易者）

```bash
MAX_OPTION_TOTAL_PRICE=20000         # 每个期权最多投入$20000
REQUIRE_CONFIRMATION=false            # 关闭确认
PRICE_DEVIATION_TOLERANCE=10          # 价格偏差容忍度10%
POSITION_SIZE_SMALL=2                 # 小仓位2张
POSITION_SIZE_MEDIUM=5                # 中仓位5张
POSITION_SIZE_LARGE=10                # 大仓位10张
```

## 常见问题

### Q1: 买入数量为0怎么办？

**A**: 可能原因：
- 账户余额不足
- 配置的总价上限过低
- 期权单价过高

解决方案：
- 增加 `MAX_OPTION_TOTAL_PRICE`
- 充值账户余额
- 选择更便宜的期权

### Q2: 卖出比例如何计算？

**A**: 卖出比例相对**初始买入量**，而不是当前持仓：

```python
# 假设初始买入10张，已卖出3张，当前持仓7张
# 指令：卖出1/3

total_buy_quantity = 10  # 历史买入总量
sell_quantity = 10 * 1/3 = 3.33 ≈ 3  # 卖出3张

# 而不是：7 * 1/3 = 2.33 ≈ 2
```

### Q3: 止盈止损如何触发？

**A**: 触发条件：
- **止损**：当前价 <= 止损价 → 立即市价清仓
- **止盈**：当前价 >= 止盈价 → 立即市价清仓

### Q4: 如何关闭自动交易？

**A**: 在 `.env` 中设置：

```bash
LONGPORT_AUTO_TRADE=false
```

或者使用 `dry_run` 模式：

```bash
LONGPORT_DRY_RUN=true
```

### Q5: 如何测试而不真实下单？

**A**: 使用模拟账户：

```bash
LONGPORT_MODE=paper  # 模拟账户
```

或启用 dry_run：

```bash
LONGPORT_DRY_RUN=true  # 所有操作都只打印，不实际执行
```

## 最佳实践

### 1. 逐步启用

```bash
# 第1步：dry_run模式测试
LONGPORT_DRY_RUN=true
LONGPORT_MODE=paper

# 第2步：模拟账户 + 确认模式
LONGPORT_DRY_RUN=false
LONGPORT_MODE=paper
REQUIRE_CONFIRMATION=true

# 第3步：真实账户 + 确认模式
LONGPORT_MODE=real
REQUIRE_CONFIRMATION=true

# 第4步：真实账户 + 自动模式（谨慎！）
REQUIRE_CONFIRMATION=false
```

### 2. 监控日志

```python
import logging

# 启用详细日志
logging.basicConfig(level=logging.INFO)
```

### 3. 定期检查持仓

```python
# 定期检查持仓和订单
broker.show_account_info()
broker.show_positions()
broker.show_today_orders()
```

### 4. 设置合理的上限

```bash
# 根据账户总资金设置
# 建议：MAX_OPTION_TOTAL_PRICE ≤ 账户资金 * 10%
```

## 技术实现

### 核心类：AutoTrader

```python
class AutoTrader:
    def __init__(self, broker: LongPortBroker):
        """初始化自动交易执行器"""
        self.broker = broker
        # 加载配置...
    
    def execute_instruction(self, instruction: OptionInstruction) -> Optional[Dict]:
        """执行单条指令"""
        # 根据指令类型分发...
    
    def _execute_buy(self, instruction: OptionInstruction) -> Optional[Dict]:
        """执行买入"""
        # 1. 生成期权代码
        # 2. 计算买入数量
        # 3. 确认（如果需要）
        # 4. 提交订单
    
    def _execute_sell(self, instruction: OptionInstruction) -> Optional[Dict]:
        """执行卖出"""
        # 1. 检查持仓
        # 2. 计算卖出数量
        # 3. 提交订单
    
    def _execute_close(self, instruction: OptionInstruction) -> Optional[Dict]:
        """执行清仓"""
        # 1. 检查持仓
        # 2. 卖出全部
    
    def _execute_modify(self, instruction: OptionInstruction) -> Optional[Dict]:
        """执行修改（止盈止损）"""
        # 1. 检查持仓
        # 2. 获取当前价格
        # 3. 检查是否触发
        # 4. 修改订单或清仓
```

## 更新日志

### 2026-02-03
- ✅ 创建 `AutoTrader` 自动交易模块
- ✅ 实现买入、卖出、清仓、修改四种指令类型
- ✅ 支持总价上限、余额检查、持仓验证
- ✅ 支持确认模式和价格偏差检查
- ✅ 支持批量执行指令
- ✅ 创建演示脚本和完整文档

## 相关文档

- [订单管理功能](./order_management.md)
- [订单格式化输出](./order_format_guide.md)
- [消息解析指南](./analyze_local_messages_guide.md)
- [风险控制配置](../doc/RISK_CONTROL.md)
