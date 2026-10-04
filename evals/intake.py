"""Taking donations into the corpus. Run by the collector only, in their own terminal.

  python -m evals.intake init CORPUS
  python -m evals.intake add CORPUS BUNDLE.zip [--donor d07] [--test-share 0.5]
  python -m evals.intake list CORPUS [--status pending]
  python -m evals.intake admit CORPUS CASE_ID      after checking the donor's answers against the original yourself
  python -m evals.intake drop CORPUS CASE_ID [--reason TEXT]
  python -m evals.intake tuned CORPUS CASE_ID      you looked at this case to change a prompt: it moves to dev
  python -m evals.intake withdraw CORPUS DONOR     deletes the donor's cases and their rows in every result

Answers are fixed by editing answers.json by hand before admitting; `admit` validates it again.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
import random
import shutil
import sys
import zipfile

from home_manager.core.answers import Answers

from .corpus import CASE_ID, DONOR_ID, CaseInfo, Corpus, write_json

BUNDLE_FORMAT = "home-manager-donation/1"
MAX_MEMBER_BYTES = 64 * 1024**2
MAX_BUNDLE_BYTES = 2 * 1024**3
ORIGINAL_SUFFIXES = {"png", "jpg", "pdf"}
SIGNATURES = {"png": b"\x89PNG\r\n\x1a\n", "jpg": b"\xff\xd8\xff", "pdf": b"%PDF-"}


def stamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_member(bundle, name):
    info = bundle.getinfo(name)
    if info.file_size > MAX_MEMBER_BYTES:
        raise ValueError(f"{name} is larger than the limit for one file.")
    return bundle.read(info)


def add(corpus, bundle_path, donor=None, test_share=0.5, rng=None):
    """Unpack one donation bundle as pending cases. Returns the new case IDs."""
    rng = rng or random.SystemRandom()
    if not 0 <= test_share <= 1:
        raise ValueError("The test share is between 0 and 1.")
    manifest = corpus.manifest()
    with zipfile.ZipFile(bundle_path) as bundle:
        names = set(bundle.namelist())
        if sum(info.file_size for info in bundle.infolist()) > MAX_BUNDLE_BYTES:
            raise ValueError("The bundle is larger than the limit.")
        for name in names:  # Only the bundle's own layout; never a path that leaves the folder.
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name:
                raise ValueError("The bundle holds an unsafe path; it was not taken in.")
        donation = json.loads(read_member(bundle, "manifest.json"))
        if donation.get("format") != BUNDLE_FORMAT:
            raise ValueError("This is not a Home Manager donation file.")
        bundle_id = donation["bundle_id"]
        if bundle_id in manifest["bundles"]:
            raise ValueError("This donation file was already taken in.")
        donor = donor or donation.get("donor")
        if not donor or not DONOR_ID.fullmatch(donor):
            raise ValueError("Give the donor's ID with --donor (lowercase letters, digits and dashes, at most 16 characters).")
        if donor in manifest.get("withdrawn", []):
            raise ValueError(f"Donor {donor} withdrew; their documents are not taken in again.")
        staged = []
        for case in donation["cases"]:
            case_id = case["case_id"]
            suffix = PurePosixPath(case["original"]).suffix.lstrip(".")
            if not CASE_ID.fullmatch(case_id) or suffix not in ORIGINAL_SUFFIXES or case["original"] != f"cases/{case_id}/original.{suffix}":
                raise ValueError("The bundle lists a case it does not hold.")
            original = read_member(bundle, case["original"])
            if not original.startswith(SIGNATURES[suffix]):
                raise ValueError(f"Case {case_id}'s original is not a {suffix.upper()} file.")
            answers = Answers.model_validate_json(read_member(bundle, f"cases/{case_id}/answers.json"))
            if answers.document_type != case["document_type"]:
                raise ValueError(f"Case {case_id}'s answers are for another document type.")
            proposal = read_member(bundle, f"cases/{case_id}/proposal.json") if f"cases/{case_id}/proposal.json" in names else None
            info = CaseInfo(case_id=case_id, donor=donor, bundle_id=bundle_id, document_type=case["document_type"], source_kind=case["source_kind"],
                            pages=int(case["pages"]), redacted=bool(case["redacted"]), home_currency=case.get("home_currency"),
                            extraction_version=case.get("extraction_version"), split="test" if rng.random() < test_share else "dev", added_at=stamp())
            staged.append((info, suffix, original, answers, proposal))
    created = []
    for info, suffix, original, answers, proposal in staged:
        folder = corpus.case_folder(donor, info.case_id)
        if folder.exists():
            raise ValueError(f"Case {info.case_id} is already in the corpus.")
        folder.mkdir(parents=True)
        (folder / f"original.{suffix}").write_bytes(original)
        (folder / "answers.json").write_text(answers.model_dump_json(indent=2) + "\n", encoding="utf-8")
        if proposal is not None:
            (folder / "proposal.json").write_bytes(proposal)
        write_json(folder / "case.json", info.model_dump())
        created.append(info.case_id)
    manifest["bundles"].append(bundle_id)
    corpus.save_manifest(manifest)
    return created


def admit(corpus, case_id):
    case = corpus.case(case_id)
    case.answers()  # Hand edits must still be valid answers.
    case.info.status = "admitted"
    case.save()
    return case


def drop(corpus, case_id, reason=""):
    case = corpus.case(case_id)
    case.info.status, case.info.notes = "dropped", reason[:500]
    case.save()
    return case


def tuned(corpus, case_id):
    """A case someone looked at to change a prompt is a dev case from then on."""
    case = corpus.case(case_id)
    case.info.used_for_tuning, case.info.split = True, "dev"
    case.save()
    return case


def withdraw(corpus, donor):
    """Delete a donor's cases and every result row about them; reports are rebuilt without them."""
    from .report import rebuild
    if not DONOR_ID.fullmatch(donor):
        raise ValueError("Invalid donor ID.")
    manifest = corpus.manifest()
    cases = {case.id for case in corpus.cases(("pending", "admitted", "dropped")) if case.info.donor == donor}
    folder = corpus.root / "donors" / donor
    if folder.exists():
        shutil.rmtree(folder)
    for run in corpus.results():
        for name in ("results.jsonl", "outputs.jsonl"):  # outputs.jsonl exists only for runs made with --keep-outputs.
            if (run / name).exists():
                lines = (run / name).read_text(encoding="utf-8").splitlines()
                kept = [line for line in lines if line.strip() and json.loads(line)["case_id"] not in cases]
                (run / name).write_text("".join(line + "\n" for line in kept), encoding="utf-8")
        rebuild(corpus, run)
    manifest.setdefault("withdrawn", []).append(donor)
    corpus.save_manifest(manifest)
    return len(cases)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m evals.intake", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init").add_argument("corpus")
    command = commands.add_parser("add")
    command.add_argument("corpus")
    command.add_argument("bundle")
    command.add_argument("--donor")
    command.add_argument("--test-share", type=float, default=0.5)
    command = commands.add_parser("list")
    command.add_argument("corpus")
    command.add_argument("--status", choices=("pending", "admitted", "dropped", "all"), default="all")
    for name in ("admit", "tuned"):
        command = commands.add_parser(name)
        command.add_argument("corpus")
        command.add_argument("case_id")
    command = commands.add_parser("drop")
    command.add_argument("corpus")
    command.add_argument("case_id")
    command.add_argument("--reason", default="")
    command = commands.add_parser("withdraw")
    command.add_argument("corpus")
    command.add_argument("donor")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            Corpus.create(args.corpus)
            print(f"Corpus ready at {Path(args.corpus).resolve()}.")
            return 0
        corpus = Corpus(args.corpus)
        if args.command == "add":
            created = add(corpus, args.bundle, args.donor, args.test_share)
            print(f"Took in {len(created)} case(s), pending your check: " + ", ".join(created))
        elif args.command == "list":
            statuses = ("pending", "admitted", "dropped") if args.status == "all" else (args.status,)
            for case in corpus.cases(statuses):
                info = case.info
                print(f"{info.case_id}  {info.donor:<8} {info.status:<9} {info.split:<5} {info.document_type:<22} {info.source_kind:<12}"
                      + ("  tuned" if info.used_for_tuning else ""))
        elif args.command == "admit":
            admit(corpus, args.case_id)
            print(f"Admitted {args.case_id}.")
        elif args.command == "drop":
            drop(corpus, args.case_id, args.reason)
            print(f"Dropped {args.case_id}.")
        elif args.command == "tuned":
            tuned(corpus, args.case_id)
            print(f"{args.case_id} is now a dev case.")
        elif args.command == "withdraw":
            count = withdraw(corpus, args.donor)
            print(f"Deleted {count} case(s) of {args.donor} and their result rows.")
    except (ValueError, OSError, zipfile.BadZipFile, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
