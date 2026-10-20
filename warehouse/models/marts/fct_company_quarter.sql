-- One row per company per fiscal quarter with every standard metric.
-- Gross profit is revenue minus cost of revenue so the two always reconcile; companies that only
-- report gross profit get cost of revenue backed out of it.

with quarterly as (

    select * from {{ ref('stg_sec__quarterly_values') }}

),

pivoted as (

    select
        ticker,
        fiscal_year,
        fiscal_quarter,
        max(period_end) filter (where standard_name = 'revenue') as period_end,
        max(value) filter (where standard_name = 'revenue') as revenue,
        max(value) filter (where standard_name = 'cost_of_revenue') as reported_cost_of_revenue,
        max(value) filter (where standard_name = 'gross_profit') as reported_gross_profit,
        max(value) filter (where standard_name = 'sales_marketing') as sales_marketing,
        max(value) filter (where standard_name = 'rnd') as rnd,
        max(value) filter (where standard_name = 'general_admin') as general_admin,
        max(value) filter (where standard_name = 'stock_comp') as stock_comp,
        max(value) filter (where standard_name = 'operating_income') as operating_income,
        max(value) filter (where standard_name = 'operating_cash_flow') as operating_cash_flow,
        max(value) filter (where standard_name = 'capex') as capex,
        max(value_method) filter (where standard_name = 'revenue') as revenue_method,
        max(value_source) filter (where standard_name = 'cost_of_revenue') as cost_of_revenue_source
    from quarterly
    group by ticker, fiscal_year, fiscal_quarter

),

metrics as (

    select
        *,
        coalesce(reported_cost_of_revenue, revenue - reported_gross_profit) as cost_of_revenue
    from pivoted

),

balances as (

    select
        ticker,
        period_end,
        max(value) filter (where standard_name = 'rpo') as rpo,
        max(value) filter (where standard_name = 'purchase_obligations') as purchase_obligations
    from {{ ref('stg_sec__balance_values') }}
    group by ticker, period_end

)

select
    metrics.ticker || '-FY' || metrics.fiscal_year || 'Q' || metrics.fiscal_quarter as company_quarter_id,
    metrics.ticker,
    companies.company_name,
    companies.segment,
    metrics.fiscal_year,
    metrics.fiscal_quarter,
    metrics.fiscal_year * 4 + metrics.fiscal_quarter as quarter_index,
    metrics.period_end,
    metrics.revenue,
    metrics.cost_of_revenue,
    metrics.revenue - metrics.cost_of_revenue as gross_profit,
    metrics.sales_marketing,
    metrics.rnd,
    metrics.general_admin,
    metrics.stock_comp,
    metrics.operating_income,
    metrics.operating_cash_flow,
    metrics.capex,
    metrics.operating_cash_flow - metrics.capex as free_cash_flow,
    balances.rpo,
    balances.purchase_obligations,
    round(100 * (metrics.revenue - metrics.cost_of_revenue) / nullif(metrics.revenue, 0), 2) as gross_margin_pct,
    round(100 * metrics.sales_marketing / nullif(metrics.revenue, 0), 2) as sales_marketing_pct,
    round(100 * metrics.rnd / nullif(metrics.revenue, 0), 2) as rnd_pct,
    round(100 * metrics.general_admin / nullif(metrics.revenue, 0), 2) as general_admin_pct,
    round(100 * metrics.stock_comp / nullif(metrics.revenue, 0), 2) as stock_comp_pct,
    round(100 * metrics.operating_income / nullif(metrics.revenue, 0), 2) as operating_margin_pct,
    round(100 * (metrics.operating_cash_flow - metrics.capex) / nullif(metrics.revenue, 0), 2) as fcf_margin_pct,
    metrics.revenue_method,
    case
        when metrics.reported_cost_of_revenue is not null then metrics.cost_of_revenue_source
        when metrics.reported_gross_profit is not null then 'revenue_minus_gross_profit'
    end as cost_of_revenue_source
from metrics
inner join {{ ref('stg_sec__companies') }} as companies using (ticker)
left join balances
    on balances.ticker = metrics.ticker
   and balances.period_end = metrics.period_end
where metrics.fiscal_year >= {{ var('first_fiscal_year') }}
