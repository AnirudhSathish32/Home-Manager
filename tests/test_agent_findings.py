"""The findings command (scripts/test_instance.py finding; docs/development.md "Agent test instance"), FR-10/14/16.

Every test writes to <root>/bugs.md under a module directory; the real docs/bugs.md is only read, as a byte template.
The command runs in-process through test_instance.main(argv) against an in-process test-mode server, so no_egress,
HM_TEST_FINDING_DATE and the module's test hook apply; test_finding_cli_smoke runs it once as a subprocess.
"""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import subprocess
import threading

import pytest

from home_manager.core import sandbox
from test_agent_guards import no_egress  # noqa: F401  (a fixture)
from test_agent_instance import PYTHON, ROOT, SCRIPT, load_script
from test_taxes_v2_browser import served

TOKEN = "f" * 43
SEED_DATE = "2026-10-17"
B0 = (ROOT / "docs" / "bugs.md").read_bytes()  # CRLF with no final newline, like the developer's file.
FIELDS = {"route": "#/money/transactions", "symptom": "category select does nothing", "kind": "friction", "severity": "medium",
          "steps": "Open Transactions\nPick a category", "expected": "The row's category changes", "actual": "Nothing happens",
          "agent": "agent-1"}
script = load_script()


@pytest.fixture(scope="module")
def test_server(tmp_path_factory):
    """A test-mode app on a free loopback port, with the sandbox over the module directory."""
    folder = tmp_path_factory.mktemp("findings")
    sandbox.activate(folder)
    try:
        with served(folder, TOKEN) as (manager, base):
            manager.configure(str(folder / "library"))
            yield folder, base
    finally:
        sandbox.deactivate()


@pytest.fixture
def finding_root(test_server, request):
    folder, base = test_server
    root = folder / re.sub(r"\W", "_", request.node.name)
    (root / "evidence").mkdir(parents=True)
    (root / ".hm-test-instance").write_text("", encoding="utf-8")
    (root / "session.json").write_text(json.dumps({"base_url": base, "link": f"{base}/#token={TOKEN}", "seed_date": SEED_DATE}), encoding="utf-8")
    (root / "bugs.md").write_bytes(B0)
    return root


@pytest.fixture(autouse=True)
def finding_date(monkeypatch):
    monkeypatch.setenv("HM_TEST_FINDING_DATE", "2026-10-18")


def shot(root, name="x.png"):
    path = root / "evidence" / name
    path.write_bytes(b"\x89PNG synthetic")
    return path


def record(root, screenshot=None, url=None, target=None, **fields):
    session = json.loads((root / "session.json").read_text(encoding="utf-8"))
    values = {**FIELDS, "url": url or session.get("base_url", "http://127.0.0.1:1") + "/#/transactions",
              "screenshot": str(screenshot or shot(root)), **fields}
    argv = ["finding", "--root", str(root), "--target", str(target or root / "bugs.md")]
    for name, value in values.items():
        if value is not None:
            argv += [f"--{name}", value]
    return script.main(argv)


def section(root):
    text = (root / "bugs.md").read_bytes().decode("utf-8")
    return text[text.index("## Agent findings"):]


def entries(root):
    return re.findall(r"^<!-- finding:([0-9a-f]{16}) -->", section(root), re.M)


# SC-09, SC-16 --------------------------------------------------------------------------------------------------------

def test_sc09_recorded_once_and_seen_again(finding_root, monkeypatch):
    first = shot(finding_root, "first.png")
    assert record(finding_root, first) == 0
    data = (finding_root / "bugs.md").read_bytes()
    assert data.startswith(B0) and data[len(B0):].startswith(b"\r\n## Agent findings\r\n")  # D-P6.
    assert b"\n" not in data.replace(b"\r\n", b"")  # The target's own newlines.
    text = section(finding_root)
    for expected in ("### #/money/transactions: category select does nothing", "- Date: 2026-10-18 (seed 2026-10-17)",
                     "- Agent: agent-1", f"- Page: {json.loads((finding_root / 'session.json').read_text())['base_url']}/#/transactions",
                     "- Kind: friction · Severity: medium", "- Steps: Open Transactions\r\n  Pick a category",
                     "- Expected: The row's category changes", "- Actual: Nothing happens", f"- Evidence: {first}"):
        assert expected in text, expected
    # Step 2: the same route and symptom on another date (spacing and case differ).
    monkeypatch.setenv("HM_TEST_FINDING_DATE", "2026-10-19")
    second = shot(finding_root, "second.png")
    assert record(finding_root, second, route=" #/Money/Transactions/ ", symptom="Category  select does NOTHING") == 0
    assert len(entries(finding_root)) == 1
    assert f"- Seen again: 2026-10-19 (seed 2026-10-17) — evidence: {second}" in section(finding_root)
    # Step 3: another symptom.
    assert record(finding_root, shot(finding_root, "third.png"), symptom="totals overlap at 390px") == 0
    assert len(entries(finding_root)) == 2
    data = (finding_root / "bugs.md").read_bytes()
    assert data.startswith(B0) and data.count(b"## Agent findings") == 1
    assert first.exists() and second.exists()


