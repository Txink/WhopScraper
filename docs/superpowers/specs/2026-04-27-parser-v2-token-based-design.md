# parser_v2 — token-based stock parser 设计

**Date:** 2026-04-27
**Status:** approved (brainstorm phase complete)
**Scope:** 替换 `app/parser/stock_parser.py`（regex-based, 1837 行）为独立的 token-based parser，位于 `app/parser_v2/`。验收以 B1 harness 三硬指标为准：regression=0、recovery_rate≥20%、chatter_false_positives=0。

---

## 1. 上下文

B1 阶段已建：1899 条手工 golden、`scripts/validate_parser.py` 三指标 harness、`app/parser_v2/__init__.py` 当前 alias 至 v1。

baseline（commit `6c20b23`）：
- v1 在 777 条单消息 trade_signal 上 pass=169 / fail=608（21.7%）
- v1 在 752 条 chatter 上产 27 条 false-positive（多为：英文新闻里抠 ticker、commentary range 当 sell range、past-ref "X 吸的" 当 BUY、modal/conditional 句"等 X 再加"等）
- regression=0（v2 当前等于 v1）

v2 目标：
- 保住 169 条 v1 已 pass（regression=0）
- 至少新 pass 122 条 v1 fail（recovery_rate≥20% = 122/608）
- 27 条 chatter FP 全 None（chatter_FP=0）

---

## 2. 设计决策（已确认）

| # | 决策 | 选择 |
|---|---|---|
| Q1 | 多 clause 消息处理 | 句子优先：切句后取首个可解 immediate-action 句 |
| Q2 | 单 clause 内 slot 抽取策略 | anchor-then-fill（动词锚定，左右扫描填 slot） |
| Q3 | chatter 拒绝策略 | C+D：动词分级 (imperative vs descriptive) + clause-level + anchor-scope 双层 modal/conditional/observation/past 检查 |
| Q4 | v1 词典数据共享 | 共享：`ticker_aliases.py`、`_FRACTION_MAP`、`_SELL_FRACTION_MAP`（后两者从 `page_settings.py` 提到 `app/parser/vocab_shared.py`） |
| Q5 | 文件结构 | 按 phase 拆模块：vocab / tokenize / clauses / anchors / chatter / slots / parse |
| Q6 | sell_quantity / position_size 字符串形式 | content 原文优先；同步清洗 golden 一律用原文 |
| Q7 | MODIFY / 止损支持 | 不实现（dead weight：golden ambiguous、trader 无路径） |

---

## 3. 架构总览

**入口签名**：`parse(content: str, message_id: str) -> StockInstruction | None`
**输入域**：单消息 content（不消费 history/refer，留给 future context_resolver layer）
**输出域**：`StockInstruction` dataclass，6 字段：instruction_type, ticker, price, price_range, referenced_lot_price, sell_quantity, position_size

**Pipeline 五阶段**：

```
content
  │
  ▼
[1. tokenize]      vocab-driven 贪心最长匹配
                   → list[Token{tag, value, start, end, direction?}]
  │
  ▼
[2. split-clauses] 按硬分隔符 / 多空格 / CONJ+新 ticker 切
                   → list[Clause]
  │
  ▼
[3. find-anchor]   遍历 clause 内 ACTION_IMP token；
                   proximity gate (±N=8 内含 TICKER+PRICE/RANGE)；
                   通过即候选
  │
  ▼
[4. chatter-check] 双层（C+D）：
                   · clause-level：含 MODAL/CONDITIONAL → 拒绝
                   · anchor-scope ±K=3：含 OBSERVATION/PAST_REF → 拒绝
                   · 右邻 1：是 "的"/"了的"/"过的" → 拒绝
                   全部 anchor 被拒 → return None
  │
  ▼
[5. fill-slots]    以 anchor 为中心抽 6 字段，构造 StockInstruction
```

**核心不变量**：找不到合格 anchor 即 None；vocab 是唯一权威表；所有字符串字段保留 content 原文。

