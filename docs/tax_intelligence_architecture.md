# Home Manager — Tax Intelligence and Tax Zen Architecture

**Status:** Architecture/design reference  
**Purpose:** Implementation reference for coding agents building Home Manager's tax intelligence, withholding optimization, and Tax Zen systems.

---

# 6. Tax Subsystem Separation

The tax subsystem should not be represented by one giant `TaxService`.

At minimum, separate these responsibilities:

```text
                        TAX SYSTEM
                            │
           ┌────────────────┼────────────────┐
           ▼                ▼                ▼
       TaxEngine      SafeHarborEngine   W4Optimizer
           │                │                │
           │                │                │
      tax liability    penalty rules    withholding
                                         optimization
```

A higher-level component coordinates them:

```text
TaxZenController
```

The complete structure is approximately:

```text
FinancialProfile
      │
      ▼
ForecastEngine
      │
      ▼
ProjectedTaxProfile
      │
      ▼
TaxEngine
      │
      ▼
TaxCalculation
      │
      ├───────────────┐
      ▼               ▼
SafeHarborEngine   PayrollProjectionEngine
      │               │
      └───────┬───────┘
              ▼
        W4Optimizer
              │
              ▼
        TaxZenController
              │
              ▼
       TaxZenStatusV1
```

---

# 7. TaxEngine

`TaxEngine` answers:

> Given these financial facts, what is the resulting tax liability?

Example interface:

```python
class TaxEngine(Protocol):

    def capabilities(self) -> TaxEngineCapabilities:
        ...

    def calculate(
        self,
        profile: TaxProfileV1
    ) -> TaxCalculationV1:
        ...

    def validate(
        self,
        profile: TaxProfileV1
    ) -> TaxValidationResultV1:
        ...
```

Example normalized result:

```json
{
  "tax_year": 2026,
  "federal": {
    "adjusted_gross_income": 95000,
    "taxable_income": 79000,
    "total_tax": 12740,
    "credits": 0
  },
  "state": null,
  "warnings": [],
  "engine_metadata": {
    "engine": "example",
    "version": "1.0"
  }
}
```

Home Manager should retain both:

```text
normalized result
+
raw engine response
```

for debugging and auditability.

---

# 8. Tax Engines Must Be Plug-and-Play

The engine registry can conceptually look like:

```python
TAX_ENGINES = {
    "filed_opentax": FiledOpenTaxAdapter,
    "engine_b": EngineBAdapter,
    "engine_c": EngineCAdapter,
}
```

Then:

```python
engine = registry.get(settings.tax_engine)
result = engine.calculate(profile)
```

Never create code like:

```python
if engine == "opentax":
    # application-specific behavior
```

outside the adapter layer.

The adapter owns all dependency-specific behavior.

Changing the underlying tax engine should not require changing:

- the UI;
- the financial database;
- the agent;
- tax forecasting;
- Tax Zen;
- reporting;
- historical financial records.

---

# 9. Capability Discovery

Tax engines have different coverage.

Therefore each adapter should expose capabilities.

Example:

```json
{
  "tax_years": [2025],
  "federal": true,
  "states": [],
  "supported_income": [
    "w2",
    "interest",
    "dividends",
    "capital_gains"
  ],
  "supports_itemized_deductions": true,
  "supports_safe_harbor": false,
  "supports_explanations": true
}
```

The orchestrator must check capabilities before invoking an engine.

Unsupported scenarios must fail explicitly rather than silently approximate a return.

---

# 10. Open-Source Tax Engines Are Replaceable Dependencies

The open-source tax landscape should be treated as a set of implementation candidates rather than permanent architectural dependencies.

Potential implementations include projects such as:

```text
TaxEngineV1
     │
     ├── FiledOpenTaxAdapter
     ├── InvaroAdapter
     ├── TelosTaxAdapter
     └── FutureTaxEngineAdapter
```

The existence of better tax engines in the future should be assumed.

Therefore:

```text
TaxEngine implementation today
            ≠
TaxEngine implementation forever
```

Home Manager should own the interface and canonical schemas.

The third-party engine should only supply the calculation implementation.

---

# 11. Tax Zen

