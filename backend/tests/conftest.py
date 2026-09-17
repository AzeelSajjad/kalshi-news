import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.config import get_settings
from app.db import Base


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(get_settings().database_url)
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.rollback()
    for table in reversed(Base.metadata.sorted_tables):
        s.execute(table.delete())
    s.commit()
    s.close()