---

## 4. 文件结构

```
backend/app/parser_v2/
  __init__.py        # from .parse import parse
  vocab.py           # 全部 vocab 表
  tokenize.py        # tokenize(content) -> list[Token]
  clauses.py         # split_clauses(tokens) -> list[Clause]
  anchors.py         # find_anchor / iterate / proximity_ok
  chatter.py         # is_chatter(anchor) -> bool
  slots.py           # fill_slots(anchor) -> dict
  _make.py           # make_stock_instruction(...) factory
  parse.py           # 编排五阶段

backend/app/parser/
  vocab_shared.py    # 新文件 — _FRACTION_MAP / _SELL_FRACTION_MAP 从 page_settings 提至此
  ticker_aliases.py  # 现状保留

backend/app/whop/page_settings.py    # 改 import path
```

**测试树**：

```
backend/tests/parser_v2/
  test_vocab.py
  test_tokenize.py
  test_clauses.py
  test_anchors.py
  test_chatter.py
  test_slots.py
  test_parse_e2e.py
backend/tests/parser/
  test_v2_against_golden.py   # B1 已建，保留作 CI gate
```

---

## 5. Vocab 表（`vocab.py`）

类别清单及方向（初版从 golden 778 trade_signal + 27 chatter FP + audit 边界 case 实证抽出，后续可增补）：

```python
# Token tag = ACTION_IMP — 命令式动词，anchor 候选
IMPERATIVE_VERBS_BUY = {
    "买", "买入", "买点",
    "吸", "回吸", "低吸", "吸点",
    "加", "加点", "加仓", "加了", "再加",
    "开", "开仓", "开点", "建仓", "建了",
    "接", "接回", "补", "补仓", "补了",
    "进了",
}
IMPERATIVE_VERBS_SELL = {
    "卖", "卖出",
    "出", "出掉", "出了", "出点",
    "减", "减点", "减仓", "减了",
    "兑现", "平仓", "清仓",
}
# tokenize 时把方向标记到 token.direction

# Token tag = ACTION_DESC — 描述性，绝不能成 anchor
DESCRIPTIVE_VERBS = {
    "回踩", "转弯", "震荡", "突破", "测试", "反弹", "回调",
    "破", "跌破", "站稳", "撑住", "持有",
}

# Token tag = MODAL
MODAL_MARKERS = {
    "可能", "可以", "估计", "应该", "大概", "也许", "或许",
    "打算", "计划", "准备", "会",
}
# 注：vocab 表中"会"按贪心最长匹配，"机会"/"会面"等会被先匹配为更长复合词
# "可以"补充进表（27 FP audit 时漏写）

# Token tag = CONDITIONAL
CONDITIONAL_MARKERS = {
    "等", "如果", "假如", "万一",
    "没破", "没跌破", "没站稳", "才",
}

# Token tag = OBSERVATION
OBSERVATION_MARKERS = {
    "看", "看下", "看看", "看一下",
    "注意", "关注", "观察",
    "比如", "比方", "之类",
    "盘后看", "盘前看",
}

# Token tag = PAST_REF
PAST_REF_MARKERS = {
    "之前", "上次", "上一次", "上一轮",
    "昨天", "前天", "财报那天", "上周",
    "历史", "原来",
}

# Token tag = QUANTIFIER —— sell_quantity 候选 / 部分情况下 position_size 提升
SELL_QUANTIFIERS = {
    "一半", "全部", "全出", "都出",
    "剩下", "剩下一半",
    "部分", "那部分",
    "1/2", "1/3", "1/4", "2/3", "3/4",
    "三分之一", "三分之二", "四分之一",
    "点",  # 弱 quantifier，slot 阶段忽略（weak=True 标记）
}
QUANTIFIER_WEAK = {"点"}

# Token tag = POSITION_SIZE
POSITION_SIZE_PHRASES = {
    "常规仓", "中仓位",
    "常规仓的一半", "常规一半", "常规的一半",
    "半仓", "一半仓",
    "小仓位", "轻仓",
    "大仓位", "重仓",
    "满仓", "底仓",
}

# Token tag = CONJ
CONJUNCTIONS = {"和", "与", "或者", "或", "再"}
```