def test_sc09_section_already_there_and_lf(finding_root):
    (finding_root / "bugs.md").write_bytes(b"# Bugs\n\nmine\n\n## Agent findings\n")
    before = (finding_root / "bugs.md").read_bytes()
    assert record(finding_root) == 0
    data = (finding_root / "bugs.md").read_bytes()
    assert data.startswith(before) and data.count(b"## Agent findings") == 1 and b"\r\n" not in data
    assert len(entries(finding_root)) == 1


def test_no_trailing_newline_prefix(finding_root):
    (finding_root / "bugs.md").write_bytes(b"# Bugs\r\n\r\nlast line ")
    assert record(finding_root) == 0
    assert (finding_root / "bugs.md").read_bytes().startswith(b"# Bugs\r\n\r\nlast line \r\n## Agent findings\r\n")


def test_seen_again_cites_screenshot(finding_root, monkeypatch):
    first = shot(finding_root, "a.png")
    record(finding_root, first)
    monkeypatch.setenv("HM_TEST_FINDING_DATE", "2026-10-20")
    second = shot(finding_root, "b.png")
    record(finding_root, second)
    text = section(finding_root)
    assert f"- Evidence: {first}" in text and f"evidence: {second}" in text
    assert first.exists() and second.exists()


def test_seen_again_message(finding_root, monkeypatch, capsys):
    """A repeat says it was seen again and names the existing entry, not the repeat's own spelling."""
    record(finding_root, shot(finding_root, "a.png"))
    assert "Recorded a new entry" in capsys.readouterr().out
    monkeypatch.setenv("HM_TEST_FINDING_DATE", "2026-10-19")
    assert record(finding_root, shot(finding_root, "b.png"), symptom="Category  select does NOTHING") == 0
    out = capsys.readouterr().out
    assert "Seen again (2026-10-19)" in out and "#/money/transactions: category select does nothing; no new entry" in out
    assert "Recorded" not in out and "NOTHING" not in out
    assert len(entries(finding_root)) == 1


def test_same_date_repeat_noop(finding_root, capsys):
    record(finding_root, shot(finding_root, "a.png"))
    before = (finding_root / "bugs.md").read_bytes()
    again = shot(finding_root, "b.png")
    assert record(finding_root, again) == 0
    assert "already recorded today" in capsys.readouterr().out
    assert (finding_root / "bugs.md").read_bytes() == before and again.exists()


def test_text_after_section_kept(finding_root):
    record(finding_root, shot(finding_root, "a.png"))
    notes = b"\r\n\r\n## Notes\r\nthe developer's own section\r\n"
    (finding_root / "bugs.md").write_bytes((finding_root / "bugs.md").read_bytes() + notes)
    assert record(finding_root, shot(finding_root, "b.png"), symptom="another symptom") == 0
    data = (finding_root / "bugs.md").read_bytes()
    assert data.endswith(notes) and data.startswith(B0)
    head = data[:data.index(b"## Notes")]
    assert head.count(b"<!-- finding:") == 2


def test_seen_again_lands_in_its_entry(finding_root, monkeypatch):
    record(finding_root, shot(finding_root, "a.png"))
    record(finding_root, shot(finding_root, "b.png"), symptom="second symptom")
    monkeypatch.setenv("HM_TEST_FINDING_DATE", "2026-10-21")
    record(finding_root, shot(finding_root, "c.png"))
    text = section(finding_root)
    second_marker = text.index(f"<!-- finding:{entries(finding_root)[1]} -->")
    assert text.index("- Seen again: 2026-10-21") < second_marker


