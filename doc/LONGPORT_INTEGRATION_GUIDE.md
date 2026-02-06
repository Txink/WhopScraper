# 长桥 OpenAPI 接入指南

本指南将帮助您快速接入长桥（LongPort）OpenAPI，实现期权交易信号的自动化执行。

## 目录

- [前置准备](#前置准备)
- [快速开始](#快速开始)
- [核心功能实现](#核心功能实现)
- [完整示例](#完整示例)
- [常见问题](#常见问题)

---

## 前置准备

### 1. 开通长桥账户

1. 下载 **LongPort** App 并完成开户
2. 访问 [LongPort OpenAPI 官网](https://open.longportapp.com)
3. 登录后进入「个人中心」获取 API 凭证：
   - `App Key`
   - `App Secret`
   - `Access Token`

⚠️ **重要提示**：请妥善保管您的 Access Token，任何人获得它都可以操作您的账户！

### 2. 配置环境变量

#### 模拟账户 vs 真实账户

长桥提供了**模拟账户**（Paper Trading）和**真实账户**两种模式：

| 模式 | 说明 | 适用场景 |
|------|------|---------|
| **模拟账户** (paper) | 虚拟资金，订单不会真实执行 | 测试策略、学习交易、调试代码 |
| **真实账户** (real) | 真实资金，订单会实际成交 | 实盘交易 |

⚠️ **重要提示**：
- 建议先在**模拟账户**测试至少 2-4 周，验证策略有效性
- 模拟账户和真实账户使用不同的 API 凭证
- 切换账户只需修改环境变量 `LONGPORT_MODE`

#### 获取 API 凭证

**模拟账户凭证**：
1. 访问 [LongPort OpenAPI 官网](https://open.longportapp.com)
2. 登录后进入「个人中心」→「模拟交易」
3. 获取模拟账户的 `App Key`、`App Secret`、`Access Token`

**真实账户凭证**：
1. 同样在「个人中心」→「实盘交易」
2. 获取真实账户的 `App Key`、`App Secret`、`Access Token`

#### 配置 .env 文件

编辑 `.env` 文件，添加长桥 API 凭证：

```env
# ============================================================
# 长桥 OpenAPI 配置
# ============================================================

# 账户模式切换：paper（模拟账户）/ real（真实账户）
LONGPORT_MODE=paper

# 模拟账户配置（用于测试，不会真实交易）
LONGPORT_PAPER_APP_KEY=your_paper_app_key
LONGPORT_PAPER_APP_SECRET=your_paper_app_secret
LONGPORT_PAPER_ACCESS_TOKEN=your_paper_access_token

# 真实账户配置（实盘交易，请谨慎使用）
LONGPORT_REAL_APP_KEY=your_real_app_key
LONGPORT_REAL_APP_SECRET=your_real_app_secret
LONGPORT_REAL_ACCESS_TOKEN=your_real_access_token

# 通用配置
LONGPORT_REGION=cn  # cn=中国大陆，hk=香港
LONGPORT_ENABLE_OVERNIGHT=false  # 是否开启夜盘行情

# 风险控制配置
LONGPORT_MAX_POSITION_RATIO=0.20  # 单个持仓不超过 20%
LONGPORT_MAX_DAILY_LOSS=0.05  # 单日最大亏损 5%
LONGPORT_MIN_ORDER_AMOUNT=100  # 最小下单金额

# 交易设置
LONGPORT_AUTO_TRADE=false  # 是否启用自动交易
LONGPORT_DRY_RUN=true  # 模拟模式（仅打印日志）
```

#### 账户切换

**切换到模拟账户**：
```env
LONGPORT_MODE=paper
```

**切换到真实账户**：
```env
LONGPORT_MODE=real
LONGPORT_AUTO_TRADE=true  # 确认启用自动交易
LONGPORT_DRY_RUN=false  # 确认关闭模拟模式
```

### 3. 安装依赖

长桥 SDK 已在 `requirements.txt` 中配置，直接安装：

```bash
pip3 install -r requirements.txt
```

### 4. 行情权限配置

**交易前必须检查行情权限！**

- **港股**：需要 BMP 以上权限才能获得实时推送
- **美股**：需要 LV1 纳斯达克最优报价权限

在 LongPort App 中：「我的 → 我的行情 → 行情商城」购买开通。

---

## 快速开始

### API 接入点

| 服务类型 | 全球接入点 | 中国大陆接入点 |
|---------|-----------|--------------|
| HTTP API | `https://openapi.longportapp.com` | `https://openapi.longportapp.cn` |
| WebSocket 行情 | `wss://openapi-quote.longportapp.com` | `wss://openapi-quote.longportapp.cn` |
| WebSocket 交易 | `wss://openapi-trade.longportapp.com` | `wss://openapi-trade.longportapp.cn` |

通过设置环境变量 `LONGPORT_REGION=cn` 自动使用中国大陆接入点。

### 测试连接

#### 快速测试（推荐）

使用我们提供的完整测试脚本：

```bash
python3 test_longport_integration.py
```

这个脚本会自动测试：
- ✅ 配置加载（自动识别模拟/真实账户）
- ✅ 账户信息获取
- ✅ 期权代码转换
- ✅ 购买数量计算
- ✅ Dry Run 模式下单
- ✅ 订单查询
- ✅ 持仓查询

#### 手动测试

如果想单独测试某个功能，可以创建 `test_longport.py`：

```python
from broker import load_longport_config, LongPortBroker

# 自动加载配置（根据 LONGPORT_MODE 环境变量）
config = load_longport_config()

# 创建交易接口
broker = LongPortBroker(config)

# 获取账户信息
balance = broker.get_account_balance()
print(f"账户模式: {balance['mode']}")
print(f"总资金: {balance['total_cash']:,.2f} {balance['currency']}")
print(f"可用资金: {balance['available_cash']:,.2f}")
```

运行测试：

```bash
python3 test_longport.py
```

---

## 核心功能实现

### 0. 配置加载器

配置加载器 `broker/config_loader.py` 已经为您创建好了，它会自动：
- 根据 `LONGPORT_MODE` 切换模拟/真实账户
- 读取对应的 API 凭证
- 加载风险控制配置
- 验证配置完整性

使用示例：

```python
from broker import load_longport_config, LongPortConfigLoader

# 方式 1: 使用快捷函数（推荐）
config = load_longport_config()  # 自动从环境变量读取模式

# 方式 2: 手动指定模式
config = load_longport_config("paper")  # 强制使用模拟账户
config = load_longport_config("real")   # 强制使用真实账户

# 方式 3: 使用配置加载器对象（高级用法）
loader = LongPortConfigLoader()
config = loader.get_config()

# 检查当前模式
if loader.is_paper_mode():
    print("当前使用模拟账户")
elif loader.is_real_mode():
    print("当前使用真实账户")

# 检查交易设置
if loader.is_auto_trade_enabled():
    print("自动交易已启用")
if loader.is_dry_run():
    print("Dry Run 模式（不实际下单）")

# 打印配置摘要
loader.print_config_summary()
```

### 1. 期权下单模块

交易模块 `broker/longport_broker.py` 已经为您创建好了，包含以下功能：

**核心特性**：
- ✅ 自动识别模拟/真实账户
- ✅ Dry Run 模式（仅打印日志，不实际下单）
- ✅ 风险控制（仓位限制、止损限制）
- ✅ 期权代码自动转换
- ✅ 购买数量自动计算

使用示例：

```python
from decimal import Decimal
from typing import Dict, Optional
from longport.openapi import TradeContext, Config, OrderSide, OrderType, TimeInForceType
import logging

logger = logging.getLogger(__name__)


class LongPortBroker:
    """长桥证券交易接口"""
    
    def __init__(self, config: Config):
        self.ctx = TradeContext(config)
        self.positions: Dict[str, Dict] = {}  # 持仓跟踪
    
    def submit_option_order(
        self,
        symbol: str,
        side: str,  # "BUY" 或 "SELL"
        quantity: int,
        price: Optional[float] = None,
        order_type: str = "LIMIT"  # "LIMIT" 或 "MARKET"
    ) -> Dict:
        """
        提交期权订单
        
        Args:
            symbol: 期权代码，如 "AAPL250131C00150000.US"
            side: 买卖方向 BUY/SELL
            quantity: 数量（合约数）
            price: 限价单价格（市价单传 None）
            order_type: 订单类型 LIMIT/MARKET
        
        Returns:
            订单信息字典
        """
        try:
            # 转换买卖方向
            order_side = OrderSide.Buy if side.upper() == "BUY" else OrderSide.Sell
            
            # 转换订单类型
            if order_type.upper() == "MARKET":
                o_type = OrderType.MO
                submitted_price = None
            else:
                o_type = OrderType.LO
                if price is None:
                    raise ValueError("限价单必须提供价格")
                submitted_price = Decimal(str(price))
            
            # 提交订单
            resp = self.ctx.submit_order(
                side=order_side,
                symbol=symbol,
                order_type=o_type,
                submitted_price=submitted_price,
                submitted_quantity=quantity,
                time_in_force=TimeInForceType.Day,
                remark=f"Auto trade via OpenAPI"
            )
            
            order_info = {
                "order_id": resp.order_id,
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": float(price) if price else None,
                "status": "submitted"
            }
            
            logger.info(f"订单提交成功: {order_info}")
            return order_info
            
        except Exception as e:
            logger.error(f"订单提交失败: {e}")
            raise
    
    def get_today_orders(self) -> list:
        """获取当日订单"""
        try:
            orders = self.ctx.today_orders()
            return [
                {
                    "order_id": order.order_id,
                    "symbol": order.symbol,
                    "side": "BUY" if order.side == OrderSide.Buy else "SELL",
                    "quantity": order.quantity,
                    "executed_quantity": order.executed_quantity,
                    "price": float(order.price) if order.price else None,
                    "status": str(order.status),
                    "submitted_at": order.submitted_at.isoformat()
                }
                for order in orders
            ]
        except Exception as e:
            logger.error(f"获取订单失败: {e}")
            return []
    
    def cancel_order(self, order_id: str) -> bool:
        """撤销订单"""
        try:
            self.ctx.cancel_order(order_id)
            logger.info(f"订单已撤销: {order_id}")
            return True
        except Exception as e:
            logger.error(f"撤销订单失败: {e}")
            return False
    
    def get_positions(self) -> list:
        """获取持仓信息"""
        try:
            positions = self.ctx.stock_positions()
            return [
                {
                    "symbol": pos.symbol,
                    "quantity": pos.quantity,
                    "available_quantity": pos.available_quantity,
                    "cost_price": float(pos.cost_price),
                    "market_value": float(pos.market_value)
                }
                for pos in positions
            ]
        except Exception as e:
            logger.error(f"获取持仓失败: {e}")
            return []


def convert_to_longport_symbol(ticker: str, option_type: str, strike: float, expiry: str) -> str:
    """
    将期权信息转换为长桥期权代码格式
    
    格式：TICKER + YYMMDD + C/P + 价格(6位，即行权价×1000)
    示例：AAPL250131C00150000.US 或 AAPL260206C110000.US
    
    Args:
        ticker: 股票代码，如 "AAPL"
        option_type: "CALL" 或 "PUT"
        strike: 行权价，如 150.0
        expiry: 到期日，如 "1/31" 或 "2025-01-31"
    
    Returns:
        长桥期权代码
    """
    from datetime import datetime
    
    # 解析到期日
    if "/" in expiry:
        # 格式：1/31
        month, day = expiry.split("/")
        year = datetime.now().year
        if int(month) < datetime.now().month:
            year += 1
        expiry_date = f"{year}{int(month):02d}{int(day):02d}"
    else:
        # 假设格式：2025-01-31
        expiry_date = expiry.replace("-", "")[-6:]  # YYMMDD
    
    # 期权类型
    opt_type = "C" if option_type.upper() == "CALL" else "P"
    
    # 行权价格式化（5位数字，与长桥 API 返回格式一致）
    # 例如：60.0 → 60000, 17.5 → 17500
    strike_str = f"{int(strike * 1000):05d}"
    
    # 组合期权代码
    symbol = f"{ticker}{expiry_date}{opt_type}{strike_str}.US"
    
    return symbol
```

### 1.5 正股交易模块

除了期权交易，`broker/longport_broker.py` 还提供完整的正股交易功能：

**核心特性**：
- ✅ 正股实时报价查询
- ✅ 正股订单提交（限价单、市价单）
- ✅ 自动市场后缀处理（.US、.HK）
- ✅ 市价单智能风险检查
- ✅ 支持止盈止损参数

#### 1.5.1 获取正股报价

```python
# 获取单个股票报价
quotes = broker.get_stock_quote(["AAPL.US"])
quote = quotes[0]

print(f"股票代码: {quote['symbol']}")
print(f"最新价: ${quote['last_done']:.2f}")
print(f"开盘价: ${quote['open']:.2f}")
print(f"最高价: ${quote['high']:.2f}")
print(f"最低价: ${quote['low']:.2f}")
print(f"成交量: {quote['volume']:,}")
print(f"成交额: ${quote['turnover']:,.0f}")

# 获取多个股票报价
symbols = ["AAPL.US", "TSLA.US", "NVDA.US"]
quotes = broker.get_stock_quote(symbols)

for quote in quotes:
    prev_close = quote.get('prev_close', 0)
    if prev_close > 0:
        change_pct = ((quote['last_done'] - prev_close) / prev_close) * 100
        print(f"{quote['symbol']}: ${quote['last_done']:.2f} ({change_pct:+.2f}%)")
```

#### 1.5.2 提交正股订单

```python
# 限价单 - 买入
order = broker.submit_stock_order(
    symbol="AAPL.US",
    side="BUY",          # BUY 或 SELL
    quantity=100,        # 股数
    price=250.00,        # 限价
    order_type="LIMIT",
    remark="买入苹果股票"
)

# 限价单 - 卖出（会自动检查持仓）
order = broker.submit_stock_order(
    symbol="AAPL.US",
    side="SELL",         # 卖出前会自动检查持仓数量
    quantity=50,         # 如果持仓不足50股，订单会被拒绝
    price=260.00,
    order_type="LIMIT",
    remark="卖出苹果股票"
)

# 市价单
order = broker.submit_stock_order(
    symbol="TSLA.US",
    side="BUY",
    quantity=50,
    order_type="MARKET",  # 市价单会自动获取当前价格进行风险检查
    remark="市价买入特斯拉"
)

# 带止盈止损的订单
order = broker.submit_stock_order(
    symbol="NVDA.US",
    side="BUY",
    quantity=20,
    price=190.00,
    trigger_price=200.00,        # 触发价格
    trailing_percent=5.0,         # 跟踪止损 5%
    remark="买入英伟达（带止损）"
)
```

**⚠️ 重要提示：卖出订单的持仓检查**

从 v2.5.2 开始，所有卖出订单（`side="SELL"`）会自动进行持仓检查：

1. **无持仓检查**：如果没有该股票/期权的持仓，订单会被拒绝
2. **数量检查**：如果卖出数量超过可用持仓，订单会被拒绝
3. **错误提示**：会显示详细的错误信息，如"可用持仓仅 30 股"

```python
# 示例：卖出检查失败的情况
try:
    order = broker.submit_stock_order(
        symbol="AAPL.US",
        side="SELL",
        quantity=1000,  # 假设只有 100 股
        price=250.00,
        order_type="LIMIT"
    )
except ValueError as e:
    print(f"订单被拒绝: {e}")
    # 输出: "持仓不足: 无法卖出 1000 股 AAPL.US"
```

#### 1.5.3 正股 vs 期权订单的区别

| 项目 | 正股订单 | 期权订单 |
|------|---------|---------|
| 数量单位 | 股数 | 合约数 |
| 订单金额 | 价格 × 数量 | 价格 × 数量 × 100 |
| 函数名称 | `submit_stock_order()` | `submit_option_order()` |
| 代码格式 | `AAPL.US` | `AAPL260131C00150000.US` |
| 最小交易单位 | 1股 | 1张合约（100股） |

#### 1.5.4 集成测试

运行正股API集成测试：

```bash
# 测试正股交易API
PYTHONPATH=. python3 test/broker/test_stock_integration.py
```

测试内容包括：
- ✅ 配置加载
- ✅ 账户信息查询
- ✅ 多股票报价查询（AAPL, TSLA, NVDA, MSFT, GOOGL）
- ✅ 单股票详细报价
- ✅ 限价单提交（Dry Run）
- ✅ 市价单提交（Dry Run）
- ✅ 订单查询
- ✅ 持仓查询

### 2. 集成到主程序

编辑 `main.py`，添加长桥交易逻辑：

```python
from broker.longport_broker import LongPortBroker, convert_to_longport_symbol
from longport.openapi import Config
import logging

logger = logging.getLogger(__name__)


class OptionSignalMonitor:
    def __init__(self):
        # ... 原有初始化代码 ...
        
        # 初始化长桥交易接口
        try:
            longport_config = Config.from_env()
            self.broker = LongPortBroker(longport_config)
            logger.info("长桥交易接口初始化成功")
        except Exception as e:
            logger.error(f"长桥交易接口初始化失败: {e}")
            self.broker = None
    
    def _on_instruction(self, instruction: OptionInstruction):
        """处理解析后的指令"""
        logger.info(f"收到指令: {instruction.to_dict()}")
        
        # 保存到 JSON
        self._save_instruction(instruction)
        
        # 如果配置了长桥交易接口，执行交易
        if self.broker:
            try:
                self._execute_trade(instruction)
            except Exception as e:
                logger.error(f"执行交易失败: {e}")
    
    def _execute_trade(self, instruction: OptionInstruction):
        """执行交易"""
        if instruction.instruction_type == "OPEN":
            # 开仓
            symbol = convert_to_longport_symbol(
                ticker=instruction.ticker,
                option_type=instruction.option_type,
                strike=instruction.strike,
                expiry=instruction.expiry or "本周"
            )
            
            # 计算购买数量（由 MAX_OPTION_TOTAL_PRICE 与可用资金控制）
            balance = self.broker.get_account_balance()
            quantity = self._calculate_quantity(
                price=instruction.price,
                available_cash=balance.get('available_cash', 10000)
            )
            
            logger.info(f"准备开仓: {symbol}, 数量: {quantity}, 价格: {instruction.price}")
            
            order = self.broker.submit_option_order(
                symbol=symbol,
                side="BUY",
                quantity=quantity,
                price=instruction.price,
                order_type="LIMIT"
            )
            
            logger.info(f"开仓订单已提交: {order['order_id']}")
        
        elif instruction.instruction_type == "STOP_LOSS":
            # 止损：这里需要根据当前持仓设置止损单
            logger.info(f"设置止损: {instruction.price}")
            # TODO: 实现止损逻辑
        
        elif instruction.instruction_type == "TAKE_PROFIT":
            # 止盈：平仓部分持仓
            logger.info(f"止盈: 价格 {instruction.price}, 比例 {instruction.sell_ratio}")
            # TODO: 实现止盈逻辑
    
    def _calculate_quantity(self, price: float, available_cash: float) -> int:
        """
        根据 MAX_OPTION_TOTAL_PRICE 与可用资金计算合约数量。
        """
        import os
        max_total = float(os.getenv('MAX_OPTION_TOTAL_PRICE', '10000'))
        cap = min(max_total, available_cash)
        single_contract = price * 100
        if single_contract <= 0:
            return 1
        quantity = int(cap / single_contract)
        return max(1, quantity)
```

### 3. 创建 broker 目录

```bash
mkdir -p broker
touch broker/__init__.py
```

---

## 使用指南（已集成模块版本）

### 快速开始 3 步

所有核心模块已经为您创建好了，只需 3 步即可开始：

#### 第 1 步：配置环境变量

编辑 `.env` 文件：

```env
# 使用模拟账户测试
LONGPORT_MODE=paper
LONGPORT_PAPER_APP_KEY=你的模拟账户_APP_KEY
LONGPORT_PAPER_APP_SECRET=你的模拟账户_APP_SECRET
LONGPORT_PAPER_ACCESS_TOKEN=你的模拟账户_ACCESS_TOKEN

# 启用自动交易（模拟账户安全）
LONGPORT_AUTO_TRADE=true
LONGPORT_DRY_RUN=false  # 关闭 dry_run 以真正提交订单（模拟账户）
```

#### 第 2 步：运行集成测试

```bash
python3 test_longport_integration.py
```

查看输出，确保所有测试通过：
- ✅ 配置加载成功
- ✅ 账户信息正常
- ✅ 可以下单（模拟账户）

#### 第 3 步：集成到主程序

在 `main.py` 中使用：

```python
from broker import LongPortBroker, load_longport_config, convert_to_longport_symbol, calculate_quantity
from models.instruction import OptionInstruction
import logging

logger = logging.getLogger(__name__)


class OptionSignalMonitor:
    def __init__(self):
        # ... 原有初始化代码 ...
        
        # 初始化长桥交易接口（自动识别模拟/真实账户）
        try:
            config = load_longport_config()
            self.broker = LongPortBroker(config)
            logger.info("✅ 长桥交易接口初始化成功")
        except Exception as e:
            logger.error(f"❌ 长桥交易接口初始化失败: {e}")
            self.broker = None
    
    def _on_instruction(self, instruction: OptionInstruction):
        """处理解析后的指令"""
        logger.info(f"收到指令: {instruction.to_dict()}")
        
        # 保存到 JSON
        self._save_instruction(instruction)
        
        # 执行交易（如果配置了 broker）
        if self.broker:
            try:
                self._execute_trade(instruction)
            except Exception as e:
                logger.error(f"执行交易失败: {e}")
    
    def _execute_trade(self, instruction: OptionInstruction):
        """执行交易"""
        if instruction.instruction_type == "OPEN":
            # 转换期权代码
            symbol = convert_to_longport_symbol(
                ticker=instruction.ticker,
                option_type=instruction.option_type,
                strike=instruction.strike,
                expiry=instruction.expiry or "本周"
            )
            
            # 计算购买数量（由 MAX_OPTION_TOTAL_PRICE 与可用资金控制）
            balance = self.broker.get_account_balance()
            quantity = calculate_quantity(
                price=instruction.price,
                available_cash=balance.get('available_cash', 10000)
            )
            
            logger.info(f"准备开仓: {symbol}, 数量: {quantity}, 价格: {instruction.price}")
            
            # 提交订单
            order = self.broker.submit_option_order(
                symbol=symbol,
                side="BUY",
                quantity=quantity,
                price=instruction.price,
                order_type="LIMIT"
            )
            
            logger.info(f"✅ 订单已提交: {order['order_id']}")
        
        elif instruction.instruction_type == "STOP_LOSS":
            # TODO: 实现止损逻辑
            logger.info(f"设置止损: {instruction.price}")
        
        elif instruction.instruction_type == "TAKE_PROFIT":
            # TODO: 实现止盈逻辑
            logger.info(f"止盈: 价格 {instruction.price}, 比例 {instruction.sell_ratio}")
```

### 模式切换示例

#### 在模拟账户测试（推荐新手）

`.env` 配置：
```env
LONGPORT_MODE=paper
LONGPORT_AUTO_TRADE=true
LONGPORT_DRY_RUN=false
```

运行程序：
```bash
python3 main.py
```

#### 仅监控不交易

`.env` 配置：
```env
LONGPORT_AUTO_TRADE=false  # 关闭自动交易
```

#### 真实账户交易（谨慎！）

⚠️ **警告**：真实账户会使用真实资金！

`.env` 配置：
```env
LONGPORT_MODE=real  # 切换到真实账户
LONGPORT_REAL_APP_KEY=你的真实账户_APP_KEY
LONGPORT_REAL_APP_SECRET=你的真实账户_APP_SECRET
LONGPORT_REAL_ACCESS_TOKEN=你的真实账户_ACCESS_TOKEN

LONGPORT_AUTO_TRADE=true
LONGPORT_DRY_RUN=false

# 风险控制（建议保守设置）
LONGPORT_MAX_POSITION_RATIO=0.10  # 单笔不超过 10%
LONGPORT_MAX_DAILY_LOSS=0.03  # 单日止损 3%
```

### 测试工作流程

推荐的测试流程：

1. **配置模拟账户** → 2-4 周测试
2. **观察策略表现** → 盈利率、胜率、最大回撤
3. **优化参数** → 仓位管理、止损止盈
4. **小额实盘** → 使用少量资金验证
5. **逐步加仓** → 确认稳定后增加资金

## 完整示例

### 示例 1：自动监控并交易

```bash
# 启动监控程序（会自动执行交易）
python3 main.py
```

程序会：
1. 监控 Whop 页面获取交易信号
2. 解析期权指令
3. 自动通过长桥 API 下单交易

### 示例 2：只监控不交易

如果只想监控信号而不自动交易，可以在 `main.py` 中注释掉交易逻辑：

```python
def _on_instruction(self, instruction: OptionInstruction):
    logger.info(f"收到指令: {instruction.to_dict()}")
    self._save_instruction(instruction)
    
    # 注释掉自动交易
    # if self.broker:
    #     self._execute_trade(instruction)
```

### 示例 3：手动测试交易

创建 `test_trade.py` 测试交易功能：

```python
from broker.longport_broker import LongPortBroker, convert_to_longport_symbol
from longport.openapi import Config

# 初始化
config = Config.from_env()
broker = LongPortBroker(config)

# 转换期权代码
symbol = convert_to_longport_symbol(
    ticker="AAPL",
    option_type="CALL",
    strike=150.0,
    expiry="1/31"
)
print(f"期权代码: {symbol}")

# 提交测试订单（使用较低价格避免成交）
order = broker.submit_option_order(
    symbol=symbol,
    side="BUY",
    quantity=1,
    price=0.50,  # 低价测试
    order_type="LIMIT"
)
print(f"订单 ID: {order['order_id']}")

# 查看订单状态
orders = broker.get_today_orders()
for order in orders:
    print(order)

# 撤销订单
broker.cancel_order(order['order_id'])
```

---

## 高级功能

### 1. 订阅实时行情

创建 `longport_quote.py` 监控期权价格：

```python
from longport.openapi import QuoteContext, Config, SubType
from time import sleep

config = Config.from_env()
ctx = QuoteContext(config)

def on_quote(symbol: str, quote):
    print(f"{symbol} 最新价: {quote.last_done}")

ctx.set_on_quote(on_quote)

# 订阅期权行情
symbols = ["AAPL250131C00150000.US"]
ctx.subscribe(symbols, [SubType.Quote], True)

print("正在监控期权价格...")
sleep(60)  # 监控 60 秒
```

### 2. 风险控制

在 `broker/longport_broker.py` 中添加风险控制：

```python
class LongPortBroker:
    def __init__(self, config: Config):
        self.ctx = TradeContext(config)
        self.max_position_ratio = 0.20  # 单个持仓不超过 20%
        self.max_daily_loss = 0.05  # 单日最大亏损 5%
        self.daily_pnl = 0.0
    
    def check_risk_limits(self, invest_amount: float) -> bool:
        """检查风险限制"""
        balance = self.ctx.account_balance()
        total_cash = float(balance[0].total_cash)
        
        # 检查单笔投资是否超限
        if invest_amount > total_cash * self.max_position_ratio:
            logger.warning(f"单笔投资超限: {invest_amount} > {total_cash * self.max_position_ratio}")
            return False
        
        # 检查当日亏损是否超限
        if self.daily_pnl < -total_cash * self.max_daily_loss:
            logger.warning(f"当日亏损超限: {self.daily_pnl}")
            return False
        
        return True
```

### 3. 持仓跟踪

```python
class PositionTracker:
    """持仓跟踪器"""
    
    def __init__(self, broker: LongPortBroker):
        self.broker = broker
        self.positions = {}
    
    def update_positions(self):
        """更新持仓信息"""
        positions = self.broker.get_positions()
        for pos in positions:
            self.positions[pos['symbol']] = pos
    
    def get_position(self, symbol: str):
        """获取指定持仓"""
        return self.positions.get(symbol)
    
    def calculate_pnl(self, symbol: str) -> float:
        """计算盈亏"""
        pos = self.get_position(symbol)
        if not pos:
            return 0.0
        
        cost = pos['cost_price'] * pos['quantity']
        market_value = pos['market_value']
        return market_value - cost
```

---

## 常见问题

### Q1: 如何处理期权代码格式？

长桥期权代码格式：`TICKER + YYMMDD + C/P + 行权价(6位，即行权价×1000)`

示例：
- `AAPL250131C150000.US` = AAPL 2025年1月31日到期 行权价150的看涨期权
- `TSLA250207P250000.US` = TSLA 2025年2月7日到期 行权价250的看跌期权

使用 `convert_to_longport_symbol()` 函数自动转换。

### Q2: 如何测试不真实下单？

方法1：使用极低的价格限价单（不会成交）
```python
order = broker.submit_option_order(
    symbol=symbol,
    side="BUY",
    quantity=1,
    price=0.01,  # 极低价格
    order_type="LIMIT"
)
# 立即撤单
broker.cancel_order(order['order_id'])
```

方法2：使用模拟模式（在代码中添加 `dry_run` 参数）

### Q3: 如何处理网络异常？

添加重试机制：

```python
from tenacity import retry, stop_after_attempt, wait_exponential

class LongPortBroker:
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def submit_option_order(self, ...):
        # 订单提交逻辑
        pass
```

### Q4: 行情权限不足怎么办？

错误信息：`QuotePermissionDenied`

解决方法：
1. 打开 LongPort App
2. 进入「我的 → 我的行情 → 行情商城」
3. 购买对应市场的实时行情权限

### Q5: 如何查看 API 调用日志？

在代码中启用详细日志：

```python
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

### Q6: 订单状态说明

| 状态 | 说明 |
|------|------|
| NotReported | 待报 |
| ReplacedNotReported | 待报(改单) |
| PendingReplace | 已报待改 |
| Replaced | 已改 |
| PartialFilled | 部分成交 |
| Filled | 全部成交 |
| PendingCancel | 待撤 |
| Canceled | 已撤 |
| Rejected | 已拒绝 |
| Expired | 已过期 |

---

## 相关链接

- [LongPort OpenAPI 官网](https://open.longportapp.com)
- [Python SDK 文档](https://longportapp.github.io/openapi/python/)
- [API 参考文档](https://open.longportapp.com/zh-CN/docs)
- [LongPort App 下载](https://longportapp.com/download)

---

## 安全建议

1. **绝不**将 `ACCESS_TOKEN` 提交到代码仓库
2. 定期更换 API 密钥
3. 设置合理的风险控制参数
4. 小额测试后再使用实际资金
5. 监控账户异常活动

---

## 下一步

1. ✅ 完成长桥 API 配置
2. ✅ 测试连接和查询账户
3. ✅ 实现期权下单逻辑
4. ✅ 添加持仓管理
5. ✅ 实现止损/止盈自动化
6. ✅ 集成到主程序
7. ⬜ 添加实时行情监控（可选）
8. ⬜ 添加通知功能（邮件/短信/Telegram）

## 已完成功能 ✅

- ✅ 模拟账户和真实账户切换
- ✅ 自动期权下单
- ✅ 持仓跟踪和管理
- ✅ 自动止损止盈
- ✅ 移动止损
- ✅ 风险控制系统
- ✅ Dry Run 模式
- ✅ 完整日志记录
- ✅ 主程序集成

## 使用指南

现在您可以：

1. **运行完整测试**：
   ```bash
   python3 test_longport_integration.py
   python3 test_position_management.py
   ```

2. **启动自动交易系统**：
   ```bash
   python3 main.py
   ```

3. **查看详细使用指南**：
   - 完整指南：[USAGE_GUIDE.md](../USAGE_GUIDE.md)
   - 快速开始：[QUICKSTART_LONGPORT.md](./QUICKSTART_LONGPORT.md)

祝交易顺利！ 🚀
