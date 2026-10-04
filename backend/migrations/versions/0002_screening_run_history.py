"""Store screening run history.

Revision ID: 0002_screening_run_history
Revises: 0001_initial
Create Date: 2026-10-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_screening_run_history"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "screening_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_screening_runs_created_at",
        "screening_runs",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_screening_runs_created_at", table_name="screening_runs")
    op.drop_table("screening_runs")