**Dual-role "一半"**：tokenize 时一律标 QUANTIFIER；slot 阶段在 BUY 上下文且无 POSITION_SIZE token 时提升为 position_size。

**TICKER / PRICE / RANGE**：正则识别，不在 vocab 表：
- `TICKER`：`r"[A-Za-z]{2,5}\b"` 大写化后比对内置美股 ticker 集合 ∪ `ticker_aliases` 别名 keys；中文 alias 通过 `ticker_aliases._get_items_sorted()` 返回的 length-desc 列表做贪心最长匹配（此私有函数已按长度逆序排好；如需稳定对外接口，提一个公开 helper `iter_aliases() -> list[tuple[str, str]]`）
- `PRICE`：`r"\d{1,4}(\.\d{1,3})?"` + sanity 上限 < 10000
- `RANGE`：`PRICE + (-|到|至) + PRICE`

**`vocab_shared.py`**：从 `page_settings.py` 移出的两个 map：
```python
# app/parser/vocab_shared.py
_FRACTION_MAP: dict[str, float] = { ... }       # 从 page_settings 移
_SELL_FRACTION_MAP: dict[str, float] = { ... }  # 从 page_settings 移
```
`page_settings.py` 改 `from app.parser.vocab_shared import _FRACTION_MAP, _SELL_FRACTION_MAP`，公开语义不变。

---

## 6. Tokenize 阶段

```python
@dataclass
class Token:
    tag: TokenTag
    value: str
    start: int
    end: int
    direction: Literal["BUY", "SELL"] | None = None
    weak: bool = False  # QUANTIFIER 弱类标记 ("点")
```

**算法**：贪心最长匹配，单遍扫描，每次 i 指针推进：

1. 跳过空白和 PUNCT
2. 数字开头 → 优先尝试 RANGE，否则 PRICE
3. ASCII 字母开头 → 尝试 TICKER（大写化后比 ticker 集合）
4. 否则在所有 vocab 表里找最长匹配 phrase；命中即对应 tag
5. 都不命中 → 单字 OTHER token，i += 1

ACTION_IMP 命中时按 `IMPERATIVE_VERBS_BUY` / `IMPERATIVE_VERBS_SELL` 写 `direction`。
QUANTIFIER 命中且 ∈ `QUANTIFIER_WEAK` 时写 `weak=True`。

**测试要点**：
- `"TSLL 27.2出一半"` → `[TICKER, PRICE, ACTION_IMP(SELL), QUANTIFIER]`
- `"甲骨文可能在193.5-196之间会转弯往下"` → `[TICKER(ORCL), MODAL, OTHER, RANGE, OTHER, MODAL, ACTION_DESC, OTHER]`
- 边界：`"机会"`不应被 tokenize 成 `MODAL("会")` + `OTHER("机")`（贪心匹配靠 vocab 长度优先）

---

## 7. Split-clauses 阶段

```python
@dataclass
class Clause:
    tokens: list[Token]
    char_start: int
    char_end: int
```

**切句规则**（强→弱）：

| # | 规则 | 例 |
|---|---|---|
| 1 | 硬分隔符：`。！？；.\n` 等 | "X。Y" → 切 |
| 2 | 连续 ≥2 空白字符 | `"...出一半  剩下一半收盘再看看"` → 切 |
| 3 | CONJ token 后紧跟新 TICKER/PRICE | `"tsll 14 和 nvdl 80"` → 切 |
| 4 | 中文逗号 `，` 后紧跟新 TICKER/PRICE | `"tsll 27 出，nvdl 80 出"` → 切 |
| 5 | 其他情况一律不切 | `"21,8-21.9 出 剩下一半"` → 不切（数字内逗号） |

