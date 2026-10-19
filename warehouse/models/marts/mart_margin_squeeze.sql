-- One row per company: FY2022 gross margin vs. the latest trailing twelve months (TTM).
-- TTM = the company's last four fiscal quarters, so companies with different fiscal year-ends
-- are compared over the same length of time. Every company gets a row; data_gaps lists anything
-- that kept a metric from being computed instead of dropping the company.

with quarters as (

    select * from {{ ref('fct_company_quarter') }}

),

latest as (

    select ticker, max(quarter_index) as latest_index
    from quarters
    where revenue is not null and cost_of_revenue is not null
    group by ticker

),

ttm as (

    select
        latest.ticker,
        latest.latest_index,
        max(q.period_end) filter (where q.quarter_index = latest.latest_index) as ttm_period_end,
        max('FY' || q.fiscal_year || ' Q' || q.fiscal_quarter) filter (where q.quarter_index = latest.latest_index) as ttm_through,

        sum(q.revenue) filter (where q.quarter_index > latest.latest_index - 4) as revenue,
        count(q.revenue) filter (where q.quarter_index > latest.latest_index - 4) as n_revenue,
        sum(q.cost_of_revenue) filter (where q.quarter_index > latest.latest_index - 4) as cost_of_revenue,
        count(q.cost_of_revenue) filter (where q.quarter_index > latest.latest_index - 4) as n_cost_of_revenue,
        sum(q.sales_marketing) filter (where q.quarter_index > latest.latest_index - 4) as sales_marketing,
        count(q.sales_marketing) filter (where q.quarter_index > latest.latest_index - 4) as n_sales_marketing,
        sum(q.rnd) filter (where q.quarter_index > latest.latest_index - 4) as rnd,
        count(q.rnd) filter (where q.quarter_index > latest.latest_index - 4) as n_rnd,
        sum(q.free_cash_flow) filter (where q.quarter_index > latest.latest_index - 4) as free_cash_flow,
        count(q.free_cash_flow) filter (where q.quarter_index > latest.latest_index - 4) as n_free_cash_flow,

        sum(q.revenue) filter (where q.quarter_index between latest.latest_index - 7 and latest.latest_index - 4) as prior_revenue,
        count(q.revenue) filter (where q.quarter_index between latest.latest_index - 7 and latest.latest_index - 4) as n_prior_revenue,
        sum(q.cost_of_revenue) filter (where q.quarter_index between latest.latest_index - 7 and latest.latest_index - 4) as prior_cost_of_revenue,
        count(q.cost_of_revenue) filter (where q.quarter_index between latest.latest_index - 7 and latest.latest_index - 4) as n_prior_cost_of_revenue
    from latest
    inner join quarters as q
        on q.ticker = latest.ticker
       and q.quarter_index between latest.latest_index - 7 and latest.latest_index
    group by latest.ticker, latest.latest_index

),

-- Baseline from the full-year FY2022 figures rather than summed quarters, so a company with
-- missing FY2022 quarterly filings (Atlassian, a foreign filer until FY2023) still has a baseline.
baseline as (

    select
        ticker,
        max(value) filter (where standard_name = 'revenue') as revenue,
        max(value) filter (where standard_name = 'cost_of_revenue') as cost_of_revenue,
        max(value) filter (where standard_name = 'gross_profit') as gross_profit
    from {{ ref('stg_sec__period_values') }}
    where fiscal_year = {{ var('baseline_fiscal_year') }}
      and fiscal_quarter = 4
      and duration_quarters = 4
    group by ticker

),

