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
