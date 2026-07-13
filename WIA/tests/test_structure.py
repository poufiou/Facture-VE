"""Tests de cohérence de la structure initiale de WIA."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_expected_project_directories_exist() -> None:
    """Vérifie que les répertoires structurants du projet sont présents."""
    expected_directories = [
        "imports",
        "engine",
        "database",
        "dashboard",
        "reports",
        "tests",
        "data",
    ]

    for directory in expected_directories:
        assert (PROJECT_ROOT / directory).is_dir()
