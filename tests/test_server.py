import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from finance_mcp.importer import import_parsed
from finance_mcp.models import StatementInput
from finance_mcp.server import (
    READ_ONLY_TOOLS,
    WRITE_TOOLS,
    create_server,
    create_service,
)


def test_tool_schemas_and_read_only_annotations(tmp_path: Path) -> None:
    async def check() -> None:
        server = create_server(create_service(tmp_path))
        tools = await server.list_tools()
        assert {tool.name for tool in tools} == READ_ONLY_TOOLS | WRITE_TOOLS
        for tool in tools:
            assert tool.outputSchema is not None
            assert tool.annotations is not None
            assert tool.annotations.readOnlyHint == (tool.name in READ_ONLY_TOOLS)

    asyncio.run(check())


def test_real_stdio_session_and_restart(
    tmp_path: Path, statement: StatementInput
) -> None:
    service = create_service(tmp_path)
    import_parsed(service.store, statement, "a" * 64, "synthetic-test-v1")

    async def check() -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "finance_mcp", "--data-dir", str(tmp_path)],
        )
        async with asyncio.timeout(30), stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                status = await session.call_tool("get_status", {})
                assert not status.isError
                assert status.structuredContent["verified_parsers"] == []
                result = await session.call_tool(
                    "search_transactions",
                    {"filters": {"start": "2026-10-01", "bank": "kaspi"}, "limit": 1},
                )
                assert result.structuredContent["total"] == 1
                created = await session.call_tool(
                    "manage_categories", {"action": "create", "name": "Food"}
                )
                assert not created.isError
                await _check_categorization(
                    session, created.structuredContent["category_id"]
                )
                invalid = await session.call_tool("search_transactions", {"limit": 0})
                assert invalid.isError

    asyncio.run(check())
    reopened = create_service(tmp_path)
    assert len(reopened.manage_categories("list")["categories"]) == 2


async def _check_categorization(session: ClientSession, category_id: int) -> None:
    arguments = {"transaction_ids": [1], "category_id": category_id}
    preview = await session.call_tool("assign_category", arguments)
    applied = await session.call_tool(
        "assign_category",
        {**arguments, "preview_token": preview.structuredContent["preview_token"]},
    )
    report = await session.call_tool(
        "spending_report", {"filters": {"start": "2026-10-01", "end": "2026-10-31"}}
    )
    assert report.structuredContent["net_spending_tiyn"] == 125000
    assert report.structuredContent["categories"][0]["name"] == "Food"
    assert report.structuredContent["filters"]["start"] == "2026-10-01"
    undone = await session.call_tool(
        "undo_change", {"change_id": applied.structuredContent["change_id"]}
    )
    assert not undone.isError
    restored = await session.call_tool("get_transaction", {"transaction_id": 1})
    assert restored.structuredContent["transaction"]["category_id"] == 1
