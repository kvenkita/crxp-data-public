```python
import requests, pandas as pd

# FEMA National Risk Index (v1.20, December 2025), census-tract layer, NC + SC
URL = ("https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/"
       "National_Risk_Index_Census_Tracts/FeatureServer/0/query")
rows, offset = [], 0
while True:
    page = requests.get(URL, params={
        "where": "STATEFIPS IN ('37','45')",
        "outFields": "TRACTFIPS,COUNTY,STATEABBRV,RISK_SCORE,RISK_RATNG,NRI_VER",
        "orderByFields": "TRACTFIPS", "resultOffset": offset, "resultRecordCount": 2000,
        "returnGeometry": "false", "f": "json"}).json()
    rows += [f["attributes"] for f in page["features"]]
    offset += len(page["features"])
    if not page.get("exceededTransferLimit"):
        break
pd.DataFrame(rows).to_csv("data/local/nri_tracts.csv", index=False)

# data/local/nri_tracts.csv (first rows)
# TRACTFIPS,COUNTY,STATEABBRV,RISK_SCORE,RISK_RATNG,NRI_VER
# 37001020100,Alamance,NC,40.59077449966109,Relatively Low,December 2025
# 37001020200,Alamance,NC,22.53695313521934,Relatively Low,December 2025
# 37001020301,Alamance,NC,30.224870084311416,Relatively Low,December 2025
```
