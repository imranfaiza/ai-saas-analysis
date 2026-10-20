-- Gemini answers about each company's latest 10-K and 10-Q margin text (written by ai/extract.py), every model.
select *
from read_csv(
    '{{ var("data_dir") }}/ai/extractions.csv',
    header = true,
    columns = {
        'tier': 'VARCHAR',
        'model': 'VARCHAR',
        'ticker': 'VARCHAR',
        'form': 'VARCHAR',
        'filing': 'VARCHAR',
        'ai_cost_pressure': 'VARCHAR',
        'main_cost_driver': 'VARCHAR',
        'ai_revenue': 'VARCHAR',
        'ai_cost_trend': 'VARCHAR',
        'evidence_quote': 'VARCHAR',
        'rationale': 'VARCHAR',
        'quote_found': 'BOOLEAN',
        'cost_usd': 'DOUBLE',
        'latency_s': 'DOUBLE',
        'extracted_at': 'TIMESTAMP'
    }
)
