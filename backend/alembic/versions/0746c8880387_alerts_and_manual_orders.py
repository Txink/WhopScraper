"""alerts and manual orders

Revision ID: 0746c8880387
Revises: d250c4f32ccf
Create Date: 2026-05-25 00:45:46.169931

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0746c8880387'
down_revision: str | Sequence[str] | None = 'd250c4f32ccf'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # tasks new columns
    op.add_column("tasks", sa.Column("source", sa.String(), nullable=True))
    op.add_column(
        "tasks",
        sa.Column("last_replaced_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("condition_type", sa.String(), nullable=False),
        sa.Column("operator", sa.String(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("pct_change_baseline", sa.String(), nullable=True),
        sa.Column("volume_window", sa.String(), nullable=True),
        sa.Column("repeat_mode", sa.String(), nullable=False),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trigger_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("idx_alerts_ticker_enabled", "alerts", ["ticker", "enabled"])
    op.create_index("idx_alerts_symbol_enabled", "alerts", ["symbol", "enabled"])

    op.create_table(
        "alert_events",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column(
            "alert_id",
            sa.Integer(),
            sa.ForeignKey("alerts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("snapshot_price", sa.Float(), nullable=False),
        sa.Column("snapshot_pct", sa.Float(), nullable=True),
        sa.Column("snapshot_volume", sa.Float(), nullable=True),
        sa.Column("message", sa.String(), nullable=False),
    )
    op.create_index("idx_alert_events_alert_ts", "alert_events", ["alert_id", "triggered_at"])
    op.create_index("idx_alert_events_ticker_ts", "alert_events", ["ticker", "triggered_at"])


def downgrade() -> None:
    op.drop_index("idx_alert_events_ticker_ts", "alert_events")
    op.drop_index("idx_alert_events_alert_ts", "alert_events")
    op.drop_table("alert_events")
    op.drop_index("idx_alerts_symbol_enabled", "alerts")
    op.drop_index("idx_alerts_ticker_enabled", "alerts")
    op.drop_table("alerts")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("last_replaced_at")
        batch.drop_column("source")