computed as (

    select
        companies.ticker,
        companies.company_name,
        companies.segment,
        companies.fiscal_year_end_month,

        100 * (baseline.revenue - coalesce(baseline.cost_of_revenue, baseline.revenue - baseline.gross_profit))
            / nullif(baseline.revenue, 0) as fy2022_gross_margin_pct,

        ttm.ttm_through,
        ttm.ttm_period_end,
        case when ttm.n_revenue = 4 then ttm.revenue end as ttm_revenue,
        case when ttm.n_revenue = 4 and ttm.n_cost_of_revenue = 4
            then 100 * (ttm.revenue - ttm.cost_of_revenue) / nullif(ttm.revenue, 0) end as ttm_gross_margin_pct,
        case when ttm.n_revenue = 4 and ttm.n_prior_revenue = 4
            then 100 * (ttm.revenue / nullif(ttm.prior_revenue, 0) - 1) end as ttm_revenue_growth_pct,
        case when ttm.n_cost_of_revenue = 4 and ttm.n_prior_cost_of_revenue = 4
            then 100 * (ttm.cost_of_revenue / nullif(ttm.prior_cost_of_revenue, 0) - 1) end as ttm_cost_of_revenue_growth_pct,
        case when ttm.n_revenue = 4 and ttm.n_sales_marketing = 4
            then 100 * ttm.sales_marketing / nullif(ttm.revenue, 0) end as ttm_sales_marketing_pct,
        case when ttm.n_revenue = 4 and ttm.n_rnd = 4
            then 100 * ttm.rnd / nullif(ttm.revenue, 0) end as ttm_rnd_pct,
        case when ttm.n_revenue = 4 and ttm.n_free_cash_flow = 4
            then 100 * ttm.free_cash_flow / nullif(ttm.revenue, 0) end as ttm_fcf_margin_pct,

        concat_ws('; ',
            case when baseline.revenue is null then 'no FY2022 annual revenue' end,
            case when baseline.revenue is not null and baseline.cost_of_revenue is null and baseline.gross_profit is null
                then 'no FY2022 cost of revenue' end,
            case when ttm.ticker is null then 'no quarter with both revenue and cost of revenue' end,
            case when ttm.n_revenue < 4 then 'TTM revenue has ' || ttm.n_revenue || '/4 quarters' end,
            case when ttm.n_cost_of_revenue < 4 then 'TTM cost of revenue has ' || ttm.n_cost_of_revenue || '/4 quarters' end,
            case when ttm.n_prior_revenue < 4 then 'prior-year TTM revenue has ' || ttm.n_prior_revenue || '/4 quarters' end,
            case when ttm.n_prior_cost_of_revenue < 4 then 'prior-year TTM cost of revenue has ' || ttm.n_prior_cost_of_revenue || '/4 quarters' end,
            case when ttm.n_sales_marketing < 4 then 'TTM S&M has ' || ttm.n_sales_marketing || '/4 quarters' end,
            case when ttm.n_rnd < 4 then 'TTM R&D has ' || ttm.n_rnd || '/4 quarters' end,
            case when ttm.n_free_cash_flow < 4 then 'TTM free cash flow has ' || ttm.n_free_cash_flow || '/4 quarters' end
        ) as data_gaps
    from {{ ref('stg_sec__companies') }} as companies
    left join baseline using (ticker)
    left join ttm using (ticker)

)

select
    ticker,
    company_name,
    segment,
    fiscal_year_end_month,
    round(fy2022_gross_margin_pct, 2) as fy2022_gross_margin_pct,
    ttm_through,
    ttm_period_end,
    round(ttm_revenue / 1e6, 1) as ttm_revenue_musd,
    round(ttm_gross_margin_pct, 2) as ttm_gross_margin_pct,
    cast(round(100 * (ttm_gross_margin_pct - fy2022_gross_margin_pct)) as integer) as margin_change_bps,
    round(ttm_revenue_growth_pct, 1) as ttm_revenue_growth_pct,
    round(ttm_cost_of_revenue_growth_pct, 1) as ttm_cost_of_revenue_growth_pct,
    round(ttm_cost_of_revenue_growth_pct - ttm_revenue_growth_pct, 1) as cost_growth_gap_pts,
    round(ttm_sales_marketing_pct, 1) as ttm_sales_marketing_pct,
    round(ttm_rnd_pct, 1) as ttm_rnd_pct,
    round(ttm_fcf_margin_pct, 1) as ttm_fcf_margin_pct,
    round(ttm_revenue_growth_pct + ttm_fcf_margin_pct, 1) as rule_of_40,
    nullif(data_gaps, '') as data_gaps
from computed
