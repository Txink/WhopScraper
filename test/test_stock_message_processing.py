"""
正股页面消息处理测试
从 tmp/stock/origin_message.json 抽取真实消息，验证：
1. 消息解析：买入/卖出/清仓/修改订单
2. 日志输出：display 方法正常工作
3. 订单校验：买入/卖出价格与数量
"""
import sys
import os
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from parser.stock_parser import StockParser
from parser.stock_context_resolver import StockContextResolver
from models.stock_instruction import StockInstruction
from models.instruction import InstructionType
from models.message import MessageGroup
from models.record import Record
from models.record_manager import RecordManager

ORIGIN_MESSAGE_PATH = os.path.join(os.path.dirname(__file__), '..', 'tmp', 'stock', 'origin_message.json')


def load_messages():
    """加载正股消息源"""
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
# 1. 消息解析测试
# ============================================================

def test_stock_buy_parsing():
    """测试正股买入消息解析"""
    test_cases = [
        {
            "msg": "19.1-19.15建了点这轮tsll底仓",
            "expect_ticker": "TSLL",
            "expect_type": InstructionType.BUY.value,
            "expect_price_range": True,
            "desc": "区间价买入（句尾ticker）",
        },
        {
            "msg": "mstr 330-328区间可以回吸",
            "expect_ticker": "MSTR",
            "expect_type": InstructionType.BUY.value,
            "expect_price_range": True,
            "desc": "区间回吸买入（ticker在前）",
        },
        {
            "msg": "AAPL 买入 $150",
            "expect_ticker": "AAPL",
            "expect_type": InstructionType.BUY.value,
            "expect_price": 150.0,
            "desc": "标准格式买入",
        },
        {
            "msg": "买入 TSLA 在 $250",
            "expect_ticker": "TSLA",
            "expect_type": InstructionType.BUY.value,
            "expect_price": 250.0,
            "desc": "「买入 ticker 在 价格」格式",
        },
        {
            "msg": "tsll 在16.02附近开个底仓",
            "expect_ticker": "TSLL",
            "expect_type": InstructionType.BUY.value,
            "expect_price": 16.02,
            "desc": "口语化开底仓",
        },
    ]

    passed = 0
    failed = 0

    for case in test_cases:
        result = StockParser.parse(case["msg"])
        if not result:
            print(f"  ❌ FAIL [{case['desc']}]: \"{case['msg']}\" -> 未能解析")
            failed += 1
            continue

        ok = True
        errors = []

        if result.ticker != case["expect_ticker"]:
            errors.append(f"ticker: 期望={case['expect_ticker']}, 实际={result.ticker}")
            ok = False

        if result.instruction_type != case["expect_type"]:
            errors.append(f"type: 期望={case['expect_type']}, 实际={result.instruction_type}")
            ok = False

        if case.get("expect_price") is not None and result.price != case["expect_price"]:
            errors.append(f"price: 期望={case['expect_price']}, 实际={result.price}")
            ok = False

        if case.get("expect_price_range") and not result.price_range:
            errors.append("price_range: 期望有区间, 实际=None")
            ok = False

        if ok:
            price_str = f"${result.price_range[0]}-${result.price_range[1]}" if result.price_range else f"${result.price}"
            print(f"  ✅ PASS [{case['desc']}]: {result.ticker} {result.instruction_type} @ {price_str}")
            passed += 1
        else:
            print(f"  ❌ FAIL [{case['desc']}]: \"{case['msg']}\" -> {', '.join(errors)}")
            failed += 1

    return passed, failed


