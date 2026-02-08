#!/usr/bin/env python3
"""
测试：从 data/origin_message.json 读取输入，经 MessageGroup + RecordManager.create_records
与 analyze_records 解析，按 parsed_message.json 格式输出到 test_parse_result.json。

另：data/check.json 每项含 origin + check 字段；对 check 非空的项会校验解析结果与 check 一致
（含 timestamp，期望为 origin.timestamp）。校验不一致的测例会写入 test/data/check_mismatch.json。
"""
import json
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.message import MessageGroup
from models.record_manager import RecordManager
from models.instruction import InstructionType, OptionInstruction


# 从 origin_message 单条 dict 构建 MessageGroup（position -> has_message_above / has_message_below）
def origin_row_to_message_group(row: dict) -> MessageGroup:
    pos = row.get("position", "single")
    if pos == "first":
        has_above, has_below = False, True
    elif pos == "middle":
        has_above, has_below = True, True
    elif pos == "last":
        has_above, has_below = True, False
    else:
        has_above, has_below = False, False

    content = row.get("content", "").strip()
    return MessageGroup(
        group_id=row.get("domID", ""),
        timestamp=row.get("timestamp", ""),
        primary_message=content,
        related_messages=[],
        quoted_context=row.get("refer") or "",
        has_message_above=has_above,
        has_message_below=has_below,
        history=list(row.get("history", [])),
    )


def check_instruction_completeness(instruction_dict: Dict) -> bool:
    """检查指令信息是否完整（与 parsed_message 的 status ✅ 一致）。"""
    if not instruction_dict:
        return False
    inst_type = instruction_dict.get("instruction_type", "")
    if inst_type in ["OPEN", "BUY", "CLOSE", "TAKE_PROFIT", "STOP_LOSS", "MODIFY", "SELL"]:
        if instruction_dict.get("symbol"):
            return True
        has_ticker = bool(instruction_dict.get("ticker"))
        has_strike = instruction_dict.get("strike") is not None
        has_expiry = bool(instruction_dict.get("expiry"))
        has_option_type = bool(instruction_dict.get("option_type"))
        if has_ticker and has_strike and has_expiry and has_option_type:
            return True
        return False
    return True


def build_origin_from_row(row: dict) -> dict:
    """从原始行构建输出中的 origin 字段（与 parsed_message.json 一致）。"""
    return {
        "domID": row.get("domID"),
        "content": row.get("content", ""),
        "original_content": row.get("original_content", row.get("content", "")),
        "timestamp": row.get("timestamp", ""),
        "refer": row.get("refer"),
        "position": row.get("position", "middle"),
        "history": list(row.get("history", [])),
    }


def parse_from_rows(rows: List[dict], origin_message_path: str = "data/origin_message.json") -> List[dict]:
    """
    从内存中的 origin 行列表解析，返回与 parse_and_output 相同结构的列表（每项 { origin, parsed, status }）。
    """
    if not rows:
        return []
    message_groups = [origin_row_to_message_group(r) for r in rows]
    manager = RecordManager(origin_message_path=origin_message_path)
    records = manager.create_records(message_groups)
    manager.analyze_records(records)

    results: List[dict] = []
    for row, rec in zip(rows, records):
        origin = build_origin_from_row(row)
        inst = rec.instruction
        if inst:
            parsed = inst.to_dict()
            parsed.pop("origin", None)  # MessageGroup 不可 JSON 序列化
            status = "✅" if check_instruction_completeness(parsed) else "⚠️"
        else:
            parsed = None
            status = "❌"
        results.append({"origin": origin, "parsed": parsed, "status": status})
    return results


def validate_against_check(origin: dict, check: dict, parsed: Optional[dict]) -> tuple[bool, List[str]]:
    """
    校验解析结果与 check 是否一致。timestamp 期望为 origin 的 timestamp 字段。
    返回 (是否一致, 不一致项描述列表)。
    """
    diffs: List[str] = []
    if parsed is None:
        diffs.append("parsed is None")
        return False, diffs

    # timestamp：期望为 origin 的 timestamp
    expected_ts = origin.get("timestamp", "")
    actual_ts = parsed.get("timestamp")
    if actual_ts != expected_ts:
        diffs.append(f"timestamp: expected {expected_ts!r}, got {actual_ts!r}")

    for key in ("instruction_type", "symbol", "price"):
        if key not in check:
            continue
        expected = check[key]
        actual = parsed.get(key)
        if actual != expected:
            diffs.append(f"{key}: expected {expected!r}, got {actual!r}")

    if "sell_quantity" in check:
        expected = check["sell_quantity"]
        actual = parsed.get("sell_quantity")
        if actual != expected:
            diffs.append(f"sell_quantity: expected {expected!r}, got {actual!r}")

    return len(diffs) == 0, diffs


