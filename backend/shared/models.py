"""SQLAlchemy ORM models for all tables."""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import (
    String, Boolean, DateTime, Numeric, Integer, Text, ForeignKey,
    UniqueConstraint, Index, ARRAY, LargeBinary, JSON
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, BYTEA
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from database import Base


def gen_uuid():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    password_hash: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    preferred_currency: Mapped[str] = mapped_column(String(3), default="USD")
    timezone: Mapped[str] = mapped_column(String(50), default="UTC")
    tax_country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    cost_basis_method: Mapped[str] = mapped_column(String(20), default="FIFO")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    accounts: Mapped[list["Account"]] = relationship("Account", back_populates="user", cascade="all, delete-orphan")
    transactions: Mapped[list["Transaction"]] = relationship("Transaction", back_populates="user")
    conversations: Mapped[list["AdvisorConversation"]] = relationship("AdvisorConversation", back_populates="user")


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    institution_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    account_type: Mapped[str] = mapped_column(String(50), nullable=False)  # BROKERAGE|IRA|ROTH_IRA|401K|CRYPTO_EXCHANGE|WALLET
    account_subtype: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    broker_account_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_taxable: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_status: Mapped[str] = mapped_column(String(20), default="NEVER")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship("User", back_populates="accounts")
    transactions: Mapped[list["Transaction"]] = relationship("Transaction", back_populates="account")
    holdings: Mapped[list["Holding"]] = relationship("Holding", back_populates="account")

    __table_args__ = (
        UniqueConstraint("user_id", "broker_account_id"),
    )


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    asset_class: Mapped[str] = mapped_column(String(30), nullable=False)  # EQUITY|CRYPTO|ETF|MUTUAL_FUND|BOND|CASH
    exchange: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    isin: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    cusip: Mapped[Optional[str]] = mapped_column(String(9), nullable=True)
    coingecko_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    polygon_ticker: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    sector: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    industry: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    transactions: Mapped[list["Transaction"]] = relationship("Transaction", back_populates="asset", foreign_keys="Transaction.asset_id")
    prices: Mapped[list["Price"]] = relationship("Price", back_populates="asset")
    tax_lots: Mapped[list["TaxLot"]] = relationship("TaxLot", back_populates="asset")

    __table_args__ = (
        UniqueConstraint("symbol", "exchange"),
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    account_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    asset_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("assets.id"), nullable=True)

    transaction_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # BUY|SELL|DIVIDEND|SPLIT|TRANSFER_IN|TRANSFER_OUT|FEE|INTEREST|DEPOSIT|WITHDRAWAL
    # MERGER|SPIN_OFF|STAKE_REWARD|AIRDROP|MINING_REWARD|SWAP
    status: Mapped[str] = mapped_column(String(20), default="SETTLED")

    quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(28, 10), nullable=True)
    price_per_unit: Mapped[Optional[Decimal]] = mapped_column(Numeric(28, 10), nullable=True)
    gross_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(28, 10), nullable=True)
    fees: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=0)
    net_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(28, 10), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    fx_rate_to_usd: Mapped[Decimal] = mapped_column(Numeric(20, 10), default=1.0)
    net_amount_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(28, 10), nullable=True)
    # AUD cost base — mandatory for ATO CGT calculations
    fx_rate_to_aud: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 10), nullable=True)
    net_amount_aud: Mapped[Optional[Decimal]] = mapped_column(Numeric(28, 10), nullable=True)
    price_per_unit_aud: Mapped[Optional[Decimal]] = mapped_column(Numeric(28, 10), nullable=True)
    # Source institution (for bank imports)
    institution: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    transacted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    settled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Corporate action fields
    split_ratio: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 6), nullable=True)
    related_asset_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("assets.id"), nullable=True)

    # Deduplication
    external_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    import_hash: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True)

    # Source tracking
    source: Mapped[str] = mapped_column(String(30), default="MANUAL")
    raw_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    account: Mapped["Account"] = relationship("Account", back_populates="transactions")
    user: Mapped["User"] = relationship("User", back_populates="transactions")
    asset: Mapped[Optional["Asset"]] = relationship("Asset", back_populates="transactions", foreign_keys=[asset_id])

    __table_args__ = (
        Index("ix_transactions_account_date", "account_id", "transacted_at"),
        Index("ix_transactions_user_date", "user_id", "transacted_at"),
        Index("ix_transactions_import_hash", "import_hash"),
    )


