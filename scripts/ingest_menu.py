import asyncio

from app.database import async_session_factory
from app.ingestion.excel_menu import ingest_menu_catalog


async def main():
    async with async_session_factory() as session:
        counts = await ingest_menu_catalog(session)
        await session.commit()
    for k, v in counts.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(main())
