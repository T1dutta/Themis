import { useState, useRef } from 'react'
import axios from 'axios'
import Papa from 'papaparse'
import './App.css'

/* ─── helpers ─────────────────────────────────────────────────────────── */
function getSeverity(score) {
  if (score >= 0.2) return 'critical'
  if (score >= 0.1) return 'warning'
  return 'pass'
}

function BadgeFor({ severity }) {
  const labels = { critical: 'CRITICAL', warning: 'WARNING', pass: 'PASS' }
  return <span className={`badge badge-${severity}`}>{labels[severity]}</span>
}

function OverallBadge({ metrics }) {
  if (!metrics || metrics.length === 0) return null
  const worst = metrics.reduce((a, b) => {
    const rank = { critical: 2, warning: 1, pass: 0 }
    return rank[getSeverity(b.score)] > rank[getSeverity(a.score)] ? b : a
  })
  const sev = getSeverity(worst.score)
  return <BadgeFor severity={sev} />
}

/* ─── App ─────────────────────────────────────────────────────────────── */
export default function App() {
  const [file, setFile]                         = useState(null)
  const [columns, setColumns]                   = useState([])
  const [selectedProtectedCols, setSelectedProtectedCols] = useState([])
  const [selectedOutcomeCol, setSelectedOutcomeCol]       = useState('')
  const [loading, setLoading]                   = useState(false)
  const [results, setResults]                   = useState(null)
  const [explanation, setExplanation]           = useState('')
  const [explainError, setExplainError]         = useState('')
  const [error, setError]                       = useState('')
  const [dragging, setDragging]                 = useState(false)
  const [timestamp, setTimestamp]               = useState('')
  const [totalRows, setTotalRows]               = useState(null)

  const fileInputRef = useRef(null)

  /* ─── file handling ─────────────────────────────────────────────────── */
  function processFile(f) {
    if (!f) return
    setFile(f)
    setColumns([])
    setSelectedProtectedCols([])
    setSelectedOutcomeCol('')
    setResults(null)
    setExplanation('')
    setExplainError('')
    setError('')
    setTotalRows(null)

    Papa.parse(f, {
      header: true,
      preview: 2,
      complete: (r) => {
        const fields = r.meta.fields || []
        setColumns(fields)
      }
    })

    // count rows separately
    Papa.parse(f, {
      header: true,
      complete: (r) => {
        setTotalRows(r.data.length)
      }
    })
  }

  function handleDrop(e) {
    e.preventDefault()
    setDragging(false)
    const f = e.dataTransfer.files[0]
    if (f && f.name.endsWith('.csv')) processFile(f)
    else setError('Please drop a valid .csv file.')
  }

  function handleDragOver(e) { e.preventDefault(); setDragging(true) }
  function handleDragLeave()  { setDragging(false) }

  function handleFileChange(e) {
    const f = e.target.files[0]
    if (f) processFile(f)
  }

  /* ─── checkbox toggle ───────────────────────────────────────────────── */
  function toggleProtected(col) {
    setSelectedProtectedCols(prev =>
      prev.includes(col) ? prev.filter(c => c !== col) : [...prev, col]
    )
  }

  /* ─── analyse ───────────────────────────────────────────────────────── */
  async function handleAnalyse() {
    setLoading(true)
    setError('')
    setResults(null)
    setExplanation('')
    setExplainError('')

    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('protected_cols', selectedProtectedCols.join(','))
      formData.append('outcome_col', selectedOutcomeCol)

      const response = await axios.post('https://us-central1-themis-179.cloudfunctions.net/analyse', formData)

      if (response.data.error) {
        setError(response.data.error)
        setLoading(false)
        return
      }

      setResults(response.data.metrics)
      setTimestamp(new Date().toLocaleString('en-IN', {
        dateStyle: 'medium', timeStyle: 'short'
      }))

      try {
        const explainRes = await axios.post(
          'https://us-central1-themis-179.cloudfunctions.net/explain',
          { metrics: response.data.metrics },
          { headers: { 'Content-Type': 'application/json' } }
        )
        if (explainRes.data.error) {
          setExplainError(explainRes.data.error)
        } else {
          setExplanation(explainRes.data.explanation || '')
        }
      } catch (explainErr) {
        const msg = explainErr.response?.data?.error || ''
        setExplainError(
          msg || 'AI explanation temporarily unavailable. Your bias metrics above are accurate.'
        )
      }
    } catch (err) {
      setError('Analysis failed. Please check your CSV has the selected columns.')
    } finally {
      setLoading(false)
    }
  }

  const canAnalyse =
    file &&
    selectedProtectedCols.length > 0 &&
    selectedOutcomeCol !== '' &&
    !loading

  /* ─── render ────────────────────────────────────────────────────────── */
  return (
    <>
      {/* ── NAVBAR ─────────────────────────────────────────────────── */}
      <nav className="navbar">
        <div className="navbar-logo">
          <span>⚖</span>Themis
        </div>
        <div className="navbar-sub">AI Bias Detection Platform</div>
      </nav>

      <div className="app-wrapper">

        {/* ── HERO ─────────────────────────────────────────────────── */}
        <section className="hero">
          <div className="hero-label">v1.0 &nbsp;·&nbsp; Fairness Engine</div>
          <h1>Detect <em>Bias</em> in Your<br />AI Systems</h1>
          <p className="hero-sub">
            Upload any dataset and Themis will automatically detect
            discrimination patterns across gender, race, age and more.
          </p>
          <div className="hero-stats">
            <div className="stat-box">
              <span className="stat-val">&lt; 30s</span>
              <span className="stat-label">Analysis Time</span>
            </div>
            <div className="stat-box">
              <span className="stat-val">Real Stats</span>
              <span className="stat-label">Not guesswork</span>
            </div>
          </div>
        </section>

        <div className="section-divider" />

        {/* ── UPLOAD ───────────────────────────────────────────────── */}
        <div className="card">
          <div className="card-title">
            <span className="dot" />
            Upload Dataset
          </div>
          <div className="card-subtitle">Accepts .csv files — headers auto-detected</div>

          <div
            className={`upload-zone${dragging ? ' drag-over' : ''}`}
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onClick={() => fileInputRef.current.click()}
          >
            <span className="upload-icon">⬆</span>
            <p><strong>Click to browse</strong> or drag & drop your CSV</p>
            <p className="upload-hint">Maximum file size: 50 MB</p>
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv"
              onChange={handleFileChange}
            />
          </div>

          {file && (
            <div className="file-selected">
              <span className="check">✔</span>
              <div>
                <div className="file-name-label">File loaded</div>
                <div className="file-name">{file.name}</div>
              </div>
            </div>
          )}
        </div>

        {/* ── COLUMN SELECTION ─────────────────────────────────────── */}
        {columns.length > 0 && (
          <div className="card">
            <div className="card-title">
              <span className="dot" />
              Select Columns to Analyse
            </div>
            <div className="card-subtitle">Protected attributes (select all that apply):</div>

            <div className="checkbox-grid">
              {columns.map(col => (
                <label
                  key={col}
                  className={`checkbox-item${selectedProtectedCols.includes(col) ? ' checked' : ''}`}
                >
                  <input
                    type="checkbox"
                    checked={selectedProtectedCols.includes(col)}
                    onChange={() => toggleProtected(col)}
                  />
                  <span className="checkbox-label" title={col}>{col}</span>
                </label>
              ))}
            </div>

            <div className="select-group">
              <span className="select-label">Outcome column (what is being decided?)</span>
              <div className="select-wrapper">
                <select
                  value={selectedOutcomeCol}
                  onChange={e => setSelectedOutcomeCol(e.target.value)}
                >
                  <option value="">— select outcome column —</option>
                  {columns.map(col => (
                    <option key={col} value={col}>{col}</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="tip-box">
              <strong>Tip:</strong> Select <strong>gender</strong>, <strong>race</strong>,{' '}
              <strong>age</strong> as protected attributes. Select{' '}
              <strong>decision</strong> or <strong>outcome</strong> as the outcome column.
            </div>
          </div>
        )}

        {/* ── ANALYSE BUTTON ───────────────────────────────────────── */}
        {file && (
          <>
            <button
              className="btn-analyse"
              onClick={handleAnalyse}
              disabled={!canAnalyse}
            >
              {loading ? (
                <>
                  <span className="spinner" />
                  Analysing…
                </>
              ) : (
                <>⚖ Analyse for Bias</>
              )}
            </button>

            {loading && (
              <div className="loading-state">
                <div className="loading-text">Processing dataset — this may take a moment</div>
              </div>
            )}

            {error && (
              <div className="error-box">
                <span>⚠</span>
                <span>{error}</span>
              </div>
            )}
          </>
        )}

        {/* ── RESULTS ──────────────────────────────────────────────── */}
        {results && (
          <div className="results-section">
            <div className="card" style={{ marginBottom: 12 }}>
              <div className="results-header">
                <div className="results-title">Bias Analysis Report</div>
                {timestamp && <div className="results-timestamp">{timestamp}</div>}
              </div>

              <div className="summary-row">
                <div className="summary-pill">
                  <span className="val">{results.length}</span>
                  <span className="lbl">Attributes Analysed</span>
                </div>
                {totalRows != null && (
                  <div className="summary-pill">
                    <span className="val">{totalRows.toLocaleString()}</span>
                    <span className="lbl">Total Rows</span>
                  </div>
                )}
                <div className="summary-pill" style={{ gap: 10 }}>
                  <span className="lbl">Overall Severity</span>
                  <OverallBadge metrics={results} />
                </div>
              </div>
            </div>

            {/* ── METRIC CARDS ─────────────────────────────────────── */}
            <div className="metric-grid">
              {results.map((m, i) => {
                const sev = getSeverity(m.score)
                const rates = m.approval_rates || {}
                const groups = Object.entries(rates)
                const maxRate = Math.max(...groups.map(([, v]) => v), 0.001)

                return (
                  <div key={i} className={`metric-card ${sev}`}>
                    <div className="metric-attr">{m.attribute}</div>
                    <div className="metric-name">{m.metric_name || 'Disparate Impact'}</div>

                    <div className="metric-badge-row">
                      <BadgeFor severity={sev} />
                    </div>

                    {groups.length > 0 && (
                      <div className="approval-rates">
                        {groups.map(([grp, rate]) => (
                          <div key={grp} className="rate-row">
                            <div className="rate-label" title={grp}>{grp}</div>
                            <div className="rate-bar-track">
                              <div
                                className="rate-bar-fill"
                                style={{ width: `${Math.min((rate / maxRate) * 100, 100)}%` }}
                              />
                            </div>
                            <div className="rate-pct">
                              {(typeof rate === 'number' ? (rate * 100).toFixed(1) : rate)}%
                            </div>
                          </div>
                        ))}
                      </div>
                    )}

                    <div className="bias-score-row">
                      <div className="bias-score-label">Bias Score</div>
                      <div className="bias-score-track">
                        <div
                          className={`bias-score-fill ${sev}`}
                          style={{ width: `${Math.min(m.score * 100, 100)}%` }}
                        />
                      </div>
                      <div className="bias-score-val">{m.score?.toFixed(3)}</div>
                    </div>
                  </div>
                )
              })}
            </div>

            {/* ── AI EXPLANATION ───────────────────────────────────── */}
            {explanation && (
              <div className="explanation-section">
                <div className="explanation-header">
                  <span className="explanation-header-icon">◈</span>
                  <div className="explanation-title">AI Explanation</div>
                  <div className="explanation-badge">Gemini powered</div>
                </div>
                <div className="explanation-body">{explanation}</div>
              </div>
            )}

            {explainError && !explanation && (
              <div className="explain-quota-notice">
                <span className="explain-quota-icon">⚠</span>
                <div>
                  <strong>AI Explanation Unavailable</strong>
                  <p>{explainError}</p>
                </div>
              </div>
            )}
          </div>
        )}

      </div>
    </>
  )
}
