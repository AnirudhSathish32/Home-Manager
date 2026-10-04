"""Engine 2's runner (finance/engines/taxcalc.py): PSLmodels Tax-Calculator on one filing unit, in its own process.

Reads {"year", "record"} as JSON on stdin and writes one JSON answer on stdout:
- {"ok": true, "version", "last_known_year", "values": {output: dollars}, "policy": {parameter: dollars or rate}};
- or {"ok": false, "code", "message"} (NOT_INSTALLED, YEAR or FAILED).
The heavy imports (pandas, numba) stay out of the app's process, and a run that hangs is stopped by the caller's timeout.
"""

import json
import sys

# The outputs read back (Tax-Calculator's records_variables.json names them).
OUTPUTS = ("c00100", "c02500", "c02900", "c03260", "standard", "c04470", "senior_deduction", "tip_income_deduction", "overtime_income_deduction",
           "auto_loan_interest_deduction", "qbided", "c04800", "taxbc", "c09600", "c05800", "c07100", "c07180", "c07220", "c07230", "odc",
           "c09200", "othertaxes", "setax", "ptax_amc", "niit", "eitc", "c11070", "c10960", "refund", "iitax", "c01000", "dwks10")
# Law for the year and filing status: the standard deduction's parts and the rate schedule (for the Tax Table rule).
POLICY = ("STD", "STD_Aged", "STD_charity_ded_nonitemizers_max", *(f"II_rt{n}" for n in range(1, 8)), *(f"II_brk{n}" for n in range(1, 7)))


def answer(found):
    sys.stdout.write(json.dumps(found))
    return 0


def main():
    request = json.loads(sys.stdin.read())
    try:
        import pandas as pd
        from taxcalc import Calculator, Policy, Records, __version__
    except ImportError as exc:
        return answer({"ok": False, "code": "NOT_INSTALLED", "message": str(exc)})
    year, record = request["year"], request["record"]
    if not Policy.JSON_START_YEAR <= year <= Policy.LAST_KNOWN_YEAR:
        return answer({"ok": False, "code": "YEAR", "message": f"its law runs {Policy.JSON_START_YEAR}–{Policy.LAST_KNOWN_YEAR}",
                       "last_known_year": Policy.LAST_KNOWN_YEAR})
    try:
        records = Records(data=pd.DataFrame([record]), start_year=year, gfactors=None, weights=None, exact_calculations=True)
        calc = Calculator(policy=Policy(), records=records, verbose=False)
        calc.calc_all()
        index = record["MARS"] - 1

        def law(name):
            value = calc.policy_param(name)
            return float(value[index]) if getattr(value, "ndim", 0) else float(value)
        return answer({"ok": True, "version": __version__, "last_known_year": Policy.LAST_KNOWN_YEAR,
                       "values": {name: float(calc.array(name)[0]) for name in OUTPUTS}, "policy": {name: law(name) for name in POLICY}})
    except Exception as exc:  # Its own failure, reported to the caller rather than a traceback it can't read.
        return answer({"ok": False, "code": "FAILED", "message": f"{type(exc).__name__}: {exc}"[:300]})


if __name__ == "__main__":
    sys.exit(main())
