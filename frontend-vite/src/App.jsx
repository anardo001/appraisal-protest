
/**
 * App.jsx — Dallas Appraisal Protest Helper
 *
 * 4-step wizard:
 *   Step 1: SearchScreen     — address lookup against DCAD SQLite (860K+ records)
 *   Step 2: CompsScreen      — comparable properties with progressive widening engine
 *   Step 3: EvidenceScreen   — inline HTML protest evidence preview
 *   Step 4: SubmitScreen     — PDF download + uFILE filing instructions
 *
 * API base is configured via VITE_API_URL env variable (falls back to localhost:8000).
 * Backend: FastAPI (main.py) served by Uvicorn on port 8000.
 *
 * @agent: For architecture overview see AGENTS.md at repo root.
 */
import { useState, useEffect, useCallback } from "react";

// API base URL — override via VITE_API_URL env var for production deployments.
// In dev: http://localhost:8000 (FastAPI/Uvicorn)
// In prod: set VITE_API_URL to the Render backend service URL
const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

const DISCLAIMER =
  "This tool is for informational and demonstration purposes only. It does not constitute legal, tax, or appraisal advice. Consult a licensed property tax professional before filing a protest.";

// ── Utility formatters ────────────────────────────────────────────────────────

/** Format a number as a USD dollar string, or "-" if null/undefined. */
const fmt = (n) => (n != null ? "$" + Number(n).toLocaleString() : "-");

/** Format a number with locale separators, or "-" if null/undefined. */
const fmtN = (n) => (n != null ? Number(n).toLocaleString() : "-");

// ── StepNav ───────────────────────────────────────────────────────────────────

/**
 * Step navigation bar. Active step is highlighted; completed steps are
 * clickable to allow backward navigation only (no skipping forward).
 */
function StepNav({ currentStep, onGoTo }) {
  const labels = ["Find Property", "Review Comps", "Evidence", "Submit"];
  return (
    <nav className="steps">
      {labels.map((label, i) => {
        const stepNum = i + 1;
        const isActive = stepNum === currentStep;
        const isClickable = stepNum < currentStep;
        return (
          <div
            key={stepNum}
            className={`step ${isActive ? "active" : ""} ${stepNum < currentStep ? "done" : ""}`}
            onClick={() => isClickable && onGoTo(stepNum)}
            style={{ cursor: isClickable ? "pointer" : "default" }}
          >
            {stepNum}. {label}
          </div>
        );
      })}
    </nav>
  );
}

// ── Step 1: SearchScreen ──────────────────────────────────────────────────────

/**
 * Step 1: Address search.
 * Calls GET /api/property?address=...&zip=...
 * Displays matching properties; user clicks one to proceed to comps.
 */
function SearchScreen({ onSelect }) {
  const [address, setAddress] = useState("");
  const [zip, setZip] = useState("");
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState(null);
  const [error, setError] = useState("");

  const runSearch = async () => {
    if (!address.trim()) return;
    setLoading(true);
    setError("");
    setResults(null);
    try {
      const url = `${API}/api/property?address=${encodeURIComponent(address.trim())}&zip=${encodeURIComponent(zip)}`;
      const res = await fetch(url);
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail || json.error || "Search failed");
      setResults(json);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div className="card">
        <div className="card-title">Find Your Property</div>
        <div className="search-wrap">
          <div className="input-group">
            <label>Street Address</label>
            <input
              type="text"
              placeholder="e.g. 123 Oak St"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runSearch()}
            />
          </div>
          <div className="input-group" style={{ maxWidth: 140 }}>
            <label>ZIP Code</label>
            <input
              type="text"
              placeholder="e.g. 75225"
              value={zip}
              maxLength={5}
              onChange={(e) => setZip(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runSearch()}
            />
          </div>
          <div style={{ paddingTop: 20 }}>
            <button className="btn btn-primary" onClick={runSearch} disabled={loading || !address.trim()}>
              {loading ? "Searching..." : "Search"}
            </button>
          </div>
        </div>
      </div>

      {loading && (
        <div className="loading">
          <div className="spinner" />
          Looking up your property...
        </div>
      )}

      {error && <div className="error-msg">{error}</div>}

      {results && results.count === 0 && (
        <div className="card">
          <p style={{ color: "var(--muted)" }}>No properties found. Try simpler address text.</p>
        </div>
      )}

      {results &&
        results.properties &&
        results.properties.map((p) => (
          <div key={p.ACCOUNT_NUM} className="prop-card" onClick={() => onSelect(p)}>
            <div className="prop-card-addr">
              {p.ADDRESS}, {p.PROPERTY_CITY} {p.PROPERTY_ZIPCODE}
            </div>
            <div className="prop-card-meta">
              Account: {p.ACCOUNT_NUM} · 2026 Value: {fmt(p.TOT_VAL)} · {p.TOT_LIVING_AREA_SF} sq ft · Built {p.YR_BUILT}
            </div>
          </div>
        ))}

      <div className="disclaimer">{DISCLAIMER}</div>
    </div>
  );
}

