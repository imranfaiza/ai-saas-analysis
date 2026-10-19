"""Recompute a company's gross margins by hand and compare them with mart_margin_squeeze.

Usage:
    python check_margin.py DUOL                                # asks for the 10-K numbers
    python check_margin.py DUOL --revenue 369.5 --cost 99.4    # numbers you read off the FY2022 10-K, in $M
"""

import argparse

import duckdb

ap = argparse.ArgumentParser()
ap.add_argument("ticker")
ap.add_argument("--revenue", type=float, help="FY2022 revenue from the 10-K, $M")
ap.add_argument("--cost", type=float, help="FY2022 cost of revenue from the 10-K, $M")
args = ap.parse_args()
t = args.ticker.upper()

HINTS = {
    "DUOL": ("FY ended Dec 31, 2022. Units: thousands -> divide by 1,000",
             "'Revenues'", "'Cost of revenues'"),
    "CRM": ("FY ended Jan 31, 2022 (10-K filed Mar 2022). Units: millions",
            "'Total revenues'", "'Total cost of revenues'"),
    "SNOW": ("FY ended Jan 31, 2022 (10-K filed Mar 2022). Units: thousands -> divide by 1,000",
             "'Revenue'", "'Cost of revenue'"),
    "WDAY": ("FY ended Jan 31, 2022. Units: millions",
             "'Total revenues'", "'Costs of subscription services' + 'Costs of professional services'"),
    "INTU": ("FY ended Jul 31, 2022. Units: millions",
             "'Total net revenue'",
             "'Cost of service and other revenue' + 'Cost of product revenue' + 'Amortization of acquired technology'"),
}


def ask(label: str) -> float | None:
    while True:
        raw = input(f"   {label} in $M (Enter to skip): ").replace(",", "").strip()
        if not raw:
            return None
        try:
            return float(eval(raw, {"__builtins__": {}}))
        except Exception:
            print("   Type a number like 26492 or a sum like 4016 + 63 + 174")


if args.revenue is None and args.cost is None:
    period, rev_line, cost_line = HINTS.get(t, ("FY2022 10-K", "total revenue", "total cost of revenue"))
    print(f"\nRead these off the {t} income statement ({period}):")
    print(f"   revenue = {rev_line}")
    print(f"   cost    = {cost_line}")
    args.revenue = ask("Revenue")
    args.cost = ask("Cost of revenue") if args.revenue else None

con = duckdb.connect("warehouse.duckdb", read_only=True)
mart = con.sql(f"select * from marts.mart_margin_squeeze where ticker = '{t}'").fetchone()
if mart is None:
    raise SystemExit(f"{t} is not in mart_margin_squeeze")
cols = [c[0] for c in con.sql("select * from marts.mart_margin_squeeze limit 0").description]
m = dict(zip(cols, mart))


def gm(revenue: float, cost: float) -> float:
    return (revenue - cost) / revenue * 100


def verdict(mine: float, theirs: float, tol: float = 0.05) -> str:
    return "MATCH" if abs(mine - theirs) <= tol else f"MISMATCH (off by {mine - theirs:+.2f})"


print(f"\n=== {m['company_name']} ({t}) ===")

# 1. FY2022 baseline
base = dict(con.sql(f"""
    select standard_name, value / 1e6
    from staging.stg_sec__period_values
    where ticker = '{t}' and fiscal_year = 2022 and duration_quarters = 4
      and standard_name in ('revenue', 'cost_of_revenue', 'gross_profit')
""").fetchall())
rev22 = base["revenue"]
cost22 = base.get("cost_of_revenue", rev22 - base.get("gross_profit", 0))
mine22 = gm(rev22, cost22)
print("\n1) FY2022 gross margin (warehouse inputs)")
print(f"   revenue         = {rev22:,.1f}")
print(f"   cost of revenue = {cost22:,.1f}")
print(f"   ({rev22:,.1f} - {cost22:,.1f}) / {rev22:,.1f} x 100 = {mine22:.2f}%")
print(f"   mart says fy2022_gross_margin_pct = {m['fy2022_gross_margin_pct']:.2f}%  ->  {verdict(mine22, m['fy2022_gross_margin_pct'])}")

if args.revenue and args.cost:
    yours = gm(args.revenue, args.cost)
    print("\n   Your numbers from the 10-K")
    print(f"   ({args.revenue:,.1f} - {args.cost:,.1f}) / {args.revenue:,.1f} x 100 = {yours:.2f}%")
    print(f"   vs warehouse {mine22:.2f}%  ->  {verdict(yours, mine22, tol=0.1)}")

# 2. Latest trailing twelve months
quarters = con.sql(f"""
    select fiscal_year, fiscal_quarter, period_end, revenue / 1e6, cost_of_revenue / 1e6, revenue_method
    from marts.fct_company_quarter
    where ticker = '{t}' and revenue is not null and cost_of_revenue is not null
    order by quarter_index desc
    limit 4
""").fetchall()[::-1]
print(f"\n2) Trailing twelve months through {m['ttm_through']}")
for fy, q, end, r, c, method in quarters:
    print(f"   FY{fy} Q{q} (ends {end}): revenue {r:>10,.1f}   cost {c:>10,.1f}   [{method}]")
ttm_rev = sum(q[3] for q in quarters)
ttm_cost = sum(q[4] for q in quarters)
mine_ttm = gm(ttm_rev, ttm_cost)
print(f"   sum: revenue {ttm_rev:,.1f}, cost {ttm_cost:,.1f}")
print(f"   ({ttm_rev:,.1f} - {ttm_cost:,.1f}) / {ttm_rev:,.1f} x 100 = {mine_ttm:.2f}%")
print(f"   mart says ttm_gross_margin_pct = {m['ttm_gross_margin_pct']:.2f}%  ->  {verdict(mine_ttm, m['ttm_gross_margin_pct'])}")

# 3. Change in basis points
bps = round((mine_ttm - mine22) * 100)
print("\n3) Margin change")
print(f"   ({mine_ttm:.2f} - {mine22:.2f}) x 100 = {bps:+d} bps")
print(f"   mart says margin_change_bps = {m['margin_change_bps']:+d}  ->  {verdict(bps, m['margin_change_bps'], tol=1)}")
print()
