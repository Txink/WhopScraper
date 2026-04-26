"""Tests for scripts/build_golden.py — prepare + merge modes."""

import json
from pathlib import Path

import pytest

from scripts.build_golden import (
    build_subagent_prompt,
    merge_batches,
    prepare_batches,
)


def _msg(domid: str, content: str) -> dict:
    return {"domID": domid, "content": content,
            "timestamp": "2025-10-07 00:00:00.000",
            "refer": None, "position": "single", "history": []}


def test_prepare_batches_splits_corpus(tmp_path: Path) -> None:
    corpus = [_msg(f"m{i}", f"content {i}") for i in range(10)]
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps(corpus, ensure_ascii=False))
    out_dir = tmp_path / "batches"

    paths = prepare_batches(corpus_path=corpus_path, out_dir=out_dir, batch_size=4)

    assert len(paths) == 3  # 10 / 4 = 3 batches (4 + 4 + 2)
    batch1 = json.loads(paths[0].read_text())
    assert len(batch1) == 4
    assert batch1[0]["domID"] == "m0"
    batch3 = json.loads(paths[2].read_text())
    assert len(batch3) == 2
    assert batch3[0]["domID"] == "m8"


def test_build_subagent_prompt_embeds_few_shot_and_input() -> None:
    batch = [_msg("m1", "TSLL 27.2出一半")]
    prompt = build_subagent_prompt(batch)
    assert "TSLL 27.2出一半" in prompt
    # few-shot embedded
    assert "few_shot_chatter_greeting" in prompt or "大家好" in prompt
    # rules embedded
    assert "trade_signal" in prompt
    assert "ambiguous" in prompt


def test_merge_batches_validates_and_sorts_to_corpus_order(tmp_path: Path) -> None:
    corpus = [_msg("m0", "x0"), _msg("m1", "x1"), _msg("m2", "x2")]
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps(corpus, ensure_ascii=False))

    # Two batch outputs, NOT in corpus order
    batch_dir = tmp_path / "batches"
    batch_dir.mkdir()
    batch1 = [
        {"domID": "m2", "content": "x2", "classification": "chatter",
         "expected": None, "requires_context": False, "notes": ""},
    ]
    batch2 = [
        {"domID": "m0", "content": "x0", "classification": "chatter",
         "expected": None, "requires_context": False, "notes": ""},
        {"domID": "m1", "content": "x1", "classification": "chatter",
         "expected": None, "requires_context": False, "notes": ""},
    ]
    (batch_dir / "batch_00_output.json").write_text(json.dumps(batch1, ensure_ascii=False))
    (batch_dir / "batch_01_output.json").write_text(json.dumps(batch2, ensure_ascii=False))

    out_path = tmp_path / "golden.json"
    merge_batches(batch_dir=batch_dir, corpus_path=corpus_path, out_path=out_path)

    merged = json.loads(out_path.read_text())
    assert [g["domID"] for g in merged] == ["m0", "m1", "m2"]


def test_merge_batches_rejects_invalid_entry(tmp_path: Path) -> None:
    corpus = [_msg("m0", "x0")]
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps(corpus, ensure_ascii=False))

    batch_dir = tmp_path / "batches"
    batch_dir.mkdir()
    bad_batch = [
        {"domID": "m0", "content": "x0", "classification": "garbage",
         "expected": None, "requires_context": False, "notes": ""},
    ]
    (batch_dir / "batch_00_output.json").write_text(json.dumps(bad_batch, ensure_ascii=False))

    out_path = tmp_path / "golden.json"
    with pytest.raises(ValueError, match="classification"):
        merge_batches(batch_dir=batch_dir, corpus_path=corpus_path, out_path=out_path)


def test_merge_batches_rejects_missing_domid(tmp_path: Path) -> None:
    """If a corpus message has no entry in any batch, merge fails loudly."""
    corpus = [_msg("m0", "x0"), _msg("m1", "x1")]
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps(corpus, ensure_ascii=False))

    batch_dir = tmp_path / "batches"
    batch_dir.mkdir()
    incomplete = [
        {"domID": "m0", "content": "x0", "classification": "chatter",
         "expected": None, "requires_context": False, "notes": ""},
        # m1 missing
    ]
    (batch_dir / "batch_00_output.json").write_text(json.dumps(incomplete, ensure_ascii=False))

    out_path = tmp_path / "golden.json"
    with pytest.raises(ValueError, match="m1"):
        merge_batches(batch_dir=batch_dir, corpus_path=corpus_path, out_path=out_path)


def test_merge_batches_rejects_duplicate_domid(tmp_path: Path) -> None:
    """Duplicate entries (same domID across batches) → fail loudly."""
    corpus = [_msg("m0", "x0")]
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps(corpus, ensure_ascii=False))

    batch_dir = tmp_path / "batches"
    batch_dir.mkdir()
    dup1 = [{"domID": "m0", "content": "x0", "classification": "chatter",
             "expected": None, "requires_context": False, "notes": ""}]
    dup2 = [{"domID": "m0", "content": "x0", "classification": "chatter",
             "expected": None, "requires_context": False, "notes": ""}]
    (batch_dir / "batch_00_output.json").write_text(json.dumps(dup1, ensure_ascii=False))
    (batch_dir / "batch_01_output.json").write_text(json.dumps(dup2, ensure_ascii=False))

    out_path = tmp_path / "golden.json"
    with pytest.raises(ValueError, match="duplicate"):
        merge_batches(batch_dir=batch_dir, corpus_path=corpus_path, out_path=out_path)
