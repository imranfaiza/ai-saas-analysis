-- Dimensional cost-of-revenue lines (e.g. "Costs of subscription services") parsed from each filing's
-- inline XBRL for companies that never tag a total cost of revenue. The companyfacts API omits these.
select *
from read_csv(
    '{{ var("data_dir") }}/component_facts.csv',
    header = true,
    columns = {
        'ticker': 'VARCHAR',
        'cik': 'VARCHAR',
        'xbrl_tag': 'VARCHAR',
        'axis': 'VARCHAR',
        'member': 'VARCHAR',
        'period_start': 'DATE',
        'period_end': 'DATE',
        'value': 'DOUBLE',
        'form': 'VARCHAR',
        'filed': 'DATE',
        'accession': 'VARCHAR'
    }
)
