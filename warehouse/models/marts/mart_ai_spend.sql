-- One row per company: how the cost structure moved from FY2022 to the latest TTM, how much future
-- spending is locked in through purchase commitments, and whether revenue and bookings are accelerating.
--   * Cost lines as % of revenue: FY2022 annual figures vs the latest four quarters (same window as
--     mart_margin_squeeze). Changes are in percentage points.
--   * Purchase obligations are non-cancelable commitments (mostly cloud hosting), usually disclosed
--     only in the 10-K, so the latest value is the most recent fiscal year end.
--   * RPO = contracted revenue not yet recognized; growth compares the latest quarter with a year earlier.

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
        sum(q.revenue) filter (where q.quarter_index > latest.latest_index - 4) as revenue,
        count(q.revenue) filter (where q.quarter_index > latest.latest_index - 4) as n_revenue,
        sum(q.cost_of_revenue) filter (where q.quarter_index > latest.latest_index - 4) as cost_of_revenue,
        sum(q.sales_marketing) filter (where q.quarter_index > latest.latest_index - 4) as sales_marketing,
        count(q.sales_marketing) filter (where q.quarter_index > latest.latest_index - 4) as n_sales_marketing,
        sum(q.rnd) filter (where q.quarter_index > latest.latest_index - 4) as rnd,
        count(q.rnd) filter (where q.quarter_index > latest.latest_index - 4) as n_rnd,
        sum(q.general_admin) filter (where q.quarter_index > latest.latest_index - 4) as general_admin,
        count(q.general_admin) filter (where q.quarter_index > latest.latest_index - 4) as n_general_admin,
        sum(q.stock_comp) filter (where q.quarter_index > latest.latest_index - 4) as stock_comp,
        count(q.stock_comp) filter (where q.quarter_index > latest.latest_index - 4) as n_stock_comp,
        sum(q.operating_income) filter (where q.quarter_index > latest.latest_index - 4) as operating_income,
        count(q.operating_income) filter (where q.quarter_index > latest.latest_index - 4) as n_operating_income,
        sum(q.revenue) filter (where q.quarter_index between latest.latest_index - 7 and latest.latest_index - 4) as prior_revenue,
        count(q.revenue) filter (where q.quarter_index between latest.latest_index - 7 and latest.latest_index - 4) as n_prior_revenue,
        sum(q.revenue) filter (where q.quarter_index between latest.latest_index - 11 and latest.latest_index - 8) as prior2_revenue,
        count(q.revenue) filter (where q.quarter_index between latest.latest_index - 11 and latest.latest_index - 8) as n_prior2_revenue
    from latest
    inner join quarters as q
        on q.ticker = latest.ticker
       and q.quarter_index between latest.latest_index - 11 and latest.latest_index
    group by latest.ticker

),

baseline as (

    select
        ticker,
        max(value) filter (where standard_name = 'revenue') as revenue,
        max(value) filter (where standard_name = 'cost_of_revenue') as cost_of_revenue,
        max(value) filter (where standard_name = 'gross_profit') as gross_profit,
        max(value) filter (where standard_name = 'sales_marketing') as sales_marketing,
        max(value) filter (where standard_name = 'rnd') as rnd,
        max(value) filter (where standard_name = 'general_admin') as general_admin,
        max(value) filter (where standard_name = 'stock_comp') as stock_comp,
        max(value) filter (where standard_name = 'operating_income') as operating_income
    from {{ ref('stg_sec__period_values') }}
    where fiscal_year = {{ var('baseline_fiscal_year') }}
      and fiscal_quarter = 4
      and duration_quarters = 4
    group by ticker

),

rpo as (

    select
        q.ticker,
        max(q.period_end) as rpo_period_end,
        arg_max(q.rpo, q.quarter_index) as rpo_latest,
        arg_max(prior.rpo, q.quarter_index) as rpo_year_ago
    from quarters as q
    left join quarters as prior
        on prior.ticker = q.ticker
       and prior.quarter_index = q.quarter_index - 4
    where q.rpo is not null
    group by q.ticker

),

