from sqlalchemy import URL, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings

settings = get_settings()
database_url = URL.create(
    drivername="postgresql+psycopg",
    username=settings.db_user,
    password=settings.db_password.get_secret_value(),
    host=settings.db_host,
    port=settings.db_port,
    database=settings.db_name,
)
engine = create_engine(
    database_url, pool_pre_ping=True, connect_args={"connect_timeout": 5}
)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    with SessionLocal() as session:
        yield session
