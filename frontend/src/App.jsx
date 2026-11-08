
import { useEffect, useState } from "react";
import "./App.css";

const API = (
  import.meta.env.VITE_API_BASE_URL || ""
).replace(/\/+$/, "");

async function apiRequest(path, options = {}, apiKey = "") {
  const headers = {
    "Content-Type": "application/json",
    ...(apiKey ? { "X-API-Key": apiKey.trim() } : {}),
    ...options.headers,
  };

  const response = await fetch(`${API}${path}`, {
    ...options,
    headers,
  });

  const text = await response.text();
  let data = {};

  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { detail: text || "Invalid server response." };
  }

  if (!response.ok) {
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : data.error?.message || `Request failed (${response.status})`
    );
  }

  return data;
}

function Status({ ok, children }) {
  return (
    <span className={`status-pill ${ok ? "is-good" : "is-muted"}`}>
      <span className="status-dot" />
      {children}
    </span>
  );
}

function Metric({ label, value, detail }) {
  return (
    <div className="metric-card">
      <span className="metric-label">{label}</span>
      <strong>{value}</strong>
      <span className="metric-detail">{detail}</span>
    </div>
  );
}

export default function App() {
  const [apiKey, setApiKey] = useState("");
  const [task, setTask] = useState(
    "Run the predefined smoke test and verify its execution evidence."
  );

  const [backend, setBackend] = useState("checking");
  const [docker, setDocker] = useState("checking");

  const [plan, setPlan] = useState(null);
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);
  const [selectedRecord, setSelectedRecord] = useState(null);

  const [loading, setLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function checkHealth() {
    try {
      await apiRequest("/health");
      setBackend("online");
    } catch {
      setBackend("offline");
    }

    try {
      await apiRequest("/api/health/docker");
      setDocker("available");
    } catch {
      setDocker("unavailable");
    }
  }

  async function loadHistory() {
    if (!apiKey.trim()) {
      setError("Enter your Pinnoto API key to access execution history.");
      return;
    }

    setHistoryLoading(true);
    setError("");

    try {
      const data = await apiRequest(
        "/api/execution/?limit=20&offset=0",
        {},
        apiKey
      );

      setHistory(Array.isArray(data.items) ? data.items : []);
    } catch (err) {
      setError(err.message);
    } finally {
      setHistoryLoading(false);
    }
  }

  useEffect(() => {
    checkHealth();
  }, []);

  async function generatePlan() {
    setLoading(true);
    setError("");
    setNotice("");
    setPlan(null);
    setResult(null);
    setSelectedRecord(null);

    try {
      const data = await apiRequest(
        "/api/agent/plan",
        {
          method: "POST",
          body: JSON.stringify({ task }),
        },
        apiKey
      );

      setPlan(data);
      setNotice("Plan received. Execution has not started.");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function executePlan() {
    if (!plan?.approval_id || !plan?.plan_hash) {
      setError("A valid pending approval is required.");
      return;
    }

    if (
      !window.confirm(
        "Approve this exact plan and execute the predefined smoke test?"
      )
    ) {
      return;
    }

    setLoading(true);
    setError("");
    setNotice("");

    try {
      const data = await apiRequest(
        "/api/agent/execute",
        {
          method: "POST",
          body: JSON.stringify({
            approval_id: plan.approval_id,
            plan_hash: plan.plan_hash,
          }),
        },
        apiKey
      );

      setResult(data);
      setPlan(null);
      setNotice("Execution response received. Review the evidence below.");
      await loadHistory();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function runContainmentTest() {
    if (
      !window.confirm(
        "Run the predefined containment test inside the Docker sandbox?"
      )
    ) {
      return;
    }

    setLoading(true);
    setError("");
    setNotice("");
    setPlan(null);

    try {
      const data = await apiRequest(
        "/api/execution/run",
        {
          method: "POST",
          body: JSON.stringify({ command: "containment_test" }),
        },
        apiKey
      );

      setResult(data);
      setNotice("Containment test response received. Inspect its evidence.");
      await loadHistory();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function inspectRecord(id) {
    setError("");
    setSelectedRecord(null);

    try {
      const data = await apiRequest(
        `/api/execution/${encodeURIComponent(id)}`,
        {},
        apiKey
      );

      setSelectedRecord(data);
    } catch (err) {
      setError(err.message);
    }
  }

  const evidence =
    result?.evidence ||
    result?.results?.[0]?.evidence ||
    selectedRecord?.evidence;

  const executionSucceeded =
    result?.success === true ||
    result?.results?.some((item) => item.success === true);

  return (
    <main className="app">
      <header className="topbar">
        <a className="brand" href="#">
          <span className="brand-mark">P</span>
          PINNOTO
        </a>

        <div className="topbar-right">
          <Status ok={backend === "online"}>
            Backend {backend}
          </Status>
          <Status ok={docker === "available"}>
            Docker {docker}
          </Status>
        </div>
      </header>

      <section className="hero">
        <div className="eyebrow">
          <span className="live-indicator" />
          CONTAINMENT-FIRST AI EXECUTION
        </div>

        <h1>
          Execute.
          <br />
          <span>Contain. Verify.</span>
        </h1>

        <p className="subtitle">
          An AI-assisted execution system with deterministic authorization,
          isolated Docker environments and cryptographically signed evidence.
        </p>

        <div className="hero-tags">
          <span>Human approval</span>
          <span>Docker isolation</span>
          <span>Ed25519 evidence</span>
        </div>
      </section>

      <section className="metrics">
        <Metric
          label="BACKEND"
          value={backend === "online" ? "Online" : "Offline"}
          detail="FastAPI service"
        />
        <Metric
          label="SANDBOX"
          value={docker === "available" ? "Ready" : "Unavailable"}
          detail="Docker execution"
        />
        <Metric
          label="EXECUTIONS"
          value={history.length}
          detail="Recent records loaded"
        />
        <Metric
          label="APPROVAL"
          value={plan ? "Pending" : "Idle"}
          detail="Explicit authorization"
        />
      </section>

      <section className="workspace">
        <div className="section-heading">
          <div>
            <span className="eyebrow">01 / CONFIGURATION</span>
            <h2>Execution workspace</h2>
          </div>
          <Status ok={Boolean(apiKey.trim())}>
            {apiKey.trim() ? "API key entered" : "Authentication required"}
          </Status>
        </div>

        <div className="workspace-grid">
          <div className="panel configuration-panel">
            <h3>Connect to Pinnoto</h3>
            <p className="muted">
              Your API key stays in this browser session and is not saved.
            </p>

            <label htmlFor="api-key">Pinnoto API key</label>
            <input
              id="api-key"
              type="password"
              autoComplete="off"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder="Enter API key"
            />

            <label htmlFor="task">Describe your task</label>
            <textarea
              id="task"
              rows={4}
              maxLength={2000}
              value={task}
              onChange={(event) => setTask(event.target.value)}
              placeholder="Describe the task for the AI agent"
            />

            <button
              className="primary-button"
              disabled={
                loading ||
                !apiKey.trim() ||
                !task.trim() ||
                backend !== "online"
              }
              onClick={generatePlan}
            >
              {loading ? "Processing..." : "Generate AI execution plan"}
              <span>→</span>
            </button>

            <button
              className="secondary-button"
              disabled={
                loading ||
                !apiKey.trim() ||
                backend !== "online" ||
                docker !== "available"
              }
              onClick={runContainmentTest}
            >
              Run predefined containment test
            </button>

            <p className="security-note">
              <span>◆</span> Only predefined backend-authorized tests are
              available through this workflow. Arbitrary code execution is
              not exposed here.
            </p>
          </div>

          <div className="panel workflow-panel">
            <h3>Execution pipeline</h3>
            <p className="muted">
              Every stage must be completed before a verified result is
              reported.
            </p>

            {[
              ["01", "AI planning", "Propose bounded work"],
              ["02", "Policy & approval", "Validate and authorize"],
              ["03", "Sandbox execution", "Run in isolated Docker"],
              ["04", "Evidence verification", "Verify signed output"],
              ["05", "Persistence", "Store execution history"],
            ].map(([number, name, description], index) => {
              const completed =
                index === 0
                  ? Boolean(plan || result)
                  : index === 1
                    ? Boolean(result)
                    : index >= 2
                      ? Boolean(result)
                      : false;

              return (
                <div className="pipeline-step" key={number}>
                  <span className={`step-number ${completed ? "done" : ""}`}>
                    {completed ? "✓" : number}
                  </span>
                  <div>
                    <strong>{name}</strong>
                    <small>{description}</small>
                  </div>
                  <span className="step-state">
                    {completed ? "Complete" : "Waiting"}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {error && (
        <div className="alert error" role="alert">
          <strong>Request failed</strong>
          <p>{error}</p>
        </div>
      )}

      {notice && (
        <div className="alert success" role="status">
          {notice}
        </div>
      )}

      {plan && (
        <section className="panel result-panel">
          <div className="section-heading">
            <div>
              <span className="eyebrow">02 / HUMAN APPROVAL</span>
              <h2>Review proposed plan</h2>
            </div>
            <Status ok={false}>Execution not started</Status>
          </div>

          <p>{plan.proposed_plan?.summary}</p>

          <div className="action-list">
            {(plan.proposed_plan?.actions || []).map((action) => (
              <div className="action-item" key={action}>
                <span>✓</span>
                {action}
              </div>
            ))}
          </div>

          <div className="hash-display">
            <label>PLAN SHA-256</label>
            <code>{plan.plan_hash}</code>
          </div>

          <p className="muted">
            Approval expires in {plan.approval_expires_in_seconds} seconds.
            Execution requires your explicit confirmation.
          </p>

          <button
            className="primary-button"
            disabled={loading}
            onClick={executePlan}
          >
            {loading ? "Executing..." : "Approve & execute"}
            <span>→</span>
          </button>
        </section>
      )}

      {(result || selectedRecord) && (
        <section className="panel result-panel">
          <div className="section-heading">
            <div>
              <span className="eyebrow">03 / EXECUTION RECEIPT</span>
              <h2>Execution evidence</h2>
            </div>

            <Status
              ok={
                selectedRecord
                  ? selectedRecord.verification_status === "verified"
                  : executionSucceeded
              }
            >
              {selectedRecord
                ? selectedRecord.verification_status || "Status unknown"
                : executionSucceeded
                  ? "Execution succeeded"
                  : "Review execution result"}
            </Status>
          </div>

          {evidence && (
            <>
              <div className="evidence-grid">
                <div>
                  <label>Execution ID</label>
                  <code>{evidence.execution_id || "Not available"}</code>
                </div>
                <div>
                  <label>Exit code</label>
                  <strong>{evidence.exit_code ?? "Unknown"}</strong>
                </div>
                <div>
                  <label>Signature algorithm</label>
                  <strong>{evidence.signature_algorithm || "Ed25519"}</strong>
                </div>
                <div>
                  <label>Verification</label>
                  <strong>
                    {selectedRecord?.verification_status ||
                      (executionSucceeded
                        ? "Backend verified"
                        : "Not confirmed")}
                  </strong>
                </div>
              </div>

              <label>Output SHA-256</label>
              <div className="hash-display">
                <code>{evidence.output_sha256 || "Unavailable"}</code>
              </div>

              <label>Signed evidence receipt</label>
              <pre>{JSON.stringify(evidence, null, 2)}</pre>
            </>
          )}

          <label>Full execution response</label>
          <pre>
            {JSON.stringify(selectedRecord || result, null, 2)}
          </pre>
        </section>
      )}

      <section className="panel history-panel">
        <div className="section-heading">
          <div>
            <span className="eyebrow">04 / AUDIT TRAIL</span>
            <h2>Execution history</h2>
          </div>

          <button
            className="small-button"
            disabled={historyLoading || !apiKey.trim()}
            onClick={loadHistory}
          >
            {historyLoading ? "Loading..." : "↻ Refresh history"}
          </button>
        </div>

        {history.length === 0 ? (
          <div className="empty-state">
            <span>◷</span>
            <strong>No records loaded</strong>
            <p>Connect with your API key and refresh execution history.</p>
          </div>
        ) : (
          <div className="history-list">
            {history.map((record) => (
              <button
                className="history-row"
                key={record.execution_id}
                onClick={() => inspectRecord(record.execution_id)}
              >
                <span className="history-icon">◈</span>
                <span className="history-info">
                  <strong>{record.command}</strong>
                  <small>{record.execution_id}</small>
                </span>
                <Status ok={record.verification_status === "verified"}>
                  {record.verification_status || "Stored"}
                </Status>
                <span>→</span>
              </button>
            ))}
          </div>
        )}
      </section>

      <footer className="app-footer">
        <strong>PINNOTO</strong>
        <span>Execute. Contain. Verify.</span>
        <span>Bounded execution · Verifiable evidence</span>
      </footer>
    </main>
  );
}
