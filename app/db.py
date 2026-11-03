from datetime import datetime, timezone
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker, with_loader_criteria
from sqlalchemy.pool import StaticPool
from . import config


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Record:
    """统一整数主键、UTC时间、软删除和SQLAlchemy原生乐观锁。"""
    from sqlalchemy import DateTime, Integer
    from sqlalchemy.orm import Mapped, mapped_column, declared_attr
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    @declared_attr.directive
    def __mapper_args__(cls):
        return {'version_id_col': cls.version}


@event.listens_for(Session, 'do_orm_execute')
def filter_deleted(state):
    if state.is_select and not state.execution_options.get('include_deleted'):
        state.statement = state.statement.options(
            with_loader_criteria(Record, lambda cls: cls.deleted_at.is_(None), include_aliases=True))


url = config.DATABASE_URL or 'postgresql+psycopg://unconfigured@localhost/tuoke'
if url.startswith('sqlite') and config.APP_ENV != 'test':
    raise RuntimeError('SQLite 仅允许 APP_ENV=test')
kwargs = {'pool_pre_ping': True}
if url.startswith('sqlite'):
    kwargs.update(connect_args={'check_same_thread': False}, poolclass=StaticPool)
engine = create_engine(url, **kwargs)
if url.startswith('sqlite'):
    @event.listens_for(engine, 'connect')
    def foreign_keys(conn, _):
        conn.execute('PRAGMA foreign_keys=ON')
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    with SessionLocal() as db:
        try:
            yield db
        except Exception:
            db.rollback()
            raise
