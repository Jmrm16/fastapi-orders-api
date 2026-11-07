"""initial_schema_with_coupons_and_audit_events

Revision ID: 1542feb7ef47
Revises: 
Create Date: 2026-11-06 19:13:54.916047

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1542feb7ef47'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema with coupon columns and indices."""
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('subtotal', sa.Float(), nullable=False, server_default='0.0'))
        batch_op.add_column(sa.Column('discount_amount', sa.Float(), nullable=False, server_default='0.0'))
        batch_op.add_column(sa.Column('idempotency_key', sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column('coupon_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_orders_idempotency_key'), ['idempotency_key'], unique=True)
        batch_op.create_index(batch_op.f('ix_orders_status'), ['status'], unique=False)
        batch_op.create_foreign_key('fk_orders_coupons', 'coupons', ['coupon_id'], ['id'])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.drop_constraint('fk_orders_coupons', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_orders_status'))
        batch_op.drop_index(batch_op.f('ix_orders_idempotency_key'))
        batch_op.drop_column('coupon_id')
        batch_op.drop_column('idempotency_key')
        batch_op.drop_column('discount_amount')
        batch_op.drop_column('subtotal')
