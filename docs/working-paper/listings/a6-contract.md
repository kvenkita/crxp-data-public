```json
// manifest.json: entry for this indicator
{
  "id": 901,
  "slug": "hazard-risk",
  "label": "Natural hazard risk score",
  "description": "FEMA's composite natural-hazard risk score (0-100; higher means more risk)",
  "category": "environment",
  "format": "number",
  "decimals": 1,
  "higherIsBetter": false,
  "classMethod": "quantile",
  "years": [2025],
  "geoLevels": ["tract", "county"],
  "source": "FEMA National Risk Index v1.20",
  "vintage": "2025–2025",
  "metaPath": "/data/meta/m901.md",
  "related": [],
  "hasZ": true,
  "hasLisa": true,
  "countyMethod": "derived from tracts"
}

// values/901.json (excerpt)
{
  "indicatorId": 901,
  "years": [2025],
  "values": {
    "37007920100": [33.2537],
    "37007920200": [57.9382],
    "37007920301": [86.4923]
  },
  "...": "749 more tracts, plus breaks and summary statistics per year"
}
```
