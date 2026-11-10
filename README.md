# Virus Inventory Search

    pip install -r requirements.txt
    streamlit run app.py

* `sources.yaml` lists the workbooks (read-only). `type: local` points at the OneDrive *synced folder*
  (`~/Library/CloudStorage/OneDrive-UniversityofCalgary/...`); `type: graph` downloads a sharing link via Microsoft Graph
  (needs `GRAPH_CLIENT_ID`, an Entra app registration with delegated `Files.Read.All`; managed tenants may need IT approval).
* `loaders.py` has one adapter per workbook layout (`flat_hub` = Whelan "AAV Data Hub", `relational` = Constructs/Stocks/Vendors).
  Each maps to the common columns in `COMMON_COLS`. Layout is auto-detected from sheet names; add a new lab by writing an adapter.
* Search: all words must match any field; `-word` excludes. Facets: lab, family, serotype, promoter, function, Cre, in-stock.
* Whelan flat layout: serotype / Cre-dependence are parsed from the item name; multi-value vial cells ("1   4") show raw text and use the first number for filtering.
