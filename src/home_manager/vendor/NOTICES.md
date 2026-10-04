# Open-source components shipped with Home Manager

## Engine 1 (the year's federal return)

- **Component:** OpenTax, by Invaro Inc. The `@invaro/opentax` 0.4.0 package is included unmodified in `opentax/`.
  - Engine: `@invaro/opentax-core` 0.1.0.
  - Rule corpus: `@invaro/opentax-corpus-us-federal` 0.37.0.
- **License:** GNU Affero General Public License v3.0 only. The full text is in `opentax/LICENSE`, and the commercial
  license terms are in `opentax/COMMERCIAL-LICENSE.md`.
- **Source:** https://github.com/Invaro/opentax-engine
- **Integrity:** `opentax/PIN.json` holds the SHA-256 of every file. The engine runs as a separate program, with its
  usage ping turned off.
- **Trademark:** "OpenTax" and the Invaro mark are trademarks of Invaro Inc.

## Engine 2 (a second opinion on the federal return)

- **Component:** Tax-Calculator, by the Policy Simulation Library (PSLmodels). The `taxcalc` 6.8.4 package is installed
  unmodified as an optional extra (`pip install "home-manager[engine2]"`); it isn't bundled here.
- **License:** CC0 1.0 Universal (public domain dedication). Its dependencies (numpy, pandas, numba, bokeh, paramtools)
  are under permissive licenses (BSD and MIT); each package carries its own license file.
- **Source:** https://github.com/PSLmodels/Tax-Calculator
- **Integrity:** each calculation records the SHA-256 of the release's law file (`policy_current_law.json`). It runs as
  a separate program and makes no network calls.
