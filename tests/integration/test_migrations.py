import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config


def test_tbank_migration_allows_tbank_bank_events(tmp_path: Path) -> None:
    db_path = tmp_path / "migration.sqlite3"
    config = _alembic_config(db_path)

    command.upgrade(config, "20260628_0009")
    assert "tbank" not in _table_sql(db_path, "bank_event_sources")

    command.upgrade(config, "20260628_0010")

    assert "tbank" in _table_sql(db_path, "bank_event_sources")
    assert "tbank" in _table_sql(db_path, "bank_events")
    assert "tbank" in _table_sql(db_path, "bank_category_rules")

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            insert into users (telegram_id, name, role, is_active)
            values (1002, 'Wife', 'wife', 1)
            """
        )
        owner_id = connection.execute("select id from users where role = 'wife'").fetchone()[0]
        connection.execute(
            """
            insert into bank_event_sources (
                code, bank, channel, owner_user_id, token_hash
            )
            values ('wife-tbank-ios', 'tbank', 'ios_shortcut', ?, ?)
            """,
            (owner_id, "0" * 64),
        )
        source_id = connection.execute(
            "select id from bank_event_sources where code = 'wife-tbank-ios'"
        ).fetchone()[0]
        connection.execute(
            """
            insert into bank_events (
                source_id,
                bank,
                channel,
                received_at,
                operation_kind,
                parse_status,
                currency,
                redacted_text,
                normalized_text_hash,
                dedupe_key
            )
            values (
                ?,
                'tbank',
                'ios_shortcut',
                '2026-06-28 12:00:00',
                'ignored',
                'ignored',
                'RUB',
                '<ignored_non_transaction_message:tbank>',
                ?,
                ?
            )
            """,
            (source_id, "1" * 64, "tbank-migration-smoke"),
        )


def test_bank_category_rule_mode_migration_backfills_existing_rules(tmp_path: Path) -> None:
    db_path = tmp_path / "migration-rule-mode.sqlite3"
    config = _alembic_config(db_path)

    command.upgrade(config, "20260629_0011")

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            insert into users (telegram_id, name, role, is_active)
            values (1001, 'Husband', 'husband', 1)
            """
        )
        owner_id = connection.execute("select id from users where role = 'husband'").fetchone()[0]
        connection.execute(
            """
            insert into categories (code, title, owner_role, sort_order, is_expense, is_active)
            values ('groceries', 'Продукты', 'system', 1, 1, 1)
            """
        )
        category_id = connection.execute(
            "select id from categories where code = 'groceries'"
        ).fetchone()[0]
        connection.executemany(
            """
            insert into bank_category_rules (
                owner_user_id, bank, merchant_key, merchant_display, category_id, hit_count,
                is_active
            )
            values (?, 'sber', ?, ?, ?, ?, ?)
            """,
            (
                (owner_id, "autosave shop", "AUTOSAVE SHOP", category_id, 2, 1),
                (owner_id, "suggest shop", "SUGGEST SHOP", category_id, 1, 1),
                (owner_id, "disabled shop", "DISABLED SHOP", category_id, 3, 0),
            ),
        )
        connection.commit()

    command.upgrade(config, "20260629_0012")

    assert "mode" in _table_sql(db_path, "bank_category_rules")
    assert "suggestion_conflict" in _table_sql(db_path, "bank_events")
    with sqlite3.connect(db_path) as connection:
        rows = dict(
            connection.execute(
                "select merchant_key, mode from bank_category_rules order by merchant_key"
            ).fetchall()
        )

    assert rows == {
        "autosave shop": "autosave",
        "disabled shop": "disabled",
        "suggest shop": "suggest",
    }


def test_transaction_scope_migration_backfills_rows_and_category_aliases(tmp_path: Path) -> None:
    db_path = tmp_path / "migration-transaction-scope.sqlite3"
    config = _alembic_config(db_path)

    command.upgrade(config, "20260629_0012")

    assert "scope" not in _table_sql(db_path, "transactions")
    assert "scope" not in _table_sql(db_path, "bank_events")

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            insert into users (telegram_id, name, role, is_active)
            values (1001, 'Husband', 'husband', 1)
            """
        )
        user_id = connection.execute("select id from users where role = 'husband'").fetchone()[0]
        connection.execute(
            """
            insert into categories (code, title, owner_role, sort_order, is_expense, is_active)
            values ('auto', 'Авто (бензин, базовое ТО)', 'system', 4, 1, 1)
            """
        )
        category_id = connection.execute(
            "select id from categories where code = 'auto'"
        ).fetchone()[0]
        connection.execute(
            """
            insert into transactions (
                amount, currency, occurred_at, payer_user_id, category_id, type, source,
                included_in_reports, created_by_user_id
            )
            values (
                10000, 'RUB', '2026-07-02 12:00:00', ?, ?, 'expense', 'card', 1, ?
            )
            """,
            (user_id, category_id, user_id),
        )
        connection.execute(
            """
            insert into bank_event_sources (
                code, bank, channel, owner_user_id, token_hash
            )
            values ('husband-sber-ios', 'sber', 'ios_shortcut', ?, ?)
            """,
            (user_id, "0" * 64),
        )
        source_id = connection.execute(
            "select id from bank_event_sources where code = 'husband-sber-ios'"
        ).fetchone()[0]
        connection.execute(
            """
            insert into bank_events (
                source_id,
                bank,
                channel,
                received_at,
                operation_kind,
                parse_status,
                amount,
                source,
                currency,
                redacted_text,
                normalized_text_hash,
                dedupe_key
            )
            values (
                ?,
                'sber',
                'ios_shortcut',
                '2026-07-02 12:00:00',
                'expense_candidate',
                'needs_confirmation',
                10000,
                'card',
                'RUB',
                '<redacted>',
                ?,
                ?
            )
            """,
            (source_id, "1" * 64, "scope-migration-smoke"),
        )
        connection.commit()

    command.upgrade(config, "20260702_0013")

    assert "scope" in _table_sql(db_path, "transactions")
    assert "scope" in _table_sql(db_path, "bank_events")
    assert "ix_transactions_scope" in _index_names(db_path, "transactions")
    assert "ix_bank_events_scope" in _index_names(db_path, "bank_events")
    with sqlite3.connect(db_path) as connection:
        transaction_scope = connection.execute("select scope from transactions").fetchone()[0]
        bank_event_scope = connection.execute("select scope from bank_events").fetchone()[0]
        categories = dict(connection.execute("select code, title from categories").fetchall())
        aliases = {
            row[0]
            for row in connection.execute(
                """
                select alias
                from category_aliases
                where alias in ('такси', 'транспорт', 'канцелярия', 'расходники')
                """
            ).fetchall()
        }

    assert transaction_scope == "household"
    assert bank_event_scope == "household"
    assert categories["auto"] == "Авто/Транспорт/Такси"
    assert categories["stationery_supplies"] == "Канцелярия/Расходники"
    assert aliases == {"такси", "транспорт", "канцелярия", "расходники"}


def _alembic_config(db_path: Path) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("script_location", "migrations")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return config


def _table_sql(db_path: Path, table_name: str) -> str:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "select sql from sqlite_master where type = 'table' and name = ?",
            (table_name,),
        ).fetchone()
    assert row is not None
    return row[0]


def _index_names(db_path: Path, table_name: str) -> set[str]:
    with sqlite3.connect(db_path) as connection:
        return {
            row[1] for row in connection.execute(f"pragma index_list('{table_name}')").fetchall()
        }
