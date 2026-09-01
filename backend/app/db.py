from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker, DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


def _ensure_dirs() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    settings.exports_dir.mkdir(parents=True, exist_ok=True)
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    settings.media_cache_dir.mkdir(parents=True, exist_ok=True)


_ensure_dirs()
engine = create_engine(
    f"sqlite:///{settings.db_path}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _add_column_if_missing(table: str, column: str, ddl: str) -> None:
    with engine.connect() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        names = {row[1] for row in rows}
        if column in names:
            return
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        conn.commit()


def init_db() -> None:
    from app import models  # noqa: F401

    _ensure_dirs()
    Base.metadata.create_all(bind=engine)
    _add_column_if_missing("messages", "media_relpath", "TEXT DEFAULT ''")
    _add_column_if_missing("messages", "media_name", "TEXT DEFAULT ''")
    _add_column_if_missing("messages", "media_mime", "TEXT DEFAULT ''")
    _add_column_if_missing("messages", "media_status", "TEXT DEFAULT ''")
    _add_column_if_missing("analysis_jobs", "prompt_id", "INTEGER")
    _add_column_if_missing("analysis_jobs", "progress", "INTEGER DEFAULT 0")
    _add_column_if_missing("analysis_jobs", "progress_label", "TEXT DEFAULT ''")
    _add_column_if_missing("accounts", "wx_username", "TEXT DEFAULT ''")
    _add_column_if_missing("analysis_results", "title", "TEXT DEFAULT ''")
    _add_column_if_missing("analysis_jobs", "kind", "TEXT DEFAULT 'report'")
    _add_column_if_missing("analysis_jobs", "contact_id", "INTEGER")
    _add_column_if_missing("analysis_jobs", "report_type", "TEXT DEFAULT 'portrait'")
    _add_column_if_missing("sync_jobs", "account_id", "INTEGER")
    _ensure_message_account_hash_index()
    from app.analyze.prompt_store import seed_default_prompts
    from app.accounts import current_account_key, migrate_local_accounts

    db = SessionLocal()
    try:
        seed_default_prompts(db)
        migrate_local_accounts(db, current_account_key())
        db.commit()
    finally:
        db.close()


def _ensure_message_account_hash_index() -> None:
    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_message_account_hash "
                    "ON messages(account_id, raw_hash)"
                )
            )
            conn.commit()
    except OperationalError:
        pass
