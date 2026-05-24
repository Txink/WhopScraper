# SPY 期权大单实时监听

## 概述

监听 **SPY** 期权大单，用于辅助观察指数趋势是否可能反转。支持三种数据源，**无需 Polygon 也可使用**：

| 数据源 | 说明 | 配置 |
|--------|------|--------|
| **yfinance**（默认） | 轮询 Yahoo 期权链，根据相邻两次成交量差值识别大单 | 无需配置 |
| **longport** | 轮询长桥期权报价（与主程序共用 LONGPORT_*），延迟通常小于 yfinance | 需 .env 中已配置 LONGPORT_PAPER_* 或 LONGPORT_REAL_*，且行情权限包含美股期权 |
| **polygon** | Polygon.io WebSocket 逐笔期权成交 | 需 POLYGON_API_KEY 且订阅 Options 数据 |

推荐：已有长桥行情时用 `--source longport`；无任何 Key 时用默认 yfinance；需实时的逐笔大单再选 polygon。

## 依赖与配置

### 1. 安装依赖

脚本依赖 `websockets`、`requests`、`yfinance`，已列入 `requirements.txt`：

```bash
pip install -r requirements.txt
```

### 2. 使用 yfinance（默认，无需 API Key）

直接运行即可，无需任何 Key：

```bash
python3 scripts/spy_options_flow_monitor.py
# 或显式指定
python3 scripts/spy_options_flow_monitor.py --source yfinance
```

### 3. 使用长桥（推荐，与主程序共用配置）

若已在 `.env` 中配置长桥（LONGPORT_PAPER_* 或 LONGPORT_REAL_*），且账户有美股期权行情权限，可直接用长桥轮询，通常比 yfinance 更及时：

```bash
python3 scripts/spy_options_flow_monitor.py --source longport
```

### 4. 使用 Polygon（可选，需 API Key）

在 [Polygon.io](https://polygon.io) 注册并获取 API Key，并订阅 **Options** 数据，通过参数传入：

```bash
python3 scripts/spy_options_flow_monitor.py --source polygon --polygon-api-key YOUR_KEY
```

### 5. 命令行参数

所有行为均通过命令行参数控制（不使用环境变量）：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--source` | 数据源：`yfinance` \| `longport` \| `polygon` | `yfinance` |
| `--polygon-api-key` | Polygon API Key（仅 `--source polygon` 时必填） | - |
| `--min-contracts` | 大单最小合约张数（仅 Polygon 逐笔模式生效） | 100 |
| `--min-premium` | 最小权利金（美元），**轮询模式只输出权利金≥此值的增量** | 50000 |
| `--expiry-days` | 只处理多少天内到期的 SPY 期权 | 45 |
| `--poll-interval` | yfinance/longport 轮询间隔（秒） | 60 |

轮询模式（yfinance/longport）下**仅按权利金过滤**：只输出「估算权利金 ≥ --min-premium」的成交量增量，避免仅因张数多就输出小额单。Polygon 逐笔模式仍按张数或权利金满足其一即输出。

**关于买/卖方向**：yfinance、longport 轮询模式只有「成交量增量」，无法区分是买入还是卖出；若需方向需使用 Polygon 等提供逐笔成交且带方向的数据源。  
**只看总价 100 万以上**：使用 `--min-premium 1000000`。

## 使用方式

在项目根目录执行：

```bash
# 默认 yfinance，无需 API Key
python3 scripts/spy_options_flow_monitor.py

# 只关注更大单、更近到期
python3 scripts/spy_options_flow_monitor.py --min-contracts 200 --min-premium 100000 --expiry-days 30

# 只看总价 100 万美元以上的大单
python3 scripts/spy_options_flow_monitor.py --min-premium 1000000

# Polygon（API Key 通过参数传入）
python3 scripts/spy_options_flow_monitor.py --source polygon --polygon-api-key YOUR_KEY

# 轮询间隔 30 秒
python3 scripts/spy_options_flow_monitor.py --source yfinance --poll-interval 30
```

## 输出说明

每行大单格式示例：

```
[大单] SPY 2025-03-21 C 600 | 张数=150 权利金≈$90,000 @ 6.00 | 14:32:05
```

（轮询模式下为「增量张数」与估算权利金；轮询无法区分该笔是买还是卖。）

含义：SPY、到期日、Call/Put、行权价；张数、权利金、价格、时间。

## 与趋势反转的关联

- **大量 Call 大单**：可能反映看涨预期或对冲空头，需结合价格与波动率判断。
- **大量 Put 大单**：可能反映看跌或对冲多头，可关注是否伴随指数拐头。
- 建议结合 SPY 价格、IV 以及大单的到期与行权分布综合判断，不作为唯一依据。

## 技术说明

- **yfinance**：轮询拉取 SPY 期权链（多到期日），对比相邻两次同一合约的 `volume`，增量达到阈值则输出；数据有延迟。
- **longport**：用长桥 `QuoteContext` 拉取 SPY 期权到期日与期权链，再轮询 `option_quote` 获取成交量，对比增量作为大单；与主程序共用长桥配置，单连接最多 500 个合约。
- **polygon**：REST 拉取 SPY 期权合约列表，WebSocket 订阅 `T.{合约}` 接收逐笔成交，本地按张数/权利金过滤后输出。