"Tax Zen" is a Home Manager product concept.

It is not an IRS legal term.

Tax Zen represents the state where projected tax outcomes satisfy the user's selected withholding objective while remaining consistent with applicable underpayment rules.

Conceptually:

```text
Current finances
      │
      ▼
Projected full-year finances
      │
      ▼
Projected tax liability
      │
      ▼
Projected withholding/payments
      │
      ▼
Safe-harbor evaluation
      │
      ▼
Target evaluation
      │
      ▼
TAX ZEN
```

---

# 12. Tax Zen Should Support Multiple Objectives

Do not hardcode:

```text
Tax Zen = $0 refund
```

Different users may prefer different outcomes.

Example policies:

```text
PRECISION

Desired balance:
approximately $0
```

```text
SMALL-REFUND

Desired result:
small refund as safety margin
```

```text
CASH-RETENTION

Desired result:
retain maximum cash during year while
maintaining an appropriate safety margin
```

```text
SAFE-HARBOR

Primary objective:
minimize underpayment-penalty risk
rather than minimize filing balance
```

Tax Zen should therefore accept a policy object.

Example:

```json
{
  "strategy": "cash_retention",
  "target_balance_due": 500,
  "maximum_expected_balance_due": 900,
  "minimum_safety_margin": 300
}
```

---

# 13. The $1,000 Rule Must Not Be Misrepresented

The system must not encode:

```text
owe < $1,000 = universally safe
```

as the complete safe-harbor definition.

Federal underpayment rules also involve current-year and prior-year tax thresholds.

Therefore Tax Zen should calculate independently:

```text
Projected balance due
Projected current-year percentage paid
Prior-year safe-harbor requirement
Applicable high-income rule
Payment timing
Annualized-income rules where applicable
```

The system may display:

```text
Projected balance due: $620
Safe-harbor status: satisfied
Estimated underpayment penalty risk: none identified
```

rather than deriving everything from one threshold.

---

# 14. SafeHarborEngine

Safe-harbor logic deserves its own deterministic engine.

Example:

```python
class SafeHarborEngine:

    def evaluate(
        self,
        current_year_tax,
        projected_withholding,
        estimated_payments,
        prior_year_tax,
        prior_year_agi,
        payment_timing
    ) -> SafeHarborResultV1:
        ...
```

Example:

```json
{
  "projected_balance_due": 720,
  "less_than_1000_test": true,
  "current_year_90_percent_test": true,
  "prior_year_test": false,
  "required_prior_year_percentage": 1.0,
  "penalty_risk": "LOW",
  "safe_harbor_satisfied": true
}
```

The underlying rules must be tax-year-specific and versioned.

---

# 15. Tax Zen Is a Continuous Control System

Tax Zen should not run once per year.

It should continuously respond to meaningful changes in the user's financial state.

Conceptually:

```text
                  Financial events
                        │
         ┌──────────────┼───────────────┐
         ▼              ▼               ▼
      Paycheck       Investment       Other
                       event          income
         │              │               │
         └──────────────┼───────────────┘
                        ▼
              FinancialProfile updated
                        ▼
                 ForecastEngine
                        ▼
                    TaxEngine
                        ▼
                SafeHarborEngine
                        ▼
                TaxZenController
                        ▼
              status / recommendation
```

Events that may trigger reevaluation include:

- new paycheck;
- bonus;
- realized capital gain/loss;
- dividend or interest income;
- job change;
- salary change;
- self-employment income;
- retirement distribution;
- deductible contribution;
- HSA contribution;
- major credit or deduction change;
- marriage or divorce;
- dependent change;
- new tax rules;
- updated expected year-end income.

---

# 16. ForecastEngine

Tax liability cannot be continuously controlled using historical data alone.

The system needs a deterministic forecasting layer.

Example:

```text
YTD salary = $63,000
Current salary = $86,545
Remaining pay periods = 6

              ↓

Projected wage income
```

The engine also needs to forecast known or reasonably estimable items such as:

```text
salary
bonuses
interest
dividends
retirement contributions
recurring deductions
expected investment distributions
self-employment income
```

Every forecast should preserve provenance:

