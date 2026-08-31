from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from tradefoundry.config import get_settings


class Base(DeclarativeBase):
    pass


def build_engine(database_url: str | None = None):
    url = database_url or get_settings().database_url
    kwargs = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, pool_pre_ping=True, connect_args=kwargs)


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def create_all(database_engine=None) -> None:
    from tradefoundry.bilateral import models as bilateral_models  # noqa: F401
    from tradefoundry.controltower import models as controltower_models  # noqa: F401
    from tradefoundry.deals import models as deal_models  # noqa: F401
    from tradefoundry.evidence import models as evidence_models  # noqa: F401
    from tradefoundry.execution import models as execution_models  # noqa: F401
    from tradefoundry.ingestion import models  # noqa: F401
    from tradefoundry.master import models as master_models  # noqa: F401
    from tradefoundry.opportunity import models as opportunity_models  # noqa: F401
    from tradefoundry.tradealpha import models as tradealpha_models  # noqa: F401

    Base.metadata.create_all(database_engine or engine)
