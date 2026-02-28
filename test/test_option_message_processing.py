"""
期权页面消息处理测试
从 data/origin_message.json 抽取真实消息，验证：
1. 消息解析：买入/卖出/清仓/修改订单
2. 日志输出：display 方法正常工作
3. 订单校验：买入/卖出价格与数量
"""
import sys
import os
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from parser.option_parser import OptionParser
from parser.message_context_resolver import MessageContextResolver
from models.instruction import OptionInstruction, InstructionType
from models.message import MessageGroup
from models.record import Record
from models.record_manager import RecordManager

ORIGIN_MESSAGE_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'origin_message.json')


def load_messages():
    """加载期权消息源"""
    with open(ORIGIN_MESSAGE_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def create_record_from_dict(msg_dict: dict) -> Record:
    """从消息字典创建 Record 对象"""
    mg = MessageGroup(
        group_id=msg_dict.get('domID', ''),
        timestamp=msg_dict.get('timestamp', ''),
        primary_message=msg_dict.get('content', ''),
        quoted_context=msg_dict.get('refer'),
        has_message_above=msg_dict.get('position') in ('middle', 'last'),
        has_message_below=msg_dict.get('position') in ('first', 'middle'),
        history=msg_dict.get('history', []),
    )
    return Record(message=mg)


# ============================================================
# 1. 消息解析测试 - 买入
# ============================================================

def test_option_buy_parsing():
    """测试期权买入消息解析"""
    test_cases = [
        {
            "msg": "合约：QQQ 11/20 614c 入场价：1.1 备注：小仓位",
            "expect_ticker": "QQQ",
            "expect_strike": 614.0,
            "expect_option_type": "CALL",
            "expect_price": 1.1,
            "desc": "合约格式（到期+行权价c+入场价）",
        },
        {
            "msg": "合约：QQQ 11/20 609P 入场价：1.5 备注：小仓位",
            "expect_ticker": "QQQ",
            "expect_strike": 609.0,
            "expect_option_type": "PUT",
            "expect_price": 1.5,
            "desc": "合约格式 PUT",
        },
        {
            "msg": "INTC - $48 CALLS 本周 $1.2",
            "expect_ticker": "INTC",
            "expect_strike": 48.0,
            "expect_option_type": "CALL",
            "expect_price": 1.2,
            "desc": "标准格式（CALLS + 本周）",
        },
        {
            "msg": "TSLA 460c 1/16 小仓位日内交易 4.10",
            "expect_ticker": "TSLA",
            "expect_strike": 460.0,
            "expect_option_type": "CALL",
            "expect_price": 4.10,
            "desc": "简化格式（ticker + strike_c + 到期 + 价格）",
        },
        {
            "msg": "AMZN 250c 2/20 4.00 小仓位",
            "expect_ticker": "AMZN",
            "expect_strike": 250.0,
            "expect_option_type": "CALL",
            "expect_price": 4.0,
            "desc": "简化格式 AMZN",
        },
        {
            "msg": "RIVN 16c 3/20 1.35",
            "expect_ticker": "RIVN",
            "expect_strike": 16.0,
            "expect_option_type": "CALL",
            "expect_price": 1.35,
            "desc": "简化格式 RIVN",
        },
        {
            "msg": "GILD - $130 CALLS 这周 1.5-1.60",
            "expect_ticker": "GILD",
            "expect_strike": 130.0,
            "expect_option_type": "CALL",
            "expect_price_range": [1.5, 1.6],
            "desc": "标准格式+价格区间",
        },
        {
            "msg": "MSFT 480c 1/23 2.70 日内小仓位",
            "expect_ticker": "MSFT",
            "expect_strike": 480.0,
            "expect_option_type": "CALL",
            "expect_price": 2.70,
            "desc": "简化格式 MSFT",
        },
        {
            "msg": "NVDA 190c 1/30 2-2.1 小仓位",
            "expect_ticker": "NVDA",
            "expect_strike": 190.0,
            "expect_option_type": "CALL",
            "expect_price": 2.0,
            "desc": "简化格式（区间取首值）",
        },
        {
            "msg": "BA - $240 CALLS EXPIRATION 2月13 $2.8",
            "expect_ticker": "BA",
            "expect_strike": 240.0,
            "expect_option_type": "CALL",
            "expect_price": 2.8,
            "desc": "EXPIRATION + 中文日期",
        },
        {
            "msg": "SPY - $680 CALLS 今天 $2.3",
            "expect_ticker": "SPY",
            "expect_strike": 680.0,
            "expect_option_type": "CALL",
            "expect_price": 2.3,
            "desc": "今天到期",
        },
    ]

    passed = 0
    failed = 0

    for case in test_cases:
        result = OptionParser.parse(case["msg"])
        if not result:
            print(f"  ❌ FAIL [{case['desc']}]: \"{case['msg'][:60]}\" -> 未能解析")
            failed += 1
            continue

        ok = True
        errors = []

        if result.ticker != case["expect_ticker"]:
            errors.append(f"ticker: 期望={case['expect_ticker']}, 实际={result.ticker}")
            ok = False

        if result.instruction_type != InstructionType.BUY.value:
            errors.append(f"type: 期望=BUY, 实际={result.instruction_type}")
            ok = False

        if case.get("expect_strike") is not None and result.strike != case["expect_strike"]:
            errors.append(f"strike: 期望={case['expect_strike']}, 实际={result.strike}")
            ok = False

        if case.get("expect_option_type") and result.option_type != case["expect_option_type"]:
            errors.append(f"option_type: 期望={case['expect_option_type']}, 实际={result.option_type}")
            ok = False

        if case.get("expect_price") is not None:
            if result.price is None or abs(result.price - case["expect_price"]) > 0.01:
                errors.append(f"price: 期望={case['expect_price']}, 实际={result.price}")
                ok = False

        if case.get("expect_price_range") is not None:
            if not result.price_range:
                errors.append(f"price_range: 期望有区间, 实际=None")
                ok = False
            else:
                low_ok = abs(result.price_range[0] - case["expect_price_range"][0]) < 0.01
                high_ok = abs(result.price_range[1] - case["expect_price_range"][1]) < 0.01
                if not (low_ok and high_ok):
                    errors.append(f"price_range: 期望={case['expect_price_range']}, 实际={result.price_range}")
                    ok = False

        if ok:
            price_str = f"${result.price_range[0]}-${result.price_range[1]}" if result.price_range else f"${result.price}"
            print(f"  ✅ PASS [{case['desc']}]: {result.ticker} ${result.strike} {result.option_type} @ {price_str}")
            passed += 1
        else:
            print(f"  ❌ FAIL [{case['desc']}]: \"{case['msg'][:60]}\" -> {', '.join(errors)}")
            failed += 1

    return passed, failed


# ============================================================
# 1b. 消息解析测试 - 卖出
# ============================================================

def test_option_sell_parsing():
    """测试期权卖出消息解析"""
    test_cases = [
        {
            "msg": "1.2-1.3开始减三分之一",
            "expect_type": InstructionType.SELL.value,
            "expect_price_range": [1.2, 1.3],
            "expect_sell_quantity": "1/3",
            "desc": "区间价格+三分之一",
        },
        {
            "msg": "1.6出三分之一",
            "expect_type": InstructionType.SELL.value,
            "expect_price": 1.6,
            "expect_sell_quantity": "1/3",
            "desc": "单价+三分之一",
        },
        {
            "msg": "1.42出一半",
            "expect_type": InstructionType.SELL.value,
            "expect_price": 1.42,
            "expect_sell_quantity": "1/2",
            "desc": "单价+一半",
        },
        {
            "msg": "0.85出三分之一",
            "expect_type": InstructionType.SELL.value,
            "expect_price": 0.85,
            "expect_sell_quantity": "1/3",
            "desc": "小数价格+三分之一",
        },
        {
            "msg": "2.6出一半",
            "expect_type": InstructionType.SELL.value,
            "expect_price": 2.6,
            "expect_sell_quantity": "1/2",
            "desc": "出一半",
        },
        {
            "msg": "TSLA 在 4.40 减仓一半",
            "expect_type": InstructionType.SELL.value,
            "expect_ticker": "TSLA",
            "expect_price": 4.40,
            "expect_sell_quantity": "1/2",
            "desc": "带 ticker 减仓一半",
        },
        {
            "msg": "0.92出三分之一cmcsa期权",
            "expect_type": InstructionType.SELL.value,
            "expect_ticker": "CMCSA",
            "expect_price": 0.92,
            "expect_sell_quantity": "1/3",
            "desc": "价格出三分之一+ticker后缀",
        },
        {
            "msg": "1.65附近出剩下三分之二",
            "expect_type": InstructionType.SELL.value,
            "expect_price": 1.65,
            "expect_sell_quantity": "2/3",
            "desc": "附近出剩下三分之二",
        },
    ]

    passed = 0
    failed = 0

    for case in test_cases:
        result = OptionParser.parse(case["msg"])
        if not result:
            print(f"  ❌ FAIL [{case['desc']}]: \"{case['msg'][:60]}\" -> 未能解析")
            failed += 1
            continue

        ok = True
        errors = []

        actual_type = result.instruction_type
        expected_types = [case["expect_type"]]
        if case["expect_type"] == InstructionType.SELL.value:
            expected_types.append(InstructionType.CLOSE.value)

        if actual_type not in expected_types:
            errors.append(f"type: 期望={case['expect_type']}, 实际={actual_type}")
            ok = False

        if case.get("expect_ticker") and result.ticker != case["expect_ticker"]:
            errors.append(f"ticker: 期望={case['expect_ticker']}, 实际={result.ticker}")
            ok = False

        if case.get("expect_price") is not None:
            if result.price is None or abs(result.price - case["expect_price"]) > 0.01:
                errors.append(f"price: 期望={case['expect_price']}, 实际={result.price}")
                ok = False

        if case.get("expect_price_range") is not None:
            if not result.price_range:
                errors.append(f"price_range: 期望有区间, 实际=None")
                ok = False
            else:
                low_ok = abs(result.price_range[0] - case["expect_price_range"][0]) < 0.01
                high_ok = abs(result.price_range[1] - case["expect_price_range"][1]) < 0.01
                if not (low_ok and high_ok):
                    errors.append(f"price_range: 期望={case['expect_price_range']}, 实际={result.price_range}")
                    ok = False

        if case.get("expect_sell_quantity") is not None:
            if result.sell_quantity != case["expect_sell_quantity"]:
                errors.append(f"sell_quantity: 期望={case['expect_sell_quantity']}, 实际={result.sell_quantity}")
                ok = False

        if ok:
            price_str = f"${result.price_range[0]}-${result.price_range[1]}" if result.price_range else f"${result.price}"
            qty_str = f" qty={result.sell_quantity}" if result.sell_quantity else ""
            print(f"  ✅ PASS [{case['desc']}]: {actual_type} @ {price_str}{qty_str}")
            passed += 1
        else:
            print(f"  ❌ FAIL [{case['desc']}]: \"{case['msg'][:60]}\" -> {', '.join(errors)}")
            failed += 1

    return passed, failed


# ============================================================
# 1c. 消息解析测试 - 清仓
# ============================================================

def test_option_close_parsing():
    """测试期权清仓消息解析"""
    test_cases = [
        {
            "msg": "0.9剩下都出",
            "expect_type": InstructionType.CLOSE.value,
            "expect_price": 0.9,
            "desc": "剩下都出",
        },
        {
            "msg": "1.5附近把剩下都出了",
            "expect_type": InstructionType.CLOSE.value,
            "expect_price": 1.5,
            "desc": "附近把剩下都出了",
        },
        {
            "msg": "4.75 amd全出",
            "expect_type": InstructionType.CLOSE.value,
            "expect_price": 4.75,
            "expect_ticker": "AMD",
            "desc": "价格+ticker全出",
        },
        {
            "msg": "1.52出剩下一半",
            "expect_type": InstructionType.SELL.value,
            "expect_price": 1.52,
            "desc": "出剩下一半",
        },
        {
            "msg": "2.75都出 hon",
            "expect_type": InstructionType.CLOSE.value,
            "expect_price": 2.75,
            "expect_ticker": "HON",
            "desc": "价格都出+ticker",
        },
    ]

    passed = 0
    failed = 0

    for case in test_cases:
        result = OptionParser.parse(case["msg"])
        if not result:
            print(f"  ❌ FAIL [{case['desc']}]: \"{case['msg'][:60]}\" -> 未能解析")
            failed += 1
            continue

        ok = True
        errors = []

        actual_type = result.instruction_type
        expected_types = [case["expect_type"]]
        if case["expect_type"] == InstructionType.CLOSE.value:
            expected_types.append(InstructionType.SELL.value)

        if actual_type not in expected_types:
            errors.append(f"type: 期望={case['expect_type']}, 实际={actual_type}")
            ok = False

        if case.get("expect_price") is not None:
            if result.price is None or abs(result.price - case["expect_price"]) > 0.01:
                errors.append(f"price: 期望={case['expect_price']}, 实际={result.price}")
                ok = False

        if case.get("expect_ticker") and result.ticker and result.ticker != case["expect_ticker"]:
            errors.append(f"ticker: 期望={case['expect_ticker']}, 实际={result.ticker}")
            ok = False

        if ok:
            print(f"  ✅ PASS [{case['desc']}]: {actual_type} @ ${result.price}")
            passed += 1
        else:
            print(f"  ❌ FAIL [{case['desc']}]: \"{case['msg'][:60]}\" -> {', '.join(errors)}")
            failed += 1

    return passed, failed


# ============================================================
# 1d. 消息解析测试 - 修改（止损/止盈）
# ============================================================

def test_option_modify_parsing():
    """测试期权止损/止盈修改消息解析"""
    test_cases = [
        {
            "msg": "止损设置在0.6",
            "expect_type": InstructionType.MODIFY.value,
            "expect_stop_loss": 0.6,
            "desc": "止损设置在",
        },
        {
            "msg": "止损在1.00",
            "expect_type": InstructionType.MODIFY.value,
            "expect_stop_loss": 1.00,
            "desc": "止损在",
        },
        {
            "msg": "止损提高到1.5",
            "expect_type": InstructionType.MODIFY.value,
            "expect_stop_loss": 1.5,
            "desc": "止损提高到",
        },
        {
            "msg": "止损设置上移到2.16",
            "expect_type": InstructionType.MODIFY.value,
            "expect_stop_loss": 2.16,
            "desc": "止损设置上移到",
        },
        {
            "msg": "小仓位 止损 在 1.3",
            "expect_type": InstructionType.MODIFY.value,
            "expect_stop_loss": 1.3,
            "desc": "仓位描述+止损在",
        },
    ]

    passed = 0
    failed = 0

    for case in test_cases:
        result = OptionParser.parse(case["msg"])
        if not result:
            print(f"  ❌ FAIL [{case['desc']}]: \"{case['msg'][:60]}\" -> 未能解析")
            failed += 1
            continue

        ok = True
        errors = []

        if result.instruction_type not in (InstructionType.MODIFY.value, "STOP_LOSS"):
            errors.append(f"type: 期望={case['expect_type']}, 实际={result.instruction_type}")
            ok = False

        if case.get("expect_stop_loss") is not None:
            actual_sl = result.stop_loss_price if result.stop_loss_price is not None else result.price
            if actual_sl is None or abs(actual_sl - case["expect_stop_loss"]) > 0.01:
                errors.append(f"stop_loss: 期望={case['expect_stop_loss']}, 实际={actual_sl}")
                ok = False

        if ok:
            sl = result.stop_loss_price if result.stop_loss_price is not None else result.price
            print(f"  ✅ PASS [{case['desc']}]: {result.instruction_type} SL=${sl}")
            passed += 1
        else:
            print(f"  ❌ FAIL [{case['desc']}]: \"{case['msg'][:60]}\" -> {', '.join(errors)}")
            failed += 1

    return passed, failed


# ============================================================
# 2. 端到端消息处理测试（从消息源加载真实消息）
# ============================================================

def test_option_e2e_from_origin():
    """从期权消息源加载真实消息进行端到端解析测试"""
    if not os.path.exists(ORIGIN_MESSAGE_PATH):
        print("  ⚠️  期权消息源不存在，跳过端到端测试")
        return 0, 0

    messages = load_messages()

    rm = RecordManager(origin_message_path="/dev/null", page_type="option")

    records = []
    for msg_dict in messages:
        content = msg_dict.get('content', '').strip()
        if not content or len(content) < 5:
            continue
        record = create_record_from_dict(msg_dict)
        record.index = len(records)
        records.append(record)

    rm.items = records

    resolver = MessageContextResolver(rm)
    for record in records:
        resolver.resolve_instruction(record)

    buy_count = 0
    sell_count = 0
    modify_count = 0
    close_count = 0

    for record in records:
        if record.instruction is None:
            continue
        inst = record.instruction
        if inst.instruction_type == InstructionType.BUY.value:
            buy_count += 1
        elif inst.instruction_type == InstructionType.SELL.value:
            sell_count += 1
        elif inst.instruction_type == InstructionType.CLOSE.value:
            close_count += 1
        elif inst.instruction_type == InstructionType.MODIFY.value:
            modify_count += 1

    parsed = buy_count + sell_count + close_count + modify_count
    total = len(records)
    unparsed = total - parsed

    print(f"  总消息数: {total}")
    print(f"  成功解析: {parsed} ({parsed / max(total, 1) * 100:.1f}%)")
    print(f"    买入: {buy_count}, 卖出: {sell_count}, 清仓: {close_count}, 修改: {modify_count}")
    print(f"  未匹配: {unparsed}")

    ok = buy_count > 0 and sell_count > 0
    if ok:
        print(f"  ✅ 端到端解析通过（至少包含买入和卖出指令）")
        return 1, 0
    else:
        print(f"  ❌ 端到端解析失败：买入={buy_count}, 卖出={sell_count}")
        return 0, 1


def test_option_context_resolution():
    """测试上下文补全：卖出/清仓消息通过 history 找到买入消息补全 symbol"""
    buy_msg = {
        "domID": "test_buy_001",
        "content": "合约：QQQ 11/20 614c 入场价：1.1 备注：小仓位",
        "timestamp": "2025-11-20 22:33:00.000",
        "refer": None,
        "position": "first",
        "history": [],
    }
    sell_msg = {
        "domID": "test_sell_001",
        "content": "1.2-1.3开始减三分之一",
        "timestamp": "2025-11-20 22:33:00.010",
        "refer": None,
        "position": "middle",
        "history": ["合约：QQQ 11/20 614c 入场价：1.1 备注：小仓位"],
    }
    close_msg = {
        "domID": "test_close_001",
        "content": "1.5附近把剩下都出了",
        "timestamp": "2025-11-20 22:33:00.050",
        "refer": None,
        "position": "last",
        "history": [
            "合约：QQQ 11/20 614c 入场价：1.1 备注：小仓位",
            "1.2-1.3开始减三分之一",
        ],
    }

    rm = RecordManager(origin_message_path="/dev/null", page_type="option")

    records = []
    for idx, md in enumerate([buy_msg, sell_msg, close_msg]):
        r = create_record_from_dict(md)
        r.index = idx
        records.append(r)

    rm.items = records

    resolver = MessageContextResolver(rm)
    for record in records:
        resolver.resolve_instruction(record)

    passed = 0
    failed = 0

    # 验证买入
    buy_inst = records[0].instruction
    if buy_inst and buy_inst.instruction_type == InstructionType.BUY.value:
        if buy_inst.ticker == "QQQ" and buy_inst.strike == 614.0:
            print(f"  ✅ PASS [买入解析]: QQQ $614 CALL @ $1.1 -> symbol={buy_inst.symbol}")
            passed += 1
        else:
            print(f"  ❌ FAIL [买入解析]: ticker={buy_inst.ticker}, strike={buy_inst.strike}")
            failed += 1
    else:
        print(f"  ❌ FAIL [买入解析]: 未解析为买入指令")
        failed += 1

    # 验证卖出（应通过 group history 找到买入消息的 symbol）
    sell_inst = records[1].instruction
    if sell_inst and sell_inst.instruction_type in (InstructionType.SELL.value, InstructionType.CLOSE.value):
        has_symbol = sell_inst.has_symbol()
        if has_symbol:
            print(f"  ✅ PASS [卖出上下文补全]: symbol={sell_inst.symbol}, source={sell_inst.source}")
            passed += 1
        else:
            print(f"  ❌ FAIL [卖出上下文补全]: 未能通过上下文补全 symbol")
            failed += 1
    else:
        print(f"  ❌ FAIL [卖出上下文补全]: 未解析为卖出指令 (type={getattr(sell_inst, 'instruction_type', None)})")
        failed += 1

    # 验证清仓
    close_inst = records[2].instruction
    if close_inst and close_inst.instruction_type in (InstructionType.CLOSE.value, InstructionType.SELL.value):
        has_symbol = close_inst.has_symbol()
        if has_symbol:
            print(f"  ✅ PASS [清仓上下文补全]: symbol={close_inst.symbol}, source={close_inst.source}")
            passed += 1
        else:
            print(f"  ❌ FAIL [清仓上下文补全]: 未能通过上下文补全 symbol")
            failed += 1
    else:
        print(f"  ❌ FAIL [清仓上下文补全]: 未解析为清仓指令 (type={getattr(close_inst, 'instruction_type', None)})")
        failed += 1

    return passed, failed


# ============================================================
# 3. 日志输出测试
# ============================================================

def test_option_display():
    """测试期权指令的日志输出（display 方法）"""
    passed = 0
    failed = 0

    display_cases = [
        OptionInstruction(
            raw_message="合约：QQQ 11/20 614c 入场价：1.1",
            instruction_type=InstructionType.BUY.value,
            ticker="QQQ",
            option_type="CALL",
            strike=614.0,
            expiry="11/20",
            price=1.1,
            position_size="小仓位",
        ),
        OptionInstruction(
            raw_message="1.6出三分之一",
            instruction_type=InstructionType.SELL.value,
            ticker="QQQ",
            option_type="CALL",
            strike=614.0,
            expiry="11/20",
            symbol="QQQ251120C614000.US",
            price=1.6,
            sell_quantity="1/3",
        ),
        OptionInstruction(
            raw_message="0.9剩下都出",
            instruction_type=InstructionType.CLOSE.value,
            ticker="QQQ",
            option_type="CALL",
            strike=614.0,
            expiry="11/20",
            symbol="QQQ251120C614000.US",
            price=0.9,
        ),
        OptionInstruction(
            raw_message="止损设置在0.6",
            instruction_type=InstructionType.MODIFY.value,
            ticker="QQQ",
            option_type="CALL",
            strike=614.0,
            expiry="11/20",
            symbol="QQQ251120C614000.US",
            stop_loss_price=0.6,
        ),
    ]

    for inst in display_cases:
        try:
            inst.display()
            print(f"  ✅ PASS: {inst.instruction_type} display 正常")
            passed += 1
        except Exception as e:
            print(f"  ❌ FAIL: {inst.instruction_type} display 异常: {e}")
            failed += 1

    # 测试解析失败的 display
    try:
        OptionInstruction.display_parse_failed(message_timestamp="2026-02-25 10:00:00.000")
        print(f"  ✅ PASS: display_parse_failed 正常")
        passed += 1
    except Exception as e:
        print(f"  ❌ FAIL: display_parse_failed 异常: {e}")
        failed += 1

    return passed, failed


# ============================================================
# 4. 订单校验测试
# ============================================================

def test_option_buy_price_validation():
    """测试期权买入价格校验"""
    test_cases = [
        {
            "msg": "合约：QQQ 11/20 614c 入场价：1.1 备注：小仓位",
            "expect_price": 1.1,
            "desc": "标准入场价",
        },
        {
            "msg": "GILD - $130 CALLS 这周 1.5-1.60",
            "expect_price_range": [1.5, 1.6],
            "desc": "价格区间",
        },
        {
            "msg": "BA - $240 CALLS EXPIRATION 2月13 $2.8",
            "expect_price": 2.8,
            "desc": "EXPIRATION格式价格",
        },
        {
            "msg": "INTC - $48 CALLS 本周 $1.2",
            "expect_price": 1.2,
            "desc": "标准格式买入价格",
        },
    ]

    passed = 0
    failed = 0

    for case in test_cases:
        result = OptionParser.parse(case["msg"])
        if not result:
            print(f"  ❌ FAIL [{case['desc']}]: 解析失败")
            failed += 1
            continue

        ok = True
        errors = []

        if case.get("expect_price") is not None:
            if result.price is None or abs(result.price - case["expect_price"]) > 0.01:
                errors.append(f"price: 期望=${case['expect_price']}, 实际=${result.price}")
                ok = False

        if case.get("expect_price_range") is not None:
            if not result.price_range:
                errors.append(f"price_range: 期望有区间, 实际=None")
                ok = False
            else:
                low_ok = abs(result.price_range[0] - case["expect_price_range"][0]) < 0.01
                high_ok = abs(result.price_range[1] - case["expect_price_range"][1]) < 0.01
                if not (low_ok and high_ok):
                    errors.append(f"price_range: 期望={case['expect_price_range']}, 实际={result.price_range}")
                    ok = False

        if ok:
            print(f"  ✅ PASS [{case['desc']}]: 价格校验通过")
            passed += 1
        else:
            print(f"  ❌ FAIL [{case['desc']}]: {', '.join(errors)}")
            failed += 1

    return passed, failed


def test_option_sell_quantity_validation():
    """测试期权卖出数量校验"""
    test_cases = [
        {
            "msg": "1.6出三分之一",
            "expect_sell_quantity": "1/3",
            "desc": "三分之一",
        },
        {
            "msg": "1.42出一半",
            "expect_sell_quantity": "1/2",
            "desc": "一半",
        },
        {
            "msg": "1.65附近出剩下三分之二",
            "expect_sell_quantity": "2/3",
            "desc": "三分之二",
        },
        {
            "msg": "2.6出一半",
            "expect_sell_quantity": "1/2",
            "desc": "出一半",
        },
        {
            "msg": "2.72出三分之一 ndaq",
            "expect_sell_quantity": "1/3",
            "desc": "三分之一+ticker",
        },
    ]

    passed = 0
    failed = 0

    for case in test_cases:
        result = OptionParser.parse(case["msg"])
        if not result:
            print(f"  ❌ FAIL [{case['desc']}]: 解析失败")
            failed += 1
            continue

        ok = True
        errors = []

        if result.sell_quantity != case["expect_sell_quantity"]:
            errors.append(f"sell_quantity: 期望={case['expect_sell_quantity']}, 实际={result.sell_quantity}")
            ok = False

        if ok:
            print(f"  ✅ PASS [{case['desc']}]: sell_quantity={result.sell_quantity}")
            passed += 1
        else:
            print(f"  ❌ FAIL [{case['desc']}]: {', '.join(errors)}")
            failed += 1

    return passed, failed


def test_option_symbol_generation():
    """测试期权 symbol 生成"""
    test_cases = [
        {
            "ticker": "QQQ",
            "option_type": "CALL",
            "strike": 614.0,
            "expiry": "11/20",
            "timestamp": "2025-11-20 22:33:00.000",
            "expect_contains": "QQQ",
            "desc": "QQQ CALL symbol 生成",
        },
        {
            "ticker": "INTC",
            "option_type": "CALL",
            "strike": 48.0,
            "expiry": "1/30",
            "timestamp": "2026-01-28 22:39:00.000",
            "expect_contains": "INTC",
            "desc": "INTC CALL symbol 生成",
        },
    ]

    passed = 0
    failed = 0

    for case in test_cases:
        inst = OptionInstruction(
            instruction_type=InstructionType.BUY.value,
            ticker=case["ticker"],
            option_type=case["option_type"],
            strike=case["strike"],
            expiry=case["expiry"],
            timestamp=case["timestamp"],
        )
        success = inst.generate_symbol()
        if success and inst.symbol and case["expect_contains"] in inst.symbol:
            print(f"  ✅ PASS [{case['desc']}]: symbol={inst.symbol}")
            passed += 1
        else:
            print(f"  ❌ FAIL [{case['desc']}]: generate_symbol={success}, symbol={inst.symbol}")
            failed += 1

    return passed, failed


# ============================================================
# 入口
# ============================================================

def main():
    print("=" * 70)
    print("期权页面消息处理测试")
    print("=" * 70)

    total_passed = 0
    total_failed = 0

    sections = [
        ("买入消息解析", test_option_buy_parsing),
        ("卖出消息解析", test_option_sell_parsing),
        ("清仓消息解析", test_option_close_parsing),
        ("止损/止盈修改解析", test_option_modify_parsing),
        ("端到端消息解析（真实消息源）", test_option_e2e_from_origin),
        ("上下文补全测试", test_option_context_resolution),
        ("日志输出（display）", test_option_display),
        ("买入价格校验", test_option_buy_price_validation),
        ("卖出数量校验", test_option_sell_quantity_validation),
        ("Symbol 生成校验", test_option_symbol_generation),
    ]

    for name, func in sections:
        print(f"\n【{name}】")
        p, f = func()
        total_passed += p
        total_failed += f

    print("\n" + "=" * 70)
    print(f"测试完成: {total_passed} 通过, {total_failed} 失败")
    print("=" * 70)

    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
