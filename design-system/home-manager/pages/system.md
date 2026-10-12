# System: Processing and Settings (Phase 2)

These are the page overrides for Processing v2 (`processing_v2.js`, route `#/processing`) and, after Build C, Settings
(restyled in place, route `#/settings`). MASTER.md wins wherever this file says nothing. The hand-off is
`../phase2-system-plan.md` Builds B and C.

**The user's jobs:**
- **Processing:** see what's running and whether each stage is healthy, start a scan or a batch read, manage watched
  folders, find failed work, and see whether the ledger breaks any rule (Data health).
- **Settings:** change one setting and confirm it was saved; know what each model and check does.

Shared: the tinted region (`.today-region`, never nested; lists inside use 1px dividers), needs-attention rows
(`.needs-row`, `.attention` = `--warning-subtle`, one text-link action), tables (sticky sunken header, 40px rows), 30px
chips (pressed = `--accent-subtle` with an `--accent` border), status badges, one primary per region. No new tokens.

## Processing (built 2026-10-11, Build B)

### Components
- **Header:** h1, subline "Capture and reading run on separate queues; you can keep working meanwhile.", then **Read all
  documents** (secondary; opens a small panel with "Also re-read documents that already have text" and Start reading)
  and **Scan Inbox** (the primary).
- **Strip** (one tinted region, "Now running"): the running work as rows (status badge, label, stage, seconds, Cancel
  named for the work) or "Nothing running.", then a 1px rule and the five stages (Capture, Reading, Recording, Item
  identification, Reconciliation) as columns divided by 1px `--border` rules: label (13px secondary, 600), state badge
  (Idle, or the live status, or "Not run yet"), "Last <when>" with the last run's badge, muted. Reconciliation adds "N
  links · N open"; Reading adds the batch line while a batch runs and the set-up links when no model is chosen.
- **Tabs:** Recent work · Data health (heart-pulse icon, a count pill of errors + warnings) · Watched folders · Scans ·
  Model runs.
- **Recent work:** "Show" kind select and All · Failed chips, then the v1 table (Work, Started, Took, Result, Details);
  Details holds Open document / Show files (which opens Scans at that scan) and the error in Technical details.
- **Data health:** intro line; a summary of badges ("N warnings · N errors · N notes", or "✓ No problems found"); one
  needs-row per rule: icon in its tone (error = `--danger` on `--danger-subtle` via `.needs-row.error`, warning =
  amber `.attention`, note = neutral), the rule's text, "N records · severity", then **Open** when one record has a
  page, or "Which record(s)" disclosure with up to 20 links and "(no page to open)" for table rows, then "and N more
  (run `home-manager check-ledger` for all)"; the rule code in Technical details. Then a "Tax engines" region: label,
  Ready / Not ready badge, note.
- **Watched folders:** intro, "Inbox: <path>" in mono, **+ Watch a folder** (secondary) opening `dialog#pr2-source-dialog`
  (path, name, subfolders; errors under the field), the v1 table with Scan now · Pause/Resume · Stop watching (confirm,
  danger), each named for the folder.
- **Scans:** scan select, state line (polite live), events table and pager.
- **Model runs:** intro, Task and Status selects (refetched on every show), the v1 9-column table; `~` stays.

### Layout
- 1440: header, strip (five equal columns), tabs, tab content full width.
- Under 1100px: the stages are 3 + 2 (rules between columns and above the second row).
- Under 600px: one compact row per stage (title, then state and last run); health rows put the action under the text;
  tables scroll inside `.table-wrap`; tabs scroll inside `.tabs`.

### States
- Nothing running: "Nothing running." No work: "No work recorded yet." (or "No failed work.", "No work of this kind
  yet."). No problems: "✓ No problems found". No folders: "No watched folders. Only Inbox is read." Family mode or no
  library: Watched folders says "Choose a library folder first."
- A tab that fails to load shows its error with Retry inside the tab only; a failed health check leaves the tab name
  without a count.
- Long paths wrap in mono.

### Decided
- `?tab=work|health|folders|scans|models`; `kind` and `status=failed` belong to Recent work, `task` and `status` to Model
  runs; only the shown tab's controls are written.
- The Now running list is the only live region; seconds update in place and are hidden from screen readers, so it
  announces only new work or a new stage.
- Polling refreshes the strip and the shown tab (not Data health, which is checked again on its next show).
- Processing has no `MIGRATED` parity pair: it shows no traced figures.

## Settings (built 2026-10-11, Build C; restyled in place)

### Components
- The tablist (`.settings-nav`): text tabs, selected = `--accent-subtle` with `--accent` text. Donate is the last tab.
- One `--surface` region (`.settings-content`), never nested cards. Inside a tab: h2, a muted lead (`.settings-lead`, or
  the `p.muted` straight after the h2), then groups (`.form` or `.settings-group`) 32px apart under h3s.
- Each form: one primary Save, an optional secondary Test connection, then the result line (`.save-result`,
  `aria-live="polite"`): ✓ "Saved." in `--text-secondary` with a `--positive` icon, or the error in `--danger`. A field's
  validation error is a `.field-error` under the field.
- Independent checks: "Every ledger extraction" (read-only `#decision-status`, link to Local models) and "Document
  reasoning reviewer" (`#reviewer-form`: Off / A second chat model / The decision model).
- Donate: the lead, "N documents checked, ready to donate." and a primary link button to `#/donate`.

### Layout
- 220px tablist + content column at most 760px. Below 800px the tablist is one horizontally scrolling row above the
  content, and `aria-orientation` turns horizontal.

### States
- Busy model queue: the model Saves (reviewer included) are disabled; the reviewer says why.
- The server's refusal of a non-loopback URL shows under `#reviewer-url`.
- Family profile: the reviewer form is hidden (`.personal-only`), as models are per computer.
- No library: Donate says "Choose a library folder first."

### Decided
- Restyled in place, not a `data-ui="v2"` twin: its forms are bound by fixed ids that six browser test files use, and
  the flag's own checkboxes live in Appearance. Every id and role name is kept.
- `?tab=library|profiles|preferences|appearance|models|checks|backup|sharing|privacy|donate`, written only when not the
  default.
- The reviewer select is `#reviewer-kind`, not `reviewer-provider`, so the shared `[data-test]` handler sends no
  `provider` to the connection test.
- Toasts stay alongside the result line (v1 tests expect them).
