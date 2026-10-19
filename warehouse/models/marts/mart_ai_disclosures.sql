-- One row per company: what its latest 10-K says about AI costs, from the model picked in the Phase 3 eval.
select
    c.ticker,
    c.company_name,
    c.segment,
    split_part(e.filing, '_', 3)::date as filing_period_end,
    e.ai_cost_pressure,
    e.main_cost_driver,
    e.ai_revenue = 'yes' as earns_ai_revenue,
    e.evidence_quote,
    e.quote_found as evidence_quote_verified,
    e.rationale,
    e.model as extraction_model
from {{ ref('stg_sec__companies') }} c
left join {{ ref('raw_ai__extractions') }} e
    on e.ticker = c.ticker
   and e.model = '{{ var("extraction_model") }}'
