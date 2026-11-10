"""Common virus-inventory search across labs / workbook layouts.   Run:  streamlit run app.py"""
from pathlib import Path
import pandas as pd
import streamlit as st
import yaml

import sources as src
from loaders import COMMON_COLS, load_workbook

HERE = Path(__file__).parent
st.set_page_config(page_title="Virus Inventory Search", page_icon="🧬", layout="wide")


@st.cache_data(show_spinner=False, ttl=600)
def load_source(entry_json: str, _mtime_key: str):
    import json
    entry = json.loads(entry_json)
    buf, mtime = src.fetch(entry)
    return load_workbook(buf, entry["name"], entry.get("layout", "auto")), mtime


def local_key(entry):
    """Cache-bust local files when they change on disk."""
    if entry.get("type", "local") == "local":
        p = Path(entry["path"]).expanduser()
        return str(p.stat().st_mtime) if p.exists() else "missing"
    return "remote"


# ---------------------------------------------------------------- load sources
cfg = yaml.safe_load((HERE / "sources.yaml").read_text())
frames, status = [], []
import json

with st.sidebar:
    st.header("Sources")
    if st.button("Reload from OneDrive"):
        st.cache_data.clear()

    for entry in cfg["sources"]:
        use = st.checkbox(entry["name"], value=True, key=f"use_{entry['name']}")
        if not use:
            continue
        try:
            df, mtime = load_source(json.dumps(entry, sort_keys=True), local_key(entry))
            frames.append(df)
            status.append((entry["name"], f"{len(df)} rows · file saved {mtime}"))
        except src.NeedsSignIn:
            st.warning(f"{entry['name']}: sign-in needed")
            if st.button("Sign in to Microsoft", key=f"si_{entry['name']}"):
                flow = src.start_device_flow()
                st.info(flow.get("message", str(flow)))
                with st.spinner("Waiting for you to finish signing in…"):
                    src.complete_device_flow(flow)
                st.rerun()
        except Exception as e:
            st.error(f"{entry['name']}: {e}")

    up = st.file_uploader("…or add a workbook (.xlsx)", type="xlsx")
    if up is not None:
        try:
            frames.append(load_workbook(up, Path(up.name).stem))
            status.append((Path(up.name).stem, f"{len(frames[-1])} rows · uploaded"))
        except Exception as e:
            st.error(f"{up.name}: {e}")
    for n, s in status:
        st.caption(f"**{n}** — {s}")

st.title("🧬 Virus Inventory Search")
if not frames:
    st.info("No sources loaded. Edit sources.yaml or upload a workbook.")
    st.stop()

data = pd.concat(frames, ignore_index=True)
for c in COMMON_COLS:
    if c not in data:
        data[c] = ""

# ---------------------------------------------------------------- search + facets
SEARCH_FIELDS = ["item_name", "family", "serotype", "promoter", "payload", "cre_dependence", "function",
                 "activity", "vendor", "catalogue", "lot", "location", "box", "notes", "owner"]
blob = data[SEARCH_FIELDS].astype(str).agg(" ".join, axis=1).str.lower()

q = st.text_input("Search", placeholder="e.g.  GCaMP8  |  cre dio chr2  |  retrograde tracer  |  dopamine sensor",
                  help="All words must match (any field). Prefix a word with - to exclude it.")

c1, c2, c3, c4 = st.columns(4)
def multisel(col, label, container):
    opts = sorted(v for v in data[col].astype(str).unique() if v)
    return container.multiselect(label, opts)

labs = multisel("lab", "Lab", c1)
fams = multisel("family", "Family", c2)
seros = multisel("serotype", "Serotype", c3)
proms = multisel("promoter", "Promoter", c4)
c5, c6, c7 = st.columns([2, 2, 1])
funcs = multisel("function", "Function", c5)
cres = multisel("cre_dependence", "Cre dependence", c6)
in_stock = c7.checkbox("In stock only", value=False)

mask = pd.Series(True, index=data.index)
for tok in q.lower().split():
    mask &= (~blob.str.contains(tok[1:], regex=False)) if tok.startswith("-") and len(tok) > 1 else blob.str.contains(tok, regex=False)
for col, sel in (("lab", labs), ("family", fams), ("serotype", seros), ("promoter", proms),
                 ("function", funcs), ("cre_dependence", cres)):
    if sel:
        mask &= data[col].isin(sel)
if in_stock:
    mask &= data["status"].isin(["In stock", "Low", "Reserved"]) | (data["vials"].fillna(0) > 0)

res = data[mask]
st.caption(f"{len(res)} of {len(data)} stocks match")

show = ["lab", "item_name", "family", "serotype", "promoter", "cre_dependence", "function", "vendor",
        "lot", "titer", "titer_unit", "vials_raw", "status", "location", "box", "position"]
event = st.dataframe(res[show], width="stretch", hide_index=True, height=420,
                     on_select="rerun", selection_mode="single-row",
                     column_config={"titer": st.column_config.NumberColumn(format="%.2e"),
                                    "vials_raw": "vials"})

sel = event.selection.rows if event and event.selection else []
if sel:
    row = res.iloc[sel[0]]
    st.subheader(row["item_name"])
    st.caption(f"{row['lab']} · {row['item_id']}")
    left, right = st.columns(2)
    for i, (k, v) in enumerate(row.items()):
        if k in ("lab", "item_name") or v in ("", None) or (isinstance(v, float) and pd.isna(v)):
            continue
        (left if i % 2 == 0 else right).markdown(f"**{k}**: {v}")

st.download_button("Download results (CSV)", res.to_csv(index=False).encode(), "virus_search_results.csv", "text/csv")
