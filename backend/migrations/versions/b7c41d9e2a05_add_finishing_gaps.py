"""add finishing gap and race time to session results

Revision ID: b7c41d9e2a05
Revises: fe633526d1b1
Create Date: 2026-09-26 22:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7c41d9e2a05"
down_revision: str | Sequence[str] | None = "fe633526d1b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable, no default: existing rows stay null until their session is
    # re-ingested, which is what the page shows as "no gap recorded".
    op.add_column(
        "session_results",
        sa.Column("gap_to_winner_ms", sa.Integer(), nullable=True),
        schema="gridmind",
    )
    op.add_column(
        "session_results", sa.Column("race_time_ms", sa.Integer(), nullable=True), schema="gridmind"
    )


def downgrade() -> None:
    op.drop_column("session_results", "race_time_ms", schema="gridmind")
    op.drop_column("session_results", "gap_to_winner_ms", schema="gridmind")
