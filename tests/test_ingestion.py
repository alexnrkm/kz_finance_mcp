from pathlib import Path

import pytest

from finance_mcp.ingestion import Ingestion, extract_pages
from finance_mcp.models import Bank, StatementInput
from finance_mcp.storage import Store


def _pdf_bytes(text: str) -> bytes:
    """Build a minimal ASCII text PDF solely for extraction tests, not bank fixtures."""
    stream = f"BT /F1 12 Tf 20 80 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 100] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length "
        + str(len(stream)).encode()
        + b" >>\nstream\n"
        + stream
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    content = b"%PDF-1.4\n"
    offsets = [0]
    for index, item in enumerate(objects, 1):
        offsets.append(len(content))
        content += f"{index} 0 obj\n".encode() + item + b"\nendobj\n"
    xref = len(content)
    content += b"xref\n0 6\n0000000000 65535 f \n"
    content += b"".join(f"{offset:010} 00000 n \n".encode() for offset in offsets[1:])
    return (
        content
        + f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    )


class SyntheticParser:
    """Test-only adapter, never registered in the installed server."""

    bank = Bank.KASPI
    version = "synthetic-test-v1"

    def __init__(self, statement: StatementInput) -> None:
        self.statement = statement

    def matches(self, pages: tuple[str, ...]) -> bool:
        return "SYNTHETIC TEST ONLY" in pages[0]

    def parse(self, pages: tuple[str, ...]) -> StatementInput:
        return self.statement


def test_pdf_text_layer_and_invalid_inputs() -> None:
    assert "SYNTHETIC TEST ONLY" in extract_pages(_pdf_bytes("SYNTHETIC TEST ONLY"))[0]
    with pytest.raises(ValueError, match="text layer"):
        extract_pages(_pdf_bytes(""))
    with pytest.raises(ValueError, match="not a PDF"):
        extract_pages(b"not pdf")
    with pytest.raises(ValueError, match="Unable"):
        extract_pages(b"%PDF-corrupt")


def test_folder_import_isolated_errors_and_archive(
    store: Store,
    statement: StatementInput,
    tmp_path: Path,
) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "good.PDF").write_bytes(_pdf_bytes("SYNTHETIC TEST ONLY"))
    (inbox / "bad.pdf").write_bytes(b"not a pdf")
    ingestion = Ingestion(store, tmp_path, [inbox], [SyntheticParser(statement)])
    result = ingestion.import_folder(str(inbox))
    assert [item["status"] for item in result["files"]] == ["error", "imported"]
    assert len(list((tmp_path / "statements").glob("*.pdf"))) == 1
    assert ingestion.import_statement("good.PDF")["status"] == "already_imported"


def test_production_has_no_unverified_fallback(store: Store, tmp_path: Path) -> None:
    source = tmp_path / "statement.pdf"
    source.write_bytes(_pdf_bytes("SYNTHETIC TEST ONLY"))
    ingestion = Ingestion(store, tmp_path, [tmp_path])
    with pytest.raises(ValueError, match="Unsupported"):
        ingestion.import_statement(str(source))
    assert not (tmp_path / "statements").exists()


def test_path_boundary_rejects_parent_and_absolute_escape(
    store: Store, tmp_path: Path
) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    outside = tmp_path / "private.pdf"
    outside.write_bytes(_pdf_bytes("SYNTHETIC TEST ONLY"))
    ingestion = Ingestion(store, tmp_path, [inbox])
    for path in (str(outside), "../private.pdf"):
        with pytest.raises(ValueError, match="outside"):
            ingestion.import_statement(path)
