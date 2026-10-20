-- One row per company: what its latest 10-K and latest 10-Q say about AI costs, from the model picked in the
-- Phase 3 eval. ai_cost_pressure takes the stronger of the two filings (reported > risk_only > none) because
-- 10-Qs often show AI costs before the next annual report does; the trend comes from the newer filing.
-- Analyst corrections in the ai_disclosure_reviews seed replace the model's answer, and are flagged.

with reviewed as (

    select
        e.* replace (coalesce(r.ai_cost_pressure, e.ai_cost_pressure) as ai_cost_pressure),
        r.ticker is not null as analyst_reviewed,
        r.reason as review_reason
    from {{ ref('raw_ai__extractions') }} as e
    left join {{ ref('ai_disclosure_reviews') }} as r
        on r.ticker = e.ticker
       and r.form = e.form
    where e.model = '{{ var("extraction_model") }}'

),

extractions as (

    select
        *,
        cast(replace(split_part(filing, '_', 3), '.txt', '') as date) as filing_period_end,
        case ai_cost_pressure when 'reported' then 3 when 'risk_only' then 2 else 1 end as pressure_rank
    from reviewed

),

annual as (

    select * from extractions where form = '10-K'
    qualify row_number() over (partition by ticker order by filing_period_end desc) = 1

),

quarterly as (

    select * from extractions where form = '10-Q'
    qualify row_number() over (partition by ticker order by filing_period_end desc) = 1

),

strongest as (

    select * from (select * from annual union all select * from quarterly)
    qualify row_number() over (partition by ticker order by pressure_rank desc, filing_period_end desc) = 1

),

newest as (

    select * from (select * from annual union all select * from quarterly)
    qualify row_number() over (partition by ticker order by filing_period_end desc) = 1

)

select
    c.ticker,
    c.company_name,
    c.segment,
    strongest.ai_cost_pressure,
    annual.ai_cost_pressure as ai_cost_pressure_10k,
    quarterly.ai_cost_pressure as ai_cost_pressure_10q,
    newest.ai_cost_trend,
    annual.main_cost_driver,
    coalesce(annual.ai_revenue = 'yes' or quarterly.ai_revenue = 'yes', false) as earns_ai_revenue,
    strongest.evidence_quote,
    strongest.quote_found as evidence_quote_verified,
    strongest.form as evidence_form,
    strongest.filing_period_end,
    newest.form as newest_form,
    newest.filing_period_end as newest_filing_period_end,
    newest.evidence_quote as newest_evidence_quote,
    strongest.rationale,
    coalesce(annual.analyst_reviewed or quarterly.analyst_reviewed, false) as analyst_reviewed,
    coalesce(annual.review_reason, quarterly.review_reason) as review_reason,
    strongest.model as extraction_model
from {{ ref('stg_sec__companies') }} as c
left join strongest using (ticker)
left join newest using (ticker)
left join annual using (ticker)
left join quarterly using (ticker)
