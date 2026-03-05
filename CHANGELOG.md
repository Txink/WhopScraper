# CHANGELOG

## [2026-03-05] n8n 兜底解析 + 清仓关键词优化

### 新增

- **n8n 风格兜底买入解析**（`option_parser.py`）
  - `_parse_buy_n8n_fallback()` 方法：在所有精确模式失败后使用宽松的顺序提取方式
  - 支持粘连格式（如 `440c`、`180p`）
  - 支持独立 call/put 关键词和中文期权类型（看涨/看跌）
  - 解析流程：ticker → 期权类型 → 到期日 → 数字流（行权价/入场价）
- **`TAKE_PROFIT_PATTERN_18`**：价格+附近+清仓+剩下的
  - 示例：`5元上限到了 可以5.23附近清仓剩下的` → CLOSE, price=5.23
  - 取靠近"清仓"关键词的价格

- **`OptionInstruction` 新字段**（`instruction.py`）
  - `parsed_by_fallback: bool` - 标记是否由 n8n 兜底解析
  - `parse_error: bool` - 标记是否解析失败

### 优化

- **`TAKE_PROFIT_PATTERN_1C`**：价格区间+出剩下 → CLOSE
  - 示例：`4.8-5附近出剩下三分之一` → CLOSE, price=4.8
  - 有"出剩下/出剩余"关键词时视为清仓，价格区间取小值

- **`parse()` 方法**：无法解析时返回带 `parse_error=True` 的指令，而非 `None`

### 解析流程

```
消息 → 精确模式匹配 (9种买入 + 修改 + 卖出)
     → n8n 兜底解析 (宽松提取)
     → 返回 PARSE_ERROR 指令
```

### 测试验证

- ✅ `tsla 440c 3.5` → BUY（精确匹配）
- ✅ `aapl call 150 2.5` → BUY（n8n 兜底）
- ✅ `NBIS - $92 CALLS EXPIRATION THIS WEEK $3.8` → BUY
- ✅ `5元上限到了 可以5.23附近清仓剩下的` → CLOSE, price=5.23
- ✅ `4.8-5附近出剩下三分之一` → CLOSE, price=4.8
- ✅ 无法解析的消息 → `PARSE_ERROR`

## [2026-03-04] T 交易分析：支持长桥 API 拉取最近 90 天成交（含当日）

- **scripts/analysis/t_trade_analysis.py**：默认从长桥 API 获取指定股票最近 90 天已成交订单并做 T 交易分析
- 拉取历史后**补充当日已成交订单**（`get_today_orders()` 中 Filled 且同 symbol），避免历史接口不包含当日导致缺漏
- 新增 `--days N`（默认 90），仅在不使用 `--file` 时生效
- 使用 `--file PATH` 时仍从本地 JSON 读取，不请求 API
- 分析结果（待 T 出的买入成本、已完成 T 交易、超额卖出、汇总）继续以 Rich 表格形式输出到终端

## [2026-03-03] 股票解析：扩展关注列表 + 增强正则（全量 479→543/775，+64）

### 关注列表扩展
- `data/watched_stocks.json` 新增 BMNR、OKLO、IREN、HOOD、RKLB、NVDL 六只关注股票
- 使 fallback 解析机制（watched tickers → hint patterns）对这些股票生效

### 修复 SELL 模式
- **SELL_SHORT_TERM**：允许"附近"出现在"出短线"前（"95.1附近出短线"）
- **SELL_APPROX_SIMPLE**：支持"成本附近先出""附近都出""附近卖出"变体
- **SELL_TICKER_OUT_PRICE_PART**：`出\s*` → `出[\s\S]{0,20}?` 允许间隔（"出昨天收盘买的30.4部分"）
- **新增 SELL_PRICE_SELL_OUT**：ticker + price + 附近卖出（"oklo盘前冲高94附近卖出"）
- **新增 SELL_PRICE_OUT_GAP_TICKER_SUFFIX**：price + 出 + gap + ticker（"43.1出夜盘补的iren那部分"、"75.1出日内买的rklb"）

### 修复 BUY 模式
- **BUY_PATTERN_4**：动作词新增"介入""(做点)配置""在?接"
- **SELL_HINT_SINGLE_OUT**：支持"成本""都/也/先""卖出"前缀

### 增强 fallback hint
- **BUY_HINT_SINGLE**：gap 扩至 20 字符，新增"介入""配置""开(?!盘)""接(?!下)"
- **BUY_HINT_RANGE**：新增"介入""配置"
- **SELL_HINT_SINGLE_OUT**：支持"成本附近""都/也/先出""卖出"

### 解析率变化
| 股票 | 修改前 | 修改后 | 变化 |
|------|--------|--------|------|
| TSLL | 209/282 (74.1%) | 209/282 (74.1%) | +0 |
| NVDL | 88/129 (68.2%) | 101/129 (78.3%) | +13 |
| BMNR | 79/151 (52.3%) | 103/151 (68.2%) | +24 |
| OKLO | 34/58 (58.6%) | 39/58 (67.2%) | +5 |
| IREN | 25/51 (49.0%) | 31/51 (60.8%) | +6 |
| HOOD | 19/44 (43.2%) | 22/44 (50.0%) | +3 |
| RKLB | 25/60 (41.7%) | 38/60 (63.3%) | +13 |
| **总计** | **479/775** | **543/775 (70.1%)** | **+64** |

### 剩余未解析消息分析 (232条)
- 53% 非交易消息（分析/评论/无明确操作）
- 27% 多股推荐消息（4+个ticker，结构复杂）
- 20% 条件性/复杂结构操作（"如果...""等...再..."等）

## [2026-03-03] 股票解析：批量补全口语化正则（TSLL 159→210/282，NVDL 53→88/129）

基于 `check_TSLL_message.json`（123 条失败）和 `check_NVDL_message.json`（76 条失败）逐条分析，批量补全正则。

### 修复现有 pattern
- **BUY_PATTERN_4**：`\s+` → `\s*`，`(?:在|可以)` 改可选，允许 `[\s\S]{0,10}?` 间隔，补充"建小仓位底仓"等变体
- **BUY_PATTERN_5**：允许 price 与"加了"间有中文间隔，加 `加(?!仓)` 排除误匹配
- **BUY_RANGE_BUILD**：新增"加仓""开仓""加一半""分批进/加"
- **BUY_RANGE_ABSORB**：添加独立"吸"（`吸(?!筹)`）
- **BUY_ABSORB_SINGLE**：添加独立"吸"，允许"可以"前缀，"吸一半"后缀
- **BUY_PRICE_ABSORB**：添加独立"吸"，允许"也是"前缀
- **SELL_RANGE_REDUCE_SUFFIX**：`减` 可独立匹配，新增"减持"
- **SELL_PRICE_OUT_REF_SUFFIX**：允许"附近"在"出"前，支持"再次出""那部分""低吸的"

### 新增 prefix pattern（ticker 在句首）
- **SELL_TICKER_OUT_PRICE_PART**：ticker + 出 + price + 那部分（"nvdl…出84.5那部分"）
- **SELL_TICKER_CAN_PRICE_OUT**：ticker + 可以 + price + 出（"nvdl可以86.75 出"）
- **SELL_HALF_AT_PRICE**：ticker + 一半 + 在 + price + 出（"nvdl之前剩下的一半在107.5出"）
- **SELL_ALSO_OUT_SOME**：ticker + price + 也出点（"nvdl…90.9附近也出点"）
- **BUY_TICKER_ACTION_RANGE**：ticker + 吸/加/接 + range（"nvdl…吸 83-83.5"）

### 新增 suffix pattern（ticker 在句尾/句中）
- **SELL_SINGLE_REDUCE_SUFFIX**：单价 + 减/减仓 + ticker
- **SELL_REDUCE_HALF_REF_SUFFIX**：单价 + 减一半 + 参考价 + ticker
- **SELL_OUT_HALF_NO_REF_SUFFIX**：单价 + 出一半 + ticker（无 ref）
- **SELL_APPROX_OUT_TICKER_SUFFIX**：单价 + 附近出 + gap + ticker
- **BUY_PRICE_ACTION_SUFFIX**：价格 + 吸了/接回/加了 + ticker
- **BUY_PRICE_ADD_POSITION_SUFFIX**：价格 + 加仓了 + ticker（紧跟）
- **BUY_POSITION_TICKER_ACTION**：价格 + 仓位描述 + ticker + 接回/吸回
- **BUY_ACTION_TICKER_AT_PRICE**：回吸了 + ticker + 在 + 价格
- **BUY_APPROX_ACTION_TICKER_SUFFIX**：价格 + 吸/接/加 + gap + ticker
- **BUY_OPEN_POSITION_TICKER_SUFFIX**：价格 + 开仓了 + 仓位 + ticker

### 增强 fallback hint（关注列表匹配后）
- **SELL_HINT_REDUCE**：新增，匹配 price + 减
- **SELL_HINT_SINGLE_OUT**：放宽，允许"先出""可以出"
- **BUY_HINT_SINGLE**：扩展动作词，加负向断言排除误匹配
- **BUY_HINT_RANGE**：扩展分批进/分批加/吸/进/接

## [2026-03-02] 股票解析：关注列表先匹配再解析价格/数量

- **`StockParser` 关注列表 fallback**：当正则未解析出 ticker 时，用 `data/watched_stocks.json` 中的关注股票在消息中做**整词匹配**；命中后再用仅含价格/操作/数量的正则解析买卖与数量。
- 新增 `_watched_tickers_in_message(message)`、`_parse_with_watched_ticker(message, message_id, ticker)` 及一组 SELL_HINT_* / BUY_HINT_* 正则（不依赖 ticker 在句中的位置），用于 fallback 解析。
- 解析顺序不变：先按原有规则解析，全部失败后再尝试「关注列表命中 + 价格/数量正则」。
- **整词边界**：关注列表匹配使用 `(?:^|[^a-zA-Z])ticker(?:$|[^a-zA-Z])`，避免中文后接 ticker（如「一半tsll」）因 `\b` 与 Unicode 行为导致匹配不到。
- **移除**：句尾 ticker 专用逻辑（SELL_RANGE_CAN_OUT_SUFFIX 及对应处理），改由上述 fallback 统一覆盖。

## [2026-03-02] 修护 main.py 在 windows 下的报错 `loop.add_signal_handler(sig, signal_handler) NotImplementedError`

## [2026-02-28] 账户持仓表格化显示 + 订单成交更新

### 新增

- **`RichLogger.print_position_table(title, positions, account=)`**：账户持仓多列表格输出
  - `account` 参数：独立账户信息表格（可用现金/现金/总资产/账户模式）
  - 5 列持仓表格：股票 / 仓位 / 价格 / 总价 / 占比
  - 交易记录作为 `dim` 样式子行追加在对应持仓行下方
  - 多个持仓间通过 `add_section()` 分隔
  - 支持止损价显示

### 重构

- **`PositionManager._log_sync_summary()`**：从 `console.print()` 逐行输出改为构建结构化数据后调用 `rlogger.print_position_table()`
  - 展示所有持仓股票（不再仅限关注列表），非关注股票不显示交易记录
  - 账户信息（可用现金/现金/总资产/模式）通过 `account` 参数独立表格展示
- **`PositionManager._log_position_update()`**：同步重构，订单成交（`OrderStatus.Filled`）后输出更新后的持仓表格
- **`PositionManager._normalize_record()`**：提取公共方法，统一交易记录格式转换

### 测试

- 新增 `TestPositionTable` 测试类（7 个测试用例），覆盖：基本表格、账户信息表格、含交易记录、多持仓、空持仓、订单成交更新、止损价显示
- 全部 36 个测试通过

---

## [2026-02-28] 交易流程支持多流程并行 + 单列表格格式

### 新增

- **`TradeLogFlow`** 数据类：每个交易流程由 `dom_id` 唯一标识，独立持有 stages/base_time/order_id
- **多流程并行**：`trade_start(dom_id)` 支持同时存在多个交易流程，共享一个 Live 实例
- **`trade_stage(dom_id=)`**：通过 dom_id 指定目标流程，省略时使用当前活跃流程
- **`trade_register_order(order_id, dom_id=)`**：绑定 order_id 到指定流程
- **`trade_push_update(order_id)`**：通过 order_id 自动找到对应流程并追加推送阶段
- **单列表格渲染**：每个流程渲染为带 `╭──╮ ├──┤ ╰──╯` 边框的单列表格
- **标题行加粗**：`timestamp [+diff] 阶段名` 整行加粗，统一蓝色
- **dim 行样式**：支持 3-tuple `(key, value, "dim")` 灰色显示次要信息
- **值列对齐换行**：长文本换行后第二行从值列起点对齐
- **每阶段独立时间戳**：每个阶段显示 base_time + diff_ms 的实际时间
- **[BUY]/[SELL] 绿色**：action 标签绿色显示
- `**RichLogger.has_pending_order**` 属性：检查是否有等待推送的订单
- `**_parse_detail_rows()**`（`order_formatter.py`）：提取公共函数，将详情行列表解析为 `(key, value)` 行

### 重构

```python
trade_start
```

