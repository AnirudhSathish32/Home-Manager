# Paystub income counting and automatic paycheck planning

## Summary

Make verified paystubs contribute net pay to Today’s **Money in**, without counting the same income again when a bank deposit arrives. Extend the existing “Plan a paycheck from this stub” feature so What If automatically fills an empty paycheck planner.

Use the preferences selected:
- Start from the latest verified stub; preserve planner edits.
- Ask which employer to use when several exist.
- Copy extra earnings and flag them for review.

## 1. Count paystubs as income

- Introduce a shared `STANDALONE_INCOME` rule: a verified, active paystub with a pay date and positive net pay counts unless an eligible linked bank deposit replaces it. Proposed, rejected, deleted, undated or incomplete stubs do not count.
- Include standalone net pay in the shared cash-flow calculation used by Today, household summaries and forecasts. Use the pay date and currency; include income-only currencies in the dashboard selector.
- Update calculation traces and USD conversion to include these same paystubs. Clicking Money in must explain each included stub and link to its document.
- Account-specific cash flow continues to include bank transactions only: an unmatched stub has no known receiving account. Do not change bank balances or spending totals.

### Prevent double counting

- Add `transaction_income_links` through the next available migration, with source IDs, matching evidence, review status and timestamps. Enforce one active deposit per stub and one active stub per deposit.
- Match within the same profile and currency, for exactly the stub’s net pay, with a deposit posted between two days before and five days after payday. Employer-name agreement improves ranking.
- A unique candidate creates a proposed link through the existing reconciliation workflow. Multiple candidates create a review issue; rejected pairs are not proposed again.
- A proposed or verified link suppresses standalone pay only while its deposit is countable income. The deposit then counts on its posting date, including when that moves income across a month boundary.
- Support accepting, rejecting and resolving income links through existing review interfaces. Revalidate links after corrections, rereading, rejection, trash or restoration; an ineligible deposit must not hide valid paystub income.
- Reconcile existing records after migration so previously verified stubs work without rescanning.

## 2. Automatically fill the What If paycheck planner

### Select the source

- Add a read-only source-list endpoint returning eligible verified USD stubs grouped by employer, with stub ID, employer, pay date and document link. Sort by pay date descending, then record ID for deterministic ties.
- On first opening an empty planner, automatically load the latest stub when there is one employer. With multiple employers, show an employer selector before filling.
- Provide a stub selector for choosing an older paycheck and a “Start blank” action.
- Display “Based on [employer], paid [date]” with a source-document link.
- Preserve edited drafts during navigation within the active profile. When a newer or corrected stub becomes available, offer an explicit update instead of replacing the draft. Clear draft/source state when switching profiles.
- Keep saved scenarios unchanged. “Add to plan,” “Update in plan” and “Save” remain explicit actions. Family mode requires choosing a personal profile for autofill.

### Fill the inputs accurately

- Reuse and extend the existing stub-to-planner converter. Copy current-period regular earnings, extra earnings, pre-tax deductions, post-tax deductions and employer contributions as per-paycheck amounts.
- Use the stub’s tax year, supported pay frequency and work state; use the profile’s filing status. Show which values came from the profile.
- Never substitute year-to-date amounts for current-period amounts. Preserve zero amounts and report missing or unsupported values instead of silently dropping them.
- Remove the silent biweekly fallback. Missing frequency, pay or tax year requires completion before calculation. Missing work state requires selecting a state or explicitly choosing no state tax.
- Copy bonus, overtime and other extra earnings, visibly warning that they repeat in the projection unless edited or removed.
- Show printed net pay and tax withholding alongside the calculated result for comparison. Do not infer W-4 settings, deduction percentages or employer-match formulas from dollar amounts. Keep these as editable assumptions.
- Keep the existing direct “Plan a paycheck from this stub” link working. Explicit source changes warn before replacing edited inputs; repeated navigation to the same source preserves edits.

## 3. Interfaces and compatibility

- Preserve existing cash-flow response fields; extend trace inputs to support income records.
- Add the source-list endpoint and an optional metadata response mode to `GET /api/paycheck/from-stub/{id}`. Metadata includes source identity, missing fields and import warnings; the existing default response remains compatible.
- Keep `POST /api/paycheck` and saved scenario calculation inputs unchanged. Partial imported drafts are completed in the UI before submission.
- Add income-link support to review, health checks and document lifecycle handling.
- Update Money, Planning and open-work documentation. Implement this independently of the larger planned bill and ledger redesign.

## 4. Validation and boundaries

- Test standalone verified income; excluded pending/rejected/incomplete stubs; payday/month boundaries; currency conversion; account filters; and trace totals matching Today.
- Test deposit matching in either ingestion order, ambiguous candidates, rejected links, corrections, deletion/restoration and migration with existing records.
- Verify forecasts, retirement pay replacement and payroll contributions do not count income twice.
- Test autofill for one employer, employer selection, older-stub selection, profile isolation, newer-stub updates and preservation of edited drafts and saved scenarios.
- Test missing frequency, zero/missing line amounts, unsupported currency, extra-earnings warnings and direct stub links.
- Run backend regression tests and browser coverage for Today and What If using synthetic records.

Split deposits across multiple accounts remain outside this change, consistent with the existing open-work plan. The planner remains an editable estimate; automatic filling does not approve documents or save scenarios.
