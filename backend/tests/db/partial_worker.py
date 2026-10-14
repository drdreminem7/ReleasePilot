"""Test helper: persist a graph checkpoint, then wait to be killed by its parent."""

import asyncio
import sys
from pathlib import Path
from uuid import UUID

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from releasepilot.db import build_engine, database_url, session_factory
from releasepilot.graph import build_graph
from releasepilot.models import Investigation, RegisteredWorkloadRecord
from releasepilot.providers import FixtureProvider
from releasepilot.read_tools import ReadOnlyTools


async def main(investigation_id: UUID, marker: Path) -> None:
    engine = build_engine()
    factory = session_factory(engine)
    with factory() as db:
        item = db.get(Investigation, investigation_id)
        assert item is not None
        workload = db.get(RegisteredWorkloadRecord, item.workload_id)
        assert workload is not None
        thread_id = str(item.langgraph_thread_id)
        workload_id = str(workload.id)
    conninfo = database_url().replace("postgresql+psycopg://", "postgresql://", 1)
    serde = JsonPlusSerializer(allowed_msgpack_modules=None)
    async with AsyncPostgresSaver.from_conn_string(conninfo, serde=serde) as saver:
        await saver.setup()
        graph = build_graph(
            ReadOnlyTools(workload),
            FixtureProvider(),
            saver,
            interrupt_after=["collect_snapshot"],
        )
        config = {"configurable": {"thread_id": thread_id}}
        await graph.ainvoke({"workload_id": workload_id}, config)
        snapshot = await graph.aget_state(config)
        assert snapshot.next == ("execute_read_only_tools",)
        marker.write_text("checkpointed")
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main(UUID(sys.argv[1]), Path(sys.argv[2])))
