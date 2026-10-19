-- Company metadata from the SEC submissions API (CIK, official name, fiscal year end as MMDD).
select *
from read_csv(
    '{{ var("data_dir") }}/companies.csv',
    header = true,
    columns = {
        'ticker': 'VARCHAR',
        'cik': 'VARCHAR',
        'sec_name': 'VARCHAR',
        'fiscal_year_end': 'VARCHAR',
        'sic': 'VARCHAR',
        'sic_description': 'VARCHAR'
    }
)