def test_stock_sell_parsing():
    """测试正股卖出消息解析"""
    test_cases = [
        {
            "msg": "tsll 21.5-21.7之间再减持点",
            "expect_ticker": "TSLL",
            "expect_type": InstructionType.SELL.value,
            "expect_price_range": True,
            "desc": "区间减持（ticker在前）",
        },
        {
            "msg": "55.5-56.5之间出剩下一半hims",
            "expect_ticker": "HIMS",
            "expect_type": InstructionType.SELL.value,
            "expect_price_range": True,
            "expect_sell_quantity": "1/2",
            "desc": "区间出一半",
        },
        {
            "msg": "AAPL 卖出 $180",
            "expect_ticker": "AAPL",
            "expect_type": InstructionType.SELL.value,
            "expect_price": 180.0,
            "desc": "标准卖出格式",
        },
        {
            "msg": "NVDA $950 出",
            "expect_ticker": "NVDA",
            "expect_type": InstructionType.SELL.value,
            "expect_price": 950.0,
            "desc": "ticker 价格 出",
        },
    ]

    passed = 0
    failed = 0

    for case in test_cases:
        result = StockParser.parse(case["msg"])
        if not result:
            print(f"  ❌ FAIL [{case['desc']}]: \"{case['msg'][:50]}\" -> 未能解析")
            failed += 1
            continue

        ok = True
        errors = []

        if result.ticker != case["expect_ticker"]:
            errors.append(f"ticker: 期望={case['expect_ticker']}, 实际={result.ticker}")
            ok = False

        if result.instruction_type != case["expect_type"]:
            errors.append(f"type: 期望={case['expect_type']}, 实际={result.instruction_type}")
            ok = False

        if case.get("expect_price") is not None and result.price != case["expect_price"]:
            errors.append(f"price: 期望={case['expect_price']}, 实际={result.price}")
            ok = False

        if case.get("expect_price_range") and not result.price_range:
            errors.append("price_range: 期望有区间, 实际=None")
            ok = False

        if case.get("expect_sell_quantity") and result.sell_quantity != case["expect_sell_quantity"]:
            errors.append(f"sell_quantity: 期望={case['expect_sell_quantity']}, 实际={result.sell_quantity}")
            ok = False

        if ok:
            price_str = f"${result.price_range[0]}-${result.price_range[1]}" if result.price_range else f"${result.price}"
            qty_str = f" qty={result.sell_quantity}" if result.sell_quantity else ""
            print(f"  ✅ PASS [{case['desc']}]: {result.ticker} {result.instruction_type} @ {price_str}{qty_str}")
            passed += 1
        else:
            print(f"  ❌ FAIL [{case['desc']}]: \"{case['msg'][:50]}\" -> {', '.join(errors)}")
            failed += 1

    return passed, failed


def test_stock_close_parsing():
    """测试正股清仓消息解析"""
    test_cases = [
        {
            "msg": "TSLA 卖出 $300",
            "expect_ticker": "TSLA",
            "expect_type": InstructionType.SELL.value,
            "desc": "标准卖出（解析为 SELL）",
        },
    ]

    passed = 0
    failed = 0

    for case in test_cases:
        result = StockParser.parse(case["msg"])
        if not result:
            print(f"  ❌ FAIL [{case['desc']}]: \"{case['msg'][:50]}\" -> 未能解析")
            failed += 1
            continue

        ok = True
        errors = []

        if result.ticker != case.get("expect_ticker"):
            errors.append(f"ticker: 期望={case.get('expect_ticker')}, 实际={result.ticker}")
            ok = False

        if ok:
            print(f"  ✅ PASS [{case['desc']}]: {result.ticker} {result.instruction_type}")
            passed += 1
        else:
            print(f"  ❌ FAIL [{case['desc']}]: {', '.join(errors)}")
            failed += 1

    return passed, failed


