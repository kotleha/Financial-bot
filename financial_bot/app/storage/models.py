from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from financial_bot.app.domain.types import (
    AuditAction,
    BankEventBank,
    BankEventChannel,
    BankEventOperationKind,
    BankEventParseStatus,
    BankEventSuggestionSource,
    CategoryOwnerRole,
    TransactionSource,
    TransactionType,
    UserRole,
)

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _sql_values(enum_type: type[StrEnum]) -> str:
    return ", ".join(f"'{item.value}'" for item in enum_type)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class UserModel(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            f"role in ({_sql_values(UserRole)})",
            name="users_role",
        ),
        UniqueConstraint("telegram_id"),
        UniqueConstraint("role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )

    owned_categories: Mapped[list["CategoryModel"]] = relationship(
        back_populates="owner",
        foreign_keys="CategoryModel.owner_user_id",
    )
    paid_transactions: Mapped[list["TransactionModel"]] = relationship(
        back_populates="payer",
        foreign_keys="TransactionModel.payer_user_id",
    )
    created_transactions: Mapped[list["TransactionModel"]] = relationship(
        back_populates="created_by",
        foreign_keys="TransactionModel.created_by_user_id",
    )
    bank_event_sources: Mapped[list["BankEventSourceModel"]] = relationship(
        back_populates="owner",
        foreign_keys="BankEventSourceModel.owner_user_id",
    )
    bank_category_rules: Mapped[list["BankCategoryRuleModel"]] = relationship(
        back_populates="owner",
        foreign_keys="BankCategoryRuleModel.owner_user_id",
    )


class CategoryModel(TimestampMixin, Base):
    __tablename__ = "categories"
    __table_args__ = (
        CheckConstraint(
            f"owner_role in ({_sql_values(CategoryOwnerRole)})",
            name="categories_owner_role",
        ),
        UniqueConstraint("code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    owner_role: Mapped[str] = mapped_column(String(32), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_expense: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )

    owner: Mapped[UserModel | None] = relationship(
        back_populates="owned_categories",
        foreign_keys=[owner_user_id],
    )
    aliases: Mapped[list["CategoryAliasModel"]] = relationship(
        back_populates="category",
        cascade="all, delete-orphan",
    )
    transactions: Mapped[list["TransactionModel"]] = relationship(back_populates="category")
    spending_limit_alerts: Mapped[list["SpendingLimitAlertModel"]] = relationship(
        back_populates="category"
    )
    bank_category_rules: Mapped[list["BankCategoryRuleModel"]] = relationship(
        back_populates="category"
    )


class CategoryAliasModel(TimestampMixin, Base):
    __tablename__ = "category_aliases"
    __table_args__ = (UniqueConstraint("alias"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alias: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)

    category: Mapped[CategoryModel] = relationship(back_populates="aliases")


class TransactionModel(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="transactions_amount_positive"),
        CheckConstraint(
            f"type in ({_sql_values(TransactionType)})",
            name="transactions_type",
        ),
        CheckConstraint(
            f"source in ({_sql_values(TransactionSource)})",
            name="transactions_source",
        ),
        Index("ix_transactions_occurred_at", "occurred_at"),
        Index("ix_transactions_payer_user_id", "payer_user_id"),
        Index("ix_transactions_category_id", "category_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payer_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=TransactionSource.UNKNOWN.value,
        server_default=TransactionSource.UNKNOWN.value,
    )
    comment: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    included_in_reports: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    payer: Mapped[UserModel] = relationship(
        back_populates="paid_transactions",
        foreign_keys=[payer_user_id],
    )
    category: Mapped[CategoryModel] = relationship(back_populates="transactions")
    created_by: Mapped[UserModel] = relationship(
        back_populates="created_transactions",
        foreign_keys=[created_by_user_id],
    )
    audit_logs: Mapped[list["OperationAuditLogModel"]] = relationship(
        back_populates="transaction",
        cascade="all, delete-orphan",
    )


class SettingModel(Base):
    __tablename__ = "settings"
    __table_args__ = (UniqueConstraint("key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class OperationAuditLogModel(Base):
    __tablename__ = "operation_audit_log"
    __table_args__ = (
        CheckConstraint(
            f"action in ({_sql_values(AuditAction)})",
            name="operation_audit_log_action",
        ),
        Index("ix_operation_audit_log_transaction_id", "transaction_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    old_value: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    changed_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    transaction: Mapped[TransactionModel] = relationship(back_populates="audit_logs")
    changed_by: Mapped[UserModel] = relationship(foreign_keys=[changed_by_user_id])


class SpendingLimitAlertModel(Base):
    __tablename__ = "spending_limit_alerts"
    __table_args__ = (
        CheckConstraint(
            "threshold_percent > 0 and threshold_percent <= 100",
            name="spending_limit_alerts_threshold_percent",
        ),
        UniqueConstraint(
            "period_start",
            "category_id",
            "threshold_percent",
            "sent_to_user_id",
        ),
        Index("ix_spending_limit_alerts_period_start", "period_start"),
        Index("ix_spending_limit_alerts_category_id", "category_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    threshold_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), nullable=False)
    sent_to_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    category: Mapped[CategoryModel] = relationship(back_populates="spending_limit_alerts")
    transaction: Mapped[TransactionModel] = relationship()
    sent_to_user: Mapped[UserModel] = relationship(foreign_keys=[sent_to_user_id])


class BankEventSourceModel(TimestampMixin, Base):
    __tablename__ = "bank_event_sources"
    __table_args__ = (
        CheckConstraint(
            f"bank in ({_sql_values(BankEventBank)})",
            name="bank_event_sources_bank",
        ),
        CheckConstraint(
            f"channel in ({_sql_values(BankEventChannel)})",
            name="bank_event_sources_channel",
        ),
        UniqueConstraint("code"),
        UniqueConstraint("token_hash"),
        Index("ix_bank_event_sources_owner_user_id", "owner_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    bank: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    owner: Mapped[UserModel] = relationship(
        back_populates="bank_event_sources",
        foreign_keys=[owner_user_id],
    )
    bank_events: Mapped[list["BankEventModel"]] = relationship(back_populates="source_record")


class BankCategoryRuleModel(Base):
    __tablename__ = "bank_category_rules"
    __table_args__ = (
        CheckConstraint(
            f"bank in ({_sql_values(BankEventBank)})",
            name="bank_category_rules_bank",
        ),
        UniqueConstraint("owner_user_id", "bank", "merchant_key"),
        Index("ix_bank_category_rules_owner_bank", "owner_user_id", "bank"),
        Index("ix_bank_category_rules_category_id", "category_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    bank: Mapped[str] = mapped_column(String(32), nullable=False)
    merchant_key: Mapped[str] = mapped_column(String(255), nullable=False)
    merchant_display: Mapped[str] = mapped_column(String(255), nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    last_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    owner: Mapped[UserModel] = relationship(
        back_populates="bank_category_rules",
        foreign_keys=[owner_user_id],
    )
    category: Mapped[CategoryModel] = relationship(back_populates="bank_category_rules")


class BankEventModel(Base):
    __tablename__ = "bank_events"
    __table_args__ = (
        CheckConstraint(
            f"bank in ({_sql_values(BankEventBank)})",
            name="bank_events_bank",
        ),
        CheckConstraint(
            f"channel in ({_sql_values(BankEventChannel)})",
            name="bank_events_channel",
        ),
        CheckConstraint(
            f"operation_kind in ({_sql_values(BankEventOperationKind)})",
            name="bank_events_operation_kind",
        ),
        CheckConstraint(
            f"parse_status in ({_sql_values(BankEventParseStatus)})",
            name="bank_events_parse_status",
        ),
        CheckConstraint(
            f"source in ({_sql_values(TransactionSource)})",
            name="bank_events_source",
        ),
        CheckConstraint(
            "suggested_category_source is null or "
            f"suggested_category_source in ({_sql_values(BankEventSuggestionSource)})",
            name="bank_events_suggested_category_source",
        ),
        CheckConstraint("amount is null or amount > 0", name="bank_events_amount_positive"),
        CheckConstraint(
            "fee_amount is null or fee_amount >= 0",
            name="bank_events_fee_amount_non_negative",
        ),
        UniqueConstraint("dedupe_key"),
        Index("ix_bank_events_source_id", "source_id"),
        Index("ix_bank_events_received_at", "received_at"),
        Index("ix_bank_events_parse_status", "parse_status"),
        Index("ix_bank_events_transaction_id", "transaction_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("bank_event_sources.id"), nullable=False)
    bank: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    operation_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    parse_status: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fee_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=TransactionSource.UNKNOWN.value,
        server_default=TransactionSource.UNKNOWN.value,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="RUB",
        server_default="RUB",
    )
    merchant: Mapped[str | None] = mapped_column(String(255), nullable=True)
    counterparty: Mapped[str | None] = mapped_column(String(255), nullable=True)
    redacted_text: Mapped[str] = mapped_column(String(2000), nullable=False)
    normalized_text_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    suggested_category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id"),
        nullable=True,
    )
    suggested_category_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), nullable=True)
    telegram_notification_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    telegram_notification_failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    telegram_notification_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    raw_text_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    source_record: Mapped[BankEventSourceModel] = relationship(back_populates="bank_events")
    suggested_category: Mapped[CategoryModel | None] = relationship()
    transaction: Mapped[TransactionModel | None] = relationship()