class Holding(Base):
    __tablename__ = "holdings"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    account_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    asset_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("assets.id"), nullable=False)

    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    average_cost_basis: Mapped[Optional[Decimal]] = mapped_column(Numeric(28, 10), nullable=True)
    total_cost_basis: Mapped[Optional[Decimal]] = mapped_column(Numeric(28, 10), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")

    last_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(28, 10), nullable=True)
    last_price_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    market_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(28, 10), nullable=True)
    unrealized_gain: Mapped[Optional[Decimal]] = mapped_column(Numeric(28, 10), nullable=True)
    unrealized_gain_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 6), nullable=True)

    as_of_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    account: Mapped["Account"] = relationship("Account", back_populates="holdings")
    asset: Mapped["Asset"] = relationship("Asset")

    __table_args__ = (
        UniqueConstraint("account_id", "asset_id", "as_of_date"),
        Index("ix_holdings_user_date", "user_id", "as_of_date"),
    )


class Price(Base):
    __tablename__ = "prices"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    asset_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("assets.id"), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    price_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price_type: Mapped[str] = mapped_column(String(20), default="CLOSE")  # OPEN|HIGH|LOW|CLOSE|REALTIME
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    asset: Mapped["Asset"] = relationship("Asset", back_populates="prices")

    __table_args__ = (
        UniqueConstraint("asset_id", "price_date", "price_type", "source"),
        Index("ix_prices_asset_date", "asset_id", "price_date"),
    )


class TaxLot(Base):
    __tablename__ = "tax_lots"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    account_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    asset_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("assets.id"), nullable=False)

    opening_transaction_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("transactions.id"), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    quantity_acquired: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    cost_basis_per_unit: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    total_cost_basis: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    quantity_remaining: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)

    closing_transaction_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("transactions.id"), nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    proceeds: Mapped[Optional[Decimal]] = mapped_column(Numeric(28, 10), nullable=True)
    realized_gain: Mapped[Optional[Decimal]] = mapped_column(Numeric(28, 10), nullable=True)
    holding_period_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_long_term: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    is_wash_sale: Mapped[bool] = mapped_column(Boolean, default=False)
    wash_sale_disallowed_loss: Mapped[Optional[Decimal]] = mapped_column(Numeric(28, 10), nullable=True)
    wash_sale_adjustment_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    lot_status: Mapped[str] = mapped_column(String(20), default="OPEN")  # OPEN|PARTIALLY_CLOSED|CLOSED

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    asset: Mapped["Asset"] = relationship("Asset", back_populates="tax_lots")

    __table_args__ = (
        Index("ix_tax_lots_account_asset", "account_id", "asset_id", "lot_status"),
        Index("ix_tax_lots_user_open", "user_id", "lot_status"),
        Index("ix_tax_lots_acquired", "acquired_at"),
    )


class AdvisorConversation(Base):
    __tablename__ = "advisor_conversations"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    messages: Mapped[list] = mapped_column(JSONB, default=list)
    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="conversations")


class ApiCredential(Base):
    __tablename__ = "api_credentials"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    credential_type: Mapped[str] = mapped_column(String(50), nullable=False)

    encrypted_access_token: Mapped[Optional[bytes]] = mapped_column(BYTEA, nullable=True)
    encrypted_refresh_token: Mapped[Optional[bytes]] = mapped_column(BYTEA, nullable=True)
    encrypted_api_key: Mapped[Optional[bytes]] = mapped_column(BYTEA, nullable=True)
    encrypted_api_secret: Mapped[Optional[bytes]] = mapped_column(BYTEA, nullable=True)
    encryption_key_id: Mapped[str] = mapped_column(String(100), nullable=False, default="default")

    token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    plaid_item_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    snaptrade_user_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    snaptrade_user_secret: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "provider", "credential_type"),
    )


class BackgroundJob(Base):
    __tablename__ = "background_jobs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    celery_task_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    result: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
