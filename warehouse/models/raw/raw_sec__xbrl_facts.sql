-- One row per company, XBRL tag, reporting period, value and filing, exactly as fetch_sec.py downloaded it.
-- The same period appears in several filings because each filing restates prior-year comparatives.
select *
from read_csv(
    '{{ var("data_dir") }}/facts.csv',
    header = true,
    columns = {
        'ticker': 'VARCHAR',
        'cik': 'VARCHAR',
        'taxonomy': 'VARCHAR',
        'tag': 'VARCHAR',
        'unit': 'VARCHAR',
        'period_start': 'DATE',
        'period_end': 'DATE',
        'value': 'DOUBLE',
        'sec_fiscal_year': 'INTEGER',
        'sec_fiscal_period': 'VARCHAR',
        'form': 'VARCHAR',
        'filed': 'DATE',
        'accession': 'VARCHAR',
        'frame': 'VARCHAR'
    }
)
