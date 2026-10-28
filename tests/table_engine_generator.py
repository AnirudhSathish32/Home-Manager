"""The layout generator's cases as PDFs (specs/pdf-table-engine/test-contract.md SC-18).

`evals/statement_layouts.py` draws each statement (positions, texts and the expected rows); this module only turns a layout into a PDF with
`tests/test_pdf.py make_pdf`, so tests can read it with the real reader. The seed is fixed: the same cases come out every run.
"""

from evals import statement_layouts
from test_pdf import make_pdf

SEED = 20261028
CASES = 200


def layout(index, seed=SEED):
    return statement_layouts.make(seed, index)


def build(path, case):
    """Write the case's PDF to `path` and return the path."""
    make_pdf(path, case.pages)
    return path
