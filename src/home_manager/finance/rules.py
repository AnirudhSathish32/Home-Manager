"""The rule sets figures rest on (docs/ui.md "Redesign: calculation observability", "Rules").

Each constant set a calculation uses (tax brackets come from confirmed tax tables, each with its own quoted sources) is
listed here with a version, the tax year it's for (None: not tied to one year), the source it was taken from, the day it
was checked against that source (None: no check is recorded), and when a CPA reviewed it (None: not reviewed, shown as a
plain fact, not a warning). values_sha256 is the digest of the values as written: changing a value without a new
version fails tests/test_provenance.py, so a figure's rule card never names a version whose values changed under it.

sync() writes the current versions into rule_sources, keeping older versions there for figures worked out before.
"""

import hashlib
import json


def _supplemental():
    from .paycheck import SUPPLEMENTAL_HIGH_OVER, SUPPLEMENTAL_HIGH_RATE_BP, SUPPLEMENTAL_RATE_BP
    return {"rate_bp": SUPPLEMENTAL_RATE_BP, "high_rate_bp": SUPPLEMENTAL_HIGH_RATE_BP, "high_over_minor": SUPPLEMENTAL_HIGH_OVER}


def _meals():
    from .tax_lines import SHARE_BP
    return {"/".join(key): share for key, share in SHARE_BP.items()}


def _rmd():
    from .retirement import UNIFORM_LIFETIME
    return {"divisors": {str(age): str(period) for age, period in UNIFORM_LIFETIME.items()},
            "start_ages": {"born 1950 or earlier": 72, "born 1951 to 1959": 73, "born 1960 or later": 75}}


def _hsa():
    from .tax_year import HSA_CATCH_UP, HSA_LIMITS
    return {"limits_minor": {str(year): list(limits) for year, limits in HSA_LIMITS.items()}, "catch_up_minor": HSA_CATCH_UP}


def _mortgage():
    from .engines.taxcalc import MORTGAGE_LIMIT
    return {"acquisition_debt_minor": MORTGAGE_LIMIT}


def _aotc():
    from .engines.taxcalc import AOTC_FULL, AOTC_QUARTER
    return {"full_minor": AOTC_FULL, "quarter_minor": AOTC_QUARTER}


def _safe_harbor():
    from .safe_harbor import HIGH_AGI, LAST_YEAR_BP, LAST_YEAR_HIGH_BP, NO_PENALTY_BELOW, THIS_YEAR_BP
    return {"this_year_bp": THIS_YEAR_BP, "last_year_bp": LAST_YEAR_BP, "last_year_high_bp": LAST_YEAR_HIGH_BP, "high_agi_minor": HIGH_AGI,
            "no_penalty_below_minor": NO_PENALTY_BELOW}


def _additional_medicare():
    from .paystub import ADDITIONAL_MEDICARE_WITHHOLDING
    return {"withholding_threshold_minor": ADDITIONAL_MEDICARE_WITHHOLDING}


def _tax_table_lookup():
    from ..household.tax_tables import TAX_TABLE_VERSION
    return {"procedure": TAX_TABLE_VERSION}