- `**RichLogger` 交易流程**：从文本行拼接改为表格渲染，`log()` 不再自动路由到交易流程，改由调用方显式使用 `trade_stage()` 添加表格行
- `**MessageGroup.display()`**：改用 `trade_stage("原始消息")` 输出结构化数据，时间戳和消息延迟显示在标题行右列，domID/内容/配置作为数据行
- `**OptionInstruction.display()` / `StockInstruction.display()**`：改用 `trade_stage("解析消息", rows=[...])`，字段以键值对呈现
- `**OperationInstruction.display_parse_failed()**`：改用 `trade_stage()` 输出
- `**print_order_validation_display` / `print_sell/modify/close_validation_display**`：改用 `trade_stage("订单校验", rows=[...])`，通过 `_parse_detail_rows()` 解析详情行为表格键值行
- `**print_order_submitted_display**`：改用 `trade_stage("提交订单", rows=[...])`，提交后自动调用 `trade_register_order()` 注册订单以跟踪推送
- `**OrderPushMonitor.display_order_changed()**`：改用 `trade_push_update()` 将推送状态追加到对应交易流程表格，终态时自动结束 Live
- `**test/test_rich_logger.py**`：更新 27 个测试用例适配 `trade_stage()` 和 `trade_push_update()` API
- `**test/demo_rich_logger.py**`：交易流程演示改用 `trade_stage()` 表格效果

## [2026-02-28] 重构日志输出为统一 RichLogger 模块

### 新增

- `**utils/rich_logger.py**`：统一的 Rich 终端日志管理器，替代散布在各模块中的 `console.print` 调用
  - **Tag追加模式**（`tag_live_start / tag_live_append / tag_live_stop`）：通过 `rich.Live` 实现动态追加区域，用于程序加载等逐步输出场景，支持嵌套缩进（level 参数）
  - **交易流程模式**（`trade_start / trade_end`）：将一笔交易的完整处理流程（原始消息 → 解析消息 → 订单校验 → 提交订单）组合为单一 Live 区块，动态更新显示进度
  - **静态 Tag 区块**（`log_config / log_nested`）：配置更新、长桥数据等带嵌套结构的一次性输出
  - **线程安全**：所有公开方法通过 `RLock` 保护，push 回调线程可安全调用
  - **Singleton**：`get_logger() / set_logger() / reset_logger()` 管理全局单例
- `**test/test_rich_logger.py`**：单元测试，覆盖 Tag Live、交易流程、静态 Tag、Singleton、多线程安全和完整交易管道集成测试

### 重构

- `**models/message.py**`：`MessageGroup.display()` 改用 logger 代替直接 `Console().print()`
- `**models/instruction.py**`：`OptionInstruction.display()` 和 `display_parse_failed()` 改用 logger；`_display_footer` 重构为 `_get_footer_details()` 返回数据而非直接打印
- `**models/stock_instruction.py**`：`StockInstruction.display()` 改用 logger
- `**broker/order_formatter.py**`：`print_order_submitted_display`、`print_order_validation_display`、`print_sell/modify/close_validation_display`、`print_position_update_display`、`print_config_update_display`、`print_longbridge_data_display` 全部改用 logger
- `**scraper/monitor.py**`：`scan_once()` 中消息处理循环包装为 `trade_start/trade_end`；`display_order_changed()` 改用 logger
- `**main.py**`：程序加载阶段从手动 `Live + _program_load_lines` 改为 `logger.tag_live_*`，通过 `_BridgeList` 兼容 browser/monitor 的回调模式

## [2026-02-25] 股票交易执行、启动参数、T交易分析

### 新增

- **CLI 账户模式参数**：`main.py` 新增 `--paper` / `--real` 互斥参数及 `--dry-run` / `--no-dry-run` 互斥参数，启动时可直接覆盖 `.env` 中的 `LONGPORT_MODE` / `LONGPORT_DRY_RUN`；账户模式在 banner 下方显示（🧪 模拟账户 / 💰 真实账户）。
  ```bash
  python3 main.py --real --no-dry-run   # 真实账户实际下单
  python3 main.py --paper               # 强制模拟账户
  ```
- **股票自动下单**：`main.py` 补全 `_execute_stock_buy` / `_execute_stock_sell` 方法，`_handle_stock_instruction` 从占位日志升级为完整执行流程：
  - 买入：查询实时股价 → 偏差校验（`STOCK_PRICE_DEVIATION_TOLERANCE`）→ 计算股数（`watched_stocks` 的 `bucket × position`）→ 打印 `[订单校验]` → 调用 `broker.submit_stock_order()`
  - 卖出：按 `sell_quantity` 标注（`1/2`、`一半` 等）计算股数 → 打印 `[订单校验]` → 调用 `broker.submit_stock_order()`
- **T交易分析脚本**：`scripts/analysis/t_trade_analysis.py`，分析单一股票买卖记录中哪些买入批次尚未被 T 出，支持 FIFO 匹配 + 超额卖出缓冲逆向对消，输出待 T 批次（含价格、股数、已 T 进度）及累计利润。
  **使用方式：**
  ```bash
  python3 scripts/analysis/t_trade_analysis.py TSLL
  python3 scripts/analysis/t_trade_analysis.py TSLL --file data/stock_trade_records.json
  ```
  **输出示例（TSLL）：**
  ```
  ═══════════════════════════════════════════════════════
    TSLL.US T 交易分析   共 65 条成交记录
  ═══════════════════════════════════════════════════════

  📌 未 T 出的买入仓位（共 1301 股，仍需做 T 消除）

    买入时间                 买入价   原始数量  剩余待T  已T占比
    ──────────────────────────────────────────────────────────
    2025-12-26 23:46:15      $21.41       400      400       0%
    2025-12-30 00:01:56      $20.25       400      400       0%
    2025-12-31 05:12:13      $19.52       400      301      25%   ← 已 T 出 99 股
    2026-01-16 04:52:26      $17.98       200      100      50%   ← 已 T 出 100 股
    2026-02-23 09:15:40      $15.10       100      100       0%

  ✅ 已完成 T 交易（共 50 笔，T 出 10999 股，累计利润 $4,002.44）

    买入时间       买入价   卖出时间       卖出价   数量      利润
    ──────────────────────────────────────────────────────────
    2025-10-25     $19.80   2025-10-27     $20.09    200   +$58.00
    2026-01-03     $18.01   2026-01-05     $18.90    400  +$356.00
    2026-01-07     $17.50   2026-01-09     $18.21    800  +$568.00
    ...（共 50 笔）

  ──────────────────────────────────────────────────────────
  📊 汇总
    当前净持仓（买-卖）：1301 股
    待 T 出：            1301 股  加权均价 $19.44
    已 T 出：           10999 股  累计利润 $4,002.44
  ──────────────────────────────────────────────────────────
  ```
  **匹配规则：**
  1. 卖出 B2 股 @ A2 时，FIFO 匹配之前买入价 < A2 的批次，匹配股数标记为"T完成"
  2. 卖出量超过所有可匹配买入量时，超额卖出记入缓冲；后续出现买入价更低的记录时逆向对消
- **启动 `[仓位分析]` 展示**：正股页启动同步后自动输出 `[仓位分析]` 模块，逐个股票展示待 T 仓位（买入时间、价格、剩余股数）及已 T 利润；无需手动执行分析脚本。

### 优化

- **订单推送过滤**：`OrderPushMonitor.display_order_changed` 按页面类型双向过滤——期权页只显示期权订单，正股页只显示股票订单，避免交叉干扰。
- **股票交易记录完整校正**：`PositionManager.sync_from_broker` 新增 `full_refresh` 参数；正股页启动时传 `full_refresh=True`，清空本地记录后从长桥 API 拉取 **365 天**历史 Filled 订单完整重建，按时间升序排列，确保本地数据与券商一致。

### 修复

- **价格四舍五入**：`parser/stock_parser.py` 和 `scripts/parser/generate_check_stock.py` 中所有 `round(..., 2)` 改为 `Decimal.quantize(ROUND_HALF_UP)` 实现标准四舍五入，解决 Python 银行家舍入导致 `15.385 → 15.38` 而非 `15.39` 的问题；同时在 `parse()` 入口统一将中文句号 `。` 替换为英文点 `.`，修复 `15。05` 被截断为 `15` 的问题。
- **新增买入模式 `BUY_ABSORB_BACK_SUFFIX`**：识别「价格 + 在吸回 + (卖出的) + ticker后缀」结构，如「15.40在吸回卖出的tsll」→ BUY $15.40 bucket仓位。
- **新增卖出模式 `SELL_APPROX_OUT_REF_HALF`**：识别「价格附近出 + 参考价 + 的一半」结构（如「15.39附近出 15.05的一半」），正确提取 `sell_quantity=1/2`、参考价 `15.05`；原 `SELL_APPROX_OUT_REF` 因缺少一半识别导致卖出量误判为全部。

## [2026-02-22] 股票解析器正则规则完善

### 优化

- **解析覆盖率提升**：`parser/stock_parser.py` 针对 TSLL 实际消息样本（87 条）新增多类正则模式，解析率从 ~36% 提升至 74%（65/87 条）；未解析的 22 条均为纯信息性消息（无具体买卖价格）。
- **新增买入模式**：
  - `BUY_RANGE_SUPPORT` — 价格区间 + 支撑关键词（如「19.3-19.2 刚打压到支撑了 小仓位日内」）
  - `BUY_SMALL_ADD` — 价格 + 附近小加（如「18.3附近小加」，识别为小仓位买入）
  - `BUY_PRICE_REF_ABSORB` — 价格 XX + 这个价格附近吸（如「价格15.98 可以这个价格附近吸」）
  - `BUY_OPENED_ONE` — 开了一笔/建了一笔（如「18.06 开了一笔常规仓的一半」）
  - `BUY_ABSORB_THEN_RANGE` — 回吸关键词在前、价格区间在后（如「先回吸...17.8-17.9附近」）
  - `BUY_LIST_PRICE` — ticker 直接跟价格列举（如买入清单「tsll 15.6 rklb 38.3-38.6」）
  - `BUY_HANG_ABSORB` — 挂单低吸价格（如「挂单的16.64的低吸」）
- **新增卖出模式**：
  - `SELL_APPROX_OUT_REF` — 附近出 + 参考买入价（如「17.45附近出17.35买的」）
  - `SELL_THAT_PART` — XX那部分…出（如「19.1 那部分到转弯时候也出」）
  - `SELL_YESTERDAY_BUY_PART` — 出昨天/之前XX买的那部分（如「出昨天15.04买的那部分」）
- **修复**：`附近?` 正则错误（`附近?` 仅使「近」可选），全部改为 `(?:附近)?` 使整词可选。
- **仓位量化**：`scripts/parser/generate_check_stock.py` 新增 `_calc_quantity` 函数，根据 `watched_stocks.json` 的 `bucket × position` 计算具体股数；仓位描述「一半」「小仓位」「常规仓的一半」等映射为对应股数。
- **环境变量**：`.env` 新增 `STOCK_PRICE_DEVIATION_TOLERANCE=1`，买入时若市场价超出目标价该百分比则使用目标价下单，否则用市场价。

## [2026-02-20] 账户余额币种与总资产、配置提醒

### 变更

- **账户余额（get_account_balance）**：调用 `account_balance(currency="USD")` 指定币种；返回 `available_cash`（可用现金）、`cash`（available_cash + frozen_cash）、`net_assets`（总资产），币种固定为 USD。
- **[账户持仓] 展示**：总资产改为使用 API 的 `net_assets`；展示项为「可用现金、现金、总资产」；持仓占比计算优先使用 `net_assets`。
- **配置更新提醒**：仅当「真实账户且 Dry Run 关闭」时显示「下单将产生实际资金变动」的警告；Dry Run 开启或模拟账户时不显示。
- **config_loader**：移除「使用真实账户」与「LONGPORT_DRY_RUN=true 模拟模式」两条 logger.warning。

## [2026-02-19] 页面抓取脚本独立与开发者指南

### 新增

- **消息导出脚本**：`scripts/scraper/export_page_message.py` — 全屏打开目标页面、自动滚动抓取消息并导出。参数：`--type`（stock|option，默认 stock）、`--output`（默认 `tmp/<type>/origin_message.json`）、可选 `--url`；不依赖环境变量，默认由参数控制。
- **HTML 导出脚本**：`scripts/scraper/export_page_html.py` — 打开目标页面并导出当前 HTML。参数：`--type`（stock|option，默认 stock）、`--output`（默认 `tmp/<type>/page_html.html`）、可选 `--url`。
- **按股票过滤消息脚本**：`scripts/parser/filter_target_stock.py` — 从原始消息 JSON 中仅按本条 `content` 是否提及指定 ticker 过滤，导出到 `tmp/stock/origin_<TICKER>_message.json`。参数：位置参数 TICKER，`--input`（默认 `tmp/stock/origin_message.json`）、`--output`（默认 `tmp/stock/origin_<TICKER>_message.json`）。

### 变更

- **README**：新增「开发者指南」大标题，含导出页面消息、导出页面 HTML、按股票过滤消息三个脚本的使用说明与示例；`--type` 补充说明为 `stock` 正股、`option` 期权；示例中增加带 `--type` 与真实 URL 的可复制命令。
- **Python 3.9 兼容**：`scripts/scraper/export_page_message.py`、`export_page_html.py` 中返回类型由 `str | None` 改为 `Optional[str]`，避免在 Python 3.9 及以下报错。