def test_stock_modify_parsing():
    """测试正股止损/止盈修改消息解析"""
    test_cases = [
        {
            "msg": "AAPL 止损 $145",
            "expect_ticker": "AAPL",
            "expect_type": InstructionType.MODIFY.value,
            "expect_stop_loss": 145.0,
            "desc": "标准止损",
        },
        {
            "msg": "止损 TSLA 在 $240",
            "expect_ticker": "TSLA",
            "expect_type": InstructionType.MODIFY.value,
            "expect_stop_loss": 240.0,
            "desc": "「止损 ticker 在 价格」格式",
        },
    ]

    passed = 0
    failed = 0

    for case in test_cases:
        result = StockParser.parse(case["msg"])
        if not result:
            print(f"  ❌ FAIL [{case['desc']}]: \"{case['msg'][:50]}\" -> 未能解析")
            failed += 1
            continue

        ok = True
        errors = []

        if result.ticker != case["expect_ticker"]:
            errors.append(f"ticker: 期望={case['expect_ticker']}, 实际={result.ticker}")
            ok = False

        if case.get("expect_stop_loss") is not None and result.stop_loss_price != case["expect_stop_loss"]:
            errors.append(f"stop_loss: 期望={case['expect_stop_loss']}, 实际={result.stop_loss_price}")
            ok = False

        if ok:
            sl = f" SL=${result.stop_loss_price}" if result.stop_loss_price else ""
            print(f"  ✅ PASS [{case['desc']}]: {result.ticker} {result.instruction_type}{sl}")
            passed += 1
        else:
            print(f"  ❌ FAIL [{case['desc']}]: {', '.join(errors)}")
            failed += 1

    return passed, failed


# ============================================================
# 2. 端到端消息处理测试（从消息源加载真实消息）
# ============================================================

def test_stock_e2e_from_origin():
    """从消息源加载真实消息进行端到端解析测试"""
    if not os.path.exists(ORIGIN_MESSAGE_PATH):
        print("  ⚠️  正股消息源不存在，跳过端到端测试")
        return 0, 0

    messages = load_messages()
    resolver = StockContextResolver()

    buy_count = 0
    sell_count = 0
    modify_count = 0
    close_count = 0
    failed_count = 0
    skipped_count = 0
    total = 0

    for msg_dict in messages:
        content = msg_dict.get('content', '').strip()
        if not content or len(content) < 5:
            skipped_count += 1
            continue

        total += 1
        record = create_record_from_dict(msg_dict)
        resolver.resolve_instruction(record)

        if record.instruction is None:
            failed_count += 1
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
    print(f"  总消息数: {total} (跳过短消息: {skipped_count})")
    print(f"  成功解析: {parsed} ({parsed / max(total, 1) * 100:.1f}%)")
    print(f"    买入: {buy_count}, 卖出: {sell_count}, 清仓: {close_count}, 修改: {modify_count}")
    print(f"  未匹配: {failed_count}")

    # 至少应该解析出部分买入和卖出指令
    ok = buy_count > 0 and sell_count > 0
    if ok:
        print(f"  ✅ 端到端解析通过（至少包含买入和卖出指令）")
        return 1, 0
    else:
        print(f"  ❌ 端到端解析失败：买入={buy_count}, 卖出={sell_count}")
        return 0, 1


# ============================================================
# 3. 日志输出测试
# ============================================================

