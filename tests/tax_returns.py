"""Synthetic 2026 returns every tax engine is checked on: the hand-worked figures in tests/test_tax_engines.py and the
worksheet conformance test (tests/test_engine_worksheets.py). Nothing here comes from anyone's real records."""

from home_manager.finance.tax_return import Business, Job, Person, ReturnInput


def profile(**changes):
    return ReturnInput.model_validate({"year": 2026, "filing_status": "single", **changes})


W2 = profile(people=[Person(birth_year=1990)], jobs=[Job(wages=8500000, federal_withheld=900000)], interest=30000)
JOINT_CONTRACT = profile(filing_status="married_joint", people=[Person(birth_year=1985), Person(birth_year=1987)],
                         jobs=[Job(name="A", wages=15000000, ss_wages=15000000, medicare_wages=15000000, federal_withheld=1400000, medicare_withheld=217500)],
                         interest=120000, ordinary_dividends=200000, qualified_dividends=160000, long_term_gain=500000,
                         businesses=[Business(name="Contract", owner="spouse", income=2500000, expenses=500000)], qualifying_children=2,
                         federal_estimated_paid=300000)
HIGH_WAGES = profile(people=[Person(birth_year=1975)], jobs=[Job(wages=26000000, ss_wages=18450000, medicare_wages=26000000, federal_withheld=6000000,
                                                                 medicare_withheld=431000)], interest=1000000, long_term_gain=2000000)
CHARITY = profile(filing_status="married_joint", people=[Person(birth_year=1985), Person(birth_year=1985)], jobs=[Job(wages=10000000)], charity=250000)
TIPPED = profile(people=[Person(birth_year=1990)], jobs=[Job(wages=6000000)], qualified_tips=500000, tipped_occupation="bartenders",
                 qualified_overtime=200000)
HSA_FAMILY = profile(filing_status="married_joint", jobs=[Job(name="A", wages=9000000, medicare_wages=9500000, ss_wages=9500000, federal_withheld=800000,
                                                              medicare_withheld=160000)],
                     interest=120000, qualified_dividends=50000, ordinary_dividends=80000, long_term_gain=300000, qualifying_children=2,
                     hsa_contributions=200000, hsa_coverage="family", charity=50000)
ITEMIZING_RETIREE = profile(people=[Person(birth_year=1958)], jobs=[Job(name="B", wages=30000000, medicare_wages=30000000, ss_wages=18450000,
                                                                       federal_withheld=6000000)],
                            short_term_gain=-500000, long_term_gain=100000, mortgage_interest=1500000, mortgage_average_balance=40000000,
                            state_local_tax=2500000, property_tax=900000, charity=400000, retirement_distributions=2000000, social_security_benefits=2400000)
HEAD_OF_HOUSEHOLD = profile(filing_status="head_of_household", people=[Person(birth_year=1995)],
                            jobs=[Job(name="D", wages=2200000, medicare_wages=2200000, ss_wages=2200000, federal_withheld=50000)],
                            qualifying_children=1, dependent_care_expenses=300000, dependent_care_people=1, student_loan_interest=150000)

RETURNS = {"w2": W2, "joint_contract": JOINT_CONTRACT, "high_wages": HIGH_WAGES, "charity": CHARITY, "tipped": TIPPED, "hsa_family": HSA_FAMILY,
           "itemizing_retiree": ITEMIZING_RETIREE, "head_of_household": HEAD_OF_HOUSEHOLD}
