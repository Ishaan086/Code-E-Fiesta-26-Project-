import React from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity, AlertTriangle, ArrowDownRight, ArrowRight, BadgeCheck, BrainCircuit,
  Check, CheckCircle2, ChevronRight, CircleDot, Clock3, Database, FileCheck2,
  GitBranch, History, Layers3, Play, RefreshCw, ShieldCheck, Sparkles,
  Workflow, X, Zap, BarChart3, PanelTop, Users,
} from "lucide-react";
import { api } from "./api/client.js";
const failureOptions = [
  { value: "schema_drift", label: "Schema drift", detail: "phone → phone_number", icon: GitBranch },
  { value: "bad_format", label: "Bad date format", detail: "28/10/2026 instead of ISO", icon: Clock3 },
  { value: "missing_field", label: "Missing email", detail: "Requires a human-supplied value", icon: Users },
  { value: "none", label: "Healthy order", detail: "Run the workflow without injection", icon: CheckCircle2 },
];
const tabs = [
  { id: "overview", label: "Pipeline", icon: Workflow },
  { id: "incidents", label: "Incidents", icon: AlertTriangle },
  { id: "benchmarks", label: "RecoveryBench", icon: BarChart3 },
  { id: "data", label: "Mock systems", icon: Database },
];

function statusClass(status = "") {
  const s = status.toLowerCase();
  if (["recovered", "succeeded", "success", "passed", "approved", "auto_applied"].includes(s)) return "good";
  if (s.includes("pending") || s === "queued" || s === "running" || s === "retrying") return "warn";
  if (["failed", "escalated", "error", "closed_manual"].includes(s)) return "bad";
  return "neutral";
}
function Pill({ children, status }) {
  return <span className={`pill ${statusClass(status || String(children))}`}><span className="pill-dot" />{children || "Unknown"}</span>;
}
function Metric({ label, value, note, icon: Icon, tone = "" }) {
  return <div className={`metric-card ${tone}`}><div className="metric-top"><span>{label}</span><span className="metric-icon"><Icon size={17} /></span></div><div className="metric-value">{value ?? "—"}</div>{note && <div className="metric-note">{note}</div>}</div>;
}
function Empty({ title, detail }) {
  return <div className="empty-state"><Layers3 size={24} /><strong>{title}</strong><span>{detail}</span></div>;
}
function SectionTitle({ eyebrow, title, subtitle, action }) {
  return <div className="section-title"><div><div className="eyebrow">{eyebrow}</div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}</div>;
}
const APPROVAL_REQUIRED_PROMPT = `
Create a synthetic AI automation failure that requires human approval.

The automation transfers customer orders to a CRM.

Generate exactly one mutation:
- op: remove_field
- field: email
- to: ""
- value: ""

Requirements:
- The missing email must make the Order payload invalid.
- Do not modify order_id, customer_id, or amount.
- Never invent or guess a replacement email.
- Explain why a human must supply the verified email.
- Return only JSON matching the configured simulation response schema.
- Use synthetic data only.
`;
export default function App() {
  const [activeTab, setActiveTab] = useState("overview");
  const [failure, setFailure] = useState("schema_drift");
  const [runs, setRuns] = useState([]);
  const [incidents, setIncidents] = useState([]);
  const [summary, setSummary] = useState({});
  const [contacts, setContacts] = useState([]);
  const [emails, setEmails] = useState([]);
  const [memories, setMemories] = useState([]);
  const [benchmarks, setBenchmarks] = useState([]);
  const [selectedRunId, setSelectedRunId] = useState(null);
  const [selectedIncidentId, setSelectedIncidentId] = useState(null);
  const [incidentDetail, setIncidentDetail] = useState(null);
  const [approvalValues, setApprovalValues] = useState({});
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);
  const [error, setError] = useState("");
  const [lastUpdated, setLastUpdated] = useState(null);
  const [gemmaStatus, setGemmaStatus] = useState({
    configured: false,
    message: "Checking Gemma configuration...",
    model_id: "gemma-4-26b-a4b-it",
  });

  const [simulationPrompt, setSimulationPrompt] = useState(
    "Invent a realistic, new failure caused by an AI automation mapping data into a CRM."
  );
  
