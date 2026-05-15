# LongPort OpenAPI 文档索引

> 来源：<https://open.longbridge.com/zh-CN/docs>
> 整理日期：2026-05-15
> 共 144 个文档页面，所有路径前缀为 `https://open.longbridge.com`

## 目录

1. [入门与通用](#1-入门与通用)
2. [行情 quote](#2-行情-quote)
3. [基本面 fundamental](#3-基本面-fundamental)
4. [资讯与社区 content](#4-资讯与社区-content)
5. [交易 trade](#5-交易-trade)
6. [账户 account](#6-账户-account)
7. [长连接协议 socket](#7-长连接协议-socket)
8. [常见问题 qa](#8-常见问题-qa)

---

## 1. 入门与通用

| 标题 | 路径 |
|---|---|
| 快速开始 | /zh-CN/docs/getting-started |
| API 参考 | /zh-CN/docs/api |
| 更新日志 | /zh-CN/docs/changelog |
| CLI | /zh-CN/docs/cli |
| MCP | /zh-CN/docs/mcp |
| LLMs | /zh-CN/docs/llm |
| 获取长连接 OTP | /zh-CN/docs/socket-token-api |

## 2. 行情 quote

### 概览

| 标题 | 路径 |
|---|---|
| 概览 | /zh-CN/docs/quote/overview |
| 命名词典 | /zh-CN/docs/quote/objects |
| 标的列表 | /zh-CN/docs/quote/security/security_list |

### 拉取行情 pull

| 标题 | 路径 |
|---|---|
| 标的基础信息 | /zh-CN/docs/quote/pull/static |
| 标的实时行情 | /zh-CN/docs/quote/pull/quote |
| 期权实时行情 | /zh-CN/docs/quote/pull/option-quote |
| 轮证实时行情 | /zh-CN/docs/quote/pull/warrant-quote |
| 标的盘口 | /zh-CN/docs/quote/pull/depth |
| 标的经纪队列 | /zh-CN/docs/quote/pull/brokers |
| 券商席位 ID | /zh-CN/docs/quote/pull/broker-ids |
| 轮证发行商 ID | /zh-CN/docs/quote/pull/issuer |
| 标的成交明细 | /zh-CN/docs/quote/pull/trade |
| 标的当日分时 | /zh-CN/docs/quote/pull/intraday |
| 标的 K 线 | /zh-CN/docs/quote/pull/candlestick |
| 标的历史 K 线 | /zh-CN/docs/quote/pull/history-candlestick |
| 标的的期权链到期日列表 | /zh-CN/docs/quote/pull/optionchain-date |
| 标的的期权链到期日期权标的列表 | /zh-CN/docs/quote/pull/optionchain-date-strike |
| 期权成交量 | /zh-CN/docs/quote/pull/option-volume |
| 期权历史成交量 | /zh-CN/docs/quote/pull/option-volume-daily |
| 轮证筛选列表 | /zh-CN/docs/quote/pull/warrant-filter |
| 市场交易日 | /zh-CN/docs/quote/pull/trade-day |
| 各市场当日交易时段 | /zh-CN/docs/quote/pull/trade-session |
| 标的当日资金流向 | /zh-CN/docs/quote/pull/capital-flow-intraday |
| 标的当日资金分布 | /zh-CN/docs/quote/pull/capital-distribution |
| 标的计算指标 | /zh-CN/docs/quote/pull/calc-index |
| 标的公告 | /zh-CN/docs/quote/pull/filings |
| 做空数据 | /zh-CN/docs/quote/pull/short-positions |
| 当前市场温度 | /zh-CN/docs/quote/pull/market_temperature |
| 历史市场温度 | /zh-CN/docs/quote/pull/history_market_temperature |

### 订阅 subscribe

| 标题 | 路径 |
|---|---|
| 订阅行情数据 | /zh-CN/docs/quote/subscribe/subscribe |
| 取消订阅行情数据 | /zh-CN/docs/quote/subscribe/unsubscribe |
| 已订阅标的行情 | /zh-CN/docs/quote/subscribe/subscription |

### 推送 push

| 标题 | 路径 |
|---|---|
| 实时价格推送 | /zh-CN/docs/quote/push/quote |
| 实时盘口推送 | /zh-CN/docs/quote/push/depth |
| 实时经纪队列推送 | /zh-CN/docs/quote/push/broker |
| 实时成交明细推送 | /zh-CN/docs/quote/push/trade |

### 自选股 watchlist

| 标题 | 路径 |
|---|---|
| 自选股分组 | /zh-CN/docs/quote/watchlist/watchlist_groups |
| 创建自选股分组 | /zh-CN/docs/quote/watchlist/watchlist_create_group |
| 更新自选股分组 | /zh-CN/docs/quote/watchlist/watchlist_update_group |
| 删除自选股分组 | /zh-CN/docs/quote/watchlist/watchlist_delete_group |
| 更新置顶证券 | /zh-CN/docs/quote/watchlist/update-pinned |

## 3. 基本面 fundamental

### 概览

| 标题 | 路径 |
|---|---|
| 概览 | /zh-CN/docs/fundamental/overview |

### 公司基本面 fundamental

| 标题 | 路径 |
|---|---|
| 公司概况 | /zh-CN/docs/fundamental/fundamental/company-profile |
| 高管团队 | /zh-CN/docs/fundamental/fundamental/executives |
| 主要股东 | /zh-CN/docs/fundamental/fundamental/shareholders |
| 投资关系 | /zh-CN/docs/fundamental/fundamental/invest-relation |
| 公司行动 | /zh-CN/docs/fundamental/fundamental/corporate-actions |
| 财务报告 | /zh-CN/docs/fundamental/fundamental/financial-report |
| 经营数据 | /zh-CN/docs/fundamental/fundamental/operating |
| 估值指标 | /zh-CN/docs/fundamental/fundamental/valuations |
| 估值历史 | /zh-CN/docs/fundamental/fundamental/valuation-history |
| 行业估值对比 | /zh-CN/docs/fundamental/fundamental/industry-valuation |
| 行业估值分布 | /zh-CN/docs/fundamental/fundamental/industry-valuation-dist |
| 分红历史 | /zh-CN/docs/fundamental/fundamental/dividends |
| 分红详情 | /zh-CN/docs/fundamental/fundamental/dividend-detail |
| 回购数据 | /zh-CN/docs/fundamental/fundamental/buyback |
| EPS 预测 | /zh-CN/docs/fundamental/fundamental/forecast-eps |
| 分析师评级 | /zh-CN/docs/fundamental/fundamental/ratings |
| 机构评级 | /zh-CN/docs/fundamental/fundamental/institution-rating |
| 机构评级详情 | /zh-CN/docs/fundamental/fundamental/institution-rating-detail |
| 机构共识 | /zh-CN/docs/fundamental/fundamental/consensus |
| 基金持仓 | /zh-CN/docs/fundamental/fundamental/fund-holdings |

### 日历 calendar

| 标题 | 路径 |
|---|---|
| 财报日历 | /zh-CN/docs/fundamental/calendar/earnings-calendar |
| 分红日历 | /zh-CN/docs/fundamental/calendar/dividend-calendar |
| 拆股日历 | /zh-CN/docs/fundamental/calendar/split-calendar |
| IPO 日历 | /zh-CN/docs/fundamental/calendar/ipo-calendar |
| 宏观日历 | /zh-CN/docs/fundamental/calendar/macro-calendar |

### 市场数据 market

| 标题 | 路径 |
|---|---|
| 市场状态 | /zh-CN/docs/fundamental/market/market-status |
| 成交统计 | /zh-CN/docs/fundamental/market/trading-stats |
| 异动行情 | /zh-CN/docs/fundamental/market/unusual-items |
| 指数成分股 | /zh-CN/docs/fundamental/market/index-components |
| A/H 溢价 | /zh-CN/docs/fundamental/market/ah-premium |
| A/H 溢价盘中数据 | /zh-CN/docs/fundamental/market/ah-premium-intraday |
| 经纪商持仓 | /zh-CN/docs/fundamental/market/broker-positions |
| 经纪商持仓详情 | /zh-CN/docs/fundamental/market/broker-holding-detail |
| 经纪商每日持仓历史 | /zh-CN/docs/fundamental/market/broker-holding-daily |

## 4. 资讯与社区 content

### 资讯 news

| 标题 | 路径 |
|---|---|
| 个股资讯 | /zh-CN/docs/content/news/news |

### 股单 sharelist

| 标题 | 路径 |
|---|---|
| 自选列表 | /zh-CN/docs/content/sharelist/list-sharelist |
| 创建自选列表 | /zh-CN/docs/content/sharelist/create-sharelist |
| 更新自选列表 | /zh-CN/docs/content/sharelist/update-sharelist |
| 删除自选列表 | /zh-CN/docs/content/sharelist/delete-sharelist |
| 股单详情 | /zh-CN/docs/content/sharelist/sharelist-detail |
| 添加标的到股单 | /zh-CN/docs/content/sharelist/add-securities |
| 从股单移除标的 | /zh-CN/docs/content/sharelist/remove-securities |
| 股单标的排序 | /zh-CN/docs/content/sharelist/sort-securities |
| 热门股单 | /zh-CN/docs/content/sharelist/popular-sharelist |

### 讨论 topics

| 标题 | 路径 |
|---|---|
| 标的社区讨论 | /zh-CN/docs/content/topics/topics |
| 讨论详情 | /zh-CN/docs/content/topics/topic-detail |
| 讨论回复 | /zh-CN/docs/content/topics/topic-replies |
| 创建讨论 | /zh-CN/docs/content/topics/create-topic |
| 创建讨论回复 | /zh-CN/docs/content/topics/create-topic-reply |
| 我的讨论 | /zh-CN/docs/content/topics/my-topics |

## 5. 交易 trade

### 概览

| 标题 | 路径 |
|---|---|
| 概览 | /zh-CN/docs/trade/trade-overview |
| 交易命名词典 | /zh-CN/docs/trade/trade-definition |
| 交易推送 | /zh-CN/docs/trade/trade-push |

### 订单 order

| 标题 | 路径 |
|---|---|
| 委托下单 | /zh-CN/docs/trade/order/submit |
| 修改订单 | /zh-CN/docs/trade/order/replace |
| 撤销订单 | /zh-CN/docs/trade/order/withdraw |
| 当日订单 | /zh-CN/docs/trade/order/today_orders |
| 历史订单 | /zh-CN/docs/trade/order/history_orders |
| 订单详情 | /zh-CN/docs/trade/order/order_detail |
| 预估最大购买数量 | /zh-CN/docs/trade/order/estimate_available_buy_limit |

### 成交 execution

| 标题 | 路径 |
|---|---|
| 当日成交明细 | /zh-CN/docs/trade/execution/today_executions |
| 历史成交明细 | /zh-CN/docs/trade/execution/history_executions |

### 资产 asset

| 标题 | 路径 |
|---|---|
| 账户资金 | /zh-CN/docs/trade/asset/account |
| 资金流水 | /zh-CN/docs/trade/asset/cashflow |
| 股票持仓 | /zh-CN/docs/trade/asset/stock |
| 基金持仓 | /zh-CN/docs/trade/asset/fund |
| 保证金比例 | /zh-CN/docs/trade/asset/margin_ratio |

## 6. 账户 account

### 概览

| 标题 | 路径 |
|---|---|
| 概览 | /zh-CN/docs/account/overview |

### 价格提醒 alert

| 标题 | 路径 |
|---|---|
| 获取价格提醒列表 | /zh-CN/docs/account/alert/list-alerts |
| 创建价格提醒 | /zh-CN/docs/account/alert/create-alert |
| 更新价格提醒 | /zh-CN/docs/account/alert/update-alert |
| 删除价格提醒 | /zh-CN/docs/account/alert/delete-alert |

### 定投 dca

| 标题 | 路径 |
|---|---|
| 检查定投支持 | /zh-CN/docs/account/dca/check-support |
| 计算定投日期 | /zh-CN/docs/account/dca/calc-date |
| 创建定期投资计划 | /zh-CN/docs/account/dca/create-dca |
| 更新定期投资计划 | /zh-CN/docs/account/dca/update-dca |
| 获取定期投资计划列表 | /zh-CN/docs/account/dca/list-dca |
| 暂停定投计划 | /zh-CN/docs/account/dca/pause-dca |
| 恢复定投计划 | /zh-CN/docs/account/dca/resume-dca |
| 终止定投计划 | /zh-CN/docs/account/dca/stop-dca |
| 删除定期投资计划 | /zh-CN/docs/account/dca/delete-dca |
| 定投统计 | /zh-CN/docs/account/dca/dca-stats |
| 定期投资交易历史 | /zh-CN/docs/account/dca/dca-history |
| 设置定投提醒 | /zh-CN/docs/account/dca/set-reminder |

### 组合分析 portfolio

| 标题 | 路径 |
|---|---|
| 盈亏分析汇总 | /zh-CN/docs/account/portfolio/profit-analysis-summary |
| 按市场盈亏分析 | /zh-CN/docs/account/portfolio/profit-analysis-by-market |
| 盈亏分析明细 | /zh-CN/docs/account/portfolio/profit-analysis-detail |
| 盈亏流水 | /zh-CN/docs/account/portfolio/profit-analysis-flows |
| 汇率 | /zh-CN/docs/account/portfolio/exchange-rates |

## 7. 长连接协议 socket

### 协议 protocol

| 标题 | 路径 |
|---|---|
| 协议概览 | /zh-CN/docs/socket/protocol/overview |
| 通信过程 | /zh-CN/docs/socket/protocol/connect |
| 解析数据包头 | /zh-CN/docs/socket/protocol/header |
| 解析握手包 | /zh-CN/docs/socket/protocol/handshake |
| 解析请求包 | /zh-CN/docs/socket/protocol/request |
| 解析响应包 | /zh-CN/docs/socket/protocol/response |
| 解析推送包 | /zh-CN/docs/socket/protocol/push |

### 业务

| 标题 | 路径 |
|---|---|
| 业务地址 | /zh-CN/docs/socket/hosts |
| 业务指令 | /zh-CN/docs/socket/biz_command |
| 控制指令 | /zh-CN/docs/socket/control-command |
| 订阅行情推送 | /zh-CN/docs/socket/subscribe_quote |
| 订阅交易推送 | /zh-CN/docs/socket/subscribe_trade |
| WebSocket 和 TCP 接入的不同点 | /zh-CN/docs/socket/diff_ws_tcp |

## 8. 常见问题 qa

| 标题 | 路径 |
|---|---|
| 通用问题 | /zh-CN/docs/qa/general |
| 行情相关 | /zh-CN/docs/qa/broker |
| 交易相关 | /zh-CN/docs/qa/trade |