// ── Step 2: CompsScreen ───────────────────────────────────────────────────────

/**
 * Step 2: Comparable properties.
 * Calls GET /api/comps?account=...&exclude_new=...&supporting_only=true
 *
 * The comp engine uses progressive widening (4 passes) with similarity scoring:
 *   PSF gap 40%, age 35%, size 25%
 *
 * Pass 4 fallback: shows all comps in neighborhood below subject $/sqft.
 */
function CompsScreen({ property, onBack, onNext }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [data, setData] = useState(null);
  const [excludeNew, setExcludeNew] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const url = `${API}/api/comps?account=${property.ACCOUNT_NUM}&exclude_new=${excludeNew}&supporting_only=true`;
      const res = await fetch(url);
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail || json.error || "Failed loading comps");
      setData(json);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [property.ACCOUNT_NUM, excludeNew]);

  useEffect(() => {
    load();
  }, [load]);

  const subjectPsf = Number(property.VAL_PER_SQFT || 0);

  return (
    <div>
      <div className="card">
        <div className="card-title">Your Property</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px 24px", fontSize: "0.88rem" }}>
          <div>
            <span style={{ color: "var(--muted)", fontSize: "0.75rem" }}>ADDRESS</span>
            <div style={{ fontWeight: 600 }}>{property.ADDRESS}, {property.PROPERTY_CITY}</div>
          </div>
          <div>
            <span style={{ color: "var(--muted)", fontSize: "0.75rem" }}>ACCOUNT</span>
            <div>{property.ACCOUNT_NUM}</div>
          </div>
          <div>
            <span style={{ color: "var(--muted)", fontSize: "0.75rem" }}>2026 PROPOSED VALUE</span>
            <div style={{ fontWeight: 700, color: "var(--navy)", fontSize: "1.05rem" }}>{fmt(property.TOT_VAL)}</div>
          </div>
          <div>
            <span style={{ color: "var(--muted)", fontSize: "0.75rem" }}>2025 CERTIFIED VALUE</span>
            <div>{fmt(property.PREV_MKT_VAL)}</div>
          </div>
        </div>
      </div>

      {loading && (
        <div className="loading">
          <div className="spinner" />
          Finding comparable properties...
        </div>
      )}
      {error && <div className="error-msg">{error}</div>}

      {data && (
        <div>
          {data.stats && data.stats.pass_num === 4 && (
            <div style={{ background: "#f0f9ff", border: "1px solid #bae6fd", borderRadius: 8, padding: "12px 16px", marginBottom: 14, fontSize: "0.82rem", color: "#0369a1" }}>
              <strong>Note:</strong> All comparable properties assessed below your $/sq ft in this neighborhood are shown.
              Only {data.stats.total_comps} qualifying propert{data.stats.total_comps === 1 ? "y was" : "ies were"} found — this strengthens your argument that your assessment is above the neighborhood norm.
            </div>
          )}

          <div className="stats-bar">
            <div className="stat-pill">
              <div className="val amber">${(data.stats.subject_psf || 0).toFixed(2)}</div>
              <div className="lbl">Your $/sq ft</div>
            </div>
            <div className="stat-pill">
              <div className="val">${(data.stats.median_comp_psf || 0).toFixed(2)}</div>
              <div className="lbl">Median comp $/sq ft</div>
            </div>
            <div className="stat-pill">
              <div className="val green">{data.stats.comps_below_subject}/{data.stats.total_comps}</div>
              <div className="lbl">Comps below you</div>
            </div>
            <div className="stat-pill">
              <div className="val amber">{fmt(data.stats.recommended_opinion_of_value)}</div>
              <div className="lbl">Suggested Opinion of Value</div>
            </div>
            <div className="stat-pill">
              <div className="val green">{fmt(data.stats.potential_reduction)}</div>
              <div className="lbl">Potential reduction</div>
            </div>
          </div>

          <div className="card">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10, marginBottom: 12 }}>
              <div className="card-title" style={{ marginBottom: 0, borderBottom: "none", paddingBottom: 0 }}>
                Comparable Properties
              </div>
              <label className="toggle-wrap">
                Exclude new construction
                <label className="toggle">
                  <input type="checkbox" checked={excludeNew} onChange={(e) => setExcludeNew(e.target.checked)} />
                  <span className="toggle-slider" />
                </label>
              </label>
            </div>

            {data.stats && (
              <div style={{ background: "#f1f5f9", border: "1px solid #e2e8f0", borderRadius: 8, padding: "10px 14px", marginBottom: 14, fontSize: "0.82rem", color: "#475569" }}>
                <strong>How comps were selected:</strong>{" "}
                Same neighborhood ({property.NBHD_CD || data.comps[0]?.NBHD_CD || "—"}) and property class ({property.SPTD_CODE || data.comps[0]?.SPTD_CODE || "—"}).{" "}
                {data.stats.pass_num < 4 && data.stats.search_sqft_lo > 0
                  ? `Search range: ${fmtN(data.stats.search_sqft_lo)}–${fmtN(data.stats.search_sqft_hi)} sq ft · Built ${data.stats.search_yr_lo}–${data.stats.search_yr_hi} (Pass ${data.stats.pass_num} of 4).`
                  : "Full neighborhood search (Pass 4)."}
                {" "}Showing homes assessed below your $/sq ft, ranked by similarity: PSF gap (40%), age (35%), size (25%).
              </div>
            )}

            <table className="comps-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Address</th>
                  <th>Sq Ft</th>
                  <th>Yr Built</th>
                  <th>CDU</th>
                  <th>2026 Value</th>
                  <th>$/Sq Ft</th>
                  <th>vs You</th>
                </tr>
              </thead>
              <tbody>
                {data.comps.map((c, i) => {
                  const psf = Number(c.VAL_PER_SQFT || 0);
                  const diff = subjectPsf > 0 ? (((psf - subjectPsf) / subjectPsf) * 100).toFixed(1) : "0.0";
                  const cls = psf < subjectPsf ? "td-green" : "td-red";
                  return (
                    <tr key={c.ACCOUNT_NUM}>
                      <td>{i + 1}</td>
                      <td>{c.ADDRESS}</td>
                      <td className="td-mono">{fmtN(c.TOT_LIVING_AREA_SF)}</td>
                      <td className="td-mono">{c.YR_BUILT}</td>
                      <td className="td-mono">{c.CDU_RATING_DESC || "—"}</td>
                      <td className="td-mono">{fmt(c.TOT_VAL)}</td>
                      <td className={`td-mono ${cls}`}>${psf}</td>
                      <td className={cls}>{diff > 0 ? "+" : ""}{diff}%</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="action-row">
            <button className="btn btn-outline" onClick={onBack}>Back</button>
            <button className="btn btn-primary" onClick={() => onNext(data, excludeNew)}>
              Build My Protest Package
            </button>
          </div>
        </div>
      )}

      <div className="disclaimer">{DISCLAIMER}</div>
    </div>
  );
}

// ── Step 3: EvidenceScreen ────────────────────────────────────────────────────

/**
 * Step 3: Evidence preview.
 * Fetches GET /api/evidence-html and renders inline (no iframe).
 * Debounced 300ms on input changes to avoid spamming the API.
 * Strips the embedded <style> block from the response to avoid CSS conflicts.
 */
function EvidenceScreen({ property, compsData, onBack, onNext, excludeNew: initExclude }) {
  const [ownerName, setOwnerName] = useState("");
  const [opinion, setOpinion] = useState(String(compsData?.stats?.recommended_opinion_of_value || ""));

  // excludeNew is locked to the value set in CompsScreen — not changeable in Step 3
  const excludeNew = initExclude ?? true;
  const [htmlLoading, setHtmlLoading] = useState(false);
  const [evidenceHtml, setEvidenceHtml] = useState("");

  const fetchEvidence = useCallback(async () => {
    setHtmlLoading(true);
    try {
      const url =
        `${API}/api/evidence-html?account=${property.ACCOUNT_NUM}` +
        `&owner_name=${encodeURIComponent(ownerName || "Property Owner")}` +
        `&opinion_of_value=${opinion}` +
        `&exclude_new=${excludeNew}` +
        `&supporting_only=true`;
      const res = await fetch(url);
      const html = await res.text();
      // Extract <body> content only; strip embedded <style> to avoid CSS conflicts with our app styles
      const bodyMatch = html.match(/<body[^>]*>([\s\S]*)<\/body>/i);
      const bodyContent = bodyMatch ? bodyMatch[1] : html;
      const stripped = bodyContent.replace(/<style[\s\S]*?<\/style>/gi, "");
      setEvidenceHtml(stripped);
    } catch (e) {
      setEvidenceHtml("<p>Error loading evidence preview.</p>");
    } finally {
      setHtmlLoading(false);
    }
  }, [property.ACCOUNT_NUM, ownerName, opinion, excludeNew]);

  // Debounce: re-fetch 300ms after any input change
  useEffect(() => {
    const timer = setTimeout(fetchEvidence, 300);
    return () => clearTimeout(timer);
  }, [fetchEvidence]);

  return (
    <div>
      <div className="card">
        <div className="card-title">Step 3: Evidence Preview</div>
        <div className="search-wrap">
          <div className="input-group">
            <label>Your Name <span style={{ color: "#dc2626" }}>*</span></label>
            <input value={ownerName} onChange={(e) => setOwnerName(e.target.value)} placeholder="e.g. John Smith" />
            <span style={{ fontSize: "0.72rem", color: "#64748b", marginTop: 3 }}>Required to continue to Step 4.</span>
          </div>
          <div className="input-group" style={{ maxWidth: 220 }}>
            <label>Opinion of Value ($)</label>
            <input type="number" value={opinion} onChange={(e) => setOpinion(e.target.value)} />
            <span style={{ fontSize: "0.72rem", color: "#64748b", marginTop: 3 }}>Auto-calculated from comp median. Adjust if needed.</span>
          </div>
        </div>

      </div>

      {htmlLoading && <div className="loading"><div className="spinner" />Loading evidence preview...</div>}
      {evidenceHtml && (
        <div className="card evidence-inline" dangerouslySetInnerHTML={{ __html: evidenceHtml }} />
      )}
      <div className="action-row">
        <button className="btn btn-outline" onClick={onBack}>Back</button>
        <button
          className="btn btn-primary"
          onClick={() => onNext({ ownerName, opinion, excludeNew })}
          disabled={!ownerName.trim()}
          title={!ownerName.trim() ? "Please enter your name above to continue" : ""}
        >
          Continue to Submit
        </button>
        {!ownerName.trim() && (
          <p style={{ fontSize: "0.75rem", color: "#d97706", marginTop: 6, textAlign: "right" }}>
            ⚠ Please enter your name to continue.
          </p>
        )}
      </div>

      <div className="disclaimer">{DISCLAIMER}</div>
    </div>
  );
}

// ── Step 4: SubmitScreen ──────────────────────────────────────────────────────

/**
 * Step 4: Review & submit.
 * - PDF download: POST /api/generate-pdf (fpdf2 backend)
 * - HTML preview: direct link to /api/evidence-html (opens new window)
 * - uFILE filing instructions with deep link to DCAD portal
 * - Settlement offer notice
 * - Filing deadline and mailing address
 */
function SubmitScreen({ property, compsData, ownerName, opinion, excludeNew, onBack }) {
  const [pdfLoading, setPdfLoading] = useState(false);
  const ufileUrl = `https://ufile.dallascad.org/?ID=${property.ACCOUNT_NUM}`;
  const opinionVal = parseInt(opinion) || compsData?.stats?.recommended_opinion_of_value || 0;

  const previewUrl =
    `${API}/api/evidence-html?account=${property.ACCOUNT_NUM}` +
    `&owner_name=${encodeURIComponent(ownerName || "Property Owner")}` +
    `&opinion_of_value=${opinionVal}` +
    `&exclude_new=${excludeNew}` +
    `&supporting_only=true`;

  const downloadPdf = async () => {
    setPdfLoading(true);
    try {
      const res = await fetch(`${API}/api/generate-pdf`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          account: property.ACCOUNT_NUM,
          owner_name: ownerName || "Property Owner",
          opinion_of_value: opinionVal,
          exclude_new: excludeNew,
          supporting_only: true,
        }),
      });
      if (!res.ok) throw new Error("PDF generation failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `protest_evidence_${property.ACCOUNT_NUM.slice(0, 12)}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      alert(e.message);
    } finally {
      setPdfLoading(false);
    }
  };

  return (
    <div>
      <div className="card">
        <div className="card-title">Step 4: Review & Submit</div>

        <div style={{ textAlign: "center", padding: "20px 0 12px" }}>
          <button className="btn btn-amber" onClick={downloadPdf} disabled={pdfLoading} style={{ fontSize: "1rem", padding: "12px 32px" }}>
            {pdfLoading ? "Generating PDF..." : "⬇ Download Evidence PDF"}
          </button>
          <div style={{ marginTop: 10 }}>
            <a href={previewUrl} target="_blank" rel="noreferrer" style={{ color: "#64748b", fontSize: "0.8rem" }}>
              View evidence as HTML (opens in new window)
            </a>
          </div>
        </div>

        <hr style={{ margin: "20px 0", borderColor: "#e2e8f0" }} />

        <h3 style={{ fontSize: "1rem", color: "var(--navy)", marginBottom: 12 }}>How to File Your Protest on uFILE</h3>
        <ol style={{ lineHeight: 2.1, paddingLeft: 20, fontSize: "0.9rem" }}>
          <li>
            Open the uFILE portal:{" "}
            <a href={ufileUrl} target="_blank" rel="noreferrer" style={{ fontWeight: 600 }}>{ufileUrl}</a>
            <div style={{ fontSize: "0.8rem", color: "#64748b" }}>Your PIN is printed at the top of your mailed Notice of Appraised Value.</div>
          </li>
          <li>Check: <strong>“Value is over market value”</strong></li>
          <li>Enter your Opinion of Value: <strong>{fmt(opinionVal)}</strong></li>
          <li>Upload the PDF evidence package — document type: <strong>OTHER</strong> — max 8 MB per file.</li>
          <li>Enter your <strong>email</strong> (required), confirm email, <strong>name</strong> (required), and phone, then submit.</li>
        </ol>

        <div style={{ background: "#fefce8", border: "1px solid #fde68a", borderRadius: 6, padding: "12px 16px", marginTop: 16, fontSize: "0.85rem", color: "#92400e" }}>
          <strong>Settlement Offer Pop-up:</strong> After uploading evidence, uFILE may display a settlement offer pop-up. You can accept the offer, decline it, or ignore it and proceed to a formal ARB hearing. The choice is entirely yours.
        </div>

        <p style={{ fontSize: "0.78rem", color: "#64748b", marginTop: 16 }}>
          <strong>Deadline: May 15, 2026.</strong> If you have difficulty uploading, mail your protest and documents to:<br />
          Appraisal Review Board, P O Box 560348, Dallas TX 75356-0348 (postmarked by May 15, 2026).
        </p>
      </div>

      <div className="action-row">
        <button className="btn btn-outline" onClick={onBack}>Back</button>
      </div>

      <div className="disclaimer">{DISCLAIMER}</div>
    </div>
  );
}