每 clause 保留原 content `char_start` / `char_end`。

---

## 8. Find-anchor 阶段

```python
@dataclass
class Anchor:
    clause: Clause
    verb_token: Token
    verb_index: int
    direction: Literal["BUY", "SELL"]
```

**遍历**：clause 顺序 → 内 token 顺序 → 每个 ACTION_IMP token 评估：

1. **proximity gate**（**N=8**）：clause 内 verb_token 左右 ±N tokens 至少含 1 TICKER + 1 PRICE/RANGE；不满足 → 跳过
2. **chatter check**（§9）：不通过 → 跳过
3. 通过 → 返回首个合格 anchor
4. 全部 ACTION_IMP 都被拒 → 进入下一 clause；全部 clause 无合格 → return None

---

## 9. Chatter-check 阶段

**层 1 — clause-level 否决**：

anchor 所在 clause 含任一 MODAL 或 CONDITIONAL token → return True（拒绝）。

**层 2 — anchor-scope 否决**（**K=3**）：

verb_token 左右 ±K tokens 内：
- 含 OBSERVATION token → True
- 含 PAST_REF token → True

**右邻语法 PAST 检查**：

verb_token 右邻 1 token 是 OTHER 类且 value ∈ `{"的", "了的", "过的"}` → True。

**对照 27 条 FP 期望 kill 路径**：

| FP 模式（节选） | kill 阶段 |
|---|---|
| `TRUMP THREATENS ... 100 ...`（无 ACTION_IMP） | §8 anchor 找不到 |
| `78-80附近可以买了长拿` | 层 1（MODAL "可以"） |
| `等讲话有大跳水再加` | 层 1（CONDITIONAL "等"） |
| `都看能到43附近在回吸` | 层 2（OBSERVATION "看"） |
| `昨天是106吸的` | 层 2 + 右邻"的" |
| `tsll nvdl meta msft 之类`（无 ACTION_IMP） | §8 anchor 找不到 |

每条 27 FP 必须有 explicit unit test：`v2.parse(content) is None`。

---

## 10. Fill-slots 阶段

```python
def fill_slots(anchor: Anchor) -> dict[str, Any]:
```

按 6 字段分别填：

### 10.1 instruction_type
直接 `anchor.direction`。

### 10.2 ticker / symbol
clause 内距 anchor verb 最近 TICKER token；中文别名走 `ticker_aliases.resolve_alias(value)` → US ticker；US-letter 形态直接 upper-case 后用作 ticker；`symbol = ticker + ".US"`。

### 10.3 price / price_range（互斥）
clause 内距 anchor verb 最近 PRICE/RANGE：
- RANGE → `price_range = (lo, hi)`，`price = None`
- PRICE → `price = float`，`price_range = None`

### 10.4 referenced_lot_price

遍历 clause 内非主价格的 PRICE token，命中以下任一即赋值：

| 规则 | 形态 | 例 |
|---|---|---|
| **R1** PRICE + "的" | `[PRICE][OTHER:的]` | `200出昨天192的` → 192 |
| **R2** PRICE + 部分 | `[PRICE][OTHER:部分\|那部分]` 或 `[PRICE][的][部分]` | `12.32 部分 12.4出` → 12.32 |
| **R3** PAST_REF 邻近 PRICE | `[PAST_REF]...[PRICE]` ≤3 tokens | `之前78的部分在78.4出` → 78 |
| **R4** PRICE + ACTION_IMP + "的" | `[PRICE][ACTION_IMP][OTHER:的]` | `14.31出一半 14吸的` → 14 |
| **R5** verb 右侧 PRICE + QUANTIFIER | anchor 右侧 `[TICKER]?[PRICE2][QUANTIFIER]`，左侧已有主 PRICE | `23.32出了bmnr21.5剩下一半` → 21.5 |

无规则命中 → `referenced_lot_price = None`。

