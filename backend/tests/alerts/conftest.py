import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.alerts.repo import AlertRepo
from app.storage.db import Base


@pytest_asyncio.fixture
async def repo() -> AlertRepo:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield AlertRepo(factory)
    await engine.dispose()
