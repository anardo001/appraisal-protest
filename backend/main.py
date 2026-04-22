
#!/usr/bin/env python3
"""
Dallas Appraisal Protest Helper - FastAPI Backend
Endpoints:
  GET  /api/health
  GET  /api/property?address=...&zip=...
  GET  /api/comps?account=...&exclude_new=true|false&supporting_only=true|false
  GET  /api/evidence-html?account=...&owner_name=...&opinion_of_value=...&exclude_new=...&supporting_only=...
  POST /api/generate-pdf  body: {account, owner_name, opinion_of_value, exclude_new, supporting_only}
"""
import os
import sqlite3
import html
import io
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

DB_PATH      = Path(os.environ.get("DB_PATH", str(Path(__file__).parent / "dcad2026.db")))
CURRENT_YEAR = date.today().year

app = FastAPI(title="Dallas Appraisal Protest Helper")



app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add Private Network Access header to suppress browser permission prompts
# Required when a public site calls an API on a different Render subdomain
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest

class PrivateNetworkAccessMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        response = await call_next(request)
        response.headers["Access-Control-Allow-Private-Network"] = "true"
        return response

app.add_middleware(PrivateNetworkAccessMiddleware)

# ── Startup: download DB from Google Drive if not present ─────────────────────
@app.on_event("startup")
async def download_db_if_missing():
    """
    On Render: DB lives on a persistent disk at /data/dcad2026.db.
    If the disk is fresh (first deploy), download the DB from Google Drive.
    Safe to run on every startup — skips if file already exists.
    """
    if not DB_PATH.exists():
        import urllib.request
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        gdrive_id  = "1-FCVXeK4rUfxfmyfgHPhKA9y2qfAa7Jb"
        # Use the confirmed direct-download URL for Google Drive
        dl_url = f"https://drive.usercontent.google.com/download?id={gdrive_id}&export=download&confirm=t"
        print(f"DB not found at {DB_PATH}. Downloading from Google Drive...")
        try:
            urllib.request.urlretrieve(dl_url, DB_PATH)
            size_mb = DB_PATH.stat().st_size / (1024 * 1024)
            print(f"DB downloaded: {size_mb:.0f} MB at {DB_PATH}")
        except Exception as e:
            print(f"ERROR: Failed to download DB: {e}", file=__import__('sys').stderr)
    else:
        size_mb = DB_PATH.stat().st_size / (1024 * 1024)
        print(f"DB found: {size_mb:.0f} MB at {DB_PATH}")

# ── DB helpers ────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def row_to_dict(r):
    return dict(r)

def get_subject(conn, account):
    row = conn.execute("""
        SELECT ACCOUNT_NUM, ADDRESS, PROPERTY_CITY, PROPERTY_ZIPCODE,
               NBHD_CD, SPTD_CODE, TOT_VAL, PREV_MKT_VAL,
               IMPR_VAL, LAND_VAL, TOT_LIVING_AREA_SF, YR_BUILT,
               NUM_BEDROOMS, NUM_FULL_BATHS,
               CDU_RATING_DESC, BLDG_CLASS_DESC, VAL_PER_SQFT
        FROM comp_view WHERE ACCOUNT_NUM = ?
    """, (account,)).fetchone()
    return row_to_dict(row) if row else None



