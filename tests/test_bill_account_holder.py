"""The account holder as the lines' person (specs/bill-total-and-account-holder, part A: FR-136 - FR-140 and the parts of FR-147 - FR-149 that concern it).

There is no test contract (the user delegated the process); each test names the requirement or scenario it covers. Expected values are written out by
hand below. Fixtures are synthetic (tests/bill_engine_fixtures.py: BL-TOTAL with the synthetic provider `LAKESIDE GAS & ELECTRIC` and the synthetic name
`Jordan A. Rivera`, BL-PHONE-AH, BL-UTIL-AH); the files go through the real services as tests/test_bill_engine_record.py does.
"""

from types import SimpleNamespace

import pytest

import bill_engine_fixtures as bf
from home_manager.app.manager import Manager
from home_manager.core.jobs import Work
from home_manager.documents import extraction
from home_manager.documents.charge_tables import ACCOUNT_HOLDER_LABELS, ANCHOR_WORDS, KEY_LABELS, account_holder_of
from home_manager.documents.reasoning import ReasoningConfig
from home_manager.finance import account_holder
from home_manager.finance.account_holder import annotate, names_match, person_of
from home_manager.finance.family_routing import FamilyRouting, suggest
from home_manager.finance.ledger import Ledger
from test_bill_engine_record import UTIL_FIELDS, UTIL_WRONG_AMOUNTS, BillRun, bill_run, phone, snapshot
from test_bills_ledger import WHO
from test_paystub_engine_record import started  # noqa: F401
from test_pdf import pdf_store  # noqa: F401

TOTAL_FIELDS = {"provider": ("LAKESIDE GAS & ELECTRIC", "LAKESIDE GAS & ELECTRIC", "LAKESIDE GAS & ELECTRIC"),
                "issue_date": ("2026-10-10", "Statement Date", "10/10/2026"), "currency": UTIL_FIELDS["currency"],
                "new_charges": ("1,667.91", "Total Current Charges", "$1,667.91"), "amount_due": ("62.91", "Current Charges due", "$62.91")}
V50 = "typed-extraction-v50-bill-account-cells"
YOU = [{"name": "Jordan Rivera", "you": True}]
FAMILY = [{"name": "Alex Sample", "member_id": "alex"}, {"name": "Blair Sample", "member_id": "blair"}]
ACCOUNT = "Account name on the bill"


def total(pdf_store, local_model, **pages):
    """BL-TOTAL (or a variant) extracted, the model right about the charge rows."""
    return bill_run(pdf_store, local_model, bf.total_pages(**pages), bf.STUB_TOTAL, TOTAL_FIELDS, classify="LAKESIDE GAS & ELECTRIC")


def persons(record, people):
    return [(item["person"]["text"], item["person"]["source"]) for item in annotate(record, people)["items"]]


def everyone(record, people):
    """The one (text, source) every line shows, else the set of them."""
    return set(persons(record, people))


# === FR-136: reading the account holder ===================================================================================================

@pytest.mark.parametrize("line, expected", [
    ("Account Name: Jordan A. Rivera", "Jordan A. Rivera"),
    ("ACCOUNT NAME JORDAN RIVERA", "JORDAN RIVERA"),
    ("Account Holder: Sam Lee", "Sam Lee"),
    ("Account Holder Name - Sam Lee", "Sam Lee"),  # The longer label wins over `account holder`.
    ("Customer Name ........ JORDAN RIVERA", "JORDAN RIVERA"),
    ("Name on account: Rivera, Jordan", "Rivera, Jordan"),
    ("account name:   Jordan   A   Rivera", "Jordan A Rivera"),  # Whitespace collapsed, case of the label ignored.
    ("Account Name: JORDAN A RIVERA  Account Number 4455-6677-8899", "JORDAN A RIVERA"),  # Cut before the next label of the line (FR-103/FR-128/this list).
    ("Account Name: Jordan Rivera Due Date 11/15/2026", "Jordan Rivera"),
    ("Customer Name: Jordan Rivera Account Name: Casey", "Jordan Rivera"),
    ("Account Name: " + "Longname " * 20, ("Longname " * 20)[:80].rstrip()),  # At most 80 characters.
    ("Your account name is Jordan Rivera", None),  # A label inside a sentence is no account-name line.
    ("Service Account Name: Jordan Rivera", None),  # Nor after other words.
    ("Account Names: Jordan Rivera", None),
    ("Account Name: 4455-6677", None),  # The value must hold a letter.
    ("Account Name:", None),
    ("Account Number 4455-6677-8899", None),
    ("Name: Jordan Rivera", None),  # A bare `Name:` is left out (OD-5).
])
def test_fr136_an_account_name_line_gives_its_value_as_printed(line, expected):
    assert account_holder_of(line) == expected


