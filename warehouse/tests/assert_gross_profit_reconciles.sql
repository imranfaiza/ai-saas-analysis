-- Where a filing reports revenue, cost of revenue and gross profit for the same period, revenue - cost
-- should equal gross profit within 1%. A failure points at a tag mapped to the wrong metric.
{{ config(severity = 'warn') }}

with periods as (

    select
        ticker,
        period_start,
        period_end,
        max(value) filter (where standard_name = 'revenue') as revenue,
        max(value) filter (where standard_name = 'cost_of_revenue') as cost_of_revenue,
        max(value) filter (where standard_name = 'gross_profit') as gross_profit
    from {{ ref('stg_sec__period_values') }}
    group by ticker, period_start, period_end

)

select *
from periods
where revenue is not null
  and cost_of_revenue is not null
  and gross_profit is not null
  and abs(revenue - cost_of_revenue - gross_profit) > 0.01 * abs(revenue)