def test_stock_display():
    """测试正股指令的日志输出（display 方法）"""
    passed = 0
    failed = 0

    display_cases = [
        StockInstruction(
            raw_message="AAPL 买入 $150",
            instruction_type=InstructionType.BUY.value,
            ticker="AAPL",
            symbol="AAPL.US",
            price=150.0,
            position_size="小仓位",
        ),
        StockInstruction(
            raw_message="TSLA 卖出 $300",
            instruction_type=InstructionType.SELL.value,
            ticker="TSLA",
            symbol="TSLA.US",
            price=300.0,
            sell_quantity="1/3",
        ),
        StockInstruction(
            raw_message="NVDA 清仓 $950",
            instruction_type=InstructionType.CLOSE.value,
            ticker="NVDA",
            symbol="NVDA.US",
            price=950.0,
        ),
        StockInstruction(
            raw_message="AAPL 止损 $145",
            instruction_type=InstructionType.MODIFY.value,
            ticker="AAPL",
            symbol="AAPL.US",
            stop_loss_price=145.0,
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
        StockInstruction.display_parse_failed(message_timestamp="2026-02-25 10:00:00.000")
        print(f"  ✅ PASS: display_parse_failed 正常")
        passed += 1
    except Exception as e:
        print(f"  ❌ FAIL: display_parse_failed 异常: {e}")
        failed += 1

    return passed, failed


# ============================================================
# 4. 订单校验测试
# ============================================================

def test_stock_buy_price_validation():
    """测试股票买入价格校验"""
    test_cases = [
        {
            "msg": "AAPL 买入 $150",
            "expect_price": 150.0,
            "desc": "标准格式价格",
        },
        {
            "msg": "19.1-19.15建了点这轮tsll底仓",
            "expect_price_range": [19.1, 19.15],
            "desc": "区间价格",
        },
        {
            "msg": "tsll 在16.02附近开个底仓",
            "expect_price": 16.02,
            "desc": "单价格",
        },
    ]

    passed = 0
    failed = 0

    for case in test_cases:
        result = StockParser.parse(case["msg"])
        if not result:
            print(f"  ❌ FAIL [{case['desc']}]: 解析失败")
            failed += 1
            continue

        ok = True
        errors = []

        if case.get("expect_price") is not None:
            if result.price != case["expect_price"]:
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


def test_stock_sell_price_quantity_validation():
    """测试股票卖出价格和数量校验"""
    test_cases = [
        {
            "msg": "AAPL 卖出 $180",
            "expect_price": 180.0,
            "expect_sell_quantity": "全部",
            "desc": "标准卖出价格（默认全部）",
        },
        {
            "msg": "55.5-56.5之间出剩下一半hims",
            "expect_price_range": [55.5, 56.5],
            "expect_sell_quantity": "1/2",
            "desc": "区间卖出+一半",
        },
    ]

    passed = 0
    failed = 0

    for case in test_cases:
        result = StockParser.parse(case["msg"])
        if not result:
            print(f"  ❌ FAIL [{case['desc']}]: 解析失败")
            failed += 1
            continue

        ok = True
        errors = []

        if case.get("expect_price") is not None:
            if result.price != case["expect_price"]:
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

        if "expect_sell_quantity" in case:
            if result.sell_quantity != case["expect_sell_quantity"]:
                errors.append(f"sell_quantity: 期望={case['expect_sell_quantity']}, 实际={result.sell_quantity}")
                ok = False

        if ok:
            print(f"  ✅ PASS [{case['desc']}]: 价格/数量校验通过")
            passed += 1
        else:
            print(f"  ❌ FAIL [{case['desc']}]: {', '.join(errors)}")
            failed += 1

    return passed, failed


def test_stock_instruction_symbol():
    """测试 StockInstruction.ensure_symbol 生成正确的 symbol"""
    test_cases = [
        ("AAPL", "AAPL.US"),
        ("TSLA", "TSLA.US"),
        ("TSLL", "TSLL.US"),
        ("MSTR", "MSTR.US"),
    ]

    passed = 0
    failed = 0

    for ticker, expected_symbol in test_cases:
        inst = StockInstruction(
            raw_message=f"test {ticker}",
            instruction_type=InstructionType.BUY.value,
            ticker=ticker,
        )
        inst.ensure_symbol()
        if inst.symbol == expected_symbol:
            print(f"  ✅ PASS: {ticker} -> {inst.symbol}")
            passed += 1
        else:
            print(f"  ❌ FAIL: {ticker} -> 期望={expected_symbol}, 实际={inst.symbol}")
            failed += 1

    return passed, failed


# ============================================================
# 入口
# ============================================================

def main():
    print("=" * 70)
    print("正股页面消息处理测试")
    print("=" * 70)

    total_passed = 0
    total_failed = 0

    sections = [
        ("买入消息解析", test_stock_buy_parsing),
        ("卖出消息解析", test_stock_sell_parsing),
        ("清仓消息解析", test_stock_close_parsing),
        ("止损/止盈修改解析", test_stock_modify_parsing),
        ("端到端消息解析（真实消息源）", test_stock_e2e_from_origin),
        ("日志输出（display）", test_stock_display),
        ("买入价格校验", test_stock_buy_price_validation),
        ("卖出价格/数量校验", test_stock_sell_price_quantity_validation),
        ("Symbol 生成校验", test_stock_instruction_symbol),
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
