# 股票页监控与关注列表

## 概述

除期权页面外，程序支持监控「正股页面」：使用独立的股票解析器将消息解析为 `StockInstruction`，仅对**关注列表**中的股票指令触发回调；期权与股票在模型、解析和监控流程上相互独立。

## 配置

- 在 `.env` 的 `PAGES` 中配置一项 `type: "stock"` 的页面，例如：
  ```json
  {
    "name": "正股页面",
    "url": "https://whop.com/joined/.../app/",
    "type": "stock"
  }
  ```
- 启动时选择「正股页面」后，将使用 `StockParser` 与 `StockContextResolver` 解析消息，并仅处理关注列表内的股票。

## 关注股票列表与仓位配置

- **路径**：`data/watched_stocks.json`（可通过环境变量 `WATCHED_STOCKS_PATH` 覆盖）。
- **格式**：按 ticker 配置总仓位**股数**与常规仓占比；常规仓 = position × bucket，常规仓的一半 = position × bucket × 0.5（具体股数）。
  ```json
  {
    "tsll": { "position": 2000, "bucket": 0.3 }
  }
  ```
  - `position`：该股票总仓位**股数**（整数）。
  - `bucket`：常规仓占比，如 `0.3` 表示常规仓 = 2000×0.3 = 600 股；常规一半 = 300 股。可选键 `regular_ratio` 同义，默认 1/3。
  可配置多个股票，键为 ticker 小写。
- **解析为具体股数**：如消息「常规仓的一半」「常规一半」会通过 `resolve_position_size_to_shares` 换算为整数股数（如 300），写入 `StockInstruction.quantity`。
- **实时生效**：列表在运行期间按文件 mtime 约 1 秒缓存，修改并保存文件后，下一次消息处理即使用新列表；无需重启程序。
- **未配置或为空**：视为不过滤，所有解析出的股票指令都会写入 record 并触发回调。

## 股票页消息抓取

股票页消息除操作指令外，常包含新闻分析、市场分析等，建议先抓取样本再调整解析规则。

### 独立脚本（推荐，参数控制、默认不依赖环境变量）

- **消息导出**：`scripts/scraper/export_page_message.py`  
  - 全屏打开浏览器，自动滚动抓取消息并导出到指定路径。  
  - 用法：`python3 scripts/scraper/export_page_message.py [--type stock|option] [--output PATH] [--url URL]`  
  - 默认：`--type stock`，`--output tmp/<type>/origin_message.json`；不传 `--url` 时从 `.env` 的 `PAGES` 中按 type 取首个页面。
- **HTML 导出**：`scripts/scraper/export_page_html.py`  
  - 打开目标页面，将当前 HTML 导出到指定路径。  
  - 用法：`python3 scripts/scraper/export_page_html.py [--type stock|option] [--output PATH] [--url URL]`  
  - 默认：`--type stock`，`--output tmp/<type>/page_html.html`。

### 原有抓取脚本（环境变量控制）

- **脚本**：`scripts/capture_stock_messages.py`
- **用法**：在项目根目录执行  
  `python3 scripts/capture_stock_messages.py`  
  **默认（自动历史分页）**：脚本有界面打开页面后，自动将消息区滚动到顶部以触发「上一页」加载，每轮加载后立即提取并按 domID 去重保存（避免 DOM 回收导致丢失），直到连续 2 轮无新消息或达到最大轮数后结束。环境变量 `AUTO_SCROLL_HISTORY=false` 可改为定时抓取模式（需手动滚动，Ctrl+C 结束）。`SCROLL_TOP_WAIT_MS`、`MAX_HISTORY_ROUNDS`、`CAPTURE_INTERVAL_SEC` 见脚本注释。
- **流程（自动模式）**：有界面打开 → 登录（如需）→ 导航到股票页 → 循环：滚动到顶部 → 等待 → 提取并去重保存 → 无新消息则结束。
- **后续**：查看 `data/stock_origin_message.json` 或自定义导出路径中的内容结构，在 `parser/stock_parser.py` 中补充或调整正则，使仅操作类指令被解析为 `StockInstruction`。

### 导出 HTML 与分析页面结构（用于调试自动滚动）

若自动历史分页不触发加载，可导出当前页 HTML 并分析滚动容器：

1. 导出：`python3 scripts/scraper/export_page_html.py --type stock`（默认保存到 `tmp/stock/page_html.html`），或 `python3 scripts/capture_stock_messages.py --export-html`（保存到 `test/data/stock_html.html`）。
2. 分析：`python3 scripts/analyze_stock_html.py`，输出第一个 `[data-message-id]` 的祖先链、可能可滚动的节点、以及推荐滚动方式。抓取脚本默认在滚动容器上**模拟鼠标滚轮向上**（`USE_WHEEL_SCROLL=true`）以触发分页加载，可设 `USE_WHEEL_SCROLL=false` 改回仅 `scrollTop=0`；`WHEEL_SCROLL_STEPS`、`WHEEL_SCROLL_DELTA` 可调滚轮步数与步长。