RULES = {
    "tax_table_lookup": {"version": "tax-table-lookup-v1", "name": "Tax table lookup", "tax_year": None,
                         "source": "Each confirmed table quotes the official pages it was read from", "checked_on": None,
                         "values": _tax_table_lookup, "values_sha256": "ea61eb0586358f12079f2a49872057978f1935faf09005f685f7dfe9c6a22858"},
    "supplemental_withholding": {"version": "1", "name": "Federal withholding on bonuses", "tax_year": None,
                                 "source": "IRS Publication 15 (Circular E), supplemental wages: 22%, and 37% above $1 million",
                                 "checked_on": None, "values": _supplemental,
                                 "values_sha256": "ab4bc0eecdf23913a530e3c79174b16c685b1e2832829455655d280286cf5d06"},
    "meals_share": {"version": "1", "name": "Business meals share", "tax_year": None, "source": "IRC §274(n): 50% of business meals",
                    "checked_on": None, "values": _meals, "values_sha256": "3ef5bee064fbdc02d53b411e0b5b515a02dc61fbbe716069291ddd791e856cfc"},
    "rmd_uniform_lifetime": {"version": "1", "name": "Required minimum distributions", "tax_year": None,
                             "source": "26 CFR 1.401(a)(9)-9(c), Table 2 (Uniform Lifetime Table); start ages under SECURE 2.0",
                             "checked_on": "2026-09-28", "values": _rmd,
                             "values_sha256": "a34b035956a250d919aecc3f7a1ccd9accba43fd9e34ecf91978d44af8de4576"},
    "hsa_limits": {"version": "1", "name": "HSA contribution limits", "tax_year": None,
                   "source": "IRC §223(b) limits as indexed for each year; §223(b)(3) catch-up from age 55",
                   "checked_on": None, "values": _hsa, "values_sha256": "ca2ce10424900ee51a8018ef22e5fdb97a710c42031596e97dee81cc4dcede56"},
    "mortgage_interest_limit": {"version": "1", "name": "Mortgage interest debt limit", "tax_year": None,
                                "source": "IRC §163(h)(3)(F): $750,000 of acquisition debt; IRS Publication 936",
                                "checked_on": None, "values": _mortgage,
                                "values_sha256": "8784569a4015f75cfe3dbe405b7a4609397c8b373a34a6ea89286f99992fc004"},
    "aotc": {"version": "1", "name": "American opportunity credit", "tax_year": None,
             "source": "IRC §25A(b)(1): 100% of the first $2,000 and 25% of the next $2,000", "checked_on": None,
             "values": _aotc, "values_sha256": "8886b3e7fb0b4f870b35e86a031ad265a9adb469b7fdee494ff1032a89b602b9"},
    "additional_medicare_withholding": {"version": "1", "name": "Additional Medicare withholding", "tax_year": None,
                                        "source": "IRC §3102(f)(1): withheld on wages above $200,000, whatever the filing status",
                                        "checked_on": None, "values": _additional_medicare,
                                        "values_sha256": "5b8713032e4d106816e65867c7456e1c083f0d24555c0c4ae3fff24aa7504f60"},
    "safe_harbor": {"version": "2026-1", "name": "Estimated tax safe harbor", "tax_year": None,
                    "source": "IRC §6654(d)(1)(B), (C) and (e)(1)", "checked_on": None, "values": _safe_harbor,
                    "values_sha256": "b4e7e90d925c52d790874b8d0c035aba02bef268c202ccd0ea56abddffe9b8bc"},
}


def digest(values):
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def rule(key):
    """A rule set's card: name, version, tax year, source, checked on, CPA review (None), and its current values."""
    entry = RULES[key]
    return {"key": key, "name": entry["name"], "version": entry["version"], "tax_year": entry["tax_year"], "source": entry["source"],
            "checked_on": entry["checked_on"], "cpa_reviewed_on": None, "values": entry["values"]()}


def sync(store):
    """Write each current version into rule_sources (older versions stay). A CPA review date set there is kept."""
    with store.connection() as db:
        for key, entry in RULES.items():
            db.execute("INSERT INTO rule_sources(key,version,name,tax_year,source,checked_on,values_sha256) VALUES(?,?,?,?,?,?,?) "
                       "ON CONFLICT(key,version) DO UPDATE SET name=excluded.name,tax_year=excluded.tax_year,source=excluded.source,"
                       "checked_on=excluded.checked_on,values_sha256=excluded.values_sha256",
                       (key, entry["version"], entry["name"], entry["tax_year"], entry["source"], entry["checked_on"], digest(entry["values"]())))


def sources(store):
    """Every rule set version the library knows, newest first within each set."""
    sync(store)
    with store.connection() as db:
        return [dict(row) for row in db.execute("SELECT * FROM rule_sources ORDER BY key, rowid DESC")]