### 10.5 sell_quantity（direction = SELL）
clause 内距 anchor verb 最近的非弱 QUANTIFIER token，原文输出（`weak=True` 的"点"忽略）。无则 None。

### 10.6 position_size（direction = BUY）
1. 优先：clause 内距 anchor 最近 POSITION_SIZE token → 原文
2. 备选：QUANTIFIER token 且 value == "一半"（dual-role 提升）→ 原文 "一半"
3. 都无 → None

---

## 11. 入口编排（`parse.py`）

```python
def parse(content: str, message_id: str) -> StockInstruction | None:
    tokens = tokenize(content)
    if not tokens:
        return None
    clauses = split_clauses(tokens)
    for clause in clauses:
        for verb_idx, verb_tok in iter_imperative(clause):
            anchor = Anchor(clause, verb_tok, verb_idx, verb_tok.direction)
            if not proximity_ok(anchor):
                continue
            if is_chatter(anchor):
                continue
            slots = fill_slots(anchor)
            return make_stock_instruction(message_id=message_id,
                                          raw_text=content, **slots)
    return None
```

`__init__.py` 最终改为 `from .parse import parse`，移除 B1 的 alias。harness alias-exemption 自动失效，触发 recovery_rate 强约束。

---

## 12. 测试与验收

| 关卡 | 命令 | 验收门 |
|---|---|---|
| vocab/tokenize | `pytest tests/parser_v2/test_tokenize.py` | 关键 case token 流正确 |
| clauses | `pytest tests/parser_v2/test_clauses.py` | 切句边界 |
| anchors | `pytest tests/parser_v2/test_anchors.py` | proximity 与 first-match |
| chatter | `pytest tests/parser_v2/test_chatter.py` | 27 条 FP 全 None |
| slots | `pytest tests/parser_v2/test_slots.py` | 6 字段、5 lot-ref 规则 |
| e2e | `pytest tests/parser_v2/test_parse_e2e.py` | golden 子集（10-20 case） |
| **harness** | `python -m scripts.validate_parser` | regression=0 ∧ recovery≥20% ∧ chatter_FP=0 |
| CI | `pytest tests/parser/test_v2_against_golden.py` | 同 harness（B1 已建） |

---

## 13. golden 清洗（与 v2 同步）

Q6=A 决议：sell_quantity / position_size 字符串需统一为 content 原文。

清洗范围：
- `data/parser_golden.json` 中 trade_signal 条目，约 200-300 条受影响
- few-shot 例子（`scripts/golden_lib.py::FEW_SHOT_EXAMPLES`）也改

时机：v2 实现完成、跑 harness 出 string-mismatch 失败时一并修。先做 v2 实现，后做 golden 清洗（可能避免无谓清洗 — 因为某些 mismatch 也许是 v2 抓 slot 时漏字符）。

---

## 14. 失败处理预案

**recovery 不到 20%**：
- 增补 vocab 短语；加 lot-ref R6
- 调高 N proximity 窗口（8→10）
- 极端：增 R6 等新 lot-ref 形态规则

**regression > 0**：
- 单 case 修；可能伴随 golden 清洗
- 字符串形式不一致（"1/2" vs "一半"）→ golden 清洗

**chatter_FP > 0**：
- 增补 MODAL/CONDITIONAL/OBSERVATION 短语
- 收紧 K=3 → K=2

---

## 15. 不在 v2 范围内

- ❌ MODIFY / 止损 / 止盈
- ❌ context-aware 解析（需 history 才能解的消息，留 future context_resolver）
- ❌ option（期权）解析（仍走现有 `option_parser.py`）
- ❌ 多动作并列消息（v2 输出 None，由 ambiguous bucket 吸收）
- ❌ 性能优化、cache、profile

---

## 16. 后续（B3 不在本 spec 范围）

v2 上线后，B3 阶段加 `PageSettings.parser_version: "v1" | "v2"` 字段 + `service.py` dispatcher + frontend form switch。本 spec 不涉及。
