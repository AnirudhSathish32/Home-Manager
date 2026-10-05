# Hand-off template for one screen

Every redesign plan uses these headings, in order. The implementation session sees only this plan, CLAUDE.md, the
skills and the code, so write down everything it needs. Write "none" rather than leaving a heading out.

```markdown
# Redesign: <page> (phase <0|1|2|3>)

## Context
Why this screen and why now. The user's job on it in one sentence. What is wrong today, from the before screenshots and
the user's words.

## Before screenshots
<folder from ui_shots.py>. Name the files the reader should look at.

## Design-system references
The sections of design-system/home-manager/MASTER.md and pages/<page>.md this plan applies, quoted briefly. Note any
deviation from them, with the reason.

## Tokens
The existing `:root` tokens used. Any new or changed tokens with light and dark values and their contrast ratios
(text ≥ 4.5:1, UI ≥ 3:1).

## Layout
ASCII at 1440×900 and at 390, plus 768 if it differs. Mark the decision region and say how it stays in view (docs/ui.md
"Layout" rules 1–2).

## Changes by file
- style.css: which sections, which rules are added or removed.
- <page>.js: which functions change, and the helpers they reuse (ui.js: amount, statusBadge, emptyState …).
- index.html: which containers change.
- Other files, if any.
Give enough detail that the implementer makes no visual decisions of its own.

## Selector contract
| Selector | Used by | Keep / rename to | Test edit |
Everything from the screen-inventory Grep commands goes here.

## States
Empty, loading, error, long text (merchant names, folder names), many rows, a narrow screen, dark theme, and a family
profile if the page is in FAMILY_ROUTES.

## Accessibility
Focus order, keyboard shortcuts kept, aria labels and live regions, reduced motion, and a meaning for every color that
doesn't rely on color alone.

## Out of scope
Things the implementer must not touch: other pages, backend, copy changes not listed above.

## Verification
- `$env:RUN_BROWSER_TESTS = "1"; .venv/Scripts/python.exe -m pytest <exact test files> -q`
- `.venv/Scripts/python.exe .claude/skills/ui-redesign/scripts/ui_shots.py --routes <route> --out <after-folder>`.
  Compare it side by side with the before screenshots, and confirm no "HORIZONTAL OVERFLOW" or page errors.
- Any new layout assertions to add, e.g. the decision button in view at 1366×768.

## Docs to update
The docs/ui.md sections that change ("Pages", "Design system", …), and pages/<page>.md if the design changed during
planning.
```
