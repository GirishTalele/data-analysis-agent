"""phase2: add result_table_json to query_runs and create derived_datasets

Revision ID: a1b2c3d4e5f6
Revises: 33897bde32dc
Create Date: 2026-07-03 13:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '33897bde32dc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('query_runs', sa.Column('result_table_json', sa.JSON(), nullable=True))
    op.create_table(
        'derived_datasets',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('source_dataset_id', sa.Text(), nullable=False),
        sa.Column('created_from_query_run_id', sa.Text(), nullable=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('stored_path', sa.Text(), nullable=False),
        sa.Column('row_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['source_dataset_id'], ['datasets.id']),
        sa.ForeignKeyConstraint(['created_from_query_run_id'], ['query_runs.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('derived_datasets')
    op.drop_column('query_runs', 'result_table_json')
