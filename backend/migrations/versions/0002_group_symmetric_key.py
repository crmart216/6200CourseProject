"""Allow encrypted groups to store their server-decrypted AES-256 group key.

Legacy groups have NULL symmetric_key and continue to use the old API.
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("groups", sa.Column("symmetric_key", sa.LargeBinary(32), nullable=True))


def downgrade():
    op.drop_column("groups", "symmetric_key")