def test_heading_in_field_escaped(finding_root):
    record(finding_root, shot(finding_root, "a.png"), actual="It broke\n## Not a section\n# nor this")
    assert record(finding_root, shot(finding_root, "b.png"), symptom="later") == 0
    text = section(finding_root)
    assert not re.search(r"^## (?!Agent findings)", text, re.M)
    assert "\\## Not a section" in text and len(entries(finding_root)) == 2


def test_comment_in_field_escaped(finding_root):
    record(finding_root, shot(finding_root, "a.png"), steps="see <!-- finding:abcdefabcdefabcd --> here")
    assert "&lt;!-- finding:abcdefabcdefabcd" in section(finding_root)
    assert len(entries(finding_root)) == 1


def test_marker_outside_section_ignored(finding_root):
    key = script.finding_key(FIELDS["route"], FIELDS["symptom"])
    prefix = B0 + f"\r\ncopied: \r\n<!-- finding:{key} -->\r\n".encode()
    (finding_root / "bugs.md").write_bytes(prefix)
    assert record(finding_root) == 0
    data = (finding_root / "bugs.md").read_bytes()
    assert data.startswith(prefix)
    assert entries(finding_root) == [key] and "Seen again" not in section(finding_root)


# Refusals (FR-14, FR-16) ---------------------------------------------------------------------------------------------

def test_sc15_page_without_marker_refused(finding_root, tmp_path):
    (tmp_path / "stub").mkdir()
    (tmp_path / "stub" / "index.html").write_text("<!doctype html><title>stub</title><p>No marker here.</p>", encoding="utf-8")
    handler = lambda *a, **k: SimpleHTTPRequestHandler(*a, directory=str(tmp_path / "stub"), **k)  # noqa: E731
    stub = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=stub.serve_forever, daemon=True).start()
    try:
        assert record(finding_root, url=f"http://127.0.0.1:{stub.server_address[1]}/") == 2
    finally:
        stub.shutdown()
        stub.server_close()
    assert (finding_root / "bugs.md").read_bytes() == B0
    assert list((finding_root / "evidence").iterdir()) == []


def test_instance_not_in_test_mode_refused(finding_root, tmp_path, capsys):
    with served(tmp_path, "plain") as (manager, base):
        manager.settings = lambda: {"test_instance": None}  # As the live app reports (the sandbox is on in this process).
        (finding_root / "session.json").write_text(json.dumps({"base_url": base, "link": f"{base}/#token=plain", "seed_date": SEED_DATE}))
        assert record(finding_root) == 2
    assert "not the test instance" in capsys.readouterr().err
    assert (finding_root / "bugs.md").read_bytes() == B0 and list((finding_root / "evidence").iterdir()) == []


def test_screenshot_outside_evidence_untouched(finding_root, tmp_path):
    decoy = tmp_path / "elsewhere.png"
    decoy.write_bytes(b"mine")
    stamp = decoy.stat().st_mtime_ns
    for path in (decoy, finding_root / "evidence" / ".." / "elsewhere.png", finding_root / "evidence"):
        assert record(finding_root, path) == 2
    assert decoy.read_bytes() == b"mine" and decoy.stat().st_mtime_ns == stamp
    assert (finding_root / "bugs.md").read_bytes() == B0


def test_target_outside_allowed_refused(finding_root, tmp_path):
    outside = tmp_path / "bugs.md"
    outside.write_bytes(B0)
    screenshot = shot(finding_root)
    assert record(finding_root, screenshot, target=outside) == 2
    assert not screenshot.exists() and outside.read_bytes() == B0


def test_refusal_deletes_screenshot(finding_root, monkeypatch):
    # No session.json.
    session = (finding_root / "session.json").read_bytes()
    (finding_root / "session.json").unlink()
    screenshot = shot(finding_root, "a.png")
    assert record_raw(finding_root, screenshot) == 2 and not screenshot.exists()
    (finding_root / "session.json").write_bytes(session)
    # A bad target.
    screenshot = shot(finding_root, "b.png")
    assert record(finding_root, screenshot, target=ROOT / "docs" / "README.md") == 2 and not screenshot.exists()
    # The lock is held.
    monkeypatch.setattr(script, "LOCK_SECONDS", 0.3)
    lock = finding_root / "bugs.md.lock"
    lock.write_bytes(b"")
    screenshot = shot(finding_root, "c.png")
    assert record(finding_root, screenshot) == 3 and not screenshot.exists() and lock.exists()
    assert (finding_root / "bugs.md").read_bytes() == B0


