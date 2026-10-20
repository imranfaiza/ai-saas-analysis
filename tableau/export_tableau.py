"""Export tidy CSVs from the warehouse for the Tableau Public workbook.

    python tableau/export_tableau.py
"""

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tableau"

DISCLOSURE = """
    case d.ai_cost_pressure
        when 'reported' then 'Says AI is raising costs now'
        when 'risk_only' then 'Lists AI as a risk only'
        else 'Not mentioned'
    end
"""

COMPANIES = f"""
    select
        m.ticker as "Ticker",
        m.company_name as "Company",
        m.segment as "Segment",
        {DISCLOSURE} as "AI Disclosure",
        case d.ai_cost_trend when 'rising' then 'Rising' when 'falling' then 'Falling' else 'Not stated' end
            as "AI Cost Trend",
        m.fy2022_gross_margin_pct as "FY2022 Gross Margin %",
        m.ttm_gross_margin_pct as "TTM Gross Margin %",
        m.margin_change_bps as "Gross Margin Change (bps)",
        m.ttm_revenue_growth_pct as "Revenue Growth %",
        m.cost_growth_gap_pts as "Cost Growth Gap (pts)",
        m.rule_of_40 as "Rule of 40",
        s.opex_pct_change as "Opex Change (pts of revenue)",
        s.operating_margin_pct_change as "Operating Margin Change (pts)",
        s.revenue_growth_change_pts as "Revenue Growth Change (pts)",
        s.rpo_growth_pct as "Backlog (RPO) Growth %",
        s.purchase_obligations_musd as "Purchase Commitments ($M)",
        s.purchase_obligations_fy2022_musd as "Purchase Commitments FY2022 ($M)",
        s.purchase_obligations_pct_of_ttm_revenue as "Commitments % of Revenue",
        m.ttm_period_end as "TTM Ends"
    from marts.mart_margin_squeeze m
    join marts.mart_ai_spend s using (ticker)
    left join marts.mart_ai_disclosures d using (ticker)
    order by m.margin_change_bps
"""

COST_LINES = f"""
    with s as (select * from marts.mart_ai_spend)
    select s.ticker as "Ticker", s.company_name as "Company", s.segment as "Segment",
           {DISCLOSURE} as "AI Disclosure", line as "Cost Line", sort as "Line Order",
           fy2022 as "FY2022 % of Revenue", ttm as "TTM % of Revenue", change as "Change (pts)"
    from s
    left join marts.mart_ai_disclosures d using (ticker),
    lateral (values
        ('Cost of revenue', 1, s.fy2022_cost_of_revenue_pct, s.ttm_cost_of_revenue_pct, s.cost_of_revenue_pct_change),
        ('Sales & marketing', 2, s.fy2022_sales_marketing_pct, s.ttm_sales_marketing_pct, s.sales_marketing_pct_change),
        ('R&D', 3, s.fy2022_rnd_pct, s.ttm_rnd_pct, s.rnd_pct_change),
        ('G&A', 4, s.fy2022_general_admin_pct, s.ttm_general_admin_pct, s.general_admin_pct_change),
        ('Operating margin', 5, s.fy2022_operating_margin_pct, s.ttm_operating_margin_pct, s.operating_margin_pct_change)
    ) as t(line, sort, fy2022, ttm, change)
    order by s.ticker, sort
"""

QUARTERLY = f"""
    select q.ticker as "Ticker", q.company_name as "Company", q.segment as "Segment",
           {DISCLOSURE} as "AI Disclosure",
           q.period_end as "Quarter End", 'FY' || q.fiscal_year || ' Q' || q.fiscal_quarter as "Fiscal Quarter",
           q.revenue / 1e6 as "Revenue ($M)", q.cost_of_revenue / 1e6 as "Cost of Revenue ($M)",
           q.gross_margin_pct as "Gross Margin %", m.fy2022_gross_margin_pct as "FY2022 Gross Margin %"
    from marts.fct_company_quarter q
    join marts.mart_margin_squeeze m using (ticker)
    left join marts.mart_ai_disclosures d using (ticker)
    where q.gross_margin_pct is not null
    order by q.ticker, q.period_end
"""


def main() -> None:
    con = duckdb.connect(str(ROOT / "warehouse.duckdb"), read_only=True)
    for name, sql in [("companies", COMPANIES), ("cost_lines", COST_LINES), ("quarterly", QUARTERLY)]:
        path = OUT / f"{name}.csv"
        df = con.sql(sql).df()
        df.to_csv(path, index=False)
        print(f"{path.name}: {len(df)} rows")


if __name__ == "__main__":
    main()
