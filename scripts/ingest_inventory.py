import asyncio

from app.database import async_session_factory
from app.ingestion.excel_inventory import ingest_inventory


async def main():
    async with async_session_factory() as session:
        counts = await ingest_inventory(session)
        await session.commit()
    for k, v in counts.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(main())