```json
{
  "value": 86545,
  "source": "payroll_projection",
  "confidence": 0.98,
  "assumption": "salary remains unchanged through year end"
}
```

Do not silently convert assumptions into facts.

---

# 17. Investment Data Requires Special Treatment

Market conditions should not cause Tax Zen to react to unrealized portfolio fluctuations unless those fluctuations affect an actual tax assumption.

Example:

```text
Stock rises $20,000
but is not sold
        │
        ▼
No realized capital gain
        │
        ▼
No direct capital-gain tax event
```

Versus:

```text
Stock sold
$20,000 realized gain
        │
        ▼
Taxable event
        │
        ▼
Tax projection recalculated
```

Expected distributions or planned future sales may be included in forecasts but must be marked as forecasts rather than realized facts.

---

# 18. W4Optimizer

Once the system determines:

```text
Projected tax liability
-
Projected withholding
-
Estimated payments
=
Projected filing balance
```

it must solve the inverse problem:

> What withholding changes should produce the desired year-end outcome?

This responsibility belongs to `W4Optimizer`.

```python
class W4Optimizer:

    def optimize(
        self,
        tax_projection,
        payroll_projection,
        tax_zen_policy
    ) -> W4RecommendationV1:
        ...
```

---

# 19. Form W-4 Control Variables

Relevant W-4 controls include:

```text
Step 3
    ↓
reduces withholding

Step 4(c)
    ↓
increases withholding directly

Step 4(a)
    ↓
increases income treated as subject to withholding

Step 4(b)
    ↓
reduces income treated as subject to withholding
```

These should be viewed as control variables available to the withholding optimizer rather than values the LLM improvises.

---

# 20. Prefer the Simplest Valid W-4 Recommendation

The optimizer should minimize unnecessary complexity.

For example, if the required result can be achieved solely through:

```text
Step 4(c): +$85/paycheck
```

do not produce simultaneous modifications to Steps 3, 4(a), 4(b), and 4(c) without a reason.

Optimization objectives should include:

```text
1. achieve tax target;
2. satisfy safety constraint;
3. minimize number of W-4 fields changed;
4. minimize size/frequency of future adjustments;
5. preserve privacy where possible.
```

---

# 21. Payroll Projection Engine

A W-4 recommendation is useless without understanding payroll timing.

The system should maintain:

```text
pay frequency
next expected paycheck
remaining pay periods
expected gross wages/pay period
current withholding/pay period
current W-4 configuration if known
expected effective date of new W-4
```

A replacement W-4 may not affect the next paycheck immediately.

Therefore recommendations must incorporate implementation latency.

---

# 22. Withholding Timing Matters

The system should model payroll withholding separately from quarterly estimated-tax payments.

Withholding and estimated payments do not necessarily behave identically for underpayment timing calculations.

Therefore:

```text
$1 withholding
```

should not automatically be treated as mathematically identical to:

```text
$1 estimated tax payment
```

for every timing-related calculation.

Safe-harbor and timing logic must remain in the deterministic `SafeHarborEngine`.

---

# 23. Tax Zen Must Include Forecast Uncertainty

A point estimate is insufficient.

Bad:

```text
Projected balance due = $760

Therefore:
Tax Zen ✓
```

Better:

```text
Expected balance due            $760

Reasonable projection range:
$250 ─────────────────── $1,480
```

Result:

```text
Tax Zen: AT RISK
```

because plausible outcomes exceed the user's selected risk threshold.

Each significant forecast should include uncertainty or confidence metadata.

Tax Zen should be evaluated against a safety margin rather than just the mean projection.

---

# 24. Example Risk Buffer

User policy:

```text
Maximum desired balance due    $999
Safety buffer                  $400
```

Control target:

```text
$999 - $400 = $599
```

The optimizer therefore attempts to steer toward approximately:

```text
$599 owed
```

rather than exactly $999.

This reduces the chance that normal forecast error pushes the user beyond the desired threshold.

---

# 25. Hysteresis / Anti-Churn

The application should not ask users to update their W-4 every time a tax projection changes.

Without damping:

```text
Monday       Change W-4
Wednesday    Change W-4 again
Friday       Change W-4 again
```

This is unacceptable UX.