def test_fr136_the_labels_are_a_fixed_list_kept_with_the_anchor_phrases():
    assert set(ACCOUNT_HOLDER_LABELS) == {"account name", "account holder", "account holder name", "customer name", "name on account"}
    assert ANCHOR_WORDS["amount_due"] and KEY_LABELS["account"]  # The same module holds FR-103's and FR-128's lists.


def test_fr136_the_first_account_name_line_is_used_and_a_different_later_one_adds_a_note():
    lines = [SimpleNamespace(id="line-1", text="LAKESIDE"), SimpleNamespace(id="line-2", text="Account Name: Jordan A. Rivera"),
             SimpleNamespace(id="line-3", text="Account Name: JORDAN A. RIVERA"), SimpleNamespace(id="line-4", text="Customer Name: Casey Lee")]
    found, note = extraction.account_holder(lines)
    assert found == {"text": "Jordan A. Rivera", "locator": {"line_ids": ["line-2"], "quotes": ["Account Name: Jordan A. Rivera"]}}
    assert note == "The account name is printed as Jordan A. Rivera and Casey Lee; Jordan A. Rivera, the first, was used."
    assert extraction.account_holder(lines[:3])[1] is None  # The same name in another case is no different value.
    assert extraction.account_holder(lines[:1]) == (None, None)


def test_sc132_a_the_user_s_bill_keeps_the_account_holder_citing_its_line_and_never_in_a_lines_holder(pdf_store, local_model):
    run = total(pdf_store, local_model)
    record = run.record
    assert record["details"]["account_holder"]["text"] == "Jordan A. Rivera"
    assert record["details"]["account_holder"]["locator"]["line_ids"] == [run.line("Account Name").id]
    assert all(item["line_holder"] is None for item in record["items"])
    assert [item["description"] for item in record["items"]][:3] == ["Delivery Charges", "Supply Charges", "Taxes and Fees"]
    assert not [note for note in run.notes if "account name is printed" in note]


def test_sc134_a_bill_printing_no_account_name_or_only_a_sentence_has_no_account_holder_and_says_shared(pdf_store, local_model):
    header = tuple(text for text in bf.TOTAL_HEADER if not text.startswith("Account Name"))
    run = total(pdf_store, local_model, header=header)
    assert "account_holder" not in run.record["details"]
    assert everyone(run.record, YOU) == {("Shared", "shared")}
    assert annotate(run.record, YOU)["account_holder_view"] is None
    sentence = (*header[:1], "Your account name is Jordan Rivera", *header[1:])
    other = total_named(pdf_store, local_model, sentence, "sentence.pdf")
    assert "account_holder" not in other.record["details"] and not [note for note in other.notes if "account name" in note.lower()]
    assert everyone(other.record, YOU) == {("Shared", "shared")}


def total_named(pdf_store, local_model, header, name):
    return bill_run(pdf_store, local_model, bf.total_pages(header=header), bf.STUB_TOTAL, TOTAL_FIELDS, classify="LAKESIDE GAS & ELECTRIC", name=name)


def test_fr136_a_photographed_bill_reads_the_account_holder_from_its_transcribed_lines(pdf_store, local_model):
    from test_bill_engine_record import scanned_stub, started_scanned
    transcription = bf.mini_transcription(1)
    transcription.insert(1, "Customer Name ..... JORDAN RIVERA")
    run = started_scanned(pdf_store, local_model, transcription)
    scanned_stub(run)
    run.extract()
    assert run.record["details"]["account_holder"]["text"] == "JORDAN RIVERA"
    assert run.record["details"]["account_holder"]["locator"]["line_ids"] == [run.line("Customer Name").id]
    assert all(item["line_holder"] is None for item in run.record["items"])


def test_fr136_an_invoice_keeps_todays_path_and_has_no_account_holder(pdf_store, local_model, monkeypatch):
    import test_bill_engine_record as record_tests
    items = record_tests.invoice_items()
    monkeypatch.setattr(record_tests, "invoice_items", lambda **options: [*items, *bf.left(600, "Account Name: Jordan Rivera")])
    run = record_tests.invoice_run(pdf_store, local_model)
    run.extract()
    assert run.record["invoice"] is not None and "account_holder" not in (run.record["details"] or {})
    assert all(item["person"]["source"] == "shared" for item in annotate(run.record, YOU)["items"])


