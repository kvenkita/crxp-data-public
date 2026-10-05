```yaml
id: 901
slug: hazard-risk
label: Natural hazard risk score
theme: environment
format: number
decimals: 1
higher_is_better: false
source: tract_csv
tract_csv:
  path: data/local/nri_tracts.csv
  geoid_col: TRACTFIPS
  value_col: RISK_SCORE
  year: 2025
  tract_vintage: 2020
  kind: index
  source_label: FEMA National Risk Index v1.20
  source_url: https://www.fema.gov/flood-maps/products-tools/national-risk-index
description: FEMA's composite natural-hazard risk score (0-100; higher means more risk)
meta_why: The score combines expected annual losses from 18 natural hazards with social
  vulnerability and community resilience, so it shows where a disaster would do the most harm.
```
