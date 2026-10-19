-- Turn reported periods into one value per company, metric and fiscal quarter.
--   * Use the reported 3-month value when the filing has one.
--   * Q1 year-to-date is the quarter itself.
--   * Otherwise subtract: this year-to-date minus last quarter's year-to-date
--     (cash flow statements only report year-to-date), or the annual total minus
--     Q1-Q3 (there is no 10-Q for the fourth quarter).

with periods as (

    select *
    from {{ ref('stg_sec__period_values') }}
    where duration_quarters <= fiscal_quarter

),

grid as (

    select
        ticker,
        standard_name,
        fiscal_year,
        fiscal_quarter,
        max(period_end) as period_end,
        max(value) filter (where duration_quarters = 1) as quarter_value,
        max(value) filter (where duration_quarters = fiscal_quarter) as ytd_value,
        max(value_source) as value_source
    from periods
    where duration_quarters = 1 or duration_quarters = fiscal_quarter
    group by ticker, standard_name, fiscal_year, fiscal_quarter

),

with_prior as (

    select
        cur.*,
        max(prior.ytd_value) filter (where prior.fiscal_quarter = cur.fiscal_quarter - 1) as prior_ytd_value,
        sum(prior.quarter_value) as prior_quarters_sum,
        count(prior.quarter_value) as prior_quarters_count
    from grid as cur
    left join grid as prior
        on prior.ticker = cur.ticker
       and prior.standard_name = cur.standard_name
       and prior.fiscal_year = cur.fiscal_year
       and prior.fiscal_quarter < cur.fiscal_quarter
    group by all

),

derived as (

    select
        ticker,
        standard_name,
        fiscal_year,
        fiscal_quarter,
        period_end,
        value_source,
        case
            when quarter_value is not null then quarter_value
            when fiscal_quarter = 1 then ytd_value
            when ytd_value is not null and prior_ytd_value is not null then ytd_value - prior_ytd_value
            when ytd_value is not null and prior_quarters_count = fiscal_quarter - 1 then ytd_value - prior_quarters_sum
        end as value,
        case
            when quarter_value is not null then 'reported_quarter'
            when fiscal_quarter = 1 then 'reported_quarter'
            when ytd_value is not null and prior_ytd_value is not null
                then case when fiscal_quarter = 4 then 'annual_minus_9m_ytd' else 'ytd_minus_prior_ytd' end
            when ytd_value is not null and prior_quarters_count = fiscal_quarter - 1 then 'annual_minus_prior_quarters'
        end as value_method
    from with_prior

)

select
    ticker || '|' || standard_name || '|FY' || fiscal_year || 'Q' || fiscal_quarter as quarterly_value_id,
    *
from derived
where value is not null