def record_raw(root, screenshot):
    """record() without reading session.json (for when it is missing)."""
    argv = ["finding", "--root", str(root), "--target", str(root / "bugs.md"), "--url", "http://127.0.0.1:1/", "--screenshot", str(screenshot)]
    for name, value in FIELDS.items():
        argv += [f"--{name}", value]
    return script.main(argv)


def test_non_loopback_base_url_refused(finding_root, no_egress):  # noqa: F811
    (finding_root / "session.json").write_text(json.dumps({"base_url": "http://192.0.2.1:8775", "link": "http://192.0.2.1:8775/#token=x", "seed_date": SEED_DATE}))
    screenshot = shot(finding_root)
    assert record(finding_root, screenshot, url="http://192.0.2.1:8775/#/home") == 2
    assert no_egress.attempts == [] and not screenshot.exists()


def test_agent_required(finding_root):
    for agent in (None, "", "   "):
        screenshot = shot(finding_root)
        assert record(finding_root, screenshot, agent=agent) == 2 and not screenshot.exists()
    assert (finding_root / "bugs.md").read_bytes() == B0


def test_developer_edit_kept(finding_root, monkeypatch):
    edited = B0 + b"\r\nthe developer typed this"
    monkeypatch.setattr(script, "_before_replace", lambda target: target.write_bytes(edited))
    screenshot = shot(finding_root)
    assert record(finding_root, screenshot) == 3
    assert (finding_root / "bugs.md").read_bytes() == edited and not screenshot.exists()
    assert not (finding_root / "bugs.md.lock").exists()


def test_concurrent_findings(finding_root, monkeypatch):
    gate = threading.Barrier(2)
    monkeypatch.setattr(script, "_before_replace", lambda target: __import__("time").sleep(0.3))
    results = {}

    def run(name):
        screenshot = shot(finding_root, f"{name}.png")
        gate.wait()
        results[name] = record(finding_root, screenshot, symptom=f"symptom {name}")

    threads = [threading.Thread(target=run, args=(name,)) for name in ("one", "two")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    found = entries(finding_root)
    assert sorted(results.values()) in ([0, 0], [0, 3]), results
    assert len(found) == list(results.values()).count(0)
    for key in found:  # Each entry is whole.
        entry = section(finding_root).split(f"<!-- finding:{key} -->")[1]
        assert "- Evidence:" in entry
    assert not (finding_root / "bugs.md.lock").exists()


def test_skill_names_finding_command():
    """FR-18 (static): the agent skill exists, records findings only through finding, and uses session.json's base_url."""
    text = (ROOT / ".claude" / "skills" / "agent-testing" / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\nname: agent-testing\ndescription: ")
    for needed in ("python scripts/test_instance.py verify", "session.json", "base_url", "#test-instance-marker",
                   "python scripts/test_instance.py finding", "--url", "evidence/", "8765", "## Agent findings",
                   ".playwright/cli.config.json", "uploads/"):
        assert needed in text, needed
    assert re.search(r"only.{0,40}way to write to `docs/bugs.md`", text)
    # The heading the code cites (docs/development.md "Agent test instance") exists.
    assert re.search(r"^## Agent test instance$", (ROOT / "docs" / "development.md").read_text(encoding="utf-8"), re.M)


def test_finding_cli_smoke(finding_root):
    env = {**os.environ, "HM_TEST_FINDING_DATE": "2026-10-18"}
    base = json.loads((finding_root / "session.json").read_text())["base_url"]
    args = [PYTHON, str(SCRIPT), "finding", "--root", str(finding_root), "--target", str(finding_root / "bugs.md"),
            "--url", base + "/#/home", "--screenshot", str(shot(finding_root))]
    for name, value in FIELDS.items():
        args += [f"--{name}", value]
    done = subprocess.run(args, env=env, cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert len(entries(finding_root)) == 1
    refused = subprocess.run(args[:-2] + ["--agent", ""], env=env, cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert refused.returncode == 2 and "missing --agent" in refused.stderr
    assert Path(args[args.index("--screenshot") + 1]).exists() is False
