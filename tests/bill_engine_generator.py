"""The bill layout generator's cases as PDFs (specs/pdf-table-engine-bills/test-contract.md SC-123).

`evals/bill_layouts.py` draws each file (positions, texts and the expected lines, amounts and split); this module only turns a layout into a PDF with
`tests/test_pdf.py make_pdf`, so tests can read it with the real reader. The seed is fixed: the same cases come out every run.
"""

from evals import bill_layouts
from test_pdf import make_pdf

SEED = 20261111
CASES = 120


def layout(index, seed=SEED, **choices):
    return bill_layouts.make(seed, index, **choices)


def build(path, case):
    """Write the case's PDF to `path` and return the path."""
    make_pdf(path, case.pages)
    return path