def test_fr136_each_part_of_a_file_of_several_bills_reads_only_its_own_lines(pdf_store, local_model):
    """FR-146's account-holder half: `publish` is given a part's own lines, so a name printed on one part's page is never carried to another part."""
    pages = [bf.page_of([*bf.mini_items(1), (40, 790, "Account Name: Part One Holder")]), bf.page_of(bf.mini_items(2))]
    run = started(pdf_store, local_model, pages, name="two.pdf")
    first = [line for line in run.lines if line.id.startswith("page-1")]
    second = [line for line in run.lines if line.id.startswith("page-2")]
    assert extraction.account_holder(first)[0]["text"] == "Part One Holder"
    assert extraction.account_holder(second) == (None, None)


# === FR-137, FR-138: matching and what the Person cell shows ============================================================================

@pytest.mark.parametrize("printed, candidate, matches", [  # SC-133, each row exact.
    ("JORDAN RIVERA", "Jordan Rivera", True), ("Rivera, Jordan", "Jordan Rivera", True), ("Jordan A. Rivera", "Jordan Rivera", True),
    ("Jordan Alex Rivera", "Jordan Rivera", True), ("Mr. Jordan Rivera Jr.", "Jordan Rivera", True), ("Jordan", "Jordan Rivera", True),
    ("Jordan A Rivera", "Jordan Alex Rivera", True), ("Jordán Rivera", "Jordan Rivera", True), ("Jordan Rivera", "Jordan Rivera III", True),
    ("J. Rivera", "Jordan Rivera", False), ("Jordan Riviera", "Jordan Rivera", False), ("Jordan & Casey Rivera", "Jordan Rivera", False),
    ("Jordan and Casey Rivera", "Jordan Rivera", False), ("Jordan / Casey Rivera", "Jordan Rivera", False),
    ("Jordan A Rivera", "Jordan B Rivera", False), ("Jordan Rivera", "My profile", False), ("My profile", "My profile", False),
    ("4455-6677", "Jordan Rivera", False), ("J", "J", False),
    ("Anne-Marie Smith", "Anne Smith", False), ("Anne Smith", "Anne-Marie Smith", False),  # Review round 1, finding 8: a hyphen is punctuation, removed.
    ("Anne-Marie Smith", "AnneMarie Smith", True), ("Anne-Marie Smith", "Anne-Marie Smith", True)])
def test_sc133_matching_table(printed, candidate, matches):
    assert names_match(printed, candidate) is matches


def test_sc133_two_candidates_matching_one_name_match_nobody_and_the_candidate_is_the_only_one_shown():
    both = [{"name": "Jordan Rivera", "you": True}, {"name": "Jordan Lee", "you": False}]
    assert person_of("Jordan", both) is None  # Two match.
    assert person_of("Jordan Lee", both) == both[1] and person_of("JORDAN RIVERA", both) == both[0]
    assert person_of("Jordan", [{"name": "My profile", "you": True}]) is None


def test_sc132_fr138_every_line_shows_the_profile_name_from_the_account_name_and_says_where_it_came_from(pdf_store, local_model):
    run = total(pdf_store, local_model)
    record = annotate(run.record, YOU)
    assert everyone(record, YOU) == {("Jordan Rivera", "account")}
    assert {item["person"]["title"] for item in record["items"]} == {ACCOUNT}
    view = record["account_holder_view"]
    assert (view["text"], view["display"], view["you"], view["name"]) == ("Jordan A. Rivera", "Jordan A. Rivera (you)", True, "Jordan Rivera")
    assert view["locator"]["line_ids"] == [run.line("Account Name").id]


def test_sc133_renaming_the_profile_changes_what_is_shown_with_no_re_read(pdf_store, local_model):
    run = total(pdf_store, local_model)
    stored = run.bill_row()["details_json"]
    assert everyone(run.record, [{"name": "Jordan Alex Rivera", "you": True}]) == {("Jordan Alex Rivera", "account")}
    assert everyone(run.record, [{"name": "Sam Lee", "you": True}]) == {("Jordan A. Rivera", "account")}  # Unmatched: the printed name.
    shown = annotate(run.record, [{"name": "Sam Lee", "you": True}])["account_holder_view"]
    assert (shown["display"], shown["you"]) == ("Jordan A. Rivera", False)
    assert run.bill_row()["details_json"] == stored and "Rivera" not in stored.replace("Jordan A. Rivera", "")  # The library never holds the profile's name.


