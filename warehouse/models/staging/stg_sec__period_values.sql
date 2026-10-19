-- One value per company, metric and reporting period, labelled with its fiscal year and quarter.
-- Periods are 1 to 4 quarters long: a quarter, a year-to-date span, or a full fiscal year.
--
-- Fiscal labels follow each company's own convention (the year the fiscal year ends in):
-- Salesforce's year ending Jan 31, 2026 is FY2026. A 7-day shift absorbs 52/53-week calendars
-- whose quarters end a few days into the next month (Adobe's FY2021 ended Dec 3, 2021).

with reported as (

    select
        ticker,
        standard_name,
        period_start,
        period_end,
        value,
        filed,
        xbrl_tag as source_detail,
        'reported' as value_source,
        1 as source_rank
    from {{ ref('stg_sec__mapped_facts') }}

),

summed as (

    select
        ticker,
        standard_name,
        period_start,
        period_end,
        value,
        filed,
        components_summed as source_detail,
        'component_sum' as value_source,
        2 as source_rank
    from {{ ref('stg_sec__cost_components') }}

),

picked as (

    select *
    from (select * from reported union all select * from summed)
    qualify row_number() over (
        partition by ticker, standard_name, period_start, period_end
        order by source_rank
    ) = 1

),

with_calendar as (

    select
        picked.*,
        companies.fiscal_year_end_month,
        date_diff('day', picked.period_start, picked.period_end) as duration_days,
        cast(picked.period_end - interval 7 day as date) as shifted_end
    from picked
    inner join {{ ref('stg_sec__companies') }} as companies using (ticker)

),

labelled as (

    select
        *,
        cast(round(duration_days / 91.3) as integer) as duration_quarters,
        cast(year(shifted_end + to_months(12 - fiscal_year_end_month)) as integer) as fiscal_year,
        cast(((month(shifted_end) - fiscal_year_end_month - 1 + 12) % 12) // 3 + 1 as integer) as fiscal_quarter
    from with_calendar

)

select
    ticker || '|' || standard_name || '|' || period_start || '|' || period_end as period_value_id,
    ticker,
    standard_name,
    period_start,
    period_end,
    duration_quarters,
    fiscal_year,
    fiscal_quarter,
    value,
    value_source,
    source_detail,
    filed
from labelled
where duration_quarters between 1 and 4
  and abs(duration_days - duration_quarters * 91.3) < 20
