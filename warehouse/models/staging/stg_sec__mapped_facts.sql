-- Translate each company's XBRL tags into standard metric names, then keep one value per
-- company, metric and period:
--   1. a company-specific mapping beats the default mapping,
--   2. a lower priority number beats a higher one,
--   3. the most recently filed value wins, so restatements replace the original number.

with facts as (

    select
        ticker,
        taxonomy || ':' || tag as xbrl_tag,
        period_start,
        period_end,
        value,
        form,
        filed,
        accession
    from {{ ref('raw_sec__xbrl_facts') }}
    where unit = 'USD'
      and period_start is not null

),

tag_map as (

    select company, xbrl_tag, standard_name, priority
    from {{ ref('xbrl_tag_map') }}

),

mapped as (

    select
        facts.ticker,
        tag_map.standard_name,
        facts.xbrl_tag,
        facts.period_start,
        facts.period_end,
        facts.value,
        facts.form,
        facts.filed,
        facts.accession,
        tag_map.company <> 'default' as is_company_override,
        tag_map.priority
    from facts
    inner join tag_map
        on tag_map.xbrl_tag = facts.xbrl_tag
       and tag_map.company in (facts.ticker, 'default')

)

select *
from mapped
qualify row_number() over (
    partition by ticker, standard_name, period_start, period_end
    order by is_company_override desc, priority, filed desc, accession desc
) = 1
