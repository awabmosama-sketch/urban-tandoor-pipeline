import asyncio

from app.database import async_session_factory
from app.ingestion.docs_pipeline import ingest_all_docs


async def main():
    async with async_session_factory() as session:
        r = await ingest_all_docs(session)
        await session.commit()
    for k, v in r.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(main())
