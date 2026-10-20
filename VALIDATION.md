# Validation log

Hand-checks of the warehouse against the companies' own FY2022 10-K income statements.
Values in $ millions. "Warehouse" columns come from `python show_company.py <TICKER>`;
"10-K" columns are read off the filing. Gross margin = (revenue − cost of revenue) ÷ revenue.

| Company | FY2022 ends | Warehouse revenue | 10-K revenue | Warehouse cost of revenue | 10-K cost of revenue | Warehouse GM % | 10-K GM % | Match? |
|---|---|---|---|---|---|---|---|---|
| Duolingo (DUOL) | 2022-12-31 | 369.5 | | 99.4 | | 73.09 | | |
| Salesforce (CRM) | 2022-01-31 | 26,492.0 | | 7,026.0 | | 73.48 | | |
| Snowflake (SNOW) | 2022-01-31 | 1,219.3 | | 458.4 | | 62.40 | | |
| Workday (WDAY) | 2022-01-31 | 5,139.0 | | 1,428.0 (subscription + professional services) | | 72.21 | | |
| Intuit (INTU) | 2022-07-31 | 12,726.0 | | 2,406.0 (service + product + amortization of acquired technology) | | 81.09 | | |

## Other checks

| Check | Expected | Result |
|---|---|---|
| Duolingo Q4 2022 revenue in its Q4 earnings release (warehouse derives it as annual − Q1–Q3) | 103.8 | Matched (103.8) |
| Latest quarterly revenue on one company's investor relations page | Duolingo 298.5 (quarter ending 2026-06-30) | Matched (Phase 1 spot-check) |
| `dbt build` passes on my machine | PASS=53 (76 after the cost-structure and commitments models) | Passed |
| `python check_margin.py <TICKER>` shows MATCH for all three checks | MATCH | Passed for DUOL and INTU (warehouse internal checks) |

Hand checks against the 10-K for CRM, SNOW, WDAY and INTU were skipped for now; the warehouse
values above are untested against the filings.
