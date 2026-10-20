-- Point-in-time (balance) values such as remaining performance obligations and purchase commitments:
-- one value per company, metric and date, labelled with the fiscal year and quarter the date closes.
-- Same tag-priority and latest-filing rules as stg_sec__mapped_facts, except purchase obligations: companies
-- use both purchase-obligation tags for anything from one small contract (10-Qs) to the full contractual-
-- obligations table (10-Ks), so the larger value on each date is kept as the total commitment.

with facts as (

    select
        ticker,
        taxonomy || ':' || tag as xbrl_tag,
        period_end,
        value,
        filed,
        accession
    from {{ ref('raw_sec__xbrl_facts') }}
    where unit = 'USD'
      and period_start is null

),

mapped as (

    select
        facts.ticker,
        tag_map.standard_name,
        facts.xbrl_tag,
        facts.period_end,
        facts.value,
        facts.filed,
        tag_map.company <> 'default' as is_company_override,
        tag_map.priority,
        facts.accession
    from facts
    inner join {{ ref('xbrl_tag_map') }} as tag_map
        on tag_map.xbrl_tag = facts.xbrl_tag
       and tag_map.company in (facts.ticker, 'default')

),

picked as (

    select *
    from mapped
    where value > 0
    qualify row_number() over (
        partition by ticker, standard_name, period_end
        order by
            case when standard_name = 'purchase_obligations' then value end desc nulls last,
            is_company_override desc, priority, filed desc, accession desc
    ) = 1

)

select
    picked.ticker || '|' || picked.standard_name || '|' || picked.period_end as balance_value_id,
    picked.ticker,
    picked.standard_name,
    picked.period_end,
    cast(year(cast(picked.period_end - interval 7 day as date) + to_months(12 - companies.fiscal_year_end_month)) as integer)
        as fiscal_year,
    cast(((month(cast(picked.period_end - interval 7 day as date)) - companies.fiscal_year_end_month - 1 + 12) % 12) // 3 + 1
        as integer) as fiscal_quarter,
    picked.value,
    picked.xbrl_tag as source_detail,
    picked.filed
from picked
inner join {{ ref('stg_sec__companies') }} as companies using (ticker)
