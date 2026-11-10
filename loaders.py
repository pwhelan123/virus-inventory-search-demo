"""Loaders that map differently-organised virus inventory workbooks into ONE common table.

Add support for a new lab layout by writing an adapter `fn(path_or_buffer) -> DataFrame`
(with COMMON_COLS) and registering it in ADAPTERS + detect_layout().
All access is read-only.
"""
from __future__ import annotations
import re
import numpy as np
import pandas as pd

COMMON_COLS = [
    "lab", "item_id", "item_name", "family", "serotype", "promoter", "payload", "cre_dependence",
    "function", "activity", "vendor", "catalogue", "lot", "titer", "titer_unit", "aliquot_uL",
    "vials", "vials_raw", "location", "box", "position", "status", "owner", "date_received",
    "expiry", "notes",
]

NA_STRINGS = {"n/av", "n/a", "na", "none", "nan", "", "-", "?"}


def _clean(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    s = str(v).strip()
    return "" if s.lower() in NA_STRINGS else s


def _first_number(v):
    m = re.search(r"-?\d+(?:\.\d+)?", str(v)) if v is not None else None
    return float(m.group()) if m else np.nan


def _empty(n):
    return pd.DataFrame({c: [""] * n for c in COMMON_COLS})


# --------------------------------------------------------------------------- layout detection
def detect_layout(xl: pd.ExcelFile) -> str:
    names = {s.lower() for s in xl.sheet_names}
    if {"constructs", "stocks"} <= names:
        return "relational"
    if "inventory" in names:
        return "flat_hub"
    raise ValueError(f"Unrecognised workbook layout; sheets = {xl.sheet_names}")


# --------------------------------------------------------------------------- adapter: relational (Okafor-style)
def load_relational(xl: pd.ExcelFile, lab: str) -> pd.DataFrame:
    con = xl.parse("Constructs", dtype=object)
    stk = xl.parse("Stocks", dtype=object)
    ven = xl.parse("Vendors", dtype=object) if "Vendors" in xl.sheet_names else pd.DataFrame(columns=["vendor_id", "vendor"])
    df = stk.merge(con, on="construct_id", how="left", suffixes=("", "_c")).merge(ven[["vendor_id", "vendor"]], on="vendor_id", how="left")
    out = _empty(len(df))
    g = lambda c: df[c].map(_clean) if c in df else [""] * len(df)
    out["lab"] = lab
    out["item_id"] = g("stock_id")
    out["item_name"] = g("construct_name")
    out["family"] = g("family")
    out["serotype"] = g("serotype_or_pseudotype")
    out["promoter"] = g("promoter")
    out["payload"] = [
        "-".join(p for p in (a, b) if p) for a, b in zip(g("transgene"), g("reporter"))
    ]
    out["cre_dependence"] = g("cre_dependence")
    out["function"] = g("function")
    out["vendor"] = g("vendor")
    out["lot"] = g("lot")
    out["titer"] = pd.to_numeric(df["titer"], errors="coerce")
    out["titer_unit"] = g("titer_unit")
    out["aliquot_uL"] = g("aliquot_uL")
    out["vials"] = pd.to_numeric(df["vials_remaining"], errors="coerce")
    out["vials_raw"] = g("vials_remaining")
    out["location"] = g("freezer")
    out["box"] = g("rack_box")
    out["position"] = g("grid_pos")
    out["status"] = g("status")
    out["owner"] = g("owner")
    out["date_received"] = pd.to_datetime(df["date_received"], errors="coerce")
    out["expiry"] = pd.to_datetime(df["expiry"], errors="coerce")
    out["notes"] = [" | ".join(x for x in (a, b) if x) for a, b in zip(g("notes"), g("notes_c"))]
    return out


# --------------------------------------------------------------------------- adapter: flat "AAV Data Hub" (Whelan-style)
_SERO = re.compile(r"(AAVrg|AAV\s?DJ|AAVDJ|r?AAV\d?(?:/\d)?(?:-?DJ)?|PHP\.?eB|AAV)", re.I)
_CRE = re.compile(r"\b(flex|flexfrt|dio|do|fas|frt)\b|-flex|-dio|-DO\b", re.I)


def _family(name: str) -> str:
    n = name.lower()
    if "aav" in n:
        return "AAV"
    for key, fam in (("lenti", "Lenti"), ("prv", "PRV"), ("rabies", "Rabies"), ("rv", "Rabies"),
                     ("cav", "CAV"), ("hsv", "HSV")):
        if key in n:
            return fam
    return "Other"


def _parse_name(name: str):
    fam = _family(name)
    sero = ""
    if fam == "AAV":
        m = _SERO.search(name)
        sero = re.sub(r"\s|^r(?=AAV)", "", m.group()) if m else ""
        sero = sero.replace("AAVDJ", "AAV-DJ")
    cre = "Cre-dependent" if _CRE.search(name) else ""
    return fam, sero, cre


def load_flat_hub(xl: pd.ExcelFile, lab: str) -> pd.DataFrame:
    raw = xl.parse("Inventory", header=None, dtype=object)
    hdr_idx = next(i for i in range(min(15, len(raw))) if str(raw.iat[i, 0]).strip().upper() == "ITEM NAME")
    df = raw.iloc[hdr_idx + 1:].copy()
    df.columns = [str(c).strip().upper() for c in raw.iloc[hdr_idx]]
    df = df[df["ITEM NAME"].map(_clean) != ""].reset_index(drop=True)
    col = lambda c: df[c] if c in df else pd.Series([""] * len(df))
    out = _empty(len(df))
    names = col("ITEM NAME").map(_clean)
    parsed = [_parse_name(n) for n in names]
    out["lab"] = lab
    out["item_id"] = [f"R{i + hdr_idx + 2}" for i in range(len(df))]       # Excel row number
    out["item_name"] = names
    out["family"] = [p[0] for p in parsed]
    out["serotype"] = [p[1] for p in parsed]
    out["promoter"] = col("PROMOTER").map(_clean)
    out["payload"] = ""
    out["cre_dependence"] = [p[2] for p in parsed]
    out["function"] = col("FUNCTION").map(_clean)
    out["activity"] = col("ACTIVITY").map(_clean)
    out["vendor"] = col("VENDOR").map(_clean)
    out["catalogue"] = col("CATALOGUE #").map(_clean)
    out["lot"] = col("LOT NUMBER").map(_clean)
    tcol = next((c for c in df.columns if c.startswith("TITER/")), None)
    out["titer"] = pd.to_numeric(df[tcol], errors="coerce") if tcol else np.nan
    out["titer_unit"] = col("TITER UNITS").map(_clean)
    out["aliquot_uL"] = col("ALIQUOT VOLUME (µL)").map(_clean)
    out["vials_raw"] = col("VIALS IN STOCK").map(_clean)
    out["vials"] = col("VIALS IN STOCK").map(_first_number)
    out["location"] = col("STOCK LOCATION").map(_clean)
    out["box"] = col("BOX").map(lambda v: "" if _clean(v) == "" else str(int(_first_number(v))) if not np.isnan(_first_number(v)) else _clean(v))
    def _last_date(v):
        if isinstance(v, str):
            m = re.findall(r"\d+/\d+/\d{4}", v)
            return m[-1] if m else None
        return v
    out["date_received"] = pd.to_datetime(col("DATE ALIQUOTED").map(_last_date), errors="coerce", format="mixed")
    out["status"] = np.where(out["vials"].fillna(-1) == 0, "Empty",
                      np.where(out["vials"].fillna(-1) <= 3, np.where(out["vials"].isna(), "Unknown", "Low"), "In stock"))
    notes = []
    for a, b, c in zip(col("COMMENTS").map(_clean), col("VALIDATED EXPRESSION").map(_clean), col("VALIDATED FUNCTION").map(_clean)):
        parts = [a]
        if b: parts.append(f"validated expression: {b}")
        if c: parts.append(f"validated function: {c}")
        notes.append(" | ".join(p for p in parts if p))
    out["notes"] = notes
    return out


ADAPTERS = {"relational": load_relational, "flat_hub": load_flat_hub}


def load_workbook(path_or_buffer, lab: str, layout: str = "auto") -> pd.DataFrame:
    xl = pd.ExcelFile(path_or_buffer, engine="openpyxl")
    layout = detect_layout(xl) if layout == "auto" else layout
    df = ADAPTERS[layout](xl, lab)
    df["layout"] = layout
    return df[COMMON_COLS + ["layout"]]
