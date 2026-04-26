"""build_golden — generate data/parser_golden.json from corpus + subagent batches.

Two-phase tool used at the orchestration layer:

  1. `prepare`: split data/stock_origin_message.json into N batches under
     data/golden_batches/batch_NN_input.json. Print the subagent prompt for
     each batch on stdout. The controller (parent conversation) dispatches
     subagents one per batch with that prompt + the batch's input messages,
     and saves each subagent's JSON response to batch_NN_output.json.

  2. `merge`: read all batch_NN_output.json files, validate each entry via
     golden_lib.validate_golden_entry, ensure no duplicate domIDs and full
     corpus coverage, sort to corpus order, write data/parser_golden.json.

Why split into prepare + merge: actual subagent dispatch is a controller
action (the orchestrating LLM in this repo's superpowers stack), not
something this Python script can perform on its own. We keep build_golden
focused on the deterministic, testable pieces (split + validate + merge)
and delegate the LLM calls to the conversation layer.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.golden_lib import (
    BUILD_PROMPT_TEMPLATE,
    FEW_SHOT_EXAMPLES,
    validate_golden_entry,
)


CORPUS_PATH_DEFAULT = Path(__file__).resolve().parent.parent.parent / "data" / "stock_origin_message.json"
BATCH_DIR_DEFAULT = Path(__file__).resolve().parent.parent.parent / "data" / "golden_batches"
GOLDEN_PATH_DEFAULT = Path(__file__).resolve().parent.parent.parent / "data" / "parser_golden.json"

DEFAULT_BATCH_SIZE = 200


# ---------------------------------------------------------------------------
# prepare — split corpus into batches
# ---------------------------------------------------------------------------


def prepare_batches(
    *,
    corpus_path: Path = CORPUS_PATH_DEFAULT,
    out_dir: Path = BATCH_DIR_DEFAULT,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[Path]:
    """Split corpus into batches, write each to out_dir/batch_NN_input.json.

    Returns the list of written paths in batch index order.
    """
    corpus = json.loads(corpus_path.read_text())
    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for i in range(0, len(corpus), batch_size):
        batch = corpus[i : i + batch_size]
        idx = len(written)
        path = out_dir / f"batch_{idx:02d}_input.json"
        path.write_text(json.dumps(batch, ensure_ascii=False, indent=2))
        written.append(path)
    return written


def build_subagent_prompt(batch: list[dict]) -> str:
    """Construct the full subagent prompt for one batch."""
    return BUILD_PROMPT_TEMPLATE.format(
        FEW_SHOT_JSON=json.dumps(FEW_SHOT_EXAMPLES, ensure_ascii=False, indent=2),
        INPUT_JSON=json.dumps(batch, ensure_ascii=False, indent=2),
    )


# ---------------------------------------------------------------------------
# merge — combine batch outputs into parser_golden.json
# ---------------------------------------------------------------------------


def merge_batches(
    *,
    batch_dir: Path = BATCH_DIR_DEFAULT,
    corpus_path: Path = CORPUS_PATH_DEFAULT,
    out_path: Path = GOLDEN_PATH_DEFAULT,
) -> None:
    """Validate + merge all batch_NN_output.json into out_path.

    Raises ValueError if:
      - any entry fails schema validation
      - any domID appears in more than one batch
      - the corpus has a domID not covered by any batch
    """
    corpus = json.loads(corpus_path.read_text())
    corpus_domids = [m["domID"] for m in corpus]
    corpus_domid_set = set(corpus_domids)

    seen: dict[str, dict] = {}
    output_files = sorted(batch_dir.glob("batch_*_output.json"))
    for path in output_files:
        entries = json.loads(path.read_text())
        if not isinstance(entries, list):
            raise ValueError(f"{path} is not a JSON array")
        for entry in entries:
            errors = validate_golden_entry(entry)
            if errors:
                raise ValueError(f"{path} entry domID={entry.get('domID')!r}: {errors}")
            domid = entry["domID"]
            if domid in seen:
                raise ValueError(f"duplicate domID across batches: {domid}")
            if domid not in corpus_domid_set:
                raise ValueError(f"{path} entry domID={domid} not in corpus")
            seen[domid] = entry

    missing = corpus_domid_set - seen.keys()
    if missing:
        raise ValueError(f"corpus domIDs missing from batch outputs: {sorted(missing)[:10]}...")

    # Sort to corpus order
    merged = [seen[domid] for domid in corpus_domids]
    out_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_prepare(args: argparse.Namespace) -> int:
    paths = prepare_batches(
        corpus_path=Path(args.corpus) if args.corpus else CORPUS_PATH_DEFAULT,
        out_dir=Path(args.out_dir) if args.out_dir else BATCH_DIR_DEFAULT,
        batch_size=args.batch_size,
    )
    print(f"Wrote {len(paths)} batches:")
    for p in paths:
        n = len(json.loads(p.read_text()))
        print(f"  {p}  ({n} messages)")
    print()
    print("To run: dispatch one subagent per batch_NN_input.json with the")
    print("prompt printed by --print-prompt, save responses to batch_NN_output.json")
    print("in the same directory, then run `build_golden.py merge`.")
    return 0


def _cmd_print_prompt(args: argparse.Namespace) -> int:
    batch_path = Path(args.batch)
    batch = json.loads(batch_path.read_text())
    print(build_subagent_prompt(batch))
    return 0


def _cmd_merge(args: argparse.Namespace) -> int:
    merge_batches(
        batch_dir=Path(args.batch_dir) if args.batch_dir else BATCH_DIR_DEFAULT,
        corpus_path=Path(args.corpus) if args.corpus else CORPUS_PATH_DEFAULT,
        out_path=Path(args.out) if args.out else GOLDEN_PATH_DEFAULT,
    )
    print(f"Merged → {args.out or GOLDEN_PATH_DEFAULT}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build parser_golden.json from corpus + subagent batches.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_prepare = sub.add_parser("prepare", help="Split corpus into batches")
    p_prepare.add_argument("--corpus", default=None)
    p_prepare.add_argument("--out-dir", default=None)
    p_prepare.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    p_prepare.set_defaults(func=_cmd_prepare)

    p_prompt = sub.add_parser("print-prompt", help="Print subagent prompt for one batch input")
    p_prompt.add_argument("batch", help="Path to batch_NN_input.json")
    p_prompt.set_defaults(func=_cmd_print_prompt)

    p_merge = sub.add_parser("merge", help="Merge batch outputs into parser_golden.json")
    p_merge.add_argument("--batch-dir", default=None)
    p_merge.add_argument("--corpus", default=None)
    p_merge.add_argument("--out", default=None)
    p_merge.set_defaults(func=_cmd_merge)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    import sys
    sys.exit(main())