def get_comps_data(conn, subject, exclude_new=True, supporting_only=False, pass_lock=None):
    """
    Find comparable properties for the subject using a progressive widening strategy.

    PROGRESSIVE WIDENING (4 passes):
    The engine starts narrow and widens until it finds enough comps (target: 15).
    Each pass loosens the size and age constraints:
      Pass 1: ±10 yr, 75%–125% size   — most similar properties
      Pass 2: ±15 yr, 65%–135% size   — moderate expansion
      Pass 3: ±20 yr, 50%–150% size   — broad expansion
      Pass 4: no size/age constraints  — all neighborhood comps (fallback)

    SIMILARITY SCORING (used to rank and select top 15):
    Each comp is scored on three dimensions, weighted by protest relevance:
      PSF gap  40%: How much lower is the comp's $/sqft vs the subject?
                    Higher weight because this directly supports the "unequal assessment" argument.
      Age      35%: How close in build year? Similar age = more comparable under Texas ARB standards.
      Size     25%: How close in square footage? Important but less determinative than PSF/age.

    SUPPORTING_ONLY mode:
    When True, only comps assessed BELOW the subject's $/sqft are returned.

    pass_lock: If set (1-4), skip progressive widening and run only that specific pass.

    Returns:
        List of up to 15 comparable property dicts with similarity metadata.
    """
    sqft     = float(subject.get("TOT_LIVING_AREA_SF") or 1500)
    yr       = int(float(subject.get("YR_BUILT") or 1980))
    subj_psf = float(subject.get("VAL_PER_SQFT") or 0)
    new_clause = f"AND CAST(YR_BUILT AS INTEGER) <= {CURRENT_YEAR - 2}" if exclude_new else ""


    bands = [
        (0.75, 1.25, 10),
        (0.65, 1.35, 15),
        (0.50, 1.50, 20),
        (0.0,  9.0,  99),
    ]
    # If the user locked a specific pass, restrict the engine to that single band
    if pass_lock is not None:
        bands = [bands[pass_lock - 1]]

    if supporting_only and subj_psf > 0:
        comps     = []
        used_band = bands[0]
        pass_num  = 1
        for pidx, (lo_mult, hi_mult, age_delta) in enumerate(bands, 1):
            sqft_lo = sqft * lo_mult if lo_mult > 0 else 0
            sqft_hi = sqft * hi_mult
            yr_lo   = yr - age_delta
            yr_hi   = yr + age_delta
            size_clause = f"AND CAST(TOT_LIVING_AREA_SF AS REAL) BETWEEN {sqft_lo} AND {sqft_hi}" if lo_mult > 0 else ""
            age_clause  = f"AND CAST(YR_BUILT AS INTEGER) BETWEEN {yr_lo} AND {yr_hi}" if age_delta < 99 else ""
            rows = conn.execute(f"""
                SELECT ACCOUNT_NUM, ADDRESS, PROPERTY_CITY, PROPERTY_ZIPCODE,
                       TOT_VAL, PREV_MKT_VAL, TOT_LIVING_AREA_SF, YR_BUILT,
                       NUM_BEDROOMS, NUM_FULL_BATHS, CDU_RATING_DESC, VAL_PER_SQFT
                FROM comp_view
                WHERE NBHD_CD  = ?
                  AND SPTD_CODE = ?
                  AND VAL_PER_SQFT IS NOT NULL
                  AND CAST(VAL_PER_SQFT AS REAL) < ?
                  AND ACCOUNT_NUM != ?
                  {size_clause}
                  {age_clause}
                  {new_clause}
                ORDER BY CAST(VAL_PER_SQFT AS REAL) ASC
                LIMIT 50
            """, (subject["NBHD_CD"], subject["SPTD_CODE"],
                  subj_psf, subject["ACCOUNT_NUM"])).fetchall()
            candidates = [row_to_dict(r) for r in rows]
            for c in candidates:
                c_sqft = float(c.get("TOT_LIVING_AREA_SF") or sqft)
                c_yr   = float(c.get("YR_BUILT") or yr)
                c_psf  = float(c.get("VAL_PER_SQFT") or 0)
                size_score = max(0, 1 - abs(c_sqft - sqft) / sqft)
                age_score  = max(0, 1 - abs(c_yr - yr) / max(age_delta, 1))
                psf_gap    = subj_psf - c_psf
                psf_score  = min(1, psf_gap / subj_psf) if subj_psf > 0 else 0
                c["_similarity"] = round(0.25 * size_score + 0.35 * age_score + 0.40 * psf_score, 4)
            comps = sorted(candidates, key=lambda c: -c["_similarity"])[:15]
            used_band = (lo_mult, hi_mult, age_delta)
            pass_num  = pidx
            if len(comps) >= 15:
                break
        band_lo    = int(sqft * used_band[0]) if used_band[0] > 0 else 0
        band_hi    = int(sqft * used_band[1]) if used_band[1] < 9.0 else 0
        band_yr_lo = yr - used_band[2] if used_band[2] < 99 else 0
        band_yr_hi = yr + used_band[2] if used_band[2] < 99 else 0
        for c in comps:
            c["_band_sqft_lo"] = band_lo
            c["_band_sqft_hi"] = band_hi
            c["_band_yr_lo"]   = band_yr_lo
            c["_band_yr_hi"]   = band_yr_hi
            c["_pass_num"]     = pass_num
        return comps
    else:
        comps     = []
        used_band = bands[0]
        pass_num  = 1
        for pidx, (lo_mult, hi_mult, age_delta) in enumerate(bands):
            sqft_lo = sqft * lo_mult
            sqft_hi = sqft * hi_mult
            yr_lo   = yr - age_delta
            yr_hi   = yr + age_delta
            size_clause = f"AND CAST(TOT_LIVING_AREA_SF AS REAL) BETWEEN {sqft_lo} AND {sqft_hi}" if lo_mult > 0 else ""
            age_clause  = f"AND CAST(YR_BUILT AS INTEGER) BETWEEN {yr_lo} AND {yr_hi}" if age_delta < 99 else ""
            rows = conn.execute(f"""
                SELECT ACCOUNT_NUM, ADDRESS, PROPERTY_CITY, PROPERTY_ZIPCODE,
                       TOT_VAL, PREV_MKT_VAL, TOT_LIVING_AREA_SF, YR_BUILT,
                       NUM_BEDROOMS, NUM_FULL_BATHS, CDU_RATING_DESC, VAL_PER_SQFT
                FROM comp_view
                WHERE NBHD_CD  = ?
                  AND SPTD_CODE = ?
                  AND VAL_PER_SQFT IS NOT NULL
                  AND ACCOUNT_NUM != ?
                  {size_clause}
                  {age_clause}
                  {new_clause}
                ORDER BY CAST(VAL_PER_SQFT AS REAL) ASC
                LIMIT 50
            """, (subject["NBHD_CD"], subject["SPTD_CODE"],
                  subject["ACCOUNT_NUM"])).fetchall()
            candidates = [row_to_dict(r) for r in rows]
            for c in candidates:
                c_sqft = float(c.get("TOT_LIVING_AREA_SF") or sqft)
                c_yr   = float(c.get("YR_BUILT") or yr)
                c_psf  = float(c.get("VAL_PER_SQFT") or 0)
                size_score = max(0, 1 - abs(c_sqft - sqft) / sqft)
                age_score  = max(0, 1 - abs(c_yr - yr) / max(age_delta, 1))
                psf_gap    = subj_psf - c_psf
                psf_score  = min(1, psf_gap / subj_psf) if subj_psf > 0 else 0
                c["_similarity"] = round(0.25 * size_score + 0.35 * age_score + 0.40 * psf_score, 4)
            comps     = sorted(candidates, key=lambda c: -c["_similarity"])[:15]
            used_band = (lo_mult, hi_mult, age_delta)
            pass_num  = pidx + 1
            if len(comps) >= 15:
                break
        band_lo    = int(sqft * used_band[0]) if used_band[0] > 0 else 0
        band_hi    = int(sqft * used_band[1]) if used_band[1] < 9.0 else 0
        band_yr_lo = yr - used_band[2] if used_band[2] < 99 else 0
        band_yr_hi = yr + used_band[2] if used_band[2] < 99 else 0
        for c in comps:
            c["_band_sqft_lo"] = band_lo
            c["_band_sqft_hi"] = band_hi
            c["_band_yr_lo"]   = band_yr_lo
            c["_band_yr_hi"]   = band_yr_hi
            c["_pass_num"]     = pass_num
        return comps

