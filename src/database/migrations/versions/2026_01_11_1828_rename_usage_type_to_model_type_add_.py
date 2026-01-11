"""rename_usage_type_to_model_type_add_model_id

Revision ID: 337b5a63aede
Revises: 9a3d79cb15d5
Create Date: 2026-01-11 18:28:17.844576

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "337b5a63aede"
down_revision = "9a3d79cb15d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rename usage_type column to model_type in predictions table
    op.alter_column(
        "predictions",
        "usage_type",
        new_column_name="model_type",
        existing_type=sa.String(),
        existing_nullable=True,
    )

    # Rename usage_type column to model_type in usage_records table
    op.alter_column(
        "usage_records",
        "usage_type",
        new_column_name="model_type",
        existing_type=sa.String(),
        existing_nullable=False,
    )

    # Add model_id column to predictions table
    op.add_column(
        "predictions",
        sa.Column("model_id", sa.String(50), nullable=True),
    )

    # Add model_id column to usage_records table
    op.add_column(
        "usage_records",
        sa.Column("model_id", sa.String(50), nullable=True),
    )

    # Update existing model_type values from old enum to new format
    # Old: 'geoinfer_global_0_0_1' -> New: 'global'
    op.execute(
        """
        UPDATE predictions
        SET model_type = 'global'
        WHERE model_type = 'geoinfer_global_0_0_1'
           OR model_type IS NULL
        """
    )

    op.execute(
        """
        UPDATE usage_records
        SET model_type = 'global'
        WHERE model_type = 'geoinfer_global_0_0_1'
        """
    )

    # Set model_id for existing records (they all used global_v0.1)
    op.execute(
        """
        UPDATE predictions
        SET model_id = 'global_v0.1'
        WHERE model_id IS NULL
        """
    )

    op.execute(
        """
        UPDATE usage_records
        SET model_id = 'global_v0.1'
        WHERE model_id IS NULL
        """
    )

    # Add result_type discriminator to existing shared_predictions result_data
    # All existing predictions are coordinate-based (Global model)
    op.execute(
        """
        UPDATE shared_predictions
        SET result_data = result_data || '{"result_type": "coordinates"}'::jsonb
        WHERE result_data->>'result_type' IS NULL
        """
    )


def downgrade() -> None:
    # Remove result_type from shared_predictions result_data
    op.execute(
        """
        UPDATE shared_predictions
        SET result_data = result_data - 'result_type'
        """
    )
    # Revert model_type values back to old enum format
    op.execute(
        """
        UPDATE predictions
        SET model_type = 'geoinfer_global_0_0_1'
        WHERE model_type = 'global'
        """
    )

    op.execute(
        """
        UPDATE usage_records
        SET model_type = 'geoinfer_global_0_0_1'
        WHERE model_type = 'global'
        """
    )

    # Drop model_id columns
    op.drop_column("usage_records", "model_id")
    op.drop_column("predictions", "model_id")

    # Rename model_type back to usage_type
    op.alter_column(
        "usage_records",
        "model_type",
        new_column_name="usage_type",
        existing_type=sa.String(),
        existing_nullable=False,
    )

    op.alter_column(
        "predictions",
        "model_type",
        new_column_name="usage_type",
        existing_type=sa.String(),
        existing_nullable=True,
    )
