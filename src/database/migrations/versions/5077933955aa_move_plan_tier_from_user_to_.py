"""Move plan_tier from User to Organization model

Revision ID: 5077933955aa
Revises: f157889e69f6
Create Date: 2025-09-23 20:53:06.738892

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "5077933955aa"
down_revision = "f157889e69f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add plan_tier column to organizations table
    op.add_column(
        "organizations",
        sa.Column("plan_tier", sa.String(), nullable=False, server_default="free"),
    )

    # Migrate existing plan_tier data from users to their organizations
    # This assumes each user belongs to exactly one organization
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
        UPDATE organizations 
        SET plan_tier = users.plan_tier 
        FROM users 
        WHERE organizations.id = users.organization_id
    """
        )
    )

    # Drop plan_tier column from users table
    op.drop_column("users", "plan_tier")


def downgrade() -> None:
    # Add plan_tier column back to users table
    op.add_column(
        "users",
        sa.Column("plan_tier", sa.String(), nullable=False, server_default="free"),
    )

    # Migrate plan_tier data back from organizations to users
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
        UPDATE users 
        SET plan_tier = organizations.plan_tier 
        FROM organizations 
        WHERE users.organization_id = organizations.id
    """
        )
    )

    # Drop plan_tier column from organizations table
    op.drop_column("organizations", "plan_tier")