def test_fr138_a_section_title_holder_wins_and_the_credit_line_takes_the_account_holder(pdf_store, local_model):  # SC-135
    run = phone(pdf_store, local_model, pages=bf.phone_pages(account="Account Name: Alex Sample"))
    people = [{"name": "Alex Sample", "you": True}]
    assert run.record["details"]["account_holder"]["text"] == "Alex Sample"
    assert persons(run.record, people) == [("Alex Sample", "line"), ("Alex Sample", "line"), ("Blair", "line"), ("Blair", "line"), ("Alex Sample", "account")]
    titles = {item["description"]: item["person"]["title"] for item in annotate(run.record, people)["items"]}
    assert titles["Basic Plan"] == "Printed for this line" and titles["Autopay Discount"] == ACCOUNT


def test_fr138_a_member_set_on_the_line_wins_and_a_bill_shared_by_line_leaves_unheld_lines_shared(pdf_store, local_model):
    run = phone(pdf_store, local_model, pages=bf.phone_pages(account="Account Name: Alex Sample"))
    record = run.record
    record["items"][0]["member_id"] = "blair"
    assert persons(record, FAMILY)[0] == ("Blair Sample", "member")
    assert persons(record, YOU)[0] == ("Someone in the family", "member")
    delivered = {**run.record, "share": {"member_id": "alex", "share_minor": 1000, "total_minor": 2000, "people": []}}  # Alex's copy, shared by line.
    assert persons(delivered, [{"name": "Alex Sample", "you": True}])[-1] == ("Shared", "shared")
    assert persons(delivered, [{"name": "Alex Sample", "you": True}])[0] == ("Alex Sample", "line")  # A line with a holder keeps it.


def test_fr138_the_manager_decides_the_people_and_sends_the_text_with_the_record(pdf_store, local_model):
    run = total(pdf_store, local_model)
    store = run.store
    me = SimpleNamespace(family=None, profile={"name": "Jordan Rivera"}, store=store, ledger=Ledger(store), family_people=lambda: FAMILY)
    me.account_people = lambda: Manager.account_people(me)
    assert me.account_people() == [{"name": "Jordan Rivera", "you": True}]
    view = Manager.record_view(me, "receipt", run.run["publication"]["id"])
    assert {item["person"]["text"] for item in view["items"]} == {"Jordan Rivera"} and view["account_holder_view"]["display"].endswith("(you)")
    default = SimpleNamespace(family=None, profile={"name": "My profile"}, store=store, ledger=Ledger(store))
    view = Manager.record_view(SimpleNamespace(**vars(default), account_people=lambda: Manager.account_people(default)), "receipt", run.run["publication"]["id"])
    assert {item["person"]["text"] for item in view["items"]} == {"Jordan A. Rivera"}  # "My profile" never matches: the printed name.
    household = SimpleNamespace(family=object(), profile={"name": "The Samples"}, store=store, family_people=lambda: FAMILY)
    assert Manager.account_people(household) == FAMILY


def test_fr137_two_family_members_with_the_same_name_stay_two_people_so_the_printed_name_matches_nobody_and_a_line_keeps_its_member(pdf_store, local_model):
    run = total(pdf_store, local_model)
    twins = [{"name": "Jordan Rivera", "member_id": "first"}, {"name": "Jordan Rivera", "member_id": "second"}]  # Family membership doesn't enforce unique names.
    household = SimpleNamespace(family=object(), profile={"name": "The Rivera family"}, store=run.store, ledger=Ledger(run.store), family_people=lambda: twins)
    household.account_people = lambda: Manager.account_people(household)
    assert household.account_people() == twins
    record = run.record
    record["items"][0]["member_id"] = "second"
    view = Manager.record_view(household, "receipt", run.run["publication"]["id"])
    assert view["account_holder_view"]["name"] is None and view["account_holder_view"]["display"] == "Jordan A. Rivera"  # Two match: no match.
    assert {item["person"]["source"] for item in view["items"]} == {"account"}
    assert annotate(record, twins)["items"][0]["person"] == {"text": "Jordan Rivera", "source": "member", "title": "Set for this line"}  # Not "Someone in the family".
    assert annotate(run.record, [twins[1]])["account_holder_view"]["name"] == "Jordan Rivera"


