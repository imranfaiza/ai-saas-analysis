select
    seed.ticker,
    seed.company_name,
    seed.segment,
    sec.cik,
    sec.sec_name,
    sec.fiscal_year_end,
    cast(substr(sec.fiscal_year_end, 1, 2) as integer) as fiscal_year_end_month
from {{ ref('companies') }} as seed
left join {{ ref('raw_sec__companies') }} as sec using (ticker)
