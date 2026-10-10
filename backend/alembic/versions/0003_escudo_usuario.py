"""quiniela: escudo de equipo como foto de perfil

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-10 20:20:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("crest_team_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_users_crest_team", "users", "teams", ["crest_team_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_users_crest_team", "users", type_="foreignkey")
    op.drop_column("users", "crest_team_id")
