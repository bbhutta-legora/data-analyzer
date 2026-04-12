# exporter.py
# Builds a Jupyter notebook (.ipynb JSON) from a session's code history.
# Pure logic — no I/O, no side effects.
# Supports: PRD #7 (Export)
# Key deps: none (builds a plain dict, no nbformat library)
#
# Each code_history entry becomes a markdown cell (explanation) followed by
# a code cell (generated code). The notebook also includes a header cell with
# library imports and a data-loading cell that reads the uploaded file.
#
# Architecture ref: "exporter.py" in planning/architecture.md

NBFORMAT_VERSION = 4
NBFORMAT_MINOR_VERSION = 5


def build_notebook(code_history: list[dict], filename: str) -> dict:
    """
    Build a complete Jupyter notebook dict from a session's code history.

    Parameters:
        code_history: list of dicts with "code" and "explanation" keys.
        filename: original uploaded filename (e.g. "sales.csv") for the data-loading cell.

    Returns:
        A dict representing a valid nbformat v4 notebook, ready to be serialized as JSON.
    """
    cells = [_make_header_cell(), _make_data_loading_cell(filename)]

    for entry in code_history:
        explanation = entry.get("explanation", "")
        code = entry.get("code", "")

        if explanation:
            cells.append(_make_markdown_cell(explanation))
        if code:
            cells.append(_make_code_cell(code))

    return _notebook_wrapper(cells)


def _make_code_cell(source: str) -> dict:
    """Create a single nbformat v4 code cell."""
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": [source],
    }


def _make_markdown_cell(source: str) -> dict:
    """Create a single nbformat v4 markdown cell."""
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": [source],
    }


def _make_header_cell() -> dict:
    """Create the imports code cell with standard analysis libraries."""
    imports = (
        "import pandas as pd\n"
        "import numpy as np\n"
        "import matplotlib.pyplot as plt\n"
        "import seaborn as sns\n"
        "import sklearn"
    )
    return _make_code_cell(imports)


def _make_data_loading_cell(filename: str) -> dict:
    """Create a code cell that loads the dataset from the uploaded file.

    Handles filenames containing quotes, backslashes, or other special characters
    by escaping them before embedding in the Python source string.
    Falls back to "data.csv" when the filename is empty.
    """
    safe_name = filename if filename else "data.csv"
    # Escape backslashes first, then single quotes, for embedding in a '-delimited string.
    escaped = safe_name.replace("\\", "\\\\").replace("'", "\\'")
    return _make_code_cell(f"df = pd.read_csv('{escaped}')")


def _notebook_wrapper(cells: list[dict]) -> dict:
    """Wrap a list of cells in the top-level nbformat v4 notebook structure."""
    return {
        "nbformat": NBFORMAT_VERSION,
        "nbformat_minor": NBFORMAT_MINOR_VERSION,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {
                "name": "python",
                "version": "3.11.0",
            },
        },
        "cells": cells,
    }
