"""Add household/salon transaction scope.

Revision ID: 20260702_0013
Revises: 20260629_0012
Create Date: 2026-07-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260702_0013"
down_revision: str | None = "20260629_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCOPE_VALUES = "'household', 'salon'"
STATIONERY_ALIASES = (
    "канцелярия",
    "канцтовары",
    "бумага",
    "ручки",
    "расходники",
)
AUTO_ALIASES = (
    "такси",
    "яндекс такси",
    "транспорт",
)


def upgrade() -> None:
    with op.batch_alter_table("transactions", recreate="always") as batch_op:
        batch_op.add_column(
            sa.Column(
                "scope",
                sa.String(length=32),
                server_default="household",
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "transactions_scope",
            f"scope in ({SCOPE_VALUES})",
        )
        batch_op.create_index("ix_transactions_scope", ["scope"])

    with op.batch_alter_table("bank_events", recreate="always") as batch_op:
        batch_op.add_column(
            sa.Column(
                "scope",
                sa.String(length=32),
                server_default="household",
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "bank_events_scope",
            f"scope in ({SCOPE_VALUES})",
        )
        batch_op.create_index("ix_bank_events_scope", ["scope"])

    op.execute(
        """
        update categories
        set title = 'Авто/Транспорт/Такси'
        where code = 'auto'
          and title = 'Авто (бензин, базовое ТО)'
        """
    )
    op.execute(
        """
        insert into categories (
            code,
            title,
            owner_user_id,
            owner_role,
            sort_order,
            is_expense,
            is_active
        )
        select 'stationery_supplies', 'Канцелярия/Расходники', null, 'system', 18, 1, 1
        where not exists (
            select 1 from categories where code = 'stationery_supplies'
        )
        """
    )
    for alias in STATIONERY_ALIASES:
        op.execute(
            sa.text(
                """
                insert into category_aliases (alias, category_id)
                select :alias, id
                from categories
                where code = 'stationery_supplies'
                  and not exists (
                      select 1 from category_aliases where alias = :alias
                  )
                """
            ).bindparams(alias=alias)
        )
    for alias in AUTO_ALIASES:
        op.execute(
            sa.text(
                """
                insert into category_aliases (alias, category_id)
                select :alias, id
                from categories
                where code = 'auto'
                  and not exists (
                      select 1 from category_aliases where alias = :alias
                  )
                """
            ).bindparams(alias=alias)
        )


def downgrade() -> None:
    all_aliases = (*STATIONERY_ALIASES, *AUTO_ALIASES)
    quoted_aliases = ", ".join(f"'{alias}'" for alias in all_aliases)
    op.execute(f"delete from category_aliases where alias in ({quoted_aliases})")
    op.execute(
        """
        update categories
        set title = 'Удалено: Канцелярия/Расходники',
            sort_order = 118,
            is_expense = 0,
            is_active = 0
        where code = 'stationery_supplies'
        """
    )
    op.execute(
        """
        update categories
        set title = 'Авто (бензин, базовое ТО)'
        where code = 'auto'
          and title = 'Авто/Транспорт/Такси'
        """
    )

    with op.batch_alter_table("bank_events", recreate="always") as batch_op:
        batch_op.drop_index("ix_bank_events_scope")
        batch_op.drop_constraint("bank_events_scope", type_="check")
        batch_op.drop_column("scope")

    with op.batch_alter_table("transactions", recreate="always") as batch_op:
        batch_op.drop_index("ix_transactions_scope")
        batch_op.drop_constraint("transactions_scope", type_="check")
        batch_op.drop_column("scope")
