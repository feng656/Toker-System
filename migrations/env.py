from logging.config import fileConfig
from alembic import context
from sqlalchemy import pool, create_engine
from app.config import DATABASE_URL
from app.models import Base

if context.config.config_file_name:
    fileConfig(context.config.config_file_name)
target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    # APScheduler的pickle jobstore由0002独立维护，不由业务ORM自动比较/删除。
    return not (type_ == 'table' and name == 'apscheduler_jobs')


def run_offline():
    context.configure(url=DATABASE_URL, target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={'paramstyle': 'named'}, compare_type=True, include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()


def run_online():
    connection = context.config.attributes.get('connection')
    engine = None
    if connection is None:
        engine = create_engine(DATABASE_URL, poolclass=pool.NullPool)
        connection = engine.connect()
    try:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True,
                          include_object=include_object,
                          render_as_batch=connection.dialect.name == 'sqlite')
        with context.begin_transaction():
            context.run_migrations()
    finally:
        if engine:
            connection.close()
            engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