// ── Root App component ────────────────────────────────────────────────────────

/**
 * Root App component — manages wizard step state and passes data between screens.
 * Step flow: 1 (Search) → 2 (Comps) → 3 (Evidence) → 4 (Submit)
 * Back navigation is always available; forward navigation requires completing each step.
 */
export default function App() {
  const [step, setStep] = useState(1);
  const [property, setProperty] = useState(null);
  const [compsData, setCompsData] = useState(null);
  const [excludeNew, setExcludeNew] = useState(true);
  const [evidenceParams, setEvidenceParams] = useState(null);

  const onSelectProperty = (p) => {
    setProperty(p);
    setStep(2);
  };

  const onNextToEvidence = (data, excl) => {
    setCompsData(data);
    if (excl !== undefined) setExcludeNew(excl);
    setStep(3);
  };

  const onNextToSubmit = (params) => {
    setEvidenceParams(params);
    setStep(4);
  };

  const goToStep = (n) => {
    if (n < step) setStep(n);
  };

  return (
    <div>

      {/* Demo strip — Second Wind Foundry callout */}
      <div className="demo-strip">
        <span className="demo-strip-label">DEMO APPLICATION</span>
        <span className="demo-strip-divider">·</span>
        <span>Conceived, Built & Deployed with </span>
        <a
          href="https://www.crimsontreesoftware.com/tour"
          target="_blank"
          rel="noreferrer"
          className="demo-strip-link"
        >
          Second Wind Foundry ↗
        </a>
      </div>

      <header className="app-header">
        <div className="app-header-main">
          <h1>Dallas Appraisal Protest Helper</h1>
          <p className="app-header-sub">2026 Tax Year</p>
        </div>
        <div className="app-header-about">
          <a href="#about" className="about-link" onClick={(e) => e.preventDefault()}>
            About This Demo
          </a>
        </div>
      </header>

      <StepNav currentStep={step} onGoTo={goToStep} />

      <main className="main">
        {step === 1 && <SearchScreen onSelect={onSelectProperty} />}
        {step === 2 && property && (
          <CompsScreen property={property} onBack={() => setStep(1)} onNext={onNextToEvidence} />
        )}
        {step === 3 && property && compsData && (
          <EvidenceScreen
            property={property}
            compsData={compsData}
            onBack={() => setStep(2)}
            onNext={onNextToSubmit}
            excludeNew={excludeNew}
          />
        )}
        {step === 4 && property && compsData && evidenceParams && (
          <SubmitScreen
            property={property}
            compsData={compsData}
            ownerName={evidenceParams.ownerName}
            opinion={evidenceParams.opinion}
            excludeNew={evidenceParams.excludeNew}
            onBack={() => setStep(3)}
          />
        )}
      </main>

      <footer className="app-footer">
        Dallas Appraisal Protest Helper · Demo Tool · Not affiliated with DCAD ·{" "}
        <a href="https://www.dallascad.org" target="_blank" rel="noreferrer">dallascad.org</a>
      </footer>
    </div>
  );
}
