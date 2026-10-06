"""Synthetic 2026 returns every tax engine is checked on: the hand-worked figures in tests/test_tax_engines.py and the
worksheet conformance test (tests/test_engine_worksheets.py). Nothing here comes from anyone's real records."""

from home_manager.finance.tax_return import Business, Job, Person, ReturnInput, Student


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
# Credits partly phased out: a one-household run of Engine 2 once dropped these (its population claim probabilities).
EITC_PHASEOUT = profile(people=[Person(birth_year=1990)], jobs=[Job(name="E", wages=3500000, medicare_wages=3500000, ss_wages=3500000, federal_withheld=100000)],
                        qualifying_children=1)
ACTC_LOW = profile(filing_status="head_of_household", people=[Person(birth_year=1992)],
                   jobs=[Job(name="F", wages=1800000, medicare_wages=1800000, ss_wages=1800000)], qualifying_children=3)

# Deductions worked through their limits: the senior deduction partly phased out (one person, then both spouses), the QBI
# deduction below and inside its phase-in, and itemizing where the SALT cap falls and the 2/37 reduction applies.
SENIOR_PHASEOUT = profile(people=[Person(birth_year=1958)], jobs=[Job(name="G", wages=9000000, medicare_wages=9000000, ss_wages=9000000, federal_withheld=1000000)])
SENIOR_COUPLE = profile(filing_status="married_joint", people=[Person(birth_year=1959), Person(birth_year=1960)],
                        jobs=[Job(name="H", wages=17000000, medicare_wages=17000000, ss_wages=17000000, federal_withheld=2200000)])
QBI_SOLE = profile(people=[Person(birth_year=1980)], businesses=[Business(name="Design", income=9000000, expenses=1000000)], federal_estimated_paid=1200000)
QBI_PHASE_IN = profile(people=[Person(birth_year=1975)], businesses=[Business(name="Consulting", income=26000000, expenses=3000000)],
                       federal_estimated_paid=5000000)
ITEMIZING_HIGH = profile(filing_status="married_joint", people=[Person(birth_year=1970), Person(birth_year=1972)],
                         jobs=[Job(name="I", wages=90000000, medicare_wages=90000000, ss_wages=18450000, federal_withheld=25000000)],
                         mortgage_interest=3000000, mortgage_average_balance=70000000, state_local_tax=5000000, property_tax=1000000, charity=2000000)

# Credits in their phase-downs: the care credit's rate at a joint $160,000, and both education credits near the top of theirs.
CDCC_PHASED = profile(filing_status="married_joint", people=[Person(birth_year=1986), Person(birth_year=1988)],
                      jobs=[Job(name="J", wages=10000000, medicare_wages=10000000, ss_wages=10000000, federal_withheld=900000),
                            Job(name="K", owner="spouse", wages=6000000, medicare_wages=6000000, ss_wages=6000000, federal_withheld=500000)],
                      qualifying_children=2, dependent_care_expenses=800000, dependent_care_people=2)
STUDENTS = profile(filing_status="married_joint", people=[Person(birth_year=1970), Person(birth_year=1972)],
                   jobs=[Job(name="L", wages=17000000, medicare_wages=17000000, ss_wages=17000000, federal_withheld=2000000)],
                   students=[Student(expenses=400000), Student(expenses=600000, aotc=False)])

RETURNS = {"w2": W2, "joint_contract": JOINT_CONTRACT, "high_wages": HIGH_WAGES, "charity": CHARITY, "tipped": TIPPED, "hsa_family": HSA_FAMILY,
           "itemizing_retiree": ITEMIZING_RETIREE, "head_of_household": HEAD_OF_HOUSEHOLD, "eitc_phaseout": EITC_PHASEOUT, "actc_low": ACTC_LOW,
           "senior_phaseout": SENIOR_PHASEOUT, "senior_couple": SENIOR_COUPLE, "qbi_sole": QBI_SOLE, "qbi_phase_in": QBI_PHASE_IN,
           "itemizing_high": ITEMIZING_HIGH, "cdcc_phased": CDCC_PHASED, "students": STUDENTS}