-- Fiscal year-end (10-K) commitments are preferred because 10-Qs often tag only one contract; a quarter-end
-- value is used only when no year-end value is recent. Values more than 15 months older than the company's
-- latest quarter are treated as stale and dropped.
commitment_points as (

    select
        b.ticker,
        b.period_end,
        b.fiscal_year,
        b.value,
        b.fiscal_quarter = 4 as is_year_end
    from {{ ref('stg_sec__balance_values') }} as b
    inner join latest using (ticker)
    inner join quarters as q
        on q.ticker = latest.ticker
       and q.quarter_index = latest.latest_index
    where b.standard_name = 'purchase_obligations'
      and b.period_end >= q.period_end - interval 15 month

),

commitments as (

    select
        ticker,
        arg_max(value, is_year_end::int * 100000 + epoch(period_end) / 86400) as purchase_obligations_latest,
        arg_max(period_end, is_year_end::int * 100000 + epoch(period_end) / 86400) as purchase_obligations_as_of
    from commitment_points
    group by ticker

),

commitments_fy2022 as (

    select ticker, arg_max(value, period_end) as purchase_obligations_fy2022
    from {{ ref('stg_sec__balance_values') }}
    where standard_name = 'purchase_obligations'
      and fiscal_year = {{ var('baseline_fiscal_year') }}
      and fiscal_quarter = 4
    group by ticker

),

computed as (

    select
        companies.ticker,
        companies.company_name,
        companies.segment,

        100 * coalesce(baseline.cost_of_revenue, baseline.revenue - baseline.gross_profit) / baseline.revenue
            as fy2022_cost_of_revenue_pct,
        100 * baseline.sales_marketing / baseline.revenue as fy2022_sales_marketing_pct,
        100 * baseline.rnd / baseline.revenue as fy2022_rnd_pct,
        100 * baseline.general_admin / baseline.revenue as fy2022_general_admin_pct,
        100 * baseline.stock_comp / baseline.revenue as fy2022_stock_comp_pct,
        100 * baseline.operating_income / baseline.revenue as fy2022_operating_margin_pct,

        case when ttm.n_revenue = 4 then 100 * ttm.cost_of_revenue / ttm.revenue end as ttm_cost_of_revenue_pct,
        case when ttm.n_revenue = 4 and ttm.n_sales_marketing = 4 then 100 * ttm.sales_marketing / ttm.revenue end
            as ttm_sales_marketing_pct,
        case when ttm.n_revenue = 4 and ttm.n_rnd = 4 then 100 * ttm.rnd / ttm.revenue end as ttm_rnd_pct,
        case when ttm.n_revenue = 4 and ttm.n_general_admin = 4 then 100 * ttm.general_admin / ttm.revenue end
            as ttm_general_admin_pct,
        case when ttm.n_revenue = 4 and ttm.n_stock_comp = 4 then 100 * ttm.stock_comp / ttm.revenue end
            as ttm_stock_comp_pct,
        case when ttm.n_revenue = 4 and ttm.n_operating_income = 4 then 100 * ttm.operating_income / ttm.revenue end
            as ttm_operating_margin_pct,

        case when ttm.n_revenue = 4 and ttm.n_prior_revenue = 4
            then 100 * (ttm.revenue / ttm.prior_revenue - 1) end as ttm_revenue_growth_pct,
        case when ttm.n_prior_revenue = 4 and ttm.n_prior2_revenue = 4
            then 100 * (ttm.prior_revenue / ttm.prior2_revenue - 1) end as prior_ttm_revenue_growth_pct,

        rpo.rpo_period_end,
        rpo.rpo_latest,
        100 * (rpo.rpo_latest / nullif(rpo.rpo_year_ago, 0) - 1) as rpo_growth_pct,
        case when ttm.n_revenue = 4 then rpo.rpo_latest / ttm.revenue end as rpo_to_ttm_revenue,

        commitments.purchase_obligations_as_of,
        commitments.purchase_obligations_latest,
        commitments_fy2022.purchase_obligations_fy2022,
        case when ttm.n_revenue = 4 then 100 * commitments.purchase_obligations_latest / ttm.revenue end
            as purchase_obligations_pct_of_ttm_revenue,
        commitments.purchase_obligations_latest / nullif(ttm.cost_of_revenue, 0) as purchase_obligations_years_of_cost
    from {{ ref('stg_sec__companies') }} as companies
    left join baseline using (ticker)
    left join ttm using (ticker)
    left join rpo using (ticker)
    left join commitments using (ticker)
    left join commitments_fy2022 using (ticker)

)