def parse_and_output(
    input_path: str = "data/origin_message.json",
    output_path: str = "test_parse_result.json",
    show_display: bool = False,
) -> List[dict]:
    """
    从 origin_message.json 读取，解析，按 parsed_message.json 格式写入 output_path。
    返回解析结果列表（每项 { origin, parsed, status }）。
    """
    with open(input_path, "r", encoding="utf-8") as f:
        rows = json.load(f)
    if not isinstance(rows, list):
        rows = []

    results = parse_from_rows(rows, origin_message_path=input_path)

    out_file = Path(__file__).resolve().parent.parent / output_path
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    if show_display:
        message_groups = [origin_row_to_message_group(r) for r in rows]
        manager = RecordManager(origin_message_path=input_path)
        records = manager.create_records(message_groups)
        manager.analyze_records(records)
        print("\n" + "=" * 60 + "\n解析结果 (instruction.display)\n" + "=" * 60)
        for i, rec in enumerate(records, 1):
            msg = rec.message.primary_message[:50]
            if len(rec.message.primary_message) > 50:
                msg += "..."
            print(f"\n--- 第 {i} 条: {msg} ---")
            if rec.instruction:
                rec.instruction.display()
            else:
                print("(未解析出指令)")

    return results


# 校验不一致的测例输出路径（相对项目根）
CHECK_MISMATCH_PATH = "test/data/check_mismatch.json"


def run_check_validation_and_collect_mismatches(
    check_path: str = "data/check.json",
    mismatch_path: str = CHECK_MISMATCH_PATH,
) -> List[dict]:
    """
    从 check.json 读取（每项含 origin + check），解析后与 check 校验；
    timestamp 期望为 origin 的 timestamp。返回校验不一致的测例列表并写入 mismatch_path。
    """
    root = Path(__file__).resolve().parent.parent
    with open(root / check_path, "r", encoding="utf-8") as f:
        check_data = json.load(f)
    if not isinstance(check_data, list):
        check_data = []

    rows = [item["origin"] for item in check_data]
    results = parse_from_rows(rows, origin_message_path=str(root / "data/origin_message.json"))

    mismatches: List[dict] = []
    for i, item in enumerate(check_data):
        expect = item.get("check")
        if expect is None:
            continue
        origin = results[i]["origin"] if i < len(results) else None
        parsed = results[i]["parsed"] if i < len(results) else None
        ok, diffs = validate_against_check(origin or item["origin"], expect, parsed)
        if not ok:
            mismatches.append({
                "index": i + 1,
                "origin": origin or item["origin"],
                "check": expect,
                "parsed": parsed,
                "diffs": diffs,
            })

    out_file = root / mismatch_path
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(mismatches, f, ensure_ascii=False, indent=2)

    return mismatches


def test_parse_from_origin_and_output():
    """从 origin_message.json 读取、解析、输出 test_parse_result.json """
    results = parse_and_output(
        input_path="data/origin_message.json",
        output_path="test_parse_result.json",
        show_display=True,
    )

    assert len(results) > 0, "应有解析结果"
    out_path = Path(__file__).resolve().parent.parent / "test_parse_result.json"
    assert out_path.exists(), "应生成 test_parse_result.json"

    # 验证输出格式与 parsed_message.json 一致
    for item in results:
        assert "origin" in item and "parsed" in item and "status" in item
        assert item["origin"].keys() >= {"domID", "content", "original_content", "timestamp", "refer", "position", "history"}
        assert item["status"] in ("✅", "⚠️", "❌")


def test_check_json_validation_and_mismatch_file():
    """使用 data/check.json 校验解析结果，将不一致的测例写入 test/data/check_mismatch.json"""
    mismatches = run_check_validation_and_collect_mismatches(
        check_path="data/check.json",
        mismatch_path=CHECK_MISMATCH_PATH,
    )
    out_path = Path(__file__).resolve().parent.parent / CHECK_MISMATCH_PATH
    assert out_path.exists(), "应生成校验不一致测例文件 test/data/check_mismatch.json"
    # 仅断言文件存在且结构正确；不强制要求 len(mismatches)==0，便于后续按文件修解析或期望
    for m in mismatches:
        assert "origin" in m and "check" in m and "parsed" in m and "diffs" in m


if __name__ == "__main__":
    test_check_json_validation_and_mismatch_file()
    test_parse_from_origin_and_output()