Use a state machine or deadband.

Example:

```text
Projected balance

$0–$600
    TAX ZEN

$600–$850
    WATCH

$850–$1,000
    ACTION SOON

>$1,000
    ACTION
```

Thresholds should depend on user policy and actual safe-harbor calculations rather than these exact example values.

A recommendation might require:

```text
material threshold breached

AND

recommended withholding change > $25/paycheck

AND/OR

material financial event occurred
```

before interrupting the user.

---

# 26. TaxZenStatus

Do not model Tax Zen as a boolean.

Use a state machine.

Example:

```text
ZEN
WATCH
AT_RISK
ACTION_RECOMMENDED
INSUFFICIENT_DATA
ENGINE_UNSUPPORTED
REVIEW_REQUIRED
```

Example result:

```json
{
  "status": "ACTION_RECOMMENDED",
  "projected_balance_due": 1380,
  "safe_harbor_satisfied": false,
  "target_balance_due": 500,
  "projection_confidence": 0.91,
  "remaining_paychecks": 8,
  "recommended_w4": {
    "step_3": 0,
    "step_4c": 110
  },
  "trigger": "realized_capital_gain"
}
```

---

# 27. Example Complete Tax Zen Event

Assume:

```text
Projected tax liability        $17,400
Projected withholding          $13,700
Projected balance due           $3,700
```

Tax Zen becomes:

```text
ACTION_RECOMMENDED
```

Suppose eight effective payroll periods remain.

The system may determine:

```text
Current projection:
$3,700 due

Desired projection:
$500 due

Additional withholding needed:
$3,200

Remaining effective payrolls:
8
```

A candidate adjustment may resemble:

```text
+$400/paycheck
```

However, the exact recommendation must come from the actual withholding calculation methodology rather than simply assuming:

```text
$3,200 ÷ 8
```

always maps directly to the appropriate W-4 value.

The recommendation must be simulated before it is presented.

---

# 28. Role of the Local LLM

The local LLM should not independently derive tax law or perform important arithmetic.

Correct model:

```text
User:
"Am I still Tax Zen?"

        ↓

LLM determines intent

        ↓

TaxZenController.status()

        ↓

Deterministic engines run

        ↓

Structured result

        ↓

LLM explains result
```

Incorrect model:

```text
User financial records
        ↓
20B LLM
        ↓
"Based on my reasoning,
I think you owe about..."
```

The second architecture is unacceptable for high-confidence financial calculations.

---

# 29. Why This Architecture Works With a ~20B Local Model

The LLM does not need to memorize or reliably execute the entire tax code.

It receives narrow tools such as:

```text
calculate_tax()
project_income()
calculate_safe_harbor()
project_withholding()
optimize_w4()
get_tax_zen_status()
explain_tax_calculation()
```

Therefore a moderately sized local model primarily needs strong:

```text
tool selection
structured-output handling
user-intent recognition
explanation
```

rather than exceptional arithmetic or tax expertise.

This reduces the intelligence burden placed on the local model and makes the system substantially more reliable.

---

# 30. Withholding Engine Is Also Replaceable

The withholding/W-4 layer should use the same dependency inversion strategy as `TaxEngine`.

```text
WithholdingEngineV1
        │
        ├── IRSTWEAdapter
        └── FutureWithholdingAdapter
```

Home Manager owns:

```text
W4RecommendationV1
PayrollProjectionV1
WithholdingProjectionV1
```

External implementations only calculate or simulate withholding behavior.

Do not allow an IRS or third-party application's internal schema to become Home Manager's canonical schema.

---

# 31. Privacy Architecture

Financial information should remain local unless a feature explicitly requires external connectivity.

Recommended capability boundaries:

```text
Vision model               NO NETWORK
Local LLM                  NO NETWORK
Tax engine                 NO NETWORK
Withholding engine         NO NETWORK
Financial database         NO NETWORK
Forecast engine            NO NETWORK

Explicit synchronization
gateway                     NETWORK WHEN NEEDED
```

Tax calculation should never require arbitrary outbound network access.

Updates should be a separate operation from calculations.

---

# 32. Dependency Security

Do not trust an open-source project's privacy claims alone.

