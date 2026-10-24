"""Check that the source layout is usable by the test runner."""

from importlib import import_module
from pathlib import Path


def test_package_imports_from_project_sources() -> None:
    package = import_module("finance_mcp")
    expected_directory = Path(__file__).resolve().parents[1] / "src" / "finance_mcp"

    assert package.__file__ is not None
    assert Path(package.__file__).resolve().parent == expected_directory
