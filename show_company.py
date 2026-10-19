"""Print one company's warehouse numbers for hand-checking against its SEC filings.

Usage:
    python show_company.py DUOL
"""

import sys

import duckdb

ticker = sys.argv[1].upper() if len(sys.argv) > 1 else "DUOL"
con = duckdb.connect("warehouse.duckdb", read_only=True)

print(f"\n{ticker}: FY2022 annual values used as the baseline ($M)")
con.sql(f"""
    select standard_name, period_start, period_end, round(value / 1e6, 1) as value_musd, value_source, source_detail
    from staging.stg_sec__period_values
    where ticker = '{ticker}' and fiscal_year = 2022 and duration_quarters = 4
    order by standard_name
""").show(max_width=200)

print(f"{ticker}: quarterly values ($M)")
con.sql(f"""
    select fiscal_year as fy, fiscal_quarter as q, period_end,
           round(revenue / 1e6, 1) as revenue, round(cost_of_revenue / 1e6, 1) as cost_of_rev,
           gross_margin_pct as gm_pct, round(sales_marketing / 1e6, 1) as s_and_m, round(rnd / 1e6, 1) as r_and_d,
           round(operating_cash_flow / 1e6, 1) as op_cash, round(capex / 1e6, 1) as capex,
           revenue_method, cost_of_revenue_source
    from marts.fct_company_quarter
    where ticker = '{ticker}'
    order by fy, q
""").show(max_rows=60, max_width=250)

print(f"{ticker}: mart_margin_squeeze row")
con.sql(f"select * from marts.mart_margin_squeeze where ticker = '{ticker}'").show(max_width=250)
