"""The pay stub layout generator's cases as PDFs (specs/pdf-table-engine-paystubs/test-contract.md SC-67).

`evals/paystub_layouts.py` draws each file (positions, texts and the expected pay lines, totals and split); this module only turns a layout into a
PDF with `tests/test_pdf.py make_pdf`, so tests can read it with the real reader. The seed is fixed: the same cases come out every run.
"""

from evals import paystub_layouts
from test_pdf import make_pdf

SEED = 20261104
CASES = 120


def layout(index, seed=SEED):
    return paystub_layouts.make(seed, index)


def build(path, case):
    """Write the case's PDF to `path` and return the path."""
    make_pdf(path, case.pages)
    return path
