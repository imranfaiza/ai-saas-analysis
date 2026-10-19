-- Every company has revenue for every fiscal quarter from FY2022 Q1 through its latest reported quarter.
-- Returns one row per missing quarter.

with bounds as (

    select ticker, max(quarter_index) as last_index
    from {{ ref('fct_company_quarter') }}
    where revenue is not null
    group by ticker

),

expected as (

    select
        companies.ticker,
        unnest(generate_series({{ var('baseline_fiscal_year') }} * 4 + 1, coalesce(bounds.last_index, 0))) as quarter_index
    from {{ ref('stg_sec__companies') }} as companies
    left join bounds using (ticker)

)

select
    expected.ticker,
    (expected.quarter_index - 1) // 4 as fiscal_year,
    (expected.quarter_index - 1) % 4 + 1 as fiscal_quarter
from expected
left join {{ ref('fct_company_quarter') }} as fct
    on fct.ticker = expected.ticker
   and fct.quarter_index = expected.quarter_index
where fct.revenue is null

union all

select ticker, null, null
from {{ ref('stg_sec__companies') }}
where ticker not in (select ticker from bounds)