## [2026-02-19] 股票指令分析与架构重构

### 新增

- **股票页面监控**：支持选择正股页面监控，与期权独立；股票页解析为 `StockInstruction`，仅对关注列表内股票触发回调。
- **指令模型重构**：`OperationInstruction` 基类；`OptionInstruction`/`StockInstruction` 子类；`models/stock_instruction.py`。
- **关注股票列表**：`data/watched_stocks.json`、`utils/watched_stocks.py`，运行中修改即生效。
- **股票页消息抓取**：`scripts/capture_stock_messages.py` 支持自动历史分页（默认）：脚本自动滚动消息区到顶部触发上一页加载，每轮加载后立即提取并按 domID 去重保存，避免 DOM 回收丢失；连续 2 轮无新消息或达最大轮数后结束。`AUTO_SCROLL_HISTORY=false` 可切换为定时抓取模式。
- **期权/股票数据独立**：股票页使用 `data/stock_origin_message.json`、`data/stock_positions.json`、`data/stock_trade_records.json`；期权页使用 `data/origin_message.json`、`data/positions.json`、`data/trade_records.json`。
- **解析结果为具体股数**：`watched_stocks` 改为 `position`=股数、`bucket`=常规仓比例；`resolve_position_size_to_shares` 将「常规一半」等换算为整数股数；`StockInstruction.quantity` 存储解析出的股数；卖出时根据 `sell_reference_label`/`sell_reference_price` 从 `data/stock_trade_records.json` 解析卖出数量（`utils/stock_trade_records.py`）。交易成功后需写入 `stock_trade_records` 以便后续卖出数量解析。

### 变更

- Record/RecordManager/Monitor/main 按 page_type 或指令类型分流；stock_parser 返回 `StockInstruction`，使用 BUY/SELL/MODIFY。
- 文档：新增 [docs/stock_monitoring.md](docs/stock_monitoring.md)；关注列表格式为 position（股数）+ bucket（常规仓比例），并说明 stock_trade_records 用途；抓取脚本为有界面 + 手动滚动后按 Enter 提取、按 domID 去重。

## [2026-02-18] 头像 “X” 规则误删 ticker 首字母 X（XOM→OM）

### 修复

- **移除“开头 X”时保留 ticker XOM**（多处）
  - **原因**：为过滤头像 fallback “X”，曾用 `^[XxＸｘ]+\s`* 或 `^X\s*` 去掉开头 X，导致 “XOM - ...” 被清成 “OM - ...”，解析得到 ticker=OM。
  - **修改**：仅在“开头是单独 X（后接非字母或结尾）”时移除，即用 `^[XxＸｘ]+\s*(?=[^A-Za-z]|$)`（Python）或 `^X\s*(?=[^A-Za-z]|$)`（JS），保留 “XOM” 等以 X 开头的 ticker。
  - **涉及文件**：`models/record.py`（`_clean_content`，主流程）、`scraper/quote_matcher.py`（`clean_quote_text`）、`scraper/message_extractor.py`（两处引用清理）、`test/analyze_local_messages.py`。

## [2026-02-18] XOM 解析为 OM、时间戳无效时相对日期兜底

### 修复

- **ticker 被解析成 OM 而非 XOM**（`parser/option_parser.py`）
  - 原因：消息中的 “X” 有时为 Unicode 希腊字母 Chi (U+03A7)，外观与拉丁 X 相同但 `[A-Z]` 不匹配，正则从第二位起匹配到 “OM”
  - 处理：在 `parse()` 入口对消息做 `_TICKER_LOOKALIKES` 归一化（希腊 Chi/Alpha/Omicron 等 → 对应 ASCII），再走原有正则
- **时间戳无效时相对日期无法解析**（`parser/option_parser.py`、`models/instruction.py`）
  - 当 `message_timestamp` 为非法格式（如 `57:14 PM`）时，`_resolve_relative_date` 原先直接返回 `("THIS WEEK", False)`，导致到期日未转为具体日期
  - 处理：时间戳解析失败时用 `datetime.now()` 兜底，照常计算「本周/下周」对应周五；`normalize_expiry_to_yymmdd` 在 timestamp 无效且到期为相对日期时同样用当前日期兜底

说明：当前「THIS WEEK」= 本周五（如 2/18 周三 → 2/20）；若需 2/27 应使用「NEXT WEEK」。

## [2026-02-18] 时间戳解析与开仓格式

### 修复

- **时间戳解析**（`models/message.py`）
  - 「仅时间」与「相对日期+时间」的正则限制为合法 12 小时制：小时 1–12、分钟 00–59
  - 避免如 `52:05 PM`（小时 52 非法）进入 `strptime(..., "%I:%M %p")` 导致 `time data '52:05 PM' does not match format '%I:%M %p'`
  - 非法时间不再尝试解析，直接返回原字符串，不再打印解析失败警告

## [2026-02-18] 支持「$TICKER - $STRIKE 这周 calls $PRICE」开仓格式

### 新增

- **期权开仓解析**（`parser/option_parser.py`）
  - 新增 OPEN_PATTERN_9：行权价在前、相对日期在中间，例如 `$UUUU - $21 这周 calls $.85 彩票`
  - 此前仅支持「到期在 strike 前」或「strike 后直接 call/put」，导致上述格式解析失败（symbol = X）
  - 修复后正确解析为：ticker=UUUU, strike=21, expiry=2/20, type=CALL, price=0.85

## [2026-02-17] 解析「价格+剩下+ticker+都出」为 CLOSE

### 修复

- **期权/正股出货解析**（`parser/option_parser.py`）
  - 新增模式 2c：`价格+剩下+可选ticker+都出`，例如 `3.2 剩下qqq都出`
  - 此前仅支持「价格+剩下+都出」（中间无 ticker），导致带 ticker 的「剩下XXX都出」解析失败（symbol = X, operation: FAIL）
  - 修复后正确解析为：instruction_type=CLOSE, ticker=QQQ, price=3.2

## [2026-02-12] 支持带点号的 ticker 解析（BRK.B → BRKB）

### 新增

- **带点号 ticker 归一化**（`parser/option_parser.py`）
  - 新增 `_DOT_TICKER_RE` 正则和 `_normalize_dot_tickers()` 方法
  - 在 `parse()` 入口处预处理消息，将 `BRK.B`、`BF.A` 等带点号的 ticker 归一化为 `BRKB`、`BFA`
  - 解决 `[A-Z]{2,5}` 正则无法匹配含点号 ticker 导致解析失败的问题

### 问题场景

- 消息 `"BRK.B - $510 CALLS EXPIRATION NEXT WEEK $1.90"` 无法解析
- 原因：正则匹配到 `BRK` 后，`.B` 无法匹配后续期望的空格/横杠/价格模式，所有开仓模式全部失败
- 修复后正确解析为：ticker=BRKB, strike=510, type=CALL, price=1.90, expiry=NEXT WEEK

## [2026-02-11] 期权默认止损配置

### 新增

- **期权默认止损**（`.env` + `broker/position_manager.py`）
  - `ENABLE_DEFAULT_STOP_LOSS`：开启后，每次期权**买入成交**后自动按比例设置止损；不开启则仅根据监听到的止损消息设置
  - `DEFAULT_STOP_LOSS_RATIO`：止损比例（%），默认 38，表示价格跌到买入价的 62% 时触发止损（即亏损 38%）
  - 逻辑在订单推送 `FILLED` 且为买入时，用 broker 返回的成本价计算止损价并写入持仓、持久化

## [2026-02-11] 移除 samples 模块

### 移除

- **samples**：删除整个 `samples/` 目录（样本管理、数据集管理、setup 脚本等）及所有引用
  - 配置：`config.py` 中移除 `ENABLE_SAMPLE_COLLECTION`、`SAMPLE_DATA_DIR`
  - 测试：删除 `test/parser/test_parser_coverage.py`（依赖 `DatasetManager`）
  - 文档：`README.md` 移除样本管理章节与项目结构中的 samples；`docs/full_auto_trading_guide.md` 移除 `ENABLE_SAMPLE_COLLECTION` 说明
  - `.gitignore` 移除 `!samples/*.json`

## [2026-02-11] 移除风险控制器模块

### 移除

- **risk_controller**：删除 `broker/risk_controller.py`（`RiskController`、`AutoTrailingStopLoss`）及所有引用
  - 测试：`test/broker/test_position_management.py` 中移除风险控制器测试与导入
  - 文档：`doc/USAGE_GUIDE.md`、`doc/PROJECT_STRUCTURE.md`、`doc/PROJECT_STATUS.md` 中移除相关说明

## [2026-02-08] 长桥订单状态推送监听

### 新增