# === FR-139: the account holder on the page, correctable ==================================================================================

def test_sc139_correct_sets_the_account_holder_extract_again_keeps_it_and_undo_restores_the_printed_one(pdf_store, local_model):
    run = total(pdf_store, local_model)
    receipt_id = run.run["publication"]["id"]
    ledger = Ledger(run.store)
    field = next(item for item in run.record["correctable"] if item["field"] == "detail:account_holder")
    assert (field["label"], field["value"]) == ("Account holder", "Jordan A. Rivera")
    done = ledger.correct("receipt", receipt_id, {"detail:account_holder": "Morgan Lee"})
    assert done["details"]["account_holder"]["text"] == "Morgan Lee"
    assert everyone(ledger.record("receipt", receipt_id), YOU) == {("Morgan Lee", "account")}
    run.stub_bill(bf.STUB_TOTAL, TOTAL_FIELDS, classify="LAKESIDE GAS & ELECTRIC")
    run.extract(force=True)
    again = ledger.record("receipt", receipt_id)
    assert again["details"]["account_holder"]["text"] == "Morgan Lee"  # The correction wins over the new reading.
    assert everyone(again, YOU) == {("Morgan Lee", "account")}
    ledger.undo_corrections("receipt", receipt_id, done["correction_ids"])
    assert ledger.record("receipt", receipt_id)["details"]["account_holder"]["text"] == "Jordan A. Rivera"
    assert everyone(ledger.record("receipt", receipt_id), YOU) == {("Jordan Rivera", "account")}


def test_fr139_cleared_means_no_account_holder_and_a_bad_value_is_refused(pdf_store, local_model):
    run = total(pdf_store, local_model)
    receipt_id, ledger = run.run["publication"]["id"], Ledger(run.store)
    cleared = ledger.correct("receipt", receipt_id, {"detail:account_holder": None})
    assert everyone(cleared, YOU) == {("Shared", "shared")} and annotate(cleared, YOU)["account_holder_view"] is None
    for bad in ("4455-6677", "x" * 81):
        with pytest.raises(ValueError, match="account holder"):
            ledger.correct("receipt", receipt_id, {"detail:account_holder": bad})
    with run.store.connection() as db:
        assert [row["value"] for row in db.execute("SELECT value FROM record_corrections WHERE field='detail:account_holder'")] == [None]
    history = [entry for entry in ledger.history("receipt", receipt_id) if entry.get("field") == "detail:account_holder"]
    assert history and history[0]["label"] == "Account holder"


def test_fr139_the_page_offers_account_holder_only_on_a_kinded_bill_that_is_not_an_invoice(pdf_store, local_model):
    run = total(pdf_store, local_model)
    assert "detail:account_holder" in {item["field"] for item in run.record["correctable"]}
    with run.store.connection() as db:
        db.execute("UPDATE receipts SET invoice_json='{}' WHERE id=?", (run.run["publication"]["id"],))
    assert "detail:account_holder" not in {item["field"] for item in Ledger(run.store).record("receipt", run.run["publication"]["id"])["correctable"]}


# === FR-147: stored bills, re-reading, corrections =========================================================================================

def read_as_v50(run, monkeypatch):
    """The reading the previous version left: no account holder, the version patched."""
    run.stub_bill(bf.STUB_TOTAL, TOTAL_FIELDS, classify="LAKESIDE GAS & ELECTRIC")
    with monkeypatch.context() as patch:
        patch.setattr(extraction, "EXTRACTION_VERSION", V50)
        patch.setattr(extraction, "account_holder", lambda lines: (None, None))
        run.extract()
    with run.store.connection() as db:
        assert db.execute("SELECT prompt_version FROM extraction_runs WHERE id=?", (run.run["id"],)).fetchone()[0] == V50
        db.execute("UPDATE receipts SET review_status='needs_review' WHERE id=?", (run.run["publication"]["id"],))
    assert "account_holder" not in run.record["details"]


def read_again(run):
    run.stub_bill(bf.STUB_TOTAL, TOTAL_FIELDS, classify="LAKESIDE GAS & ELECTRIC")
    config = ReasoningConfig(base_url=run.local_model["config"].base_url, model="synthetic-reasoning")
    run_id, reused = run.extraction.enqueue(run.doc["id"], run.parse_id, config)
    assert reused is True
    run.extraction.run(run_id, Work.detached())
    run.run = run.extraction.get(run_id)
    assert run.run["status"] == "succeeded", run.run["error"]