const refresh = useCallback(async () => {
  try {
    const [r, i, s, c, e, m, b, g] = await Promise.all([
      api("/runs?limit=30"),
      api("/incidents?limit=50"),
      api("/dashboard/summary"),
      api("/crm-contacts?limit=50"),
      api("/emails?limit=50"),
      api("/repair-memory?limit=30"),
      api("/benchmark?limit=10"),
      api("/ai-simulator/status"),
    ]);

    setRuns(r);
    setIncidents(i);
    setSummary(s);
    setContacts(c);
    setEmails(e);
    setMemories(m);
    setBenchmarks(b);
    setGemmaStatus(g);

    setSelectedRunId((current) =>
      current && r.some((item) => item.id === current)
        ? current
        : (r[0]?.id ?? null)
    );

    setSelectedIncidentId((current) =>
      current && i.some((item) => item.id === current)
        ? current
        : (i[0]?.id ?? null)
    );

    setLastUpdated(new Date());
    setError("");
  } catch (err) {
    setError(err.message || "Could not connect to backend");
  }
}, []);


  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 1300);
    return () => clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    if (!selectedIncidentId) { setIncidentDetail(null); return; }
    let alive = true;
    api(`/incidents/${selectedIncidentId}`).then((item) => { if (alive) setIncidentDetail(item); }).catch(() => {});
    return () => { alive = false; };
  }, [selectedIncidentId, incidents]);

  const selectedRun = useMemo(() => runs.find((item) => item.id === selectedRunId) || runs[0] || null, [runs, selectedRunId]);
  const currentIncident = incidentDetail || incidents.find((item) => item.id === selectedIncidentId) || null;
  const latestBenchmark = benchmarks[0] || null;

  async function handleGemmaSimulation(promptOverride = null) {
  const promptToUse = (
    promptOverride ?? simulationPrompt
  ).trim();

  if (!promptToUse) {
    setError("Please enter a simulation prompt.");
    return;
  }

  setBusy(true);
  setToast(null);
  setError("");

  try {
    const result = await api("/runs", {
      method: "POST",
      body: JSON.stringify({
        inject: "gemma_simulate",
        simulation_prompt: promptToUse,
      }),
    });

    setSelectedRunId(result.run_id);

    setToast(
      `AI simulation queued: run #${result.run_id}`
    );

    await refresh();
  } catch (err) {
    setError(
      err.message || "Could not generate the simulation."
    );
  } finally {
    setBusy(false);
  }
}
  async function handleRun() {
    setBusy(true); setToast(null); setError("");
    try {
      const result = await api("/runs", { method: "POST", body: JSON.stringify({ inject: failure }) });
      setToast(`Run #${result.run_id} queued`); setSelectedRunId(result.run_id); await refresh();
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  async function handleDecision(incident, approve) {
    setBusy(true); setError("");
    try {
      if (approve) {
        const patch = incident.patch_ops || [];
        const missing = patch.find((op) => op.op === "set_value" && op.value == null);
        const value = approvalValues[incident.id] || "";
        const body = missing ? { field: missing.field, value } : {};
        if (missing && !value.trim()) throw new Error(`Enter the real ${missing.field} value before approving.`);
        await api(`/incidents/${incident.id}/approve`, { method: "POST", body: JSON.stringify(body) });
        setToast(`Incident #${incident.id} approved`);
      } else {
        await api(`/incidents/${incident.id}/reject`, { method: "POST", body: "{}" });
        setToast(`Incident #${incident.id} rejected`);
      }
      await refresh();
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  async function handleBenchmark() {
    setBusy(true); setError("");
    try {
      const result = await api("/benchmark", { method: "POST", body: JSON.stringify({ repetitions: 3, include_human_approval_simulation: true }) });
      setToast(`Benchmark #${result.benchmark_id} queued`); setActiveTab("benchmarks"); await refresh();
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  const activeNodes = ["receive_order", "create_crm_record", "send_confirmation"];
  const traceFor = (name) => selectedRun?.traces?.filter((trace) => trace.step_name === name).slice(-1)[0];
  const selectedIssue = selectedRun?.incidents?.[0];
  const patchOps = selectedIssue?.patch_ops || [];

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><Sparkles size={20} /></div><div><strong>HELIOS</strong><span>SELF-HEALING ENGINE</span></div></div>
      <div className="workspace-label">WORKSPACE</div>
      <nav className="side-nav">{tabs.map(({ id, label, icon: Icon }) => <button key={id} className={activeTab === id ? "nav-item active" : "nav-item"} onClick={() => setActiveTab(id)}><Icon size={17} /><span>{label}</span>{id === "incidents" && incidents.filter((i) => i.status === "PENDING_APPROVAL").length > 0 && <b>{incidents.filter((i) => i.status === "PENDING_APPROVAL").length}</b>}</button>)}</nav>
      <div className="sidebar-bottom"><div className="live-indicator"><span className="pulse" /> API polling active</div><div className="api-url">localhost:8000</div><p>Controlled repair for business workflows.</p></div>
    </aside>

    <main className="main-content">
      <header className="topbar"><div className="crumb"><span>Workspace</span><ChevronRight size={14} /><strong>{tabs.find((t) => t.id === activeTab)?.label}</strong></div><div className="topbar-right"><span className="update-label">{lastUpdated ? `Updated ${lastUpdated.toLocaleTimeString()}` : "Connecting…"}</span><button className="icon-button" onClick={refresh} title="Refresh"><RefreshCw size={16} /></button><div className="avatar">PS</div></div></header>
      {error && <div className="alert error-alert"><AlertTriangle size={16} /><span>{error}</span><button onClick={() => setError("")}><X size={15}/></button></div>}
      {toast && <div className="alert success-alert"><CheckCircle2 size={16}/><span>{toast}</span><button onClick={() => setToast(null)}><X size={15}/></button></div>}

      {activeTab === "overview" && <>
        <section className="hero-row"><div><div className="eyebrow"><span className="eyebrow-dot"/> WORKFLOW RELIABILITY PLATFORM</div><h1>Self-healing, with<br/><span>proof of recovery.</span></h1><p>Inject a failure. Diagnose the cause. Validate a repair. Recover safely — or route it to a human.</p></div><div className="hero-graphic"><div className="orb orb-one"/><div className="orb orb-two"/><div className="orb-core"><ShieldCheck size={35}/></div><div className="orbit-label label-top">DETECT</div><div className="orbit-label label-right">REPAIR</div><div className="orbit-label label-left">VERIFY</div></div></section>
        <section className="metrics-grid">
          <Metric label="Workflow runs" value={summary.total_runs ?? 0} note="Recent 100 runs" icon={Activity}/>
          <Metric label="Recovered" value={summary.recovered_runs ?? 0} note="Passed RepairProof" icon={BadgeCheck} tone="metric-good"/>
          <Metric label="Needs approval" value={summary.pending_approvals ?? 0} note="Human-in-the-loop" icon={Users} tone="metric-warn"/>
          <Metric label="Escalated / failed" value={summary.failed_or_escalated_runs ?? 0} note="Requires investigation" icon={AlertTriangle} tone="metric-bad"/>
        </section>
        <section className="panel gemma-panel">
  <SectionTitle
    eyebrow="GENERATIVE FAILURE LAB"
    title="Simulate a new AI automation issue"
    subtitle="Gemma generates a new incident and proposes constrained data mutations. Your existing backend validates and processes the resulting failure."
    action={
      <span className="source-label">
        {gemmaStatus.configured
          ? "Gemma configured"
          : "API key needed"}
      </span>
    }
  />

  <label className="field-label" htmlFor="gemma-prompt">
    WHAT SHOULD THE AI AUTOMATION BE DOING?
  </label>

  <textarea
    id="gemma-prompt"
    value={simulationPrompt}
    onChange={(event) =>
      setSimulationPrompt(event.target.value)
    }
    maxLength={1000}
    placeholder="Example: An AI agent maps order data into a CRM. Invent a new mapping issue."
    style={{
      width: "100%",
      minHeight: "110px",
      marginTop: "10px",
      padding: "12px",
      borderRadius: "10px",
      resize: "vertical",
      font: "inherit",
      boxSizing: "border-box",
    }}
  />

  <div style={{ marginTop: "12px" }}>
    <button
      className="primary-button"
      onClick={handleGemmaSimulation}
      disabled={
        busy ||
        !gemmaStatus.configured ||
        !simulationPrompt.trim()
      }
    >
      <Sparkles size={16} />
      {busy ? "Generating..." : "Generate issue with Gemma"}
      <ArrowRight size={16} />
    </button>
    <button
  type="button"
  className="primary-button"
  style={{ marginLeft: "10px" }}
  onClick={() =>
    handleGemmaSimulation(APPROVAL_REQUIRED_PROMPT)
  }
  disabled={busy || !gemmaStatus.configured}
>
  Generate Approval-Required Issue
</button>
  </div>

  <p style={{ marginTop: "12px", opacity: 0.8 }}>
    {gemmaStatus.message}
  </p>

  {selectedRun?.simulation && (
    <div style={{ marginTop: "20px" }}>
      <div className="eyebrow">
        GENERATED SCENARIO · RUN #{selectedRun.id}
      </div>

      <h3>{selectedRun.simulation.title}</h3>

      <p>{selectedRun.simulation.description}</p>

      <p>
        <strong>Category:</strong>{" "}
        {selectedRun.simulation.fault_type}
      </p>

      <p>
        <strong>Component:</strong>{" "}
        {selectedRun.simulation.automation_component}
      </p>

      <p>
        <strong>Expected handling:</strong>{" "}
        {selectedRun.simulation.expected_handling}
      </p>

      <p>
        <strong>Simulation status:</strong>{" "}
        {selectedRun.simulation.status}
      </p>

      <h4>Applied mutations</h4>

      <pre className="json-box">
        {JSON.stringify(
          selectedRun.simulation.mutation,
          null,
          2
        )}
      </pre>

      {selectedRun.simulation.error && (
        <div className="alert error-alert">
          {selectedRun.simulation.error}
        </div>
      )}
    </div>
  )}
</section>
        <div className="content-grid">
          <section className="panel run-panel">
            <SectionTitle eyebrow="CONTROL PLANE" title="Run a workflow" subtitle="Choose a deterministic failure scenario and observe the repair lifecycle." />
            <div className="failure-options">{failureOptions.map(({ value, label, detail, icon: Icon }) => <button key={value} className={`failure-option ${failure === value ? "selected" : ""}`} onClick={() => setFailure(value)}><span className="failure-icon"><Icon size={18}/></span><span className="failure-copy"><strong>{label}</strong><small>{detail}</small></span><span className="radio-dot" /></button>)}</div>
            <button className="primary-button run-button" onClick={handleRun} disabled={busy}><Play size={16} fill="currentColor"/>{busy ? "Working…" : "Run workflow"}<ArrowRight size={16}/></button>
            <div className="panel-note"><Zap size={15}/><span>Mock CRM + email sink. No real emails are sent.</span></div>
          </section>
          <section className="panel pipeline-panel">
            <SectionTitle eyebrow="LIVE TRACE" title="Pipeline execution" subtitle={selectedRun ? `Run #${selectedRun.id} · ${selectedRun.inject_type || "none"}` : "Run a workflow to populate this view."} action={selectedRun && <Pill status={selectedRun.status}>{selectedRun.status}</Pill>}/>
            <div className="pipeline-list">{activeNodes.map((node, idx) => {
              const trace = traceFor(node); const isFailed = trace?.status === "FAILED"; const isSuccess = trace?.status === "SUCCESS";
              const Icon = isFailed ? AlertTriangle : isSuccess ? CheckCircle2 : CircleDot;
              return <div key={node} className="pipeline-node-wrap"><div className={`pipeline-node ${isFailed ? "node-failed" : isSuccess ? "node-success" : ""}`}><span className="node-icon"><Icon size={18}/></span><div className="node-content"><strong>{node.replaceAll("_", " ")}</strong><small>{trace ? `${trace.duration_ms?.toFixed(1) || 0} ms · attempt ${trace.attempt}` : "Waiting for execution"}</small>{isFailed && <em>{trace.error?.split("\n")[0]?.slice(0, 95)}</em>}</div><Pill status={trace?.status || "Waiting"}>{trace?.status || "Waiting"}</Pill></div>{idx < activeNodes.length - 1 && <div className="pipeline-connector"><span/><span/><span/></div>}</div>;
            })}</div>
            {selectedRun?.error && <div className="inline-error"><AlertTriangle size={15}/>{selectedRun.error}</div>}
            <div className="selected-run-footer"><span><History size={14}/> Recent runs</span><div className="run-chips">{runs.slice(0, 5).map((r) => <button key={r.id} onClick={() => setSelectedRunId(r.id)} className={selectedRun?.id === r.id ? "run-chip active" : "run-chip"}>#{r.id}</button>)}</div></div>
          </section>
        </div>

        <div className="content-grid second-grid">
          <section className="panel diagnosis-panel"><SectionTitle eyebrow="HEAL LAYER" title="Diagnosis & patch" subtitle="A repair must pass deterministic validation before execution."/>
            {!selectedIssue ? <Empty title="No incident for this run" detail="Inject one of the failure types to see diagnosis and patch operations."/> : <>
              <div className="diagnosis-summary"><div><span className="field-label">ROOT CAUSE</span><strong>{selectedIssue.root_cause || "Diagnosis pending"}</strong></div><div className="diagnosis-tags"><Pill status={selectedIssue.source}>{selectedIssue.source || "Unknown"}</Pill><Pill status={selectedIssue.risk}>{selectedIssue.risk || "Risk unknown"} risk</Pill></div></div>
              <div className="confidence-row"><span>Diagnosis confidence</span><strong>{selectedIssue.confidence == null ? "—" : `${Math.round(selectedIssue.confidence * 100)}%`}</strong></div><div className="confidence-track"><div style={{ width: `${Math.round((selectedIssue.confidence || 0) * 100)}%` }}/></div>
              <div className="diff-title"><span>PROPOSED PATCH</span><Pill status={selectedIssue.status}>{selectedIssue.status}</Pill></div>
              <div className="code-diff">{patchOps.length ? patchOps.map((op, index) => <div key={index} className="diff-line"><span className="diff-plus">{op.op === "rename_field" ? "~" : "+"}</span><code>{op.op === "rename_field" ? `${op.field}  →  ${op.to}` : op.op === "reformat_value" ? `${op.field}  →  ${op.format}` : `${op.field}  =  ${op.value == null ? "[human input required]" : JSON.stringify(op.value)}`}</code></div>) : <div className="diff-line"><code>No supported patch proposed.</code></div>}</div>
              {selectedIssue.validation && <div className="validation-list">{(selectedIssue.validation.reasons || []).map((r, i) => <div key={i}><Check size={13}/>{r}</div>)}</div>}
              {selectedIssue.status === "RECOVERED" && <div className="proof-chip"><ShieldCheck size={16}/><span>RepairProof passed</span><CheckCircle2 size={15}/></div>}
            </>}
          </section>
          <section className="panel approval-panel"><SectionTitle eyebrow="HUMAN IN THE LOOP" title="Approval queue" subtitle="Risky repairs stay paused until an operator decides." action={<span className="queue-count">{incidents.filter((i) => i.status === "PENDING_APPROVAL").length} pending</span>}/>
            {incidents.filter((i) => i.status === "PENDING_APPROVAL").length === 0 ? <Empty title="Queue is clear" detail="Missing fields and uncertain repairs will appear here for review."/> : <div className="approval-list">{incidents.filter((i) => i.status === "PENDING_APPROVAL").map((incident) => {
              const needsField = incident.patch_ops?.find((op) => op.op === "set_value" && op.value == null);
              return <div className="approval-card" key={incident.id}><div className="approval-head"><span className="approval-symbol"><Users size={16}/></span><div><strong>Incident #{incident.id}</strong><small>Run #{incident.run_id} · {incident.failed_step}</small></div><Pill status="PENDING_APPROVAL">Pending</Pill></div><p>{incident.root_cause}</p>{needsField && <label className="input-label">Enter verified {needsField.field}<input type="email" placeholder="customer@example.com" value={approvalValues[incident.id] || ""} onChange={(e) => setApprovalValues((prev) => ({ ...prev, [incident.id]: e.target.value }))}/></label>}<div className="approval-actions"><button className="secondary-button" onClick={() => handleDecision(incident, false)} disabled={busy}><X size={14}/> Reject</button><button className="primary-button small" onClick={() => handleDecision(incident, true)} disabled={busy}><Check size={14}/> Approve & retry</button></div></div>;
            })}</div>}
          </section>
        </div>

        <section className="panel history-panel"><SectionTitle eyebrow="OBSERVABILITY" title="Recent incident history" subtitle="Every state transition is recorded with timestamps." action={<button className="text-button" onClick={() => setActiveTab("incidents")}>View all <ArrowRight size={14}/></button>}/>
          {incidents.length === 0 ? <Empty title="No incidents yet" detail="Run one of the injected scenarios to start your incident history."/> : <div className="table-wrap"><table><thead><tr><th>INCIDENT</th><th>ROOT CAUSE</th><th>SOURCE</th><th>RISK</th><th>STATUS</th><th></th></tr></thead><tbody>{incidents.slice(0, 5).map((i) => <tr key={i.id}><td><strong>#{i.id}</strong><small>Run #{i.run_id}</small></td><td className="cause-cell">{i.root_cause || i.error}</td><td><span className="source-label">{i.source || "—"}</span></td><td>{i.risk || "—"}</td><td><Pill status={i.status}>{i.status}</Pill></td><td><button className="table-action" onClick={() => { setSelectedIncidentId(i.id); setActiveTab("incidents"); }}>Details <ChevronRight size={13}/></button></td></tr>)}</tbody></table></div>}
        </section>
      </>}

      {activeTab === "incidents" && <section className="page-section"><SectionTitle eyebrow="INCIDENT MANAGEMENT" title="Incidents & approvals" subtitle="Select an incident to inspect its diagnosis, patch validation, and audit timeline." action={<button className="secondary-button" onClick={refresh}><RefreshCw size={14}/> Refresh</button>}/><div className="incident-layout"><div className="panel incident-list-panel">{incidents.length === 0 ? <Empty title="No incidents found" detail="Run a failure scenario to generate an incident."/> : incidents.map((i) => <button className={`incident-list-item ${selectedIncidentId === i.id ? "active" : ""}`} key={i.id} onClick={() => setSelectedIncidentId(i.id)}><span className="incident-mark"><AlertTriangle size={16}/></span><span className="incident-list-text"><strong>Incident #{i.id}</strong><small>{i.root_cause || i.error}</small><span>Run #{i.run_id} · {i.failed_step}</span></span><Pill status={i.status}>{i.status}</Pill></button>)}</div><div className="panel incident-detail-panel">{!currentIncident ? <Empty title="Select an incident" detail="Incident detail and event timeline appear here."/> : <><div className="detail-header"><div><div className="eyebrow">INCIDENT #{currentIncident.id}</div><h2>{currentIncident.root_cause || "Undiagnosed failure"}</h2><p>Run #{currentIncident.run_id} · {currentIncident.failed_step}</p></div><Pill status={currentIncident.status}>{currentIncident.status}</Pill></div><div className="detail-stats"><div><span>Confidence</span><strong>{currentIncident.confidence == null ? "—" : `${Math.round(currentIncident.confidence * 100)}%`}</strong></div><div><span>Risk</span><strong>{currentIncident.risk || "—"}</strong></div><div><span>Source</span><strong>{currentIncident.source || "—"}</strong></div></div><h3>Proposed operations</h3><pre className="json-box">{JSON.stringify(currentIncident.patch_ops || [], null, 2)}</pre><h3>Event timeline</h3><div className="timeline">{(currentIncident.events || []).map((ev) => <div className="timeline-row" key={ev.id}><span className="timeline-dot"/><div><strong>{ev.event_type.replaceAll("_", " ")}</strong><small>{ev.created_at ? new Date(ev.created_at).toLocaleString() : ""}</small>{ev.details && Object.keys(ev.details).length > 0 && <code>{JSON.stringify(ev.details)}</code>}</div></div>)}</div>{currentIncident.status === "PENDING_APPROVAL" && <div className="approval-detail-actions"><button className="secondary-button" onClick={() => handleDecision(currentIncident, false)} disabled={busy}>Reject</button><button className="primary-button small" onClick={() => handleDecision(currentIncident, true)} disabled={busy}>Approve & retry</button></div>}</>}</div></div></section>}

      {activeTab === "benchmarks" && <section className="page-section"><SectionTitle eyebrow="EVIDENCE, NOT CLAIMS" title="RecoveryBench" subtitle="Compare retry-only, deterministic rules, and the complete repair pipeline against the same injected failures." action={<button className="primary-button" onClick={handleBenchmark} disabled={busy}><Play size={15} fill="currentColor"/> Run benchmark (3 reps)</button>}/><div className="benchmark-explainer"><div className="bench-icon"><BarChart3 size={22}/></div><div><strong>Controlled evaluation</strong><p>Each benchmark runs schema drift, bad date formatting, and missing email. The missing-email case can use a clearly labelled simulated human approval fixture. Treat results as prototype measurements, not production reliability claims.</p></div></div>{!latestBenchmark ? <div className="panel"><Empty title="No benchmark runs yet" detail="Start a benchmark to compare the three recovery modes."/></div> : <><div className="benchmark-state"><div><span>Latest benchmark</span><strong>#{latestBenchmark.id}</strong></div><Pill status={latestBenchmark.status}>{latestBenchmark.status}</Pill>{latestBenchmark.created_at && <small>Started {new Date(latestBenchmark.created_at).toLocaleString()}</small>}</div>{latestBenchmark.metrics ? <div className="panel"><div className="table-wrap"><table><thead><tr><th>MODE</th><th>CASES</th><th>DIAGNOSIS ACCURACY</th><th>RECOVERY RATE</th><th>FALSE-FIX RATE</th><th>MEAN DURATION</th><th>PROOF PASSES</th></tr></thead><tbody>{Object.entries(latestBenchmark.metrics).map(([mode, m]) => <tr key={mode}><td><strong>{mode.replaceAll("_", " ")}</strong></td><td>{m.cases}</td><td>{m.diagnosis_accuracy_pct}%</td><td>{m.recovery_rate_pct}%</td><td>{m.false_fix_rate_pct}%</td><td>{m.mean_recovery_time_ms} ms</td><td>{m.proof_pass_count}</td></tr>)}</tbody></table></div></div> : <div className="panel"><Empty title="Benchmark in progress" detail="This page refreshes automatically. Trial details appear when the benchmark completes."/></div>}{latestBenchmark.metrics?.error && <div className="alert error-alert">{latestBenchmark.metrics.error}</div>}{latestBenchmark.trials?.length > 0 && <div className="panel"><SectionTitle eyebrow="RAW TRIALS" title="Trial-level results" subtitle="Use these records to explain the aggregate figures."/><div className="table-wrap"><table><thead><tr><th>RUN</th><th>MODE</th><th>FAILURE</th><th>STATUS</th><th>DIAGNOSIS</th><th>PROOF</th><th>DURATION</th></tr></thead><tbody>{latestBenchmark.trials.slice(0, 60).map((t, idx) => <tr key={`${t.run_id}-${idx}`}><td>#{t.run_id}</td><td>{t.mode}</td><td>{t.failure}</td><td><Pill status={t.status}>{t.status}</Pill></td><td>{t.diagnosis_correct ? "Correct" : "Not correct"}</td><td>{t.proof_passed ? <span className="text-good">Passed</span> : "—"}</td><td>{t.duration_ms} ms</td></tr>)}</tbody></table></div></div>}</>}</section>}

      {activeTab === "data" && <section className="page-section"><SectionTitle eyebrow="MOCK INTEGRATIONS" title="Business systems" subtitle="Inspect the persisted CRM contacts, email sink records, and reusable repairs."/><section className="metrics-grid data-metrics"><Metric label="CRM contacts" value={contacts.length} note="Unique by order ID" icon={Users}/><Metric label="Email sink records" value={emails.length} note="No actual emails sent" icon={PanelTop}/><Metric label="Verified memories" value={memories.length} note="Stored repair signatures" icon={BrainCircuit}/><Metric label="Unique orders" value={new Set(contacts.map((x) => x.order_id)).size} note="Mock CRM state" icon={Database}/></section><div className="content-grid data-grid"><div className="panel"><SectionTitle eyebrow="CRM MOCK SERVICE" title="Customer contacts"/><div className="table-wrap"><table><thead><tr><th>ORDER</th><th>CUSTOMER</th><th>EMAIL</th><th>PHONE</th></tr></thead><tbody>{contacts.slice(0, 15).map((c) => <tr key={c.id}><td>{c.order_id}</td><td>{c.customer_name}</td><td>{c.email}</td><td>{c.phone}</td></tr>)}</tbody></table></div>{contacts.length === 0 && <Empty title="No contacts yet" detail="Run a healthy or recovered order."/>}</div><div className="panel"><SectionTitle eyebrow="MAIL SINK" title="Confirmation records"/><div className="table-wrap"><table><thead><tr><th>ORDER</th><th>RECIPIENT</th><th>STATUS</th></tr></thead><tbody>{emails.slice(0, 15).map((e) => <tr key={e.id}><td>{e.order_id}</td><td>{e.recipient}</td><td><Pill status={e.status}>{e.status}</Pill></td></tr>)}</tbody></table></div>{emails.length === 0 && <Empty title="No confirmations yet" detail="The mock mail sink is empty."/>}</div></div><div className="panel memory-panel"><SectionTitle eyebrow="APPROVED REPAIR MEMORY" title="Reusable repair signatures" subtitle="Only previously verified safe patches are eligible for reuse."/>{memories.length === 0 ? <Empty title="No verified repairs saved" detail="Recover a supported low-risk failure to seed this catalog."/> : <div className="table-wrap"><table><thead><tr><th>SIGNATURE</th><th>PATCH</th><th>VERIFIED USES</th><th>LAST USED</th></tr></thead><tbody>{memories.map((m) => <tr key={m.id}><td><code>{m.signature}</code></td><td><code>{JSON.stringify(m.patch_ops)}</code></td><td>{m.verified_uses}</td><td>{m.last_used_at ? new Date(m.last_used_at).toLocaleString() : "—"}</td></tr>)}</tbody></table></div>}</div></section>}
      <footer className="footer"><span>HELIOS · PS4 SELF-HEALING WORKFLOW ENGINE</span><span><span className="pulse"/> API connected by polling</span></footer>
    </main>
  </div>;
}