select
    ticker,
    company_name,
    segment,
    round(fy2022_cost_of_revenue_pct, 1) as fy2022_cost_of_revenue_pct,
    round(ttm_cost_of_revenue_pct, 1) as ttm_cost_of_revenue_pct,
    round(ttm_cost_of_revenue_pct - fy2022_cost_of_revenue_pct, 1) as cost_of_revenue_pct_change,
    round(fy2022_sales_marketing_pct, 1) as fy2022_sales_marketing_pct,
    round(ttm_sales_marketing_pct, 1) as ttm_sales_marketing_pct,
    round(ttm_sales_marketing_pct - fy2022_sales_marketing_pct, 1) as sales_marketing_pct_change,
    round(fy2022_rnd_pct, 1) as fy2022_rnd_pct,
    round(ttm_rnd_pct, 1) as ttm_rnd_pct,
    round(ttm_rnd_pct - fy2022_rnd_pct, 1) as rnd_pct_change,
    round(fy2022_general_admin_pct, 1) as fy2022_general_admin_pct,
    round(ttm_general_admin_pct, 1) as ttm_general_admin_pct,
    round(ttm_general_admin_pct - fy2022_general_admin_pct, 1) as general_admin_pct_change,
    round(fy2022_stock_comp_pct, 1) as fy2022_stock_comp_pct,
    round(ttm_stock_comp_pct, 1) as ttm_stock_comp_pct,
    round(ttm_stock_comp_pct - fy2022_stock_comp_pct, 1) as stock_comp_pct_change,
    round(fy2022_operating_margin_pct, 1) as fy2022_operating_margin_pct,
    round(ttm_operating_margin_pct, 1) as ttm_operating_margin_pct,
    round(ttm_operating_margin_pct - fy2022_operating_margin_pct, 1) as operating_margin_pct_change,
    round((ttm_sales_marketing_pct + ttm_rnd_pct + ttm_general_admin_pct)
        - (fy2022_sales_marketing_pct + fy2022_rnd_pct + fy2022_general_admin_pct), 1) as opex_pct_change,
    round(ttm_revenue_growth_pct, 1) as ttm_revenue_growth_pct,
    round(prior_ttm_revenue_growth_pct, 1) as prior_ttm_revenue_growth_pct,
    round(ttm_revenue_growth_pct - prior_ttm_revenue_growth_pct, 1) as revenue_growth_change_pts,
    rpo_period_end,
    round(rpo_latest / 1e6, 1) as rpo_musd,
    round(rpo_growth_pct, 1) as rpo_growth_pct,
    round(rpo_to_ttm_revenue, 2) as rpo_to_ttm_revenue,
    purchase_obligations_as_of,
    round(purchase_obligations_latest / 1e6, 1) as purchase_obligations_musd,
    round(purchase_obligations_fy2022 / 1e6, 1) as purchase_obligations_fy2022_musd,
    round(100 * (purchase_obligations_latest / nullif(purchase_obligations_fy2022, 0) - 1), 1)
        as purchase_obligations_growth_since_fy2022_pct,
    round(purchase_obligations_pct_of_ttm_revenue, 1) as purchase_obligations_pct_of_ttm_revenue,
    round(purchase_obligations_years_of_cost, 2) as purchase_obligations_years_of_cost
from computed
