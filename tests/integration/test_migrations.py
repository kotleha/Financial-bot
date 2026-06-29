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