def test_sc143_the_version_moved_an_undecided_bill_gains_its_account_holder_on_extract_again(pdf_store, local_model, monkeypatch):
    assert extraction.EXTRACTION_VERSION == "typed-extraction-v56-money-sign-rule" != V50
    run = started(pdf_store, local_model, bf.total_pages())
    run.__class__ = BillRun
    read_as_v50(run, monkeypatch)
    read_again(run)
    assert run.record["details"]["account_holder"]["text"] == "Jordan A. Rivera"
    assert everyone(run.record, YOU) == {("Jordan Rivera", "account")}


def test_sc143_a_correction_made_before_the_re_read_wins_and_a_confirmed_bill_is_never_rewritten(pdf_store, local_model, monkeypatch):
    run = started(pdf_store, local_model, bf.total_pages())
    run.__class__ = BillRun
    read_as_v50(run, monkeypatch)
    receipt_id, ledger = run.run["publication"]["id"], Ledger(run.store)
    ledger.correct("receipt", receipt_id, {"detail:account_holder": "Morgan Lee"})  # A bill that printed none (to the old reading) takes the entry.
    read_again(run)
    assert run.record["details"]["account_holder"]["text"] == "Morgan Lee"
    # A confirmed bill keeps what it was read as: no account holder, its lines Shared, until Account holder is set by Correct.
    elsewhere = tuple(text.replace("4455-6677-8899", "7788-6677-1122") for text in bf.TOTAL_HEADER)  # Another file, not a copy of the first.
    other = started(pdf_store, local_model, bf.total_pages(header=elsewhere), name="other.pdf")
    other.__class__ = BillRun
    read_as_v50(other, monkeypatch)
    other_id = other.run["publication"]["id"]
    ledger.review("receipt", other_id, "verified")
    before = other.bill_row()
    read_again(other)
    assert other.run["publication"]["id"] == other_id and other.bill_row()["details_json"] == before["details_json"]
    assert everyone(other.record, YOU) == {("Shared", "shared")}
    ledger.correct("receipt", other_id, {"detail:account_holder": "Jordan Rivera"})
    assert everyone(ledger.record("receipt", other_id), YOU) == {("Jordan Rivera", "account")}
    assert annotate(ledger.record("receipt", other_id), YOU)["account_holder_view"]["locator"]["line_ids"] == []  # No source line: you set it.


def test_fr148_a_second_reading_changes_nothing_and_asks_the_model_nothing_more(pdf_store, local_model):
    run = total(pdf_store, local_model)
    first, first_notes, first_questions = snapshot(run), run.notes, run.asked()
    run.stub_bill(bf.STUB_TOTAL, TOTAL_FIELDS, classify="LAKESIDE GAS & ELECTRIC")
    run.extract(force=True)
    assert snapshot(run) == first and run.notes == first_notes and run.asked() == first_questions


# === FR-140: a family's bill ================================================================================================================

def test_sc136_the_account_name_suggests_a_whole_bill_for_one_member_and_never_sets_a_line(pdf_store, local_model):
    utility = bill_run(pdf_store, local_model, bf.util_pages(account="Account Name: Blair Sample"), bf.STUB_UTIL_WRONG, {**UTIL_FIELDS, **UTIL_WRONG_AMOUNTS})
    receipt_id = utility.run["publication"]["id"]
    assert utility.record["details"]["account_holder"]["text"] == "Blair Sample"
    routing = FamilyRouting(utility.store)
    routing.refresh({}, WHO[:2], FAMILY)
    [listed] = routing.list()
    assert listed["id"] == receipt_id
    assert (listed["suggested"]["mode"], listed["suggested"]["members"], listed["suggested"]["reason"]) == ("member", ["blair"], "The account is in Blair Sample's name")
    assert listed["routing"] == "suggested" and not listed["delivered"]
    assert all(item["member_id"] is None for item in Ledger(utility.store).record("receipt", receipt_id)["items"])
    assert everyone(Ledger(utility.store).record("receipt", receipt_id), FAMILY) == {("Blair Sample", "account")}