## 数据文件（与期权独立）

| 用途 | 期权 | 股票 |
|------|------|------|
| 原始消息 | `data/origin_message.json` | `data/stock_origin_message.json` |
| 持仓 | `data/positions.json` | `data/stock_positions.json` |
| 交易记录 | `data/trade_records.json` | `data/stock_trade_records.json` |

选择正股页面启动时，程序会使用上表「股票」列路径；选择期权页面时使用「期权」列路径，互不覆盖。

- **股票交易记录**：成交成功后应写入 `data/stock_trade_records.json`（格式与期权 trade_records 一致：按 symbol 的订单列表）。卖出指令若带 `sell_reference_label`（如「昨天16.02的」）、`sell_reference_price`，会从此文件按日期与参考价汇总对应买入股数，得到具体卖出数量并写入 `StockInstruction.quantity`。

## 解析规则参考（`parser/stock_parser.py`）

解析器内置多类正则模式，覆盖常见的口语化买卖指令。核心规则如下：

### 买入模式

| 模式名 | 典型示例 |
|--------|---------|
| `BUY_RANGE_ABSORB` | `19.6-19.7附近小仓位回吸一笔` |
| `BUY_RANGE_RETRACE` | `15.1-15在回吸今天卖出的部分` |
| `BUY_RANGE_BUILD` | `21.3-21.4附近建个小仓位` |
| `BUY_RETRACE` | `回踩15.05回吸` |
| `BUY_ABSORB_SINGLE` | `16.01附近回吸一笔` |
| `BUY_ABSORB_THEN_RANGE` | `先回吸卖出数量的一半...17.8-17.9附近` |
| `BUY_RANGE_SUPPORT` | `19.3-19.2 刚打压到支撑了 小仓位日内` |
| `BUY_SMALL_ADD` | `18.3附近小加` |
| `BUY_PRICE_REF_ABSORB` | `价格15.98 可以这个价格附近吸` |
| `BUY_OPENED_ONE` | `18.06 开了一笔常规仓的一半` |
| `BUY_HANG_ORDER` | `可以挂小仓位单在19.2这里` |
| `BUY_HANG_ABSORB` | `挂单的16.64的低吸` |
| `BUY_CATCH_PRICE` | `15。03附近接` |
| `BUY_LIST_PRICE` | `tsll 15.6 rklb 38.3-38.6附近` |

### 卖出模式

| 模式名 | 典型示例 |
|--------|---------|
| `SELL_HALF_WITH_REF` | `14.31出一半 14吸的` |
| `SELL_RANGE_HALF` | `19.8-19.9附近出掉剩下一半` |
| `SELL_SINGLE_HALF` | `19.6附近出一半` |
| `SELL_TIME_REDUCE` | `19时候减掉 18.3加仓的` |
| `SELL_RANGE_FULL` | `18.4-18.5附近把另外一半减掉` |
| `SELL_RANGE_BETWEEN` | `19.6-19.8之间出` |
| `SELL_APPROX_OUT_REF` | `17.45附近出17.35买的` |
| `SELL_THAT_PART` | `19.1 那部分到转弯时候也出` |
| `SELL_YESTERDAY_BUY_PART` | `出昨天15.04买的那部分` |
| `SELL_SHORT_TERM` | `18.45出短线` |
| `SELL_APPROX_SIMPLE` | `19.45附近 出` |

### 仓位描述映射

| 描述 | 计算 |
|------|------|
| 常规仓（默认） | `position × bucket` |
| 一半 / 小仓位 / 常规仓的一半 | `position × bucket × 0.5` |

> 说明：`position` 和 `bucket` 来自 `data/watched_stocks.json`，如 `{"tsll": {"position": 2000, "bucket": 0.3}}`，常规仓 = 600 股，一半 = 300 股。

### 买入价格选择逻辑

环境变量 `STOCK_PRICE_DEVIATION_TOLERANCE`（默认 `1`，单位 %）：
- 若**市场价 ≤ 目标价 × (1 + tolerance%)**，使用市场价下单；
- 否则使用目标价下单，防止高于目标价过多时以市场价成交。

## 相关文件

| 文件 | 说明 |
|------|------|
| `models/instruction.py` | `OperationInstruction` 基类、`OptionInstruction`、`InstructionType` |
| `models/stock_instruction.py` | `StockInstruction` |
| `parser/stock_parser.py` | 股票指令解析 |
| `parser/stock_context_resolver.py` | 股票页解析入口 |
| `utils/watched_stocks.py` | 关注列表、股数/常规仓比例、`resolve_position_size_to_shares` |
| `utils/stock_trade_records.py` | 股票交易记录读写、按参考价/日期解析卖出数量 |
| `data/watched_stocks.json` | 关注列表数据（position=股数，bucket=常规仓比例） |
| `data/stock_origin_message.json` | 股票页原始消息（监控与抓取脚本均写入） |
