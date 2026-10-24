"""Local PDF ingestion; bank formats must be verified before registration."""

import hashlib
import os
from collections.abc import Sequence
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol

import pdfplumber
from pdfminer.pdfexceptions import PDFException
from pdfplumber.utils.exceptions import PdfminerException

from finance_mcp.importer import import_parsed
from finance_mcp.models import Bank, StatementInput
from finance_mcp.storage import Record, Store, rows

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 200
MAX_FOLDER_FILES = 200


class BankParser(Protocol):
    """Contract for a tested bank-format adapter; production has no fallback parser."""

    bank: Bank
    version: str

    def matches(self, pages: tuple[str, ...]) -> bool: ...

    def parse(self, pages: tuple[str, ...]) -> StatementInput: ...


def extract_pages(content: bytes) -> tuple[str, ...]:
    """Extract the text layer without OCR or model calls."""
    if not content.startswith(b"%PDF-"):
        raise ValueError("File is not a PDF")
    try:
        with pdfplumber.open(BytesIO(content)) as pdf:
            if len(pdf.pages) > MAX_PDF_PAGES:
                raise ValueError(f"PDF exceeds {MAX_PDF_PAGES} pages")
            pages = tuple(page.extract_text(layout=True) or "" for page in pdf.pages)
    except (PDFException, PdfminerException, ValueError, TypeError) as error:
        raise ValueError(
            "Unable to read PDF; check that it is valid and not encrypted"
        ) from error
    if not any(page.strip() for page in pages):
        raise ValueError("PDF has no text layer; OCR is not supported")
    return pages


class Ingestion:
    """Restrict filesystem access to explicitly configured import roots."""

    def __init__(
        self,
        store: Store,
        data_dir: Path,
        roots: Sequence[Path],
        parsers: Sequence[BankParser] = (),
    ) -> None:
        if not roots:
            raise ValueError("At least one import root is required")
        self.store = store
        self.archive = data_dir.resolve() / "statements"
        self.roots = tuple(root.resolve() for root in roots)
        self.parsers = tuple(parsers)

    def checked_path(self, value: str) -> Path:
        """Resolve symlinks before enforcing the configured root boundary."""
        path = Path(value).expanduser()
        resolved = (path if path.is_absolute() else self.roots[0] / path).resolve(
            strict=True
        )
        if not any(resolved.is_relative_to(root) for root in self.roots):
            raise ValueError("Path is outside the configured import roots")
        return resolved

    def import_statement(self, path: str) -> Record:
        """Hash before parsing; accept only a verified, unambiguous bank adapter."""
        source = self.checked_path(path)
        content = _read_pdf(source)
        digest = hashlib.sha256(content).hexdigest()
        with self.store.connect() as connection:
            existing = rows(
                connection, "SELECT id FROM statements WHERE sha256=?", (digest,)
            )
        if existing:
            return {"status": "already_imported", "statement_id": existing[0]["id"]}
        pages = extract_pages(content)
        matches = [parser for parser in self.parsers if parser.matches(pages)]
        if len(matches) != 1:
            raise ValueError(
                "Unsupported or ambiguous format; verified bank samples are required"
            )
        parser = matches[0]
        statement = parser.parse(pages)
        if statement.bank != parser.bank:
            raise ValueError("Bank parser returned a different bank")
        _archive(self.archive, digest, content)
        return import_parsed(self.store, statement, digest, parser.version)

    def import_folder(self, path: str) -> Record:
        """Import direct PDF children, reporting a separate result for each file."""
        folder = self.checked_path(path)
        if not folder.is_dir():
            raise ValueError("Expected a folder")
        files = sorted(
            item for item in folder.iterdir() if item.suffix.casefold() == ".pdf"
        )
        if len(files) > MAX_FOLDER_FILES:
            raise ValueError(f"Import at most {MAX_FOLDER_FILES} PDFs per call")
        return {"files": [_import_one(self, source) for source in files]}


def _read_pdf(path: Path) -> bytes:
    if not path.is_file() or path.suffix.casefold() != ".pdf":
        raise ValueError("Expected a local PDF file")
    with path.open("rb") as stream:
        content = stream.read(MAX_PDF_BYTES + 1)
    if len(content) > MAX_PDF_BYTES:
        raise ValueError("PDF exceeds the 20 MiB limit")
    return content


def _archive(directory: Path, digest: str, content: bytes) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=directory) as temporary_directory:
        temporary_path = Path(temporary_directory) / "statement.tmp"
        with temporary_path.open("wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, directory / f"{digest}.pdf")


def _import_one(ingestion: Ingestion, path: Path) -> Record:
    try:
        return {"file": path.name, **ingestion.import_statement(str(path))}
    except (OSError, ValueError) as error:
        message = (
            str(error) if isinstance(error, ValueError) else "Cannot access local PDF"
        )
        return {"file": path.name, "status": "error", "message": message}