def compute_stats(subject, comps):
    subj_psf  = float(subject.get("VAL_PER_SQFT") or 0)
    sqft      = float(subject.get("TOT_LIVING_AREA_SF") or 1)
    psfs      = [float(c.get("VAL_PER_SQFT") or 0) for c in comps if c.get("VAL_PER_SQFT")]
    median    = sorted(psfs)[len(psfs) // 2] if psfs else 0
    avg       = round(sum(psfs) / len(psfs), 2) if psfs else 0
    below     = len([p for p in psfs if p < subj_psf])
    rec_val   = round(median * sqft / 1000) * 1000
    sqfts     = [float(c.get("TOT_LIVING_AREA_SF") or 0) for c in comps if c.get("TOT_LIVING_AREA_SF")]
    yrs       = [int(float(c.get("YR_BUILT") or 0)) for c in comps if c.get("YR_BUILT")]
    return {
        "subject_psf":                  subj_psf,
        "median_comp_psf":              round(median, 2),
        "avg_comp_psf":                 avg,
        "comps_below_subject":          below,
        "total_comps":                  len(comps),
        "recommended_opinion_of_value": int(rec_val),
        "potential_reduction":          int(float(subject.get("TOT_VAL") or 0) - rec_val),
        "comp_sqft_min":                int(min(sqfts)) if sqfts else 0,
        "comp_sqft_max":                int(max(sqfts)) if sqfts else 0,
        "comp_yr_min":                  min(yrs) if yrs else 0,
        "comp_yr_max":                  max(yrs) if yrs else 0,
    }

def get_band_desc(comps, sqft_lo, sqft_hi, yr_lo, yr_hi):
    pass_num = comps[0].get("_pass_num", 1) if comps else 1
    if pass_num < 4 and sqft_lo > 0:
        return f"similar size ({sqft_lo:,} to {sqft_hi:,} sq ft), built between {yr_lo} and {yr_hi}"
    else:
        return "same neighborhood and property class (all available comparable properties)"

def get_band_vals(comps, subject):
    if comps:
        return (
            comps[0].get("_band_sqft_lo", 0),
            comps[0].get("_band_sqft_hi", 0),
            comps[0].get("_band_yr_lo", 0),
            comps[0].get("_band_yr_hi", 0),
        )
    sqft = float(subject.get("TOT_LIVING_AREA_SF") or 1500)
    yr   = int(float(subject.get("YR_BUILT") or 1980))
    return int(sqft * 0.75), int(sqft * 1.25), yr - 15, yr + 15

# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "db_exists": DB_PATH.exists()}


@app.get("/api/property")
def property_lookup(address: str = Query(""), zip: str = Query("")):
    address  = address.strip().upper()
    zip_code = zip.strip()
    if not address:
        raise HTTPException(status_code=400, detail="address required")
    parts      = address.split()
    street_num = parts[0]
    street_kw  = parts[1] if len(parts) > 1 else ""
    conn = get_db()
    try:
        params = [street_num]
        zip_clause  = ""
        name_clause = ""
        if zip_code:
            zip_clause = "AND ai.PROPERTY_ZIPCODE LIKE ?"
            params.append(f"{zip_code[:5]}%")
        if street_kw:
            name_clause = "AND ai.FULL_STREET_NAME LIKE ?"
            params.append(f"%{street_kw}%")
        sql = f"""
            SELECT cv.ACCOUNT_NUM, cv.ADDRESS, cv.PROPERTY_CITY, cv.PROPERTY_ZIPCODE,
                   cv.NBHD_CD, cv.SPTD_CODE, cv.TOT_VAL, cv.PREV_MKT_VAL,
                   cv.IMPR_VAL, cv.LAND_VAL, cv.TOT_LIVING_AREA_SF, cv.YR_BUILT,
                   cv.NUM_BEDROOMS, cv.NUM_FULL_BATHS,
                   cv.CDU_RATING_DESC, cv.BLDG_CLASS_DESC, cv.VAL_PER_SQFT
            FROM account_info ai
            JOIN comp_view cv ON ai.ACCOUNT_NUM = cv.ACCOUNT_NUM
            WHERE ai.STREET_NUM = ?
              {zip_clause}
              {name_clause}
            ORDER BY ai.FULL_STREET_NAME
            LIMIT 10
        """
        rows    = conn.execute(sql, params).fetchall()
        results = [row_to_dict(r) for r in rows]
        for p in results:
            prev = float(p.get("PREV_MKT_VAL") or 0)
            curr = float(p.get("TOT_VAL") or 0)
            p["change_pct"] = round((curr - prev) / prev * 100, 1) if prev > 0 else 0
            p["change_amt"] = int(curr - prev)
        return {"count": len(results), "properties": results}
    finally:
        conn.close()



@app.get("/api/comps")
def get_comps(
    account: str = Query(""),
    exclude_new: str = Query("true"),
    supporting_only: str = Query("true"),
    pass_override: str = Query(""),  # Optional: "1", "2", "3", or "4" to lock a specific pass
):

    account         = account.strip()
    exc_new         = exclude_new.lower() != "false"
    sup_only        = supporting_only.lower() != "false"
    pass_lock       = int(pass_override) if pass_override in ("1", "2", "3", "4") else None
    if not account:
        raise HTTPException(status_code=400, detail="account required")
    conn = get_db()
    try:
        subject = get_subject(conn, account)
        if not subject:
            raise HTTPException(status_code=404, detail=f"Account {account} not found")
        comps   = get_comps_data(conn, subject, exc_new, sup_only, pass_lock=pass_lock)
        stats   = compute_stats(subject, comps)
        stats["supporting_only"] = sup_only
        stats["pass_num"]        = comps[0].get("_pass_num", 1) if comps else 1
        stats["search_sqft_lo"]  = comps[0].get("_band_sqft_lo", 0) if comps else 0
        stats["search_sqft_hi"]  = comps[0].get("_band_sqft_hi", 0) if comps else 0
        stats["search_yr_lo"]    = comps[0].get("_band_yr_lo", 0) if comps else 0
        stats["search_yr_hi"]    = comps[0].get("_band_yr_hi", 0) if comps else 0
        return {"subject": subject, "comps": comps, "stats": stats}
    finally:
        conn.close()


@app.get("/api/evidence-html", response_class=HTMLResponse)
def evidence_html(
    account: str = Query(""),
    owner_name: str = Query("Property Owner"),
    opinion_of_value: str = Query(""),
    exclude_new: str = Query("true"),
    supporting_only: str = Query("true"),
):
    account         = account.strip()
    owner_name      = html.escape(owner_name.strip())
    opinion_str     = opinion_of_value.strip()
    exc_new         = exclude_new.lower() != "false"
    sup_only        = supporting_only.lower() != "false"
    if not account:
        raise HTTPException(status_code=400, detail="account required")
    conn = get_db()
    try:
        subject = get_subject(conn, account)
        if not subject:
            raise HTTPException(status_code=404, detail=f"Account {account} not found")
        comps   = get_comps_data(conn, subject, exc_new, sup_only)
        stats   = compute_stats(subject, comps)
        opinion   = int(opinion_str) if opinion_str.isdigit() else stats["recommended_opinion_of_value"]
        reduction = int(float(subject.get("TOT_VAL") or 0)) - opinion
        today     = date.today().strftime("%B %d, %Y")

        sqft_lo, sqft_hi, yr_lo, yr_hi = get_band_vals(comps, subject)
        band_desc = get_band_desc(comps, sqft_lo, sqft_hi, yr_lo, yr_hi)

        rows_html = ""
        for i, c in enumerate(comps, 1):
            psf    = float(c.get("VAL_PER_SQFT") or 0)
            subpsf = float(subject.get("VAL_PER_SQFT") or 0)
            diff   = round((psf - subpsf) / subpsf * 100, 1) if subpsf else 0
            color  = "#16a34a" if psf < subpsf else "#dc2626"
            val    = float(c.get("TOT_VAL") or 0)
            rows_html += (
                f"<tr>"
                f"<td>{i}</td>"
                f"<td>{c.get('ADDRESS','')}</td>"
                f"<td>{c.get('TOT_LIVING_AREA_SF','')}</td>"
                f"<td>{c.get('YR_BUILT','')}</td>"
                f"<td>${val:,.0f}</td>"
                f"<td style='color:{color};font-weight:700'>${psf}</td>"
                f"<td style='color:{color}'>{diff:+.1f}%</td>"
                f"</tr>"
            )

        subj_addr  = subject.get("ADDRESS","")
        subj_city  = subject.get("PROPERTY_CITY","")
        subj_zip   = subject.get("PROPERTY_ZIPCODE","")
        subj_acct  = subject.get("ACCOUNT_NUM","")
        subj_nbhd  = subject.get("NBHD_CD","")
        subj_sptd  = subject.get("SPTD_CODE","")
        subj_val   = float(subject.get("TOT_VAL") or 0)
        subj_prev  = float(subject.get("PREV_MKT_VAL") or 0)
        subj_sf    = subject.get("TOT_LIVING_AREA_SF","")
        subj_yr    = subject.get("YR_BUILT","")
        subj_bed   = subject.get("NUM_BEDROOMS","")
        subj_bath  = subject.get("NUM_FULL_BATHS","")
        subj_cdu   = subject.get("CDU_RATING_DESC","")
        subj_psf_v = subject.get("VAL_PER_SQFT","")
        tot_comps  = stats["total_comps"]
        below      = stats["comps_below_subject"]
        med_psf    = stats["median_comp_psf"]
        subj_psf_f = stats["subject_psf"]
        pass_num   = comps[0].get("_pass_num", 1) if comps else 1
        comp_sqft_min = stats.get("comp_sqft_min", 0)
        comp_sqft_max = stats.get("comp_sqft_max", 0)
        comp_yr_min   = stats.get("comp_yr_min", 0)
        comp_yr_max   = stats.get("comp_yr_max", 0)

        # Pass 4 banner deliberately omitted from evidence package — this is for ARB filing,
        # not internal user guidance. The broadened search note is shown in the app UI only.
        pass4_banner = ""

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Protest Evidence - {subj_addr}</title>
<style>
  body {{ font-family: Georgia, serif; max-width: 900px; margin: 40px auto; padding: 0 20px; color: #1e293b; }}
  h1 {{ font-size: 1.6rem; border-bottom: 3px solid #1e3a5f; padding-bottom: 8px; color: #1e3a5f; }}
  h2 {{ font-size: 1.1rem; margin-top: 2rem; color: #1e3a5f; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 0.9rem; }}
  th {{ background: #1e3a5f; color: white; padding: 8px 10px; text-align: left; }}
  td {{ padding: 7px 10px; border-bottom: 1px solid #e2e8f0; }}
  tr:nth-child(even) td {{ background: #f8fafc; }}
  p {{ line-height: 1.7; margin-top: 0.8rem; }}
</style>
</head>
<body>
<h1>Appraisal Protest Evidence Package</h1>
<p><strong>Prepared:</strong> {today} | <strong>Basis:</strong> Texas Tax Code §41.41(a)(1) & §41.43(b)(3)</p>
<h2>Subject Property</h2>
<table>
  <tr><th>Field</th><th>Value</th></tr>
  <tr><td>Owner</td><td>{owner_name}</td></tr>
  <tr><td>Address</td><td>{subj_addr}, {subj_city} {subj_zip}</td></tr>
  <tr><td>Account Number</td><td>{subj_acct}</td></tr>
  <tr><td>Neighborhood Code</td><td>{subj_nbhd}</td></tr>
  <tr><td>Property Class</td><td>{subj_sptd} — Single Family Residential</td></tr>
  <tr><td>2026 Proposed Value</td><td>${subj_val:,.0f}</td></tr>
  <tr><td>2025 Certified Value</td><td>${subj_prev:,.0f}</td></tr>
  <tr><td>Living Area</td><td>{subj_sf} sq ft</td></tr>
  <tr><td>Year Built</td><td>{subj_yr}</td></tr>
  <tr><td>Bedrooms / Baths</td><td>{subj_bed} / {subj_bath}</td></tr>
  <tr><td>CDU Rating</td><td>{subj_cdu}</td></tr>
  <tr><td>$/sq ft (proposed)</td><td><strong style="color:#d97706">${subj_psf_v}</strong></td></tr>
</table>
<h2>Statistical Summary</h2>
<table>
  <tr><th>Metric</th><th>Value</th></tr>
  <tr><td>Subject $/sq ft</td><td><strong>${subj_psf_f:.2f}</strong></td></tr>
  <tr><td>Median comparable $/sq ft</td><td><strong>${med_psf:.2f}</strong></td></tr>
  <tr><td>Comps assessed below subject</td><td><strong>{below} of {tot_comps}</strong></td></tr>
  <tr><td>Owner Opinion of Value</td><td><strong>${opinion:,.0f}</strong></td></tr>
  <tr><td>Requested Reduction</td><td><strong>${reduction:,.0f}</strong></td></tr>
</table>
<h2>Comparable Properties — PO Ex. 1</h2>
{pass4_banner}
<table>
  <tr>
    <th>#</th><th>Property Address</th><th>Sq Ft</th><th>Yr Built</th>
    <th>2026 Assessed Value</th><th>$/Sq Ft</th><th>vs. Subject</th>
  </tr>
  {rows_html}
</table>
<h2>Argument Narrative</h2>
<p>The subject property at <strong>{subj_addr}</strong> (Account: {subj_acct})
is proposed for assessment at <strong>${subj_val:,.0f}</strong>
({subj_sf} sq ft at ${subj_psf_v}/sq ft) for the 2026 tax year.</p>
<p>Pursuant to Texas Tax Code §41.43(b)(3), the property owner respectfully protests that
this value is unequal to comparable properties in the same neighborhood.
A review of <strong>{tot_comps} comparable single-family residential properties</strong>
in neighborhood code <strong>{subj_nbhd}</strong> — same property class ({subj_sptd}),
with living areas ranging from <strong>{comp_sqft_min:,} to {comp_sqft_max:,} sq ft</strong>
and built between <strong>{comp_yr_min} and {comp_yr_max}</strong> — reveals a median
assessed value of <strong>${med_psf:.2f}/sq ft</strong>,
compared to the subject's proposed <strong>${subj_psf_f:.2f}/sq ft</strong>.</p>
<p><strong>{below} of {tot_comps} comparable properties</strong> are assessed at a lower
dollar-per-square-foot rate than the subject property. This constitutes unequal appraisal
under Texas law. Applying the median comparable rate of ${med_psf:.2f}/sq ft to the
subject's {subj_sf} sq ft yields an equalized value of <strong>${opinion:,.0f}</strong>.
The property owner respectfully requests the ARB reduce the 2026 assessed value to
<strong>${opinion:,.0f}</strong>, a reduction of <strong>${reduction:,.0f}</strong>.</p>
</body>
</html>"""
        return HTMLResponse(content=html_content)
    finally:
        conn.close()


class PDFRequest(BaseModel):
    account: str
    owner_name: str = "Property Owner"
    opinion_of_value: int | str = ""  # Accept int from frontend or str from direct API calls
    exclude_new: bool = True
    supporting_only: bool = True


@app.post("/api/generate-pdf")
def generate_pdf(req: PDFRequest):
    account         = req.account.strip()
    owner_name      = html.escape(req.owner_name.strip())
    opinion_str     = str(req.opinion_of_value).strip()
    exclude_new     = req.exclude_new
    supporting_only = req.supporting_only
    if not account:
        raise HTTPException(status_code=400, detail="account required")
    conn = get_db()
    try:
        from fpdf import FPDF
        subject = get_subject(conn, account)
        if not subject:
            raise HTTPException(status_code=404, detail=f"Account {account} not found")
        comps   = get_comps_data(conn, subject, exclude_new, supporting_only)
        stats   = compute_stats(subject, comps)
        opinion   = int(opinion_str) if opinion_str.isdigit() else stats["recommended_opinion_of_value"]
        reduction = int(float(subject.get("TOT_VAL") or 0)) - opinion
        today     = date.today().strftime("%B %d, %Y")
        pass_num  = comps[0].get("_pass_num", 1) if comps else 1

        sqft_lo, sqft_hi, yr_lo, yr_hi = get_band_vals(comps, subject)
        band_desc = get_band_desc(comps, sqft_lo, sqft_hi, yr_lo, yr_hi)

        subj_val = float(subject.get("TOT_VAL") or 0)
        subj_psf = stats["subject_psf"]
        med_psf  = stats["median_comp_psf"]
        tot_c    = stats["total_comps"]
        below    = stats["comps_below_subject"]

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        pdf.set_font("Helvetica", "B", 18)
        pdf.set_text_color(30, 58, 95)
        pdf.cell(0, 10, "Appraisal Protest Evidence Package", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(100, 116, 139)
        pdf.cell(0, 6, f"Prepared: {today}  |  Texas Tax Code SS41.41(a)(1) & SS41.43(b)(3)", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(30, 58, 95)
        pdf.cell(0, 8, "Subject Property", new_x="LMARGIN", new_y="NEXT")
        fields = [
            ("Owner",            owner_name),
            ("Address",          f"{subject.get('ADDRESS','')} {subject.get('PROPERTY_CITY','')} {subject.get('PROPERTY_ZIPCODE','')}"),
            ("Account Number",   subject.get("ACCOUNT_NUM","")),
            ("Neighborhood",     subject.get("NBHD_CD","")),
            ("2026 Proposed",    f"${subj_val:,.0f}"),
            ("2025 Certified",   f"${float(subject.get('PREV_MKT_VAL') or 0):,.0f}"),
            ("Living Area",      f"{subject.get('TOT_LIVING_AREA_SF','')} sq ft"),
            ("Year Built",       str(subject.get("YR_BUILT",""))),
            ("Beds / Baths",     f"{subject.get('NUM_BEDROOMS','')}/{subject.get('NUM_FULL_BATHS','')}"),
            ("CDU Rating",       str(subject.get("CDU_RATING_DESC",""))),
            ("$/sq ft proposed", f"${subj_psf:.2f}"),
        ]
        pdf.set_text_color(30, 41, 59)
        for label, val in fields:
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(55, 6, label + ":", border=0)
            pdf.set_font("Helvetica", "", 9)
            pdf.cell(0, 6, str(val), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(30, 58, 95)
        pdf.cell(0, 8, "Statistical Summary", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(30, 41, 59)
        comp_sqft_min = stats.get("comp_sqft_min", 0)
        comp_sqft_max = stats.get("comp_sqft_max", 0)
        comp_yr_min   = stats.get("comp_yr_min", 0)
        comp_yr_max   = stats.get("comp_yr_max", 0)
        for line in [
            f"Subject $/sq ft: ${subj_psf:.2f}",
            f"Median comparable $/sq ft: ${med_psf:.2f}",
            f"Comps below subject: {below} of {tot_c}",
            f"Owner Opinion of Value: ${opinion:,.0f}",
            f"Requested reduction: ${reduction:,.0f}",
        ]:
            pdf.cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

        # Pass 4 banner deliberately omitted from PDF evidence — this is for ARB filing,
        # not internal user guidance. The broadened search note is shown in the app UI only.

        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(30, 58, 95)
        pdf.cell(0, 8, "Comparable Properties - PO Ex. 1", new_x="LMARGIN", new_y="NEXT")
        pdf.set_fill_color(30, 58, 95)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 8)
        col_w = [8, 65, 18, 18, 32, 20, 20]
        for i, h in enumerate(["#", "Address", "Sq Ft", "Yr Blt", "2026 Value", "$/Sq Ft", "vs Subj"]):
            pdf.cell(col_w[i], 7, h, border=1, fill=True)
        pdf.ln()
        pdf.set_text_color(30, 41, 59)
        for idx, c in enumerate(comps, 1):
            psf  = float(c.get("VAL_PER_SQFT") or 0)
            diff = round((psf - subj_psf) / subj_psf * 100, 1) if subj_psf else 0
            pdf.set_font("Helvetica", "", 7)
            pdf.set_fill_color(248, 250, 252)
            fill = idx % 2 == 0
            for i, v in enumerate([
                str(idx),
                str(c.get("ADDRESS",""))[:35],
                str(c.get("TOT_LIVING_AREA_SF","")),
                str(c.get("YR_BUILT","")),
                f"${float(c.get('TOT_VAL') or 0):,.0f}",
                f"${psf}",
                f"{diff:+.1f}%",
            ]):
                pdf.cell(col_w[i], 6, v, border=1, fill=fill)
            pdf.ln()
        pdf.ln(4)

        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(30, 58, 95)
        pdf.cell(0, 8, "Argument Narrative", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(30, 41, 59)
        para1 = (
            f"The subject property at {subject.get('ADDRESS','')} "
            f"(Account: {subject.get('ACCOUNT_NUM','')}) is proposed for assessment at "
            f"${subj_val:,.0f} ({subject.get('TOT_LIVING_AREA_SF','')} sq ft at "
            f"${subj_psf:.2f}/sq ft) for the 2026 tax year."
        )
        para2 = (
            f"Pursuant to Texas Tax Code SS41.43(b)(3), the property owner respectfully "
            f"protests that this value is unequal to comparable properties in the same "
            f"neighborhood. A review of {tot_c} comparable single-family residential "
            f"properties in neighborhood code {subject.get('NBHD_CD','')} -- same property "
            f"class ({subject.get('SPTD_CODE','')}), with living areas ranging from "
            f"{comp_sqft_min:,} to {comp_sqft_max:,} sq ft and built between {comp_yr_min} "
            f"and {comp_yr_max} -- reveals a median assessed "
            f"value of ${med_psf:.2f}/sq ft, compared to the subject's proposed ${subj_psf:.2f}/sq ft."
        )
        para3 = (
            f"{below} of {tot_c} comparable properties are assessed at a lower "
            f"dollar-per-square-foot rate than the subject property. This constitutes "
            f"unequal appraisal under Texas law. Applying the median comparable rate of "
            f"${med_psf:.2f}/sq ft to the subject's {subject.get('TOT_LIVING_AREA_SF','')} "
            f"sq ft yields an equalized value of ${opinion:,.0f}. The property owner "
            f"respectfully requests the ARB reduce the 2026 assessed value to "
            f"${opinion:,.0f}, a reduction of ${reduction:,.0f}."
        )
        for para in [para1, para2, para3]:
            pdf.multi_cell(0, 5, para)
            pdf.ln(3)

        buf = io.BytesIO()
        pdf.output(buf)
        buf.seek(0)
        filename = f"protest_evidence_{account[:12]}.pdf"
        return StreamingResponse(
            buf,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    finally:
        conn.close()



@app.get("/api/generate-pdf")
def generate_pdf_get(
    account: str = Query(""),
    owner_name: str = Query("Property Owner"),
    opinion_of_value: str = Query(""),
    exclude_new: str = Query("true"),
    supporting_only: str = Query("true"),
):
    """
    GET version of generate-pdf — accepts query params instead of POST body.
    Enables direct <a href> linking for mobile Safari compatibility.
    Same logic as the POST endpoint.
    """
    req = PDFRequest(
        account=account,
        owner_name=html.escape(owner_name),
        opinion_of_value=opinion_of_value,
        exclude_new=exclude_new.lower() != "false",
        supporting_only=supporting_only.lower() != "false",
    )
    return generate_pdf(req)

if __name__ == "__main__":
    import uvicorn
    if not DB_PATH.exists():
        import sys
        print(f"ERROR: DB not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)
    print(f"Starting Dallas Protest Helper API on http://localhost:8000")
    print(f"Database: {DB_PATH}")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)