For embedded dependencies:

1. pin a reviewed version or commit;
2. record its hash;
3. audit dependencies;
4. review outbound networking;
5. sandbox where feasible;
6. prevent calculation processes from having unnecessary network access;
7. keep update functionality separate;
8. preserve dependency version information with calculation records.

For precompiled binaries, source review alone does not prove that the binary corresponds exactly to the reviewed source.

Where practical, build sensitive dependencies from pinned source.

---

# 33. Licensing Must Remain Part of Dependency Selection

Do not treat:

```text
open source
```

as equivalent to:

```text
unrestricted commercial embedding
```

Before shipping any dependency, confirm:

```text
license
distribution obligations
linking/derivative-work implications
commercial-use restrictions
attribution requirements
```

License assumptions should not be permanently encoded into system architecture.

---

# 34. Provenance and Auditability

Every high-impact value should be traceable.

Example:

```text
Projected federal tax:
$14,228
```

should be traceable to:

```text
Tax engine:
Engine A

Engine version:
x.y.z

Tax year:
2026

Calculation timestamp:
...

Input profile version:
FinancialProfileV1 / revision 183

Source facts:
paycheck_2026_09_30
brokerage_statement_2026_09
interest_projection_2026

Forecast assumptions:
salary unchanged
expected remaining dividends = $430
```

A user should eventually be able to ask:

> Why did Tax Zen change?

and receive a deterministic causal explanation such as:

```text
Tax Zen changed because:

1. A $9,840 realized long-term capital gain was imported.
2. Projected federal liability increased by $X.
3. Expected withholding did not change.
4. Projected balance due therefore increased from $Y to $Z.
```

The LLM may translate this into conversational language, but it should not invent the causal chain.

---

# 35. Keep Facts, Forecasts, and Inferences Separate

The database must distinguish:

```text
FACT
FORECAST
USER_ASSUMPTION
MODEL_EXTRACTION
DERIVED_VALUE
```

Example:

```text
YTD federal withholding:
FACT

Expected December bonus:
USER_ASSUMPTION

Projected December withholding:
FORECAST

Projected annual tax:
DERIVED_VALUE

W-2 Box 1 extracted by vision model:
MODEL_EXTRACTION
```

This distinction is critical for reliable financial reasoning.

---

# 36. Confidence Should Be End-to-End

Confidence is not simply LLM confidence.

The system should consider:

```text
document extraction certainty
schema completeness
data freshness
forecast uncertainty
tax-engine support
unknown financial events
```

Example:

```json
{
  "tax_projection": 14320,
  "confidence": "MEDIUM",
  "reasons": [
    "December bonus unknown",
    "brokerage year-end distribution not yet announced"
  ]
}
```

Tax Zen should become more conservative when uncertainty increases.

---

# 37. Historical Reproducibility

Every calculation should be reproducible later.

Store:

```text
canonical input snapshot
engine version
rule/tax year
forecast assumptions
calculation result
Tax Zen policy
W-4 recommendation
timestamp
```

A future engine upgrade must not rewrite historical calculations as though they had been generated by the newer engine.

Instead:

```text
Calculation #152
Engine: EngineA v2.1

Calculation #153
Engine: EngineB v1.0
```

---

# 38. Engine Comparison Mode

Because `TaxEngine` is abstracted, Home Manager may eventually support running multiple engines.

Example:

```text
TaxProfileV1
      │
      ├──── Engine A → $14,282
      └──── Engine B → $14,282
```

Result:

```text
Agreement ✓
```

or:

```text
Engine A → $14,282
Engine B → $14,661

DISAGREEMENT: $379
REVIEW REQUIRED
```

This can become an additional validation mechanism for high-impact calculations.

It should not be required for the initial implementation.

---

# 39. Recommended Core Service Boundaries

The tax-related system should approximately contain:

```text
FinancialProfileService
LedgerService

ForecastEngine
PayrollProjectionEngine

TaxEngine
SafeHarborEngine
WithholdingEngine
W4Optimizer
TaxZenController

AgentToolLayer

LocalLLM
```

Avoid collapsing these responsibilities into a single "AI financial agent."

---

# 40. Suggested Project Structure