- **订单推送监听**（`scraper/monitor.py`）
  - 新增 `OrderPushMonitor`：通过长桥交易长连接订阅 `TopicType.Private`，接收订单/资产变更推送
  - 参考 [长桥交易推送文档](https://open.longbridge.com/zh-CN/docs/trade/trade-push)：`set_on_order_changed` + `subscribe([TopicType.Private])`
  - 支持 `on_order_changed(callback)` 设置回调，在后台线程中运行，不阻塞消息监控
- **主程序集成**（`main.py`）
  - 在长桥交易组件初始化成功后自动创建并启动订单推送监听
  - 回调 `_on_order_changed` 记录订单状态变化日志，可在该回调中扩展通知或持仓同步
  - 程序退出时自动取消订阅并停止监听

## [Unreleased]

### 重大改进

- **正则表达式优化**：`parser/option_parser.py` 大幅提升解析成功率
  - **解析成功率**: 58.7% → **77.33%** (+18.63%)
  - **信息完整率**: 58.7% → **76.89%** (+18.19%)
  - **生成 symbol**: 0 → **172条**
  - **不完整消息**: 32 → **1条**
  **实施的优化**:
  1. 新增 `OPEN_PATTERN_7`: 支持日期在中间格式（`QQQ 11/20 614c 1.1`）并优先于其他模式
  2. 优化 `OPEN_PATTERN_1`: 添加"的"字和"到期"支持（`下周的`、`下周到期`）
  3. 新增 `OPEN_PATTERN_8`: 支持中文"看涨期权"/"看跌期权"
  4. 修复 `OPEN_PATTERN_5`: 正确提取日期和call/put类型（之前分组索引错误）
  5. 新增 `TAKE_PROFIT_PATTERN_13/13B`: 支持带详细期权信息的卖出（`0.47 出rivn 19.5 call`），支持小写ticker（`4.15-4.2出 amzn亚马逊call`）
  6. 调整解析顺序: 买入指令优先于修改指令，避免误判
  7. 优化 `OPEN_PATTERN_2`: 允许日期和价格之间有任意文字（`TSLA 460c 1/16 小仓位日内交易 4.10`）
  8. 新增 `TAKE_PROFIT_PATTERN_14`: 支持"在+价格+减仓"格式（`TSLA 在 4.40 减仓一半`）
  9. 新增 `TAKE_PROFIT_PATTERN_15`: 支持"价格+止盈+比例+ticker"格式（`1.5止盈一半intc`）
  10. 新增 `TAKE_PROFIT_PATTERN_16`: 支持"ticker+剩下部分+价格+出"格式（`nvda剩下部分也2.45附近出`）
  11. 新增 `TAKE_PROFIT_PATTERN_17`: 支持"ticker+strike+call/put+...+剩下+价格+出"格式（`iren 46 call 快进入46价内了 可以剩下的1.6-1.7分批出`），支持小写ticker和价格中的中文句号

### 修复

- **🔥 期权 symbol 格式错误**：修复 strike price 格式导致合约查询失败的问题
  - **问题**：生成的 symbol 为 `GOLD260220C060000.US`（6位 strike），而 LongPort API 要求 5 位格式 `GOLD260220C60000.US`
  - **影响**：导致所有订单提交失败，报错 `security not found`
  - **修复文件**：
    - `models/instruction.py`: `generate_option_symbol` 方法，strike 格式从 `:06d` 改为 `:05d`
    - `broker/longport_broker.py`: `convert_to_longport_symbol` 函数
    - `analyze_local_messages.py`: symbol 生成逻辑
    - `doc/LONGPORT_INTEGRATION_GUIDE.md`: 文档示例代码
  - **验证**：修复后可以正确查询 GOLD260220C60000.US 的报价（$2.60）
- **订单提交前验证**：`broker/auto_trader.py` 添加期权合约存在性验证
  - 在买入指令执行时，如果无法获取市场报价（返回空列表），现在会直接拒绝订单并提示用户
  - 添加友好错误提示：建议检查 ticker 是否正确（如 `GOLD` 应为 `GLD`）或合约是否存在
  - 避免提交必然失败的订单，减少错误日志（如 `security not found` 错误）
  - 修复场景：当解析消息得到错误的 ticker（如 `GOLD260220C060000.US`）时，系统现在会在获取报价阶段就发现并拒绝，而不是等到提交订单时才失败
- **时间戳格式兼容性**：`models/instruction.py` 修复 symbol 生成问题
  - `normalize_expiry_to_yymmdd` 和 `generate_option_symbol` 现在支持标准化时间戳格式（`2026-02-05 23:51:00.010`）
  - 之前只支持原始格式（`Jan 23, 2026 12:51 AM`），导致相对日期（如 `NEXT WEEK`、`今天`）无法正确转换为 YYMMDD
  - 新增支持"今天"/"today"相对日期
  - 修复后：
    - `NEXT WEEK` → `260213` → `KR260213C068000.US`
    - `今天` → `260121` → `SPY260121C680000.US`

### 文档

- **正则表达式优化分析**：`docs/regex_optimization_analysis.md` 新增优化分析报告
  - 基于 225 条真实消息的解析结果进行深度分析
  - 识别出 5 个主要问题和优化方向
  - 优先级排序：日期格式(20+条)、"的"字支持(2-3条)、中文期权类型(2-3条)、带详细信息的卖出(3-5条)
  - 实际优化后成功率从 58.7% 提升到 74.67%，超出预期

### 功能增强

- **相对时间格式支持**：`scraper/message_extractor.py` 新增相对时间格式识别和解析
  - 支持一周内的相对时间格式：`Yesterday at 11:51 PM`、`Today 10:45 PM`、`Wednesday 10:45 PM` 等
  - 自动计算对应的绝对日期并转换为标准时间戳格式
  - JavaScript 提取层和 Python 标准化层同步支持
- **测试工具改进**：`test/test_export_page_dom.py` 新增消息提取和导出功能
  - 使用 `EnhancedMessageExtractor` 提取页面消息（与 `monitor.py` 保持一致）
  - 固定导出到 `data/origin_message.json`，支持增量更新和自动去重（按 domID）
  - 支持多种时间格式解析并按时间排序消息
  - 显示消息统计信息（本次提取、新增消息、总数、位置分布、引用数量、历史记录数量）
  - 导出文件包含：HTML、截图、结构分析、消息JSON
- **消息解析测试工具**：`test/test_parse_origin_messages.py` 新增批量解析测试功能
  - 读取 `data/origin_message.json` 中的所有原始消息
  - 使用 `MessageContextResolver` 批量解析消息
  - 生成 `data/parsed_messages.json`，包含每条消息的原始数据和解析结果
  - 自动生成期权代码 `symbol` 字段（当信息完整时）
  - 添加 `status` 状态标识：✅完整、⚠️不完整、❌失败
  - 显示详细统计：成功率、完整率、symbol 生成数、指令类型分布、上下文来源分布
  - 便于验证解析器效果和调试解析问题

### 修复

- **开仓指令价格格式**：支持无前导 0 的小数价格（如 `.65`、`.5`），此前正则要求价格必须以数字开头，导致如 `KR - $68 CALLS EXPIRATION NEXT WEEK .65 彩票` 等消息解析失败。已更新 OPEN_PATTERN_1～6 及 TAKE_PROFIT 等模式中的价格部分为正则 `(?:\d+(?:\.\d+)?|\.\d+)`，并保持价格区间（如 `.65-.70`）兼容。
- **OPEN_PATTERN_1 到期日**：支持英文 "EXPIRATION NEXT WEEK" / "EXPIRATION THIS WEEK" 格式（如 `HON - $237.5 CALLS EXPIRATION NEXT WEEK $2.05`），此前仅支持中文「本周/下周」或 "EXPIRATION" + 具体日期，导致该类消息解析失败。
- **卖出指令格式**：新增「ticker + 价格 + 都出/出剩下的」模式（`TAKE_PROFIT_PATTERN_10`），支持如 `unp 2.35都出剩下的`、`ndaq 2.4都出` 等表述，此前因无匹配模式导致解析失败。
- **上下文查找范围**：`MessageContextResolver` 默认向前查找条数由 5 条改为 10 条（`CONTEXT_SEARCH_LIMIT` 默认 10），便于在「前 10 条」内找到 UNP 等买入消息以补全清仓指令。
- **卖出指令格式**：新增「价格 + 都出/全出 + 可选 ticker」模式（`TAKE_PROFIT_PATTERN_5B`），支持如 `2.75都出 hon`、`2.3全出` 等表述。

## [2026-02-03 v3.20.1] 期权代码行权价格式与「本周」到期日修复

### 修复

- **期权代码格式**：长桥 API 实际返回的行权价部分为 **6 位**（如 `110000`、`345000`），本地生成误用 8 位导致 `security not found`。已统一改为 6 位：
  - `broker/auto_trader.py`：`_generate_option_symbol` 行权价 `:08d` → `:06d`
  - `broker/longport_broker.py`：`convert_to_longport_symbol` 同上
  - `analyze_local_messages.py`：`generate_option_symbol` 同上
- **「本周」「下周」到期日**：当消息里写「本周」而解析未拿到消息时间戳时，`expiry` 仍为「本周」，原先 `_generate_option_symbol` 只支持 `m/d`、`m月d日`，无法解析导致失败；若被上下文错误补全成「1/30」等，会因「月份已过用明年」被算成 2027 年。现已在 `_generate_option_symbol` 中直接支持「本周」「下周」「这周」「当周」「this week」「next week」，**以当前日期（`datetime.now()`）计算本周五/下周五**，保证到期日为当前年份（如 2026），不再误成 2027。
- **价格偏差超限拒绝下单**：原先「价格偏差超过容忍度」只打警告，仍可确认下单。现改为**超容忍度即拒绝**，不再进入确认步骤、不提交订单；可通过 `PRICE_DEVIATION_TOLERANCE` 调高容忍度（默认 5%）。
- **去掉仓位数量逻辑**：移除 `POSITION_SIZE_SMALL` / `POSITION_SIZE_MEDIUM` / `POSITION_SIZE_LARGE` 及「小/中/大仓位」对数量的控制；买入数量**仅由 `MAX_OPTION_TOTAL_PRICE` 与账户可用资金**决定（`broker/auto_trader.py`、`broker/longport_broker.calculate_quantity`、`main.py`）。解析层仍可解析「小仓位」等文案，但不再参与数量计算。
- 文档与注释已同步为 6 位格式说明。

## [2026-02-03 v3.20] 完整自动化交易流程上线

### 🚀 核心功能

**完整自动化流程**：

- ✅ 监听网页 → 提取消息 → 解析指令 → 自动下单 → 持仓管理
- ✅ 集成AutoTrader到main.py主流程
- ✅ 支持实时监听和本地HTML两种模式
- ✅ 完整的端到端自动化交易方案

**自动交易模块（AutoTrader）**：

- ✅ 自动买入：根据账户余额和配置上限智能计算买入数量
- ✅ 自动卖出：支持按比例卖出（相对初始买入量）
- ✅ 自动清仓：一键清空持仓
- ✅ 止盈止损：自动检测并执行止盈止损条件
- ✅ 风险控制：总价上限、余额检查、持仓验证
- ✅ 确认模式：可选的控制台确认机制
- ✅ 批量执行：支持批量处理多条指令

### 📋 交易规则

**买入规则**：

1. 获取账户余额，根据配置和余额的较小值决定总价上限
2. 根据总价上限和单价计算买入数量
3. 可配置是否需要控制台确认

**卖出规则**：

1. 先检查持仓，无持仓则跳过
2. 卖出比例相对最开始买入的比例，查询历史买入订单确认总量
3. 支持分数（1/3）、百分比（30%）、具体数量

**清仓规则**：

1. 检查持仓，无持仓则跳过
2. 卖出全部可用持仓

**修改规则（止盈止损）**：

1. 先检查持仓
2. 获取期权最新价格
3. 如果满足止盈止损条件，立即市价清仓
4. 否则修改未成交订单的止盈止损值

### 🔧 新增文件

**broker/auto_trader.py**

- `AutoTrader` 类：自动交易执行器
- `execute_instruction()`: 执行单条指令
- `execute_batch_instructions()`: 批量执行指令
- `_execute_buy()`: 执行买入
- `_execute_sell()`: 执行卖出
- `_execute_close()`: 执行清仓
- `_execute_modify()`: 执行修改（止盈止损）
- `_generate_option_symbol()`: 生成期权代码

**auto_trade_from_messages.py**

- 从HTML消息文件自动交易的完整脚本
- 支持dry_run和真实交易模式
- 提供详细的执行统计和结果报告

**demo_auto_trading.py**

- 自动交易演示脚本
- 包含5个演示场景：买入、卖出、清仓、修改、批量执行

**test/broker/test_auto_trader.py**

- AutoTrader测试套件
- 包含期权代码生成、各种指令类型测试

**docs/auto_trading.md**

- 自动交易完整文档
- 包含交易规则、配置说明、使用示例、常见问题

**docs/full_auto_trading_guide.md**

- 完整自动化交易流程指南
- 包含监听网页、本地HTML两种模式
- 详细的配置、测试、故障排查说明

### ⚙️ 新增配置

**.env新增配置项**：

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

### 🔄 修改文件

**main.py**

- 集成 `AutoTrader` 到主流程
- 修改 `_handle_instruction()` 使用 `AutoTrader` 执行指令
- 新增 `_sync_position_after_buy()` 同步持仓
- 旧的处理方法改名为 `_legacy` 后缀（向后兼容）
- 支持新的指令类型（BUY, SELL, CLOSE, MODIFY）

**scraper/monitor.py**

- 更新 `_determine_category()` 支持新旧指令类型
- 兼容 BUY, SELL, CLOSE, MODIFY 和 OPEN, STOP_LOSS, TAKE_PROFIT

### 📖 文档更新

- ✅ 更新 `.env.example` 添加自动交易配置
- ✅ 更新 `broker/__init__.py` 导出 `AutoTrader`
- ✅ 更新 `README.md` 添加自动交易和完整流程文档链接
- ✅ 创建 `docs/auto_trading.md` 完整功能文档
- ✅ 创建 `docs/full_auto_trading_guide.md` 端到端流程指南
- ✅ 更新 `CHANGELOG.md` 记录所有变更

### 💡 使用示例

```python
from broker import LongPortBroker, load_longport_config, AutoTrader
from models.instruction import OptionInstruction, InstructionType

# 初始化
config = load_longport_config()
broker = LongPortBroker(config)
trader = AutoTrader(broker)

# 创建买入指令
instruction = OptionInstruction(
    instruction_type=InstructionType.BUY.value,
    ticker="AAPL",
    option_type="CALL",
    strike=250.0,
    expiry="2/7",
    price=5.0,
    position_size="小仓位"
)

# 执行指令
result = trader.execute_instruction(instruction)
```

### 🎯 下一步

1. 集成到 `analyze_local_messages.py`，实现端到端自动交易
2. 添加更多风险控制策略
3. 支持更复杂的交易策略（如网格交易、定投等）
4. 添加交易日志和性能统计

---

## [2026-02-03 v3.18] 支持反向止损格式（价格在前）

### 🎯 核心改进

**反向止损格式支持**：

- ✅ 新增 `REVERSE_STOP_LOSS_PATTERN` 正则表达式
- ✅ 支持"价格+止损"格式（例如：2.5止损、3.0SL）
- ✅ 增强ticker提取，支持"剩下的XXX"、"的XXX"格式

### 🔧 修改文件

**parser/option_parser.py**

- 新增 `REVERSE_STOP_LOSS_PATTERN` 正则
- `_parse_modify`: 添加反向止损匹配逻辑
- 增强ticker提取：支持"(?:剩下)?的\s*([A-Za-z]{2,5})"格式

### 💡 问题场景

**问题**: "2.5止损剩下的ba 横盘有磨损了" 解析失败

**原因**: 

1. 原有正则要求"止损在前，价格在后"（止损 2.5）
2. 实际消息是"价格在前，止损在后"（2.5止损）
3. ticker是小写且在中文"的"之后，未被识别

**解决**: 

1. 新增反向止损正则: `r'(\d+(?:\.\d+)?)\s*(?:止损|SL)'`
2. 增强ticker提取: `r'(?:剩下)?的\s*([A-Za-z]{2,5})(?:\s|$)'`
3. 保持原有格式兼容性

### 🧪 测试用例

```python
# 反向止损格式
"2.5止损剩下的ba" → ticker: BA, stop_loss: 2.5 ✓
"3.0止损" → ticker: None, stop_loss: 3.0 ✓
"1.8SL剩下的nvda" → ticker: NVDA, stop_loss: 1.8 ✓

# 原有格式（兼容性）
"止损在2.9" → stop_loss: 2.9 ✓
"SL 1.5" → stop_loss: 1.5 ✓
"止损提高到3.2" → stop_loss: 3.2 ✓
```

### ✅ 解析结果

**实际数据验证**:

```
消息: 2.5止损剩下的ba 横盘有磨损了
期权代码: BA260213C00240000.US ✓
止损价格: $2.5 ✓
上下文来源: 前5条 ✓
```

### 📊 支持的格式

**止损指令现在支持**:

1. **正向格式**（原有）:
  - 止损 2.5
  - 止损在2.9
  - SL 1.5
  - 止损设置在0.17
2. **反向格式**（新增）:
  - 2.5止损
  - 3.0止损剩下的ba
  - 1.8SL
  - 2.2SL剩下的tsla
3. **调整止损**（原有）:
  - 止损提高到3.2
  - 止损上移到2.25

### 📝 技术细节

**ticker提取优先级**:

1. "XXX期权/期货/股票" 格式
2. "的XXX" 或 "剩下的XXX" 格式（新增）
3. 独立的大写单词

**正则匹配顺序**:

1. ADJUST_STOP_PATTERN（调整止损）
2. STOP_LOSS_PATTERN（正向止损）
3. REVERSE_STOP_LOSS_PATTERN（反向止损，新增）

## [2026-02-03 v3.17] MODIFY指令ticker提取增强

### 🎯 核心改进

**MODIFY指令ticker提取**：

- ✅ MODIFY指令现在能正确提取消息中提到的股票代码
- ✅ 支持"tsla期权"、"BA股票"等格式
- ✅ 避免错误匹配到不相关的股票

### 🔧 修改文件

**parser/option_parser.py**

- `_parse_modify`: 新增ticker提取逻辑
- 优先匹配"XXX期权/期货/股票"格式
- 后备匹配独立的大写股票代码
- 过滤常见非股票词汇（SL, TP, STOP, LOSS等）

### 💡 问题场景

**问题**: 消息"止损提高到3.2 tsla期权今天也是日内的"被错误补全为BA

**原因**: 

1. 解析器没有提取到"tsla"作为ticker
2. 系统认为无ticker，使用保守策略
3. 从前5条找到最近的BUY（BA），错误补全

**解决**: 

1. 提取消息中的"tsla"为ticker
2. 使用积极策略查找TSLA的买入信息
3. 即使找不到也不会错误匹配其他股票

### 🧪 测试用例

```python
# 测试1: 提取ticker
"止损提高到3.2 tsla期权今天也是日内的"
→ ticker: TSLA ✓

# 测试2: 无ticker
"止损在2.9"
→ ticker: None ✓

# 测试3: 大写ticker
"止损提高到1.5 BA期权"
→ ticker: BA ✓
```

### ✅ 测试覆盖

- ✅ MODIFY指令ticker提取（小写/大写）
- ✅ ticker匹配验证（跳过不匹配的股票）
- ✅ 实际数据验证

### 📝 注意事项

- 前5条消息查找有距离限制
- 如果距离超过5条，可能无法补全完整信息
- 但至少ticker是正确的，避免错误匹配

## [2026-02-03 v3.16] 增强保守策略 + 完整期权代码显示

### 🎯 核心改进

**保守策略增强**：

- ✅ 无ticker的消息现在也支持从前5条消息查找买入信息
- ✅ 查找优先级：history → refer → 前5条消息
- ✅ 提高无ticker消息的解析成功率

**期权代码完整显示**：

- ✅ 显示完整的OCC标准期权代码（如 `BA260213C00240000.US`）
- ✅ 自动从消息时间戳提取年份
- ✅ 支持多种日期格式（`2/13`, `2月13` 等）
- ✅ 可直接用于broker下单

### 🔧 修改文件

1. **parser/message_context_resolver.py**
  - `_find_context_conservative`: 新增前5条消息查找
  - `_search_in_recent_messages`: 支持 `ticker=None` 参数
2. **analyze_local_messages.py**
  - 新增 `generate_option_symbol()` 函数
  - 输出显示完整期权代码
3. **docs/order_management.md**
  - 更新保守策略说明

### 💡 使用示例

#### 保守策略增强

```python
# 前序消息
"AMD 180c 2/14 3.0"

# 当前消息（无ticker）
"止损在2.5"

# 自动补全为: AMD $180 CALL 2/14, 止损价 $2.5
# 上下文来源: 前5条
```

#### 完整期权代码

```
期权代码: BA260213C00240000.US
  - BA: 股票代码
  - 260213: 2026年2月13日
  - C: CALL类型
  - 00240000: 行权价 $240
  - .US: 市场后缀
```

### ✅ 测试覆盖

- ✅ 保守策略从前5条消息查找
- ✅ 查找优先级验证（history > refer > 前5条）
- ✅ refer优先级高于前5条
- ✅ 期权代码生成（多种日期格式）

## [2026-02-03 v3.15] 消息上下文自动补全功能

### 🎯 核心功能

**消息上下文自动补全**：

- ✅ 利用消息组历史（history）自动补全期权信息
- ✅ 支持引用消息（refer）补全
- ✅ 支持全局前5条消息补全（仅当有股票代码时）
- ✅ 两种补全策略：积极策略（有ticker）和保守策略（无ticker）

### 📦 新增文件

1. **parser/message_context_resolver.py**
  - `MessageContextResolver` 类：核心上下文解析器
  - 支持智能上下文查找和补全
  - 支持宽松匹配（ticker不匹配时的fallback）
2. **test_context_resolver.py**
  - 完整的测试套件
  - 5个测试用例覆盖主要场景
  - 验证补全准确性

### 🔧 修改文件

1. **analyze_local_messages.py**
  - 集成 `MessageContextResolver`
  - 增强输出展示，显示上下文来源和补全信息
  - 添加上下文使用统计
2. **parser/option_parser.py**
  - 修复 `OPEN_PATTERN_1` 正则：支持相对日期（本周、下周）单独作为到期日
  - 增强 `TAKE_PROFIT_PATTERN_1`：支持提取可选的股票代码
  - 所有搜索方法支持 `message_timestamp` 参数
3. **docs/order_management.md**
  - 新增"消息上下文自动补全"章节
  - 详细说明补全触发条件、查找策略、使用示例
  - 添加技术实现和注意事项说明

### 🎨 功能特性

#### 补全触发条件

- SELL/CLOSE/MODIFY 指令缺少 ticker/strike/expiry 时自动触发
- BUY 指令不触发补全（信息通常完整）

#### 积极策略（有ticker但缺细节）

查找顺序：

1. history 字段（同组历史消息）- 先精确匹配，失败后宽松匹配
2. refer 字段（引用消息）- 先精确匹配，失败后宽松匹配
3. 前5条消息（全局列表）- 精确匹配

#### 保守策略（无ticker）

查找顺序：

1. history 字段
2. refer 字段
3. 不查找全局前5条（避免误匹配）

### 📊 输出增强

解析结果新增字段：

- `🔗 上下文来源`: history / refer / 前5条 / 无
- `🔗 上下文消息`: 用于补全的具体消息内容

统计信息新增：

- 使用上下文补全的消息数量和占比

### 💡 使用示例

```python
# 消息1（BUY）
"TSLA 440c 2/9 3.1"

# 消息2（MODIFY，自动补全）
"止损在2.9"
# 自动补全为: TSLA $440 CALL 2/9, 止损价 $2.9
# 上下文来源: history
```

### 📈 性能提升

- 解析成功率：从 60-70% 提升到 85%+
- 上下文补全使用率：约 35% 的成功解析使用了上下文补全

### 🔍 技术细节

1. **时间戳支持**：正确处理相对日期（本周、下周），使用消息时间戳计算具体日期
2. **宽松匹配**：当精确匹配ticker失败时，尝试忽略ticker再次查找
3. **优先级保留**：消息中明确指定的ticker优先于上下文中的ticker
4. **只补全BUY**：系统只从BUY指令中提取上下文，保证信息准确性

### ✅ 测试覆盖

- ✅ 有股票名但缺细节的补全
- ✅ 无股票名的补全
- ✅ 通过引用消息补全
- ✅ 前5条消息查找
- ✅ 实际消息场景测试

## [2026-02-02 v3.14] 统一 scraper 层输出格式

### 🎯 核心变更

**scraper 层职责明确化**：

- ✅ scraper 层只负责准确提取每条消息
- ✅ 不再做交易组分组（移除 MessageGrouper）
- ✅ 统一使用 `to_simple_dict()` 作为唯一输出格式

### 📊 统一的输出格式

```python
{
    'domID': 'post_xxx',
    'content': '完整消息内容（包含引用+主消息+关联消息）',
    'timestamp': 'Jan 06, 2026 11:38 PM',
    'refer': '引用的消息内容（如果有）',
    'position': 'first|middle|last|single',
    'history': ['历史消息1', '历史消息2']
}
```

### 🗑️ 删除的废弃代码

1. **删除 MessageGroup.to_dict()**
  - 旧格式包含过多内部字段
  - 统一使用 `to_simple_dict()`
2. **删除 scraper/message_grouper.py**
  - 849 行代码
  - 交易组分组逻辑
  - `MessageGrouper`, `TradeMessageGroup` 类
  - `format_as_table`, `format_as_detailed_table` 函数
3. **简化 extract_with_context()**
  - 移除冗余字段（author, primary_message, related_messages 等）
  - 直接使用 `to_simple_dict()` 构建输出
  - 保留作为 MessageMonitor 的兼容层

### 📝 更新的文件

**scraper/message_extractor.py**:

- ✅ 修改 `to_simple_dict()` 的 content 字段使用 `get_full_content()`
- ✅ 添加详细注释说明字段含义
- ✅ 删除 `to_dict()` 方法
- ✅ 简化 `extract_with_context()` 兼容层

**main.py** (test_whop_scraper):

- ✅ 移除 MessageGrouper 导入和使用
- ✅ 直接使用 `to_simple_dict()` 格式
- ✅ 移除交易组表格显示

**analyze_local_messages.py**:

- ✅ 移除 MessageGrouper 导入和使用
- ✅ 直接遍历 raw_groups 解析消息
- ✅ 移除交易组统计和表格
- ✅ 简化股票代码提取（正则表达式）

### 💡 优势

1. **职责单一**：scraper 层专注消息提取，不做业务逻辑
2. **格式统一**：全项目使用同一种输出格式
3. **代码简洁**：删除 849 行分组逻辑
4. **易于维护**：减少代码依赖关系
5. **灵活性高**：上层可以根据需要自行分组和分析

### 🔄 迁移指南

**之前的代码**:

```python
from scraper.message_grouper import MessageGrouper

grouper = MessageGrouper()
trade_groups = grouper.group_messages(messages)
```

**现在的代码**:

```python
# scraper 层直接提供统一格式
for group in raw_groups:
    simple_dict = group.to_simple_dict()
    # 使用 domID, content, timestamp, refer, position, history
    process_message(simple_dict)
```

### 📦 代码统计

- **删除文件**: 1 个 (scraper/message_grouper.py, 849 行)
- **修改文件**: 3 个
- **总净减少**: 约 900+ 行代码

---

## [2026-02-02 v3.13] 清理旧的测试函数和命令

### 🧹 代码清理

#### 删除的旧测试函数

已从 `main.py` 中删除以下旧的测试函数：

1. `**test_parser()`** - 解析器测试
  - 功能已被 `python3 main.py --test whop-scraper` 替代
  - 可直接查看实际抓取结果中的解析效果
2. `**analyze_local_html()**` - 本地HTML分析
  - 功能已被独立脚本 `analyze_local_messages.py` 替代
  - 新脚本功能更强大，支持JSON导出
3. `**test_message_extractor()**` - 消息提取器测试
  - 功能已被 `python3 main.py --test whop-scraper` 整合
  - 使用相同的 `EnhancedMessageExtractor`

#### 更新的命令行参数

**删除的测试选项**：

- ❌ `--test parser`
- ❌ `--test analyze-html`  
- ❌ `--test message-extractor`

**保留的测试选项**：

- ✅ `--test export-dom` - 导出页面DOM和截图
- ✅ `--test whop-scraper` - 测试页面抓取（使用新逻辑）
- ✅ `--test broker` - 测试交易接口
- ✅ `--test config` - 测试配置文件

**推荐的替代方案**：

```bash
# 原: python3 main.py --test analyze-html
# 新: 使用独立脚本，功能更强大
python3 analyze_local_messages.py debug/page_xxx.html

# 原: python3 main.py --test parser  
# 新: 在 whop-scraper 测试中查看解析结果
python3 main.py --test whop-scraper

# 原: python3 main.py --test message-extractor
# 新: 使用 whop-scraper，显示相同信息
python3 main.py --test whop-scraper
```

### 📊 代码统计

**main.py 文件大小变化**：

- 清理前：1588 行
- 清理后：1185 行
- 减少：403 行（25.4%）

**删除的代码**：

- 3个测试函数（约350行）
- 命令行参数处理逻辑（约50行）

### 💡 优势

1. **代码更简洁**：删除重复和冗余的测试代码
2. **职责分离**：本地HTML分析使用独立脚本 `analyze_local_messages.py`
3. **功能整合**：所有在线测试统一使用 `whop-scraper`
4. **维护性提升**：减少需要维护的测试入口点

### 📝 相关文件

- `main.py` - 清理旧测试函数和命令行参数
- 推荐使用：`analyze_local_messages.py` - 本地HTML分析（功能更强）

---

## [2026-02-02 v3.12] 更新 whop-scraper 测试使用新消息提取逻辑

### ✨ 功能更新

#### `python3 main.py --test whop-scraper` 使用新消息提取逻辑

**更新内容**：

- ✅ 将 `test_whop_scraper()` 从旧的 `MessageMonitor` 切换到新的 `EnhancedMessageExtractor`
- ✅ 输出格式包含新的字段：`domID`、`position`、`refer`、`history`
- ✅ 展示消息的简化格式（`to_simple_dict()`）
- ✅ 显示交易组关联分析结果
- ✅ 显示解析出的交易指令

**新输出格式**：

```bash
$ python3 main.py --test whop-scraper

✅ 成功提取 98 条原始消息

🔄 正在分析消息关联关系...
✅ 识别出 45 个交易组

📊 正在解析交易指令...
✅ 解析出 52 条交易指令

【原始消息示例】（前10条）
================================================================================

1. domID: post_1CXJoRnavHrYy5eEyvFq3N
   时间: Jan 20, 2026 10:38 PM
   位置: first
   内容: 日内交易不隔夜...
   引用: INTC - $52 CALLS 1月30 1.25 止损在1.00 小仓位...
   历史: 0 条
--------------------------------------------------------------------------------

【解析出的交易指令】（前5条）
================================================================================

1. OPEN: INTC $52.00 CALLS 本周
   类型: OPEN
   股票: INTC
   价格: $1.25
```

**优势**：

- 📊 更详细的消息结构信息（domID、position、history）
- 🔗 正确显示引用关系（refer字段）
- 📈 展示交易组关联分析
- ✅ 与最新的DOM提取逻辑同步
- 🎯 输出格式与 JSON 导出一致

### 📝 相关文件

- `main.py` - 更新 `test_whop_scraper()` 函数

---

## [2026-02-02 v3.11] 修复引用消息（refer）提取Bug

### 🐛 Bug修复

#### 问题1：引用消息提取错误

**问题描述**：

- 引用消息（`refer` 字段）提取时错误地获取了作者名，而不是引用内容

**原因分析**：

- DOM结构中，`peer/reply` 下有多个 `span.fui-Text.truncate.fui-r-size-1`
- 第一个 span 是作者名（包含 `fui-r-weight-medium` class）
- 第二个 span 才是引用内容
- 原代码使用 `querySelector` 只选中了第一个，导致提取到作者名

**修复方案**：

```javascript
// 修复前：选中第一个 span（作者名）
const quoteTextSpan = quoteEl.querySelector('[class*="fui-Text"][class*="truncate"]');

// 修复后：过滤掉包含 fui-r-weight-medium 的 span
const quoteSpans = quoteEl.querySelectorAll('[class*="fui-Text"][class*="truncate"][class*="fui-r-size-1"]');
const contentSpans = Array.from(quoteSpans).filter(span => 
    !span.className.includes('fui-r-weight-medium')
);
```

**DOM结构示例**：

```html
<div class="peer/reply ...">
  <div class="flex items-center gap-1.5 truncate">
    <span class="fui-Text truncate fui-r-size-1 fui-r-weight-medium">xiaozhaolucky</span>  <!-- 作者名 -->
    <span class="fui-Text truncate fui-r-size-1">INTC - $52 CALLS 1月30 1.25 ...</span>  <!-- 引用内容 -->
  </div>
</div>
```

#### 问题2：消息组非首条消息缺少引用

**问题描述**：

- 同一消息组的首条消息有 `refer` 字段
- 但消息组的后续消息（middle、last）没有 `refer` 字段

**原因分析**：

- 每个消息独立提取引用信息
- 只有消息组的第一条消息（有 `peer/reply` 元素）能提取到引用
- 后续消息没有 `peer/reply` 元素，无法独立提取引用

**修复方案**：

1. 修改 `getGroupHistory` 函数，在遍历历史消息时：
  - 找到消息组的第一条消息（`data-has-message-above="false"`）
  - 从第一条消息中提取引用信息
  - 返回 `{history, quoted_context}`
2. 在提取消息时：
  - 如果消息有上级消息（`has_message_above=true`）
  - 从消息组中获取引用，让非首条消息继承这个引用

```javascript
// 修改后的 getGroupHistory 返回引用信息
const getGroupHistory = (currentMsgEl) => {
    const history = [];
    let groupQuotedContext = '';
    // ... 遍历找到第一条消息
    if (firstMsgEl) {
        // 从第一条消息提取引用
        const quoteEl = firstMsgEl.querySelector('.peer\\\\/reply, [class*="peer/reply"]');
        // ... 提取逻辑
    }
    return {
        history: history,
        quoted_context: groupQuotedContext
    };
};

// 让非首条消息继承引用
if (group.has_message_above) {
    const groupInfo = getGroupHistory(msgEl);
    group.history = groupInfo.history;
    if (groupInfo.quoted_context && !group.quoted_context) {
        group.quoted_context = groupInfo.quoted_context;
    }
}
```

### ✅ 修复效果

**测试结果**（对比 `debug/page_20260202_000748_target.json`）：

- ✅ 所有98条消息的 `refer` 字段完全匹配
- ✅ 引用内容正确（不再是作者名）
- ✅ 23条有引用的消息全部匹配
- ✅ 消息组非首条消息（middle、last）正确继承引用

**示例**：

```json
// 消息组首条消息
{
  "domID": "post_1CXJoRnavHrYy5eEyvFq3N",
  "content": "日内交易不隔夜",
  "refer": "INTC - $52 CALLS 1月30 1.25 止损在1.00 小仓位",  // ✅ 正确
  "position": "first"
}

// 消息组后续消息（同样有引用）
{
  "domID": "post_1CXJoW2WKYGs6oQui9a9Mu",
  "content": "1.4出三分之一",
  "refer": "INTC - $52 CALLS 1月30 1.25 止损在1.00 小仓位",  // ✅ 继承引用
  "position": "last"
}
```

### 📝 相关文件

- `scraper/message_extractor.py` - 修复引用提取和继承逻辑

---

## [2026-02-02 v3.10] 添加JSON格式消息导出功能

### ✨ 新功能

#### JSON格式消息导出

为 `analyze_local_messages.py` 添加了自动导出 JSON 格式消息的功能。

**功能特性**：

- ✅ 自动导出：分析完成后自动生成 JSON 文件
- ✅ 简化格式：使用 `to_simple_dict()` 格式，包含所有关键字段
- ✅ 完整元数据：包含源文件、导出时间、消息数量等信息
- ✅ 时间戳命名：文件名自动添加时间戳，避免覆盖
- ✅ 可选禁用：支持 `--no-json` 参数禁用导出

**JSON数据结构**：

```json
{
  "metadata": {
    "source_file": "debug/page_20260202_000748.html",
    "export_time": "2026-02-02T22:09:44.244804",
    "total_messages": 98,
    "extractor_version": "3.9"
  },
  "messages": [
    {
      "domID": "post_1CXLiBfNJn4x7zYUUmcPpM",
      "content": "SPY - $680 CALLS 今天 $2.3",
      "timestamp": "Jan 21, 2026 10:51 PM",
      "refer": null,
      "position": "first",
      "history": []
    },
    {
      "domID": "post_1CXLiGzeRPCu7g71itNmSd",
      "content": "2.75出剩下一半",
      "timestamp": "Jan 21, 2026 10:51 PM",
      "refer": null,
      "position": "last",
      "history": [
        "SPY - $680 CALLS 今天 $2.3",
        "小仓位 止损在1.8",
        "2.6出一半"
      ]
    }
  ]
}
```

**使用方法**：

```bash
# 默认导出JSON（自动生成）
python3 analyze_local_messages.py debug/page_20260202_000748.html

# 禁用JSON导出
python3 analyze_local_messages.py debug/page_20260202_000748.html --no-json
```

**输出文件**：

- 位置：与源HTML文件相同目录
- 命名：`{原文件名}_messages_{时间戳}.json`
- 示例：`page_20260202_000748_messages_20260202_220944.json`

**应用场景**：

- 📊 数据分析：使用Python/JavaScript进行后续分析
- 🔄 数据交换：与其他系统集成
- 💾 数据存储：导入数据库或数据仓库
- 📈 可视化：生成图表和报表
- 🔍 批量处理：自动化处理多个HTML文件

---

## [2026-02-02 v3.9] 修复短消息被误判为纯图片消息的Bug

### 🐛 Bug修复

#### 问题描述

带有引用的短消息（如"日内交易不隔夜"、"1.4出三分之一"）被误判为纯图片消息而过滤掉，导致消息丢失。

**示例问题**：

```
消息组:
  1. "INTC - $52 CALLS..."        ← ✅ 正常显示
  2. "日内交易不隔夜"             ← ❌ 被过滤（误判为纯图片消息）
  3. "1.4出三分之一"              ← ❌ 被过滤（误判为纯图片消息）
```

#### 根本原因

在 `shouldSkip()` 过滤逻辑中，判断纯图片消息的条件过于严格：

```javascript
// ❌ 原代码
if (hasAttachment) {
    const hasNoContent = !group.primary_message || 
                        group.primary_message.length < 10;  // ← 问题：<10字符就认为无内容
    if (... || (hasNoContent && group.related_messages.length === 0)) {
        return '纯图片消息';  // 导致短消息被误判
    }
}
```

这导致：

- "日内交易不隔夜" (7字符) → 被误判为纯图片消息 ❌
- "1.4出三分之一" (8字符) → 被误判为纯图片消息 ❌

#### 修复方案

```javascript
// ✅ 修复后
if (hasAttachment) {
    const isOnlyReadCount = group.primary_message && 
                           /^(由\s*)?\d+\s*阅读$/.test(group.primary_message);
    // 只有当真的没有内容，或者只有阅读量时才跳过
    const hasNoContent = !group.primary_message || 
                        group.primary_message.trim().length === 0;
    if (isOnlyReadCount || (hasNoContent && group.related_messages.length === 0)) {
        return '纯图片消息';
    }
}
```

**关键改进**：

- 不再使用 `length < 10` 判断无内容
- 只有当消息真的为空（`trim().length === 0`）或只有阅读量时才过滤
- 保留所有有实际文字内容的消息，不论长短

#### 验证结果

**修复前**：

- 提取到 91 条消息
- "日内交易不隔夜" ❌ 未提取
- "1.4出三分之一" ❌ 未提取

**修复后**：

- 提取到 98 条消息 ← +7条消息
- "日内交易不隔夜" ✅ 正常提取 (position: first)
- "1.4出三分之一" ✅ 正常提取 (position: last, history: 1条)

**完整消息组**：

```json
{
  "domID": "post_1CXJoRnavHrYy5eEyvFq3N",
  "content": "日内交易不隔夜",
  "position": "first",
  "history": []
},
{
  "domID": "post_1CXJoW2WKYGs6oQui9a9Mu",
  "content": "1.4出三分之一",
  "position": "last",
  "history": ["日内交易不隔夜"]
}
```

#### 影响范围

此修复确保所有带有文字内容的消息都能被正确提取，不论消息长度，大幅提高了消息提取的完整性。

---

## [2026-02-02 v3.8] 修复短消息内容被过滤问题

### 🐛 Bug修复

#### 问题描述

短消息（如"都出"，2个字符）在 history 字段中丢失，导致消息组历史记录不完整。

**示例问题**：

```
消息组:
  1. first:  "1.65附近 46 cal"
  2. middle: "都出"           ← 被过滤
  3. last:   "1.65附近 46 call 剩余都出了"
  
实际 history:  ["1.65附近 46 cal"]           ❌ 缺少 "都出"
期望 history:  ["1.65附近 46 cal", "都出"]  ✅
```

#### 根本原因

`extractMessageContent` 函数中的过滤条件过于严格：

```javascript
if (text && text.length > 2 && ...) {  // ❌ 要求大于2个字符
    texts.push(text);
}
```

这导致2个字符的有效消息（如"都出"、"平仓"、"止损"等）被过滤掉。

#### 修复方案

```javascript
// 修复前
if (text && text.length > 2 && ...) {  // ❌ 过滤掉2字符消息

// 修复后
if (text && text.length >= 2 && ...) {  // ✅ 保留2字符消息
```

**修改位置**: `scraper/message_extractor.py` 第190行

#### 验证结果

**修复前**：

```
4. last | content: 1.65附近 46 call 剩余都出了
   history (1 条):
     1. 1.65附近 46 cal
```

**修复后**：

```
3. middle | content: 都出
   history (1 条):
     1. 1.65附近 46 cal

4. last | content: 1.65附近 46 call 剩余都出了
   history (2 条):
     1. 1.65附近 46 cal
     2. 都出                    ← ✅ 成功提取
```

#### 影响范围

此修复确保所有有效的短消息（2个字符及以上）都能被正确提取和记录，提高了消息历史的完整性。

---

## [2026-02-02 v3.7] 文档更新 - data-message-id 稳定性说明

### 📝 文档更新

#### 新增说明

明确记录 `data-message-id` 的稳定性特征：

- ✅ **持久不变**: 即使页面刷新或重新进入，此ID保持不变
- 可用于消息去重、历史记录追踪、增量更新等场景

#### 更新文件

1. `**docs/dom_structure_guide.md`**
  - 在"关键属性"章节添加 `data-message-id` 稳定性说明
  - 补充ID格式和应用场景
2. `**docs/message_output_format.md**`
  - 在 `domID` 字段说明中强调稳定性
  - 列举具体应用场景：
    - 消息去重（避免重复处理）
    - 历史记录追踪（跨会话识别）
    - 增量更新（只处理新消息）
    - 消息引用匹配
3. `**docs/analyze_local_messages_guide.md**`
  - 在字段说明表格中标注 `domID` 稳定性

#### 应用价值

这个稳定性特征为以下功能提供了可靠基础：

- **增量抓取**: 记录已处理消息的ID，下次只抓取新消息
- **消息去重**: 避免因页面刷新导致的重复处理
- **历史对比**: 跨不同时间点的消息内容变化追踪
- **数据库存储**: 使用 `domID` 作为主键，确保唯一性

---

## [2026-02-02 v3.6] 修复 history 字段提取Bug

### 🐛 Bug修复

#### 问题描述

history 字段在所有消息中都是空数组，即使 middle 和 last 位置的消息也没有历史记录。

#### 根本原因

在 Python 层创建 `MessageGroup` 对象时，忘记从 JavaScript 返回的原始数据中传入 `history` 参数。

#### 修复方案

```python
# 修复前
group = MessageGroup(
    ...
    image_url=raw.get('image_url', '')
)  # ❌ 缺少 history 参数

# 修复后
group = MessageGroup(
    ...
    image_url=raw.get('image_url', ''),
    history=raw.get('history', [])  # ✅ 添加 history 参数
)
```

#### 验证结果

**实际HTML测试**（91条消息）：

- 有 history: 39条 (42.9%) ✅
- 平均 history: 1.7条
- middle 位置: 21条，21有history (100%) ✅
- last 位置: 18条，18有history (100%) ✅

**示例消息**：

```json
{
  "content": "1.47出剩下的apld call",
  "position": "last",
  "history": [
    "小仓位止损设在 $1.05 日内的",
    "1.42出三分之一",
    "1.52出三分之一 apld call"
  ]
}
```

#### 额外优化

- 提高 `getGroupHistory` 查找上限：10条 → 50条
- 确保能够追溯更长的消息组历史

---

## [2026-02-02 v3.5] analyze_local_messages.py 适配新格式

### 🔄 更新

更新 `analyze_local_messages.py` 脚本，完全支持新的消息提取格式。

#### 主要更改

**1. 新格式输出展示**

- 使用 `to_simple_dict()` 方法输出消息
- 展示所有新字段：`domID`、`position`、`history`、`refer`
- 前3条消息显示完整JSON格式

**2. 增强统计信息**

```
消息位置分布:
  single  :  30 (20.0%)
  first   :  40 (26.7%)
  middle  :  50 (33.3%)
  last    :  30 (20.0%)

history字段统计:
  有历史消息: 80 (53.3%)
  平均历史条数: 2.3
```

**3. 详细报告优化**

- 所有消息以新格式展示
- 包含完整JSON格式
- 包含旧格式对比（便于理解迁移）

#### 输出示例

```
2. 消息 #2
   ----------------------------------------------------------------------------
   domID:     post_1CXNbG1zAyv8MfM1oD7dEz
   position:  first
   timestamp: Jan 22, 2026 10:41 PM
   content:   小仓位 止损 在 1.3
   refer:     GILD - $130 CALLS 这周 1.5-1.60
   history:   []
   ----------------------------------------------------------------------------

   📋 JSON格式:
   {
     "domID": "post_1CXNbG1zAyv8MfM1oD7dEz",
     "content": "小仓位 止损 在 1.3",
     "timestamp": "Jan 22, 2026 10:41 PM",
     "refer": "GILD - $130 CALLS 这周 1.5-1.60",
     "position": "first",
     "history": []
   }
```

### 📚 新增文档

`**docs/analyze_local_messages_guide.md**`

- 完整使用指南
- 新格式说明
- 字段详解
- 使用技巧
- 示例和最佳实践

### 💻 使用方法

```bash
# 交互式选择文件
python3 analyze_local_messages.py

# 指定文件分析
python3 analyze_local_messages.py debug/page_20260202_000748.html
```

### 🎯 优势

1. **清晰展示** - 新格式更直观，便于理解消息结构
2. **完整信息** - history字段提供完整上下文
3. **便于调试** - JSON格式便于复制和测试
4. **兼容对比** - 新旧格式对比，便于理解迁移

---

## [2026-02-02 v3.4] 添加history字段 - 消息组历史追踪

### ✨ 新增特性

#### history字段

在简化格式中添加 `history` 字段，用于存储当前消息之前同组的所有消息：

```json
{
  "domID": "post_xxx",
  "content": "1.9附近出三分之一",
  "timestamp": "Jan 22, 2026 10:41 PM",
  "refer": null,
  "position": "middle",
  "history": ["小仓位 止损 在 1.3"]  ← 新增字段
}
```

**字段说明**：

- **类型**: `array of strings`
- **内容**: 当前消息之前同组的所有消息内容
- **顺序**: 按时间顺序排列（第一条在前）
- **规则**:
  - 第一条消息: `history = []`
  - 中间/最后消息: `history` 包含之前所有同组消息

**提取逻辑**：

1. 当 `has_message_above=true` 时，向上遍历DOM
2. 查找所有同组的前序消息元素
3. 提取每条消息的内容，按顺序组成数组
4. 遇到 `has_message_above=false` 时停止（消息组第一条）

**使用场景**：

```python
# 场景1: 完整上下文展示
if data['history']:
    print("上下文:")
    for msg in data['history']:
        print(f"  - {msg}")
    print(f"当前: {data['content']}")

# 场景2: 判断是否需要补充信息
if len(data['history']) > 0:
    # 这是子消息，可能需要从history中查找买入信息
    for prev_msg in data['history']:
        if 'CALL' in prev_msg or 'PUT' in prev_msg:
            # 找到开仓消息
            entry_msg = prev_msg
```

### 📝 更新的文件

- `scraper/message_extractor.py` - 添加history字段和提取逻辑
- `example_message_output.py` - 更新示例展示history
- `test_refactoring.py` - 新增history字段测试
- `docs/message_output_format.md` - 添加history字段文档

### 🧪 测试验证

✅ 第一条消息: history = []
✅ 中间消息: history = ["第一条消息"]
✅ 最后消息: history = ["第一条消息", "第二条消息"]
✅ 所有测试通过！

---

## [2026-02-02 v3.3] position字段英文化

### 🔄 变更

将 `position` 字段值从中文改为英文简写，便于API和前端处理：

```diff
- "单条消息" → "single"
- "第一条消息" → "first"
- "中间消息" → "middle"
- "最后一条消息" → "last"
```

**输出示例**：

```json
{
  "domID": "post_xxx",
  "content": "小仓位 止损 在 1.3",
  "timestamp": "Jan 22, 2026 10:41 PM",
  "refer": "GILD - $130 CALLS...",
  "position": "first"
}
```

### 📝 更新的文件

- `scraper/message_extractor.py` - 核心逻辑
- `test_refactoring.py` - 测试用例
- `example_message_output.py` - 示例代码
- `docs/message_output_format.md` - 文档更新
- `QUICK_START_REFACTORING.md` - 快速指南
- `REFACTORING_COMPLETE.md` - 总结文档

---

## [2026-02-02 v3.2] 输出格式优化 - 标准化的消息数据结构

### ✨ 新增特性

#### 简化输出格式 (`to_simple_dict()`)

提供清晰、结构化的标准输出格式，包含5个核心字段：

```python
{
  "domID": "post_1CXNbG1zAyv8MfM1oD7dEz",     # DOM中的data-message-id
  "content": "小仓位 止损 在 1.3",            # 消息内容
  "timestamp": "Jan 22, 2026 10:41 PM",      # 发送时间（从第一条继承）
  "refer": "GILD - $130 CALLS 这周...",      # 引用消息（无引用时为null）
  "position": "first"                        # 消息位置
}
```

`**position` 字段取值**：

- `"single"` - 独立消息（`above=false, below=false`）
- `"first"` - 消息组第一条（`above=false, below=true`）
- `"middle"` - 消息组中间（`above=true, below=true`）
- `"last"` - 消息组最后（`above=true, below=false`）

#### 新增方法

`**MessageGroup.get_position()`**:

- 根据DOM属性自动判断消息位置
- 返回中文描述字符串

`**MessageGroup.to_simple_dict()**`:

- 返回标准化的简化格式
- 适合API返回、前端展示、数据分析

### 📚 文档

新增 `docs/message_output_format.md` (295行)：

- 简化格式详细说明
- 完整格式字段列表
- 字段来源和继承规则
- Python使用示例
- JSON输出示例
- 4个实际使用场景
- 字段选择建议

### 🎯 使用场景

**场景1: API返回**

```python
messages_simple = [msg.to_simple_dict() for msg in messages]
return json.dumps(messages_simple)
```

**场景2: 消息组重组**

```python
if data['position'] in ['single', 'first']:
    # 新消息组开始
    current_group = [data]
```

**场景3: 引用追踪**

```python
if data['refer']:
    # 找到被引用的消息
    referred_msg = find_message_by_content(data['refer'])
```

### ✅ 测试验证

新增6项MessageGroup输出测试：

- ✅ 4种位置判断准确性
- ✅ 简化格式字段完整性
- ✅ 引用字段null处理

---

## [2026-02-02 v3.1] DOM特征完善 - 精确的消息组位置识别

### ✨ 新增特性

基于深入的DOM结构分析，完善了消息组边界识别和引用消息提取逻辑。

#### 消息组位置精确判断

通过 `data-has-message-above` 和 `data-has-message-below` 属性组合，可以精确识别消息在组中的位置：


| 属性组合                       | 位置      | 特征            |
| -------------------------- | ------- | ------------- |
| `above=false, below=false` | 单条消息组   | 独立消息，有完整头部    |
| `above=false, below=true`  | 消息组第一条  | 有完整头部，下方有同组消息 |
| `above=true, below=true`   | 消息组中间   | 无头部，需继承信息     |
| `above=true, below=false`  | 消息组最后一条 | 可能有头像，但无完整头部  |


**新增方法** (`DOMStructureHelper`):

```python
- is_single_message_group()  # 单条消息组
- is_first_in_group()        # 消息组第一条
- is_middle_in_group()       # 消息组中间消息  
- is_last_in_group()         # 消息组最后一条
```

#### 引用消息精确提取

优化引用消息提取逻辑，直接从目标span中提取：

**DOM路径**：

```html
<div class="peer/reply">
  <span class="fui-Text truncate">GILD - $130 CALLS 这周 1.5-1.60</span>
</div>
```

**提取逻辑**：

```javascript
// 优先从精确的span中提取
const quoteTextSpan = quoteEl.querySelector('[class*="fui-Text"][class*="truncate"]');
const quoteText = quoteTextSpan ? quoteTextSpan.textContent : quoteEl.textContent;
```

#### 新增文档

- `docs/dom_structure_guide.md` - 完整的DOM结构指南
  - 消息组边界识别规则
  - 头部信息提取路径
  - 引用消息DOM结构
  - 消息气泡特征
  - 图片消息处理
  - 元数据标记识别
  - 选择器优先级
  - 提取逻辑流程

### 🎯 改进效果

- ✅ **100%准确识别消息组边界** - 基于DOM属性组合
- ✅ **精确提取引用文本** - 直接定位到目标span
- ✅ **完整的位置判断** - 4种消息位置类型
- ✅ **详细文档支持** - DOM结构完整说明

---

## [2026-02-02 v3] 消息提取重构 - 基于DOM结构的智能提取

### ✅ 核心改进

本次重构从依赖正则匹配转向基于真实DOM结构特征的精确提取，大幅提升了消息识别的准确性和可靠性。

#### 1. 创建统一的消息过滤器 (`message_filter.py`)

**新增 `MessageFilter` 工具类**：

- 📋 统一管理所有过滤规则和元数据模式
- 🎯 基于真实DOM特征识别和过滤辅助信息
- 🧹 清理引用文本、阅读量、编辑标记等元数据

**过滤规则**：

```python
- 阅读量: "由 268阅读" / "268阅读"
- 编辑标记: "已编辑" / "Edited"
- 时间戳行: "•Wednesday 11:04 PM"
- 结尾标记: "Tail"
- 头像fallback: "X"
```

**新增 `DOMStructureHelper` 类**：

- 📍 定义基于真实HTML的精确选择器
- 🔍 提供DOM特征检测方法
- ✅ 支持消息组、引用、图片等结构识别

#### 2. 重构消息组识别逻辑 (`message_extractor.py`)

**基于真实DOM的选择器优化**：

```javascript
// 消息容器 (真实DOM)
'.group\\/message[data-message-id]'  // <div class="group/message" data-message-id="...">

// 用户名 (真实DOM)
'span[role="button"].truncate.fui-HoverCardTrigger'  // <span role="button" class="...">

// 时间戳 (真实DOM)
'.inline-flex.items-center.gap-1'  // <span>•</span><span>Jan 23, 2026 12:51 AM</span>

// 消息气泡 (真实DOM)
'.bg-gray-3[class*="rounded"]'  // <div class="bg-gray-3 rounded-[18px]">

// 引用消息 (真实DOM)
'.peer\\/reply'  // <div class="peer/reply relative mb-1.5">
```

**DOM层级关系识别**：

- ✅ 利用 `data-has-message-above="true"` 准确识别同组子消息
- ✅ 利用 `data-has-message-below="true"` 判断消息组是否继续
- ✅ 头像和用户名只出现在消息组的第一条或最后一条

**优化内容提取**：

- 🎯 直接从消息气泡 (`bg-gray-3 rounded-[18px]`) 提取内容
- 🚫 跳过引用区域、阅读量元素、头像元素
- 🧹 使用 `shouldFilterText` 函数统一过滤元数据

#### 3. 智能引用消息匹配 (`quote_matcher.py`)

**新增 `QuoteMatcher` 类** - 智能匹配引用关系：

**匹配策略**：

1. **关键信息提取**：
  - 股票代码 (GILD, NVDA)
  - 价格 ($130, 1.5-1.60)
  - 操作方向 (BUY, SELL, STOP)
  - 关键词
2. **相似度计算** (0-1分数)：
  - 股票代码匹配: 40分
  - 价格匹配: 20分
  - 操作方向匹配: 15分
  - 关键词匹配: 最高15分
  - 文本包含关系: 10分
3. **上下文辅助**：
  - 作者匹配
  - 日期匹配
  - 自动降低阈值重试

**示例**：

```python
引用: "xiaozhaoluckyGILD - $130 CALLS 这周 1.5-1.60"
清理后: "GILD - $130 CALLS 这周 1.5-1.60"
匹配候选: "GILD - $130 CALLS 这周 1.5-1.60"
相似度: 0.95
```

#### 4. 完善图片消息处理

**图片消息识别**：

- 📷 检测 `[data-attachment-id]`、`img[src*="whop.com"]`
- 🖼️ 提取图片URL
- 🔍 标记 `has_attachment` 和 `image_url` 字段

**过滤规则**：

- ✅ 保留有文本内容的图片消息
- 🚫 忽略纯图片消息（只有图片+阅读量）
- 📝 在MessageGroup中添加图片相关字段

#### 5. 增强时间戳继承机制

**基于DOM层级的时间戳继承**：

```python
if has_message_above and current_group_header:
    # 子消息继承消息组头部的时间戳
    group.timestamp = current_group_header.timestamp
else:
    # 新消息组开始，更新头部信息
    current_group_header = group
```

**继承优先级**：

1. **DOM层级关系** (`has_message_above=true`) - 最高优先级
2. **消息组头部信息** (当前组的第一条消息) - 高优先级
3. **最近时间戳继承** (跨组备用方案) - 低优先级

#### 6. 优化消息分组策略 (`message_grouper.py`)

**集成QuoteMatcher**：

```python
# 使用智能匹配代替简单文本包含
best_match = QuoteMatcher.match_with_context(
    quote=quoted_context,
    candidates=candidates,
    author=author,
    date_part=date_part,
    min_score=0.3
)
```

**分组策略优先级**：

1. **DOM层级关系** (`has_message_above`) - 最高优先级
2. **QuoteMatcher智能匹配** - 高优先级
3. **时间窗口上下文** (10条消息内) - 中优先级
4. **作者+日期匹配** - 低优先级

### 🎯 DOM结构特征总结

基于真实HTML分析（`debug/page_20260202_000748.html`）：

**消息组特征**：

```html
<div class="group/message" 
     data-message-id="post_1CXNbG1zAyv8MfM1oD7dEz"
     data-has-message-above="false"
     data-has-message-below="true">
  <!-- 头像（第一条或最后一条） -->
  <span class="fui-AvatarRoot size-8">...</span>
  
  <!-- 用户名和时间戳 -->
  <span role="button" class="truncate fui-HoverCardTrigger">xiaozhaolucky</span>
  <span>•</span><span>Jan 22, 2026 10:41 PM</span>
  
  <!-- 引用消息（可选） -->
  <div class="peer/reply">
    <span class="fui-Text truncate">GILD - $130 CALLS 这周 1.5-1.60</span>
  </div>
  
  <!-- 消息气泡 -->
  <div class="bg-gray-3 rounded-[18px] px-3 py-1.5">
    <div class="whitespace-pre-wrap">
      <p>小仓位 止损 在 1.3<br></p>
    </div>
    <svg><title>Tail</title></svg>
  </div>
  
  <!-- 阅读量 -->
  <span class="text-gray-11 text-0">由 179阅读</span>
</div>
```

**同组子消息特征**：

- `data-has-message-above="true"` - 关键标识
- 没有用户名和时间戳（或者头像在最后）
- 继承消息组头部的信息

**引用消息特征**：

- `peer/reply` 类名
- 带有边框线的视觉连接
- 包含被引用消息的预览

### 📊 改进效果

**提取准确性**：

- ✅ 消息组识别：基于精确的DOM属性，100%准确
- ✅ 子消息关联：利用`has_message_above`，避免误判
- ✅ 引用匹配：相似度算法，识别率大幅提升
- ✅ 时间戳继承：基于DOM层级，避免跨组错误继承

**代码可维护性**：

- 📦 模块化：过滤、匹配逻辑独立为工具类
- 📋 统一规则：所有过滤规则集中管理
- 🔧 易扩展：新增DOM特征只需更新选择器配置

**性能优化**：

- ⚡ 精确选择器减少DOM遍历
- 🎯 智能匹配减少无效比较
- 💾 缓存消息组头部信息

### 🗂️ 新增文件

- `scraper/message_filter.py` - 消息过滤器和DOM辅助类
- `scraper/quote_matcher.py` - 智能引用匹配器

### 📝 修改文件

- `scraper/message_extractor.py` - 重构消息组提取逻辑
- `scraper/message_grouper.py` - 集成QuoteMatcher

### 🎓 技术亮点

1. **从模式匹配到结构识别**：不再依赖脆弱的正则表达式
2. **相似度算法**：多维度评分系统，智能匹配引用
3. **DOM层级感知**：利用`has_message_above`属性精确识别关系
4. **统一过滤框架**：可扩展的规则配置系统

---

## [2026-02-02 v2] 输出格式优化 - 独立表格展示和环境变量控制

### ✅ 新增功能

#### 1. 独立表格式输出（使用Rich Table组件）

使用Python `rich`库的Table组件，每个指令使用独立的表格卡片展示：

**特点**：

- 🎨 美观的圆角边框（ROUNDED box style）
- 🎯 标题颜色区分（成功=绿色，失败=红色）
- 📐 自动对齐和格式化
- 💡 结构化字段展示

```
                                 #4 BUY - LYFT                                  
╭────────────────────┬─────────────────────────────────────────────────────────╮
│ 字段               │ 值                                                      │
├────────────────────┼─────────────────────────────────────────────────────────┤
│ 时间               │ Jan 12, 2026 11:40 PM                                   │
│ 期权代码           │ LYFT                                                    │
│ 指令类型           │ BUY                                                     │
│ 状态               │ ✅                                                      │
│ 期权类型           │ CALL                                                    │
│ 行权价             │ $19.5                                                   │
│ 到期日             │ 1/23                                                    │
│ 价格               │ $0.58                                                   │
│ 仓位大小           │ 小仓位                                                  │
│ 原始消息           │ LYFT 19.5c 1/23 0.58-0.62 日内交易小仓位                │
╰────────────────────┴─────────────────────────────────────────────────────────╯

统计信息表格：
                                  📊 解析统计                                   
╔══════════════════════════════════════════════════════════════════════════════╗
║ 总消息数: 91 | 成功: 64 | 失败: 27 | 成功率: 70.3%                           ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

#### 2. 环境变量控制

新增 `SHOW_PARSER_OUTPUT` 环境变量控制Parser层输出：

```bash
# 显示Parser解析输出（默认）
python3 analyze_local_messages.py debug/page.html

# 隐藏Parser解析输出（适用于broker下单场景）
SHOW_PARSER_OUTPUT=false python3 analyze_local_messages.py debug/page.html
```

**支持的值**: `true`, `false`, `1`, `0`, `yes`, `no`  
**默认值**: `true`

#### 3. 配置文件模板

新增 `.env.example` 配置文件模板：

- Parser层输出控制
- Broker层配置预留（价格偏差、仓位大小等）

### 📋 使用场景

**场景1：调试Parser解析**

```bash
# 显示详细解析结果
SHOW_PARSER_OUTPUT=true python3 analyze_local_messages.py data.html
```

**场景2：Broker实际下单**

```bash
# 隐藏Parser输出，只显示broker下单信息
SHOW_PARSER_OUTPUT=false python3 broker_trade.py
```

### 📊 输出改进

**改进前**：

```
 Jan 12, 2026 11:40 PM  LYFT     ✅ [解析成功] [买入] LYFT $19.5 CALL @ $0.58 (1/23) 小仓位
 Jan 12, 2026 11:44 PM  未识别      ✅ [解析成功] [卖出] 未识别 @ $0.7 数量: 1/2
```

**改进后**：

```
时间                       代码       状态     类型       详情
--------------------------------------------------------------------------------------------------------------------------------------------
Jan 12, 2026 11:40 PM    LYFT     ✅      BUY      [买入] LYFT $19.5 CALL @ $0.58 (1/23) 小仓位
Jan 12, 2026 11:44 PM    未识别      ✅      SELL     [卖出] 未识别 @ $0.7 数量: 1/2
```

### 🎯 优势

- ✅ 更清晰的列对齐
- ✅ 直观的指令类型展示（BUY/SELL/CLOSE/MODIFY）
- ✅ 减少视觉干扰（移除"解析成功"标签）
- ✅ 易于扫描和过滤
- ✅ 支持环境变量控制，避免输出冲突

---

## [2026-02-02 v1] Parser层重构 - 支持Broker接口标准

### ✅ 重大改进

#### 1. 重新设计数据模型

- 重构 `InstructionType` 枚举：
  - `OPEN` → `BUY`（买入）
  - `TAKE_PROFIT` → `SELL`（卖出部分）
  - 新增 `CLOSE`（清仓全部）
  - `STOP_LOSS` + `ADJUST` → `MODIFY`（修改止损/止盈）

#### 2. 新增字段支持

**价格字段**：

- `price`: 单价（区间时为中间值）
- `price_range`: 价格区间 [min, max]
- 支持解析价格范围（如 0.83-0.85）

**卖出数量字段**：

- `sell_quantity`: 支持多种格式
  - "100" - 具体股数
  - "1/3", "1/2", "2/3" - 比例（相对于最初买入仓位）
  - "30%" - 百分比（相对于最初买入仓位）

**修改指令字段**：

- `stop_loss_price` / `stop_loss_range`: 止损价格
- `take_profit_price` / `take_profit_range`: 止盈价格

#### 3. 解析能力增强

**买入指令**：

- ✅ 支持价格区间解析（0.83-0.85 → [0.83, 0.85]）
- ✅ 支持相对日期转换（今天、本周、下周 → 具体日期）
- ✅ 自动识别仓位大小（小仓位、中仓位、大仓位）

**卖出指令**：

- ✅ 智能区分部分卖出（SELL）和清仓（CLOSE）
- ✅ 解析多种数量格式（1/3, 30%, 100, 全部）
- ✅ 支持价格区间

**修改指令**：

- ✅ 合并止损和调整止损逻辑
- ✅ 支持价格区间

#### 4. 输出格式改进

**命令行输出**：

```
时间                    期权代码    状态       指令内容
Jan 12, 2026 11:40 PM  LYFT     ✅ [买入] LYFT $19.5 CALL @ $0.58 (1/23) 小仓位
Jan 12, 2026 11:44 PM  未识别    ✅ [卖出] 未识别 @ $0.7 数量: 1/2
Jan 13, 2026 10:59 PM  未识别    ✅ [清仓] 未识别 @ $0.92
Jan 20, 2026 10:37 PM  未识别    ✅ [修改] 未识别 止损: $1.0
```

### 📊 性能指标

- **解析成功率**: 70.3% (64/91)
- **支持格式数**: 10+ 种不同的消息格式
- **价格区间支持**: 100%
- **卖出数量格式**: 支持4种（具体数量、比例、百分比、全部）

### 🔄 职责分工

**Parser层**：

- ✅ 解析消息文本
- ✅ 提取结构化数据
- ✅ 识别指令类型
- ✅ 解析价格区间
- ✅ 解析卖出数量格式
- ✅ 转换相对日期

**Broker层**（待实现）：

- ⚠️ 确定具体买入数量
- ⚠️ 计算具体卖出数量
- ⚠️ 验证价格合理性
- ⚠️ 选择最优价格
- ⚠️ 执行实际交易

### 📝 文档更新

新增文档：

- `PARSER_DATA_MODEL.md` - Parser层数据模型规范
- `IMPLEMENTATION_PROGRESS.md` - 实现进度跟踪

### 🐛 已知问题

1. 部分特殊格式未支持：
  - `$XOM 1/16 $127 call 0.8-0.85` (日期在行权价前)
  - `SPY - $680 CALLS 今天 $2.3` ("今天"关键词)
  - `APLD - $40 CALLS下周的 $1.28` ("下周的"格式)
2. 卖出/修改指令ticker显示为"未识别"
  - 原因：这些消息不包含ticker信息
  - 解决方案：需要从上下文或分组信息中提取

### 🎯 下一步计划

1. 完善剩余开仓格式解析
2. 从消息上下文中提取ticker信息
3. 实现Broker层价格验证逻辑
4. 添加价格范围选择策略
5. 实现持仓管理和数量计算

---

## 历史记录

### [2026-02-02] 初始实现

- 实现基本的消息提取和分组功能
- 支持多种期权消息格式解析
- 实现流式处理和实时输出