def test_sc136_a_phone_bill_keeps_its_share_by_line_suggestion_and_its_credit_stays_shared_in_the_inbox(pdf_store, local_model):
    run = phone(pdf_store, local_model, pages=bf.phone_pages(account="Account Name: Alex Sample"))
    routing = FamilyRouting(run.store)
    routing.refresh({}, WHO[:2], FAMILY)
    [listed] = routing.list()
    assert (listed["suggested"]["mode"], set(listed["suggested"]["members"]), listed["suggested"]["ask"]) == ("lines", {"alex", "blair"}, None)
    record = Ledger(run.store).record("receipt", run.run["publication"]["id"])
    assert [item["member_id"] for item in record["items"]] == ["alex", "alex", "blair", "blair", None]  # Who has what only; the name set nothing.
    assert persons(record, FAMILY)[-1] == ("Alex Sample", "account")  # Shown beside the select, which keeps "Shared (taxes, fees)" as its empty choice.


@pytest.mark.parametrize("holder, lines, people, expected", [
    ("Blair Sample", [], FAMILY, ("member", ["blair"], "The account is in Blair Sample's name")),
    ("Blair", [], FAMILY, ("member", ["blair"], "The account is in Blair Sample's name")),
    ("Sample", [], FAMILY, (None, [], "Nothing on it says whose it is")),  # Last name alone matches nobody.
    ("Casey Sample", [], FAMILY, (None, [], "Nothing on it says whose it is")),
    ("Blair Sample", [{"line_holder": "Dana", "member_id": None}], FAMILY, (None, [], "Nothing on it says whose it is")),  # A line holder decides first.
    (None, [], FAMILY, (None, [], "Nothing on it says whose it is")),
    ("Blair Sample", [], [*FAMILY, {"name": "Blair Sample", "member_id": "other"}], (None, [], "Nothing on it says whose it is")),  # Two members match.
])
def test_fr140_suggest_gains_one_rule_after_the_phone_and_card_rules(holder, lines, people, expected):
    row = {"record_type": "receipt", "name": "CITY POWER & WATER", "last_four": None}
    assert suggest(row, {}, WHO[:2], lines, people, holder)[:3] == expected
    card = {**row, "last_four": "1234"}
    assert suggest(card, {}, WHO[:2], lines, people, holder)[0] is None  # An unlisted card still asks first.


def test_fr140_the_suggestion_follows_the_person_you_confirm_nothing_is_sent_by_it(pdf_store, local_model):
    utility = bill_run(pdf_store, local_model, bf.util_pages(account="Account Name: Blair Sample"), bf.STUB_UTIL_WRONG, {**UTIL_FIELDS, **UTIL_WRONG_AMOUNTS})
    routing = FamilyRouting(utility.store)
    routing.refresh({}, WHO[:2], FAMILY)
    assignment = routing.get("receipt", utility.run["publication"]["id"])
    assert assignment["status"] == "suggested" and not assignment["delivered"]
    routing.refresh({}, WHO[:2], [{"name": "Alex Sample", "member_id": "alex"}])  # Blair left the family: nothing suggested, nothing delivered.
    assert routing.get("receipt", utility.run["publication"]["id"])["status"] == "unassigned"


def test_fr138_the_page_shows_the_servers_text_and_its_source():
    """The page (receipt.js, document_v2.js) decides nothing: it shows `person.text` and `person.title`, and Account holder from `account_holder_view`."""
    from pathlib import Path
    static = Path(account_holder.__file__).parents[1] / "app" / "static"
    receipt, document = (static / "receipt.js").read_text(encoding="utf-8"), (static / "document_v2.js").read_text(encoding="utf-8")
    assert "row.person.text" in receipt and "row.person.title" in receipt
    assert "account_holder_view" in document and '"Account holder"' in document and "detail:account_holder" in document


# === FR-149 (the account-holder part): the diagnose probe counts account-name lines and never prints the name ====================================

def test_sc145_diagnose_counts_account_name_lines_per_page_and_prints_no_name(tmp_path):
    from test_bill_engine_generator import probe, written
    named = probe(written(tmp_path, "total.pdf", bf.total_pages()), tmp_path)
    plain = probe(written(tmp_path, "util.pdf", bf.util_pages()), tmp_path)
    assert named.returncode == 0 and plain.returncode == 0, (named.stderr[-300:], plain.stderr[-300:])
    assert "account-name lines: 1" in named.stdout and "account-name lines: 0" in plain.stdout
    for text in ("Jordan", "Rivera", "LAKESIDE", "Account Name"):
        assert text not in named.stdout, text