A conceptual layout:

```text
home_manager/

  domain/
    financial/
      schemas/
      models/

    tax/
      schemas/
      policies/

  services/
    financial/
      profile_service.py
      ledger_service.py
      forecast_service.py

    tax/
      tax_service.py
      safe_harbor_service.py
      withholding_service.py
      w4_optimizer.py
      tax_zen_controller.py

  adapters/
    tax/
      filed_opentax_adapter.py
      future_tax_adapter.py

    withholding/
      irs_twe_adapter.py
      future_withholding_adapter.py

    llm/
      local_llm_adapter.py

  infrastructure/
    database/
    files/
    security/

  agent/
    tools/
    orchestration/
```

Exact folder names are flexible.

Separation of responsibilities is not.

---

# 41. Recommended Tax Zen API

The rest of Home Manager should have a simple high-level entry point.

Example:

```python
status = tax_zen_controller.evaluate(
    financial_profile=profile,
    policy=user.tax_zen_policy
)
```

Return:

```json
{
  "status": "WATCH",
  "federal": {
    "projected_tax": 15420,
    "projected_withholding": 14690,
    "projected_balance_due": 730,
    "safe_harbor_satisfied": true
  },
  "uncertainty": {
    "low_balance_due": 410,
    "expected_balance_due": 730,
    "high_balance_due": 1180
  },
  "action": null,
  "next_recalculation_trigger": [
    "new_paycheck",
    "realized_investment_event",
    "material_profile_change"
  ]
}
```

The UI and LLM consume this object.

They should not reconstruct the calculations independently.

---

# 42. Notification Logic

A Tax Zen recalculation and a user notification are two separate events.

The engine may calculate frequently.

The user should be interrupted rarely.

Example:

```text
new transaction
      ↓
recalculate
      ↓
status remains ZEN
      ↓
NO NOTIFICATION
```

Versus:

```text
capital gain realized
      ↓
recalculate
      ↓
ZEN → ACTION_RECOMMENDED
      ↓
NOTIFY USER
```

Good notification triggers include:

```text
Tax Zen state transition
safe-harbor status changes
material W-4 recommendation appears
large change in projected liability
critical missing information
tax engine can no longer confidently model scenario
```

---

# 43. Tax Zen Should Explain Why It Wants a W-4 Change

Never show only:

```text
Set Step 4(c) to $137.
```

Provide:

```text
Why:

A newly imported brokerage transaction
increased projected taxable capital gains.

Projected balance before adjustment:
$1,640 due

Tax Zen target:
$500 due

Remaining effective pay periods:
10

Recommended W-4:
Step 4(c): $X

Expected balance after adjustment:
approximately $500 due
```

The deterministic calculation produces the figures.

The LLM may render the explanation.

---

# 44. W-4 Recommendations Require User Action

Home Manager should initially recommend rather than automatically submit W-4 changes.

Flow:

```text
Home Manager detects problem
        ↓
calculates recommendation
        ↓
explains recommendation
        ↓
user reviews
        ↓
user submits W-4 to employer/payroll system
```

Do not design the core architecture around automatic employer submission.

If employer/payroll integrations are added later, keep them behind a separate explicit action interface.

---

# 45. Validation Strategy

Tax calculations require unusually strong testing.

At minimum use:

```text
unit tests
golden test cases
property tests where appropriate
tax-year regression tests
cross-engine comparisons where possible
official example comparisons
W-4 round-trip simulations
boundary tests
```

Critical boundaries include:

```text
$999 vs $1,000 expected balance
tax-bracket transitions
capital-loss limitations
credit phaseouts
safe-harbor income thresholds
year changes
filing-status changes
remaining-paycheck = 1
remaining-paycheck = 0
```

---

# 46. W-4 Round-Trip Testing

The `W4Optimizer` should not simply generate a recommendation.

It should verify it.

Process:

```text
Tax projection
      ↓
W4Optimizer proposes W-4
      ↓
Payroll withholding simulator
      ↓
Projected future withholding
      ↓
Tax calculation rerun
      ↓
Does result meet Tax Zen target?
```

If not:

```text
iterate
```

Conceptually:

```python
candidate = optimizer