-- Build total cost of revenue for companies that only tag its component lines
-- (see seeds/cost_of_revenue_components.csv for exactly which tags are summed).
-- A period is only emitted when every component is present, so a missing line can't
-- silently understate cost.

with components as (

    select
        company as ticker,
        component,
        xbrl_tag,
        coalesce(axis, '') as axis,
        coalesce(member, '') as member
    from {{ ref('cost_of_revenue_components') }}

),

expected as (

    select ticker, count(distinct component) as n_components
    from components
    group by ticker

),

matched as (

    select
        facts.ticker,
        components.component,
        facts.xbrl_tag,
        facts.period_start,
        facts.period_end,
        facts.value,
        facts.filed,
        facts.accession
    from {{ ref('raw_sec__component_facts') }} as facts
    inner join components
        on components.ticker = facts.ticker
       and components.xbrl_tag = facts.xbrl_tag
       and components.axis = coalesce(facts.axis, '')
       and components.member = coalesce(facts.member, '')

),

latest as (

    select *
    from matched
    qualify row_number() over (
        partition by ticker, component, period_start, period_end
        order by filed desc, accession desc
    ) = 1

)

select
    latest.ticker,
    'cost_of_revenue' as standard_name,
    latest.period_start,
    latest.period_end,
    sum(latest.value) as value,
    max(latest.filed) as filed,
    string_agg(latest.component, ' + ' order by latest.component) as components_summed
from latest
inner join expected using (ticker)
group by latest.ticker, latest.period_start, latest.period_end, expected.n_components
having count(*) = expected.n_components
