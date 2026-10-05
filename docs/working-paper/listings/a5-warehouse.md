```sql
SELECT geoid, year, value, moe, reliability, est_method, source_id
FROM read_parquet('warehouse/tract_indicators/901.parquet')
ORDER BY value DESC
LIMIT 5;

-- result
--       geoid  year   value  moe  reliability est_method source_id
-- 45057011209  2025 96.1091 <NA>         <NA>  tract_csv tract_csv
-- 37179020401  2025 95.1197 <NA>         <NA>  tract_csv tract_csv
-- 45091061008  2025 90.5545 <NA>         <NA>  tract_csv tract_csv
-- 37179021020  2025 90.5165 <NA>         <NA>  tract_csv tract_csv
-- 37119003020  2025 90.0039 <NA>         <NA>  tract_csv tract_csv
```
