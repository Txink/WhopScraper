from __future__ import annotations

from app.storage.schema import InstructionLabelRow


def test_instruction_labels_table_registered() -> None:
    assert InstructionLabelRow.__tablename__ == "instruction_labels"
    cols = set(InstructionLabelRow.__table__.columns.keys())
    assert cols == {"task_id", "verdict", "corrected_payload", "updated_at"}
