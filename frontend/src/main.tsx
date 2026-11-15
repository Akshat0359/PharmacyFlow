import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowUpRight,
  Check,
  ChevronRight,
  ClipboardCheck,
  FileText,
  FlaskConical,
  LayoutDashboard,
  LogOut,
  Mic,
  Search,
  ShieldCheck,
  Square,
  Upload,
  X,
  Clock,
  AlertTriangle,
} from "lucide-react";
import "./style.css";

type Case = {
  id: string;
  kind: string;
  state: string;
  patient_id: string | null;
  mode: string;
  payload: any;
  action: any;
  action_hash: string;
  approved_by: string;
  result: any;
  revision: number;
  tool_calls: number;
  created_at: number;
  updated_at: number;
  events?: any[];
};
type User = { sub: string; role: string; tenant: string; mode: string };
const label = (s: string) => s.replaceAll("_", " ");
const short = (s: string) => s.slice(0, 8).toUpperCase();
const date = (n: number) => new Date(n * 1000).toLocaleString();
let bearer = sessionStorage.getItem("pf-token") || "";
async function api(path: string, options: RequestInit = {}) {
  const response = await fetch("/api" + path, {
    ...options,
    headers: {
      ...(options.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      Authorization: "Bearer " + bearer,
      ...options.headers,
    },
  });
  if (!response.ok) {
    const e = await response
      .json()
      .catch(() => ({ detail: response.statusText }));
    throw new Error(
      typeof e.detail === "string" ? e.detail : JSON.stringify(e.detail),
    );
  }
  return response.json();
}
const post = (path: string, body?: any, method = "POST") =>
  api(path, { method, body: body ? JSON.stringify(body) : undefined });
function Badge({ state }: { state: string }) {
  return (
    <span className={"badge " + state}>
      <i />
      {label(state)}
    </span>
  );
}
function Brand() {
  return (
    <div className="brand">
      <span className="brandmark">✳</span>PharmacyFlow<span>AI</span>
    </div>
  );
}

function App() {
  const [user, setUser] = useState<User | null>(null),
    [mode, setMode] = useState("fixture"),
    [demo, setDemo] = useState(true);
  const [cases, setCases] = useState<Case[]>([]),
    [metrics, setMetrics] = useState<any>(null),
    [evaluations, setEvaluations] = useState<any[]>([]);
  const [tab, setTab] = useState("Overview"),
    [query, setQuery] = useState(""),
    [selected, setSelected] = useState<Case | null>(null);
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [username, setUsername] = useState("pharmacist"),
    [password, setPassword] = useState("");
  const upload = useRef<HTMLInputElement>(null);
  async function refresh() {
    const snapshot = bearer;
    if (!snapshot) return;
    const u = await api("/me");
    const list = await api("/cases");
    const [m, e] =
      u.role === "patient"
        ? [null, []]
        : await Promise.all([api("/metrics"), api("/evaluations")]);
    if (snapshot !== bearer) return;
    setUser(u);
    setMode(u.mode);
    setCases(list);
    setMetrics(m);
    setEvaluations(e);
  }
  async function act(fn: () => Promise<any>) {
    setBusy(true);
    setError("");
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    fetch("/health")
      .then((r) => r.json())
      .then((h) => setDemo(h.demo_accounts))
      .catch(() => {});
    refresh().catch(() => {
      bearer = "";
      sessionStorage.removeItem("pf-token");
    });
    const timer = setInterval(() => refresh().catch(() => {}), 3000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    if (!selected) return;
    const id = selected.id;
    const timer = setInterval(
      () =>
        api("/cases/" + id)
          .then((c) => setSelected((old) => (old?.id === id ? c : old)))
          .catch(() => {}),
      2000,
    );
    return () => clearInterval(timer);
  }, [selected?.id]);
  const open = (id: string) =>
    act(async () => setSelected(await api("/cases/" + id)));
  const logout = () =>
    act(async () => {
      await post("/logout");
      bearer = "";
      sessionStorage.removeItem("pf-token");
      setUser(null);
      setSelected(null);
      setCases([]);
      setPassword("");
    });
  if (!user)
    return (
      <div className="login">
        <div className="login-story">
          <Brand />
          <div className="eyebrow">THE WORKFLOW, WITH EVIDENCE.</div>
          <h1>
            A clearer path
            <br />
            from request
            <br />
            to review.
          </h1>
          <p>
            A multimodal agent laboratory for prescription intake and refill
            management.
          </p>
          <div className="login-flow">
            <span>
              <FileText />
              Intake
            </span>
            <ChevronRight />
            <span>
              <ShieldCheck />
              Verify
            </span>
            <ChevronRight />
            <span>
              <ClipboardCheck />
              Review
            </span>
          </div>
          <small>SYNTHETIC PATIENTS · SIMULATED CALLS · MOCK PHARMACY</small>
        </div>
        <form
          className="login-form"
          onSubmit={(e) => {
            e.preventDefault();
            act(async () => {
              const r = await post("/login", { username, password });
              bearer = r.token;
              sessionStorage.setItem("pf-token", bearer);
              setUser(r.user);
              setMode(r.mode);
            });
          }}
        >
          <span className="eyebrow">WELCOME TO THE LAB</span>
          <h2>Open your workspace</h2>
          <p>
            {demo
              ? "Demo roles use DEMO_PASSWORD from your local .env. Individual accounts use their own password."
              : "Use your individual account. Shared demo accounts are disabled."}
          </p>
          {demo && (
            <label>
              Role
              <select
                aria-label="Role"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              >
                {["pharmacist", "staff", "patient", "administrator"].map(
                  (r) => (
                    <option key={r}>{r}</option>
                  ),
                )}
              </select>
            </label>
          )}
          <label>
            Username
            <input
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </label>
          <label>
            {demo ? "Demo password" : "Password"}
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button className="primary" disabled={busy}>
            Enter workspace
            <ArrowUpRight size={18} />
          </button>
          <p className="notice">
            <ShieldCheck />
            Synthetic demonstration. Pharmacists retain verification and
            dispensing responsibility.
          </p>
        </form>
      </div>
    );
  const visible = cases.filter(
    (c) =>
      (tab !== "Intake queue" || c.kind === "intake") &&
      (tab !== "Escalations" ||
        ["escalated", "clarification", "rejected"].includes(c.state)) &&
      (c.id + c.state + c.patient_id)
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  return (
    <div className="shell">
      <aside>
        <Brand />
        <div className="workspace">
          <span className="avatar">PF</span>
          <div>
            Fictional pharmacy<small>{user.tenant} workspace</small>
          </div>
          <i className="online" />
        </div>
        <div className="nav-title">WORKSPACE</div>
        <nav>
          {["Overview", "Intake queue", "Escalations", "Evaluations"].map(
            (t, i) => (
              <button
                key={t}
                className={tab === t ? "active" : ""}
                onClick={() => setTab(t)}
              >
                {
                  [
                    <LayoutDashboard />,
                    <FileText />,
                    <AlertTriangle />,
                    <FlaskConical />,
                  ][i]
                }
                {t}
              </button>
            ),
          )}
        </nav>
        <div className="sidebar-bottom">
          <div className="lab-note">
            <ShieldCheck />
            <b>Built for review</b>
            <p>Synthetic data only. Every decision leaves evidence.</p>
          </div>
          <div className="profile">
            <span className="avatar">{user.role[0].toUpperCase()}</span>
            <div>
              {user.role}
              <small>{mode} mode</small>
            </div>
            <button aria-label="Sign out" onClick={logout}>
              <LogOut size={18} />
            </button>
          </div>
        </div>
      </aside>
      <main>
        <header>
          <div className="breadcrumb">
            Workspace <ChevronRight size={14} />{" "}
            {user.role === "patient" ? "Patient desk" : tab}
          </div>
          <div className="header-right">
            <span className="synthetic">SYNTHETIC DEMO</span>
            <Badge state={mode + "_mode"} />
          </div>
        </header>
        <div className="content">
          {error && (
            <div className="error" role="alert">
              {error}
              <button onClick={() => setError("")}>Dismiss</button>
            </div>
          )}
          {busy && <small role="status">Working…</small>}
          {user.role === "patient" ? (
            <PatientDesk cases={cases} act={act} open={open} mode={mode} />
          ) : (
            <>
              <div className="page-heading">
                <div>
                  <div className="eyebrow">
                    A LITTLE LESS FRICTION. A LOT MORE CLARITY.
                  </div>
                  <h1>
                    {tab === "Overview" ? "Your pharmacy, in flow." : tab}
                  </h1>
                  <p>
                    Intake, verification and review — connected by evidence.
                  </p>
                </div>
                <button
                  className="primary"
                  disabled={busy}
                  onClick={() => upload.current?.click()}
                >
                  <Upload size={17} />
                  Upload prescription
                </button>
              </div>
              <input
                ref={upload}
                type="file"
                hidden
                accept="application/pdf,image/png,image/jpeg"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file)
                    act(async () => {
                      const form = new FormData();
                      form.append("file", file);
                      form.append("request_key", crypto.randomUUID());
                      const c = await api("/intakes", {
                        method: "POST",
                        body: form,
                      });
                      setSelected(c);
                    });
                  e.target.value = "";
                }}
              />
              {tab === "Evaluations" ? (
                <Evaluations
                  runs={evaluations}
                  act={act}
                  open={open}
                  role={user.role}
                />
              ) : (
                <>
                  <div className="stats">
                    {[
                      ["completed", "Completed requests", <Check />],
                      ["human_review", "Human review", <ClipboardCheck />],
                      ["failed_actions", "Failed actions", <AlertTriangle />],
                      [
                        "duplicate_prevention",
                        "Duplicates prevented",
                        <ShieldCheck />,
                      ],
                    ].map(([key, title, icon]) => (
                      <div className="stat" key={String(key)}>
                        <div>
                          {title}
                          {icon}
                        </div>
                        <strong>
                          {metrics?.measures?.[String(key)]?.value ?? "—"}
                        </strong>
                        <span>Measured {mode} activity</span>
                      </div>
                    ))}
                  </div>
                  <div className="main-grid">
                    <section className="panel">
                      <div className="panel-title">
                        <div>
                          <h2>
                            Request queue <span>{visible.length}</span>
                          </h2>
                          <p>Every request has a next step.</p>
                        </div>
                        <Badge state="live_updates" />
                      </div>
                      <div className="table-controls">
                        <div className="tabs">
                          <button className="chosen">All requests</button>
                        </div>
                        <label className="search">
                          <Search size={16} />
                          <input
                            aria-label="Search cases"
                            placeholder="Search cases…"
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                          />
                        </label>
                      </div>
                      <div className="table-wrap">
                        <table>
                          <thead>
                            <tr>
                              <th>REQUEST</th>
                              <th>PATIENT</th>
                              <th>STATUS</th>
                              <th>UPDATED</th>
                            </tr>
                          </thead>
                          <tbody>
                            {visible.map((c) => (
                              <tr
                                key={c.id}
                                tabIndex={0}
                                onClick={() => open(c.id)}
                                onKeyDown={(e) => {
                                  if (e.key === "Enter") open(c.id);
                                }}
                              >
                                <td>
                                  <span className={"request-icon " + c.kind}>
                                    <FileText size={18} />
                                  </span>
                                  <b>PF-{short(c.id)}</b>
                                  <small>{label(c.kind)}</small>
                                </td>
                                <td>{c.patient_id || "Match pending"}</td>
                                <td>
                                  <Badge state={c.state} />
                                </td>
                                <td>{date(c.updated_at)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      {!visible.length && (
                        <div className="empty">
                          <FileText />
                          <h3>No requests here yet</h3>
                          <p>
                            Upload a synthetic prescription or start a patient
                            refill.
                          </p>
                        </div>
                      )}
                    </section>
                    <div className="side-panels">
                      <section className="panel signals">
                        <div className="panel-title">
                          <h2>
                            <Activity size={18} />
                            Workflow agents
                          </h2>
                        </div>
                        {[
                          ["Intake", "Extract fields and match records"],
                          ["Execution", "Prepare, submit and reconcile"],
                          ["Verification", "Check source and persisted state"],
                        ].map(([a, d], i) => (
                          <div className="agent" key={a}>
                            <span>0{i + 1}</span>
                            <div>
                              <b>{a}</b>
                              <p>{d}</p>
                            </div>
                            <i className="online" />
                          </div>
                        ))}
                        <div className="agent-footer">
                          Bounded tools · durable checkpoints
                        </div>
                      </section>
                      <section className="panel signals">
                        <div className="panel-title">
                          <h2>Operational signals</h2>
                        </div>
                        {metrics?.alerts?.length ? (
                          metrics.alerts.map((a: any) => (
                            <div className="alert" key={a.name}>
                              <b>{a.name}</b>
                              {a.case_ids.map((id: string) => (
                                <button key={id} onClick={() => open(id)}>
                                  {short(id)}
                                </button>
                              ))}
                            </div>
                          ))
                        ) : (
                          <p className="signal-good">
                            <Check size={16} />
                            No active alert thresholds
                          </p>
                        )}
                      </section>
                    </div>
                  </div>
                  <section className="panel measurements">
                    <div className="panel-title">
                      <div>
                        <h2>Measurements you can inspect</h2>
                        <p>
                          Open any metric to inspect its contributing cases.
                        </p>
                      </div>
                    </div>
                    <div className="measurement-grid">
                      {Object.entries(metrics?.measures || {}).map(
                        ([name, m]: any) => (
                          <details key={name}>
                            <summary>
                              <span>{label(name)}</span>
                              <b>
                                {typeof m.value === "number"
                                  ? Number(m.value.toFixed(3))
                                  : m.value}
                              </b>
                              <small>{m.unit}</small>
                            </summary>
                            <div className="metric-cases">
                              {m.case_ids.map((id: string) => (
                                <button key={id} onClick={() => open(id)}>
                                  PF-{short(id)}
                                </button>
                              ))}
                              {!m.case_ids.length && (
                                <small>No contributing cases</small>
                              )}
                            </div>
                          </details>
                        ),
                      )}
                    </div>
                    <p className="fineprint">{metrics?.cost_note}</p>
                    <details>
                      <summary>Provider usage and pricing coverage</summary>
                      <p>
                        Pricing assumptions: {metrics?.pricing_version}.
                        Unpriced calls are unavailable charges, not zero-cost
                        calls.
                      </p>
                      <pre>
                        {JSON.stringify(metrics?.cost_coverage, null, 2)}
                      </pre>
                    </details>
                  </section>
                </>
              )}
            </>
          )}
          <p className="fineprint">
            SYNTHETIC DATA ONLY · Pharmacists retain responsibility for
            prescription verification and dispensing.
          </p>
        </div>
      </main>
      {selected && (
        <CaseDrawer
          c={selected}
          user={user}
          busy={busy}
          act={act}
          update={setSelected}
          close={() => setSelected(null)}
        />
      )}
    </div>
  );
}

function CaseDrawer({
  c,
  user,
  busy,
  act,
  update,
  close,
}: {
  c: Case;
  user: User;
  busy: boolean;
  act: any;
  update: (c: Case) => void;
  close: () => void;
}) {
  const [doc, setDoc] = useState(""),
    [docError, setDocError] = useState(""),
    [fields, setFields] = useState<Record<string, string>>({}),
    [attest, setAttest] = useState(false);
  const [candidates, setCandidates] = useState<any[]>([]),
    [patient, setPatient] = useState(""),
    [reason, setReason] = useState("");
  const dialog = useRef<HTMLElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement;
    dialog.current?.focus();
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
      if (e.key === "Tab") {
        const nodes = dialog.current?.querySelectorAll<HTMLElement>(
          "button:not(:disabled),input:not(:disabled),select,textarea,summary",
        );
        if (!nodes?.length) return;
        const first = nodes[0],
          last = nodes[nodes.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", handler);
    return () => {
      document.removeEventListener("keydown", handler);
      previous?.focus();
    };
  }, []);
  useEffect(() => {
    setAttest(false);
  }, [c.action_hash, c.revision]);
  useEffect(() => {
    let url = "",
      active = true;
    setDoc("");
    setDocError("");
    if (c.kind === "intake")
      fetch("/api/cases/" + c.id + "/document", {
        headers: { Authorization: "Bearer " + bearer },
      })
        .then((r) => {
          if (!r.ok) throw new Error("Source unavailable");
          return r.blob();
        })
        .then((b) => {
          url = URL.createObjectURL(b);
          if (active) setDoc(url);
          else URL.revokeObjectURL(url);
        })
        .catch((e) => setDocError(e.message));
    return () => {
      active = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [c.id]);
  useEffect(() => {
    if (
      c.kind === "intake" &&
      c.state === "clarification" &&
      user.role === "pharmacist"
    )
      api(`/cases/${c.id}/candidates`)
        .then(setCandidates)
        .catch(() => setCandidates([]));
  }, [c.id, c.state]);
  const action = (path: string, body?: any, method?: string) =>
    act(async () => {
      update(await post(`/cases/${c.id}${path}`, body, method));
      setFields({});
    });
  const editable =
    user.role === "pharmacist" && ["review", "clarification"].includes(c.state);
  return (
    <div className="drawer-backdrop">
      <section
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-label="Case details"
        ref={dialog}
        tabIndex={-1}
      >
        <div className="drawer-header">
          <div>
            <div className="eyebrow">CASE PF-{short(c.id)}</div>
            <h2>
              {c.kind === "intake"
                ? "Prescription evidence & review"
                : "Refill request"}{" "}
              <Badge state={c.state} />
            </h2>
          </div>
          <button aria-label="Close case" onClick={close}>
            <X />
          </button>
        </div>
        <div className="drawer-body">
          <div className="notice">
            <ShieldCheck size={18} />
            {c.state === "completed"
              ? "Recorded for pharmacist processing. No medication has been dispensed."
              : "Review source evidence and unresolved fields before approval."}
          </div>
          {c.kind === "intake" && (
            <div className="review-grid">
              <div className="document">
                <h3>Original document</h3>
                {docError ? (
                  <p role="alert">{docError}</p>
                ) : doc ? (
                  c.payload.mime === "application/pdf" ? (
                    <iframe title="Original synthetic prescription" src={doc} />
                  ) : (
                    <img src={doc} alt="Original synthetic prescription" />
                  )
                ) : (
                  <p>Loading source…</p>
                )}
              </div>
              <div>
                <h3>Extracted fields</h3>
                <p>
                  Model confidence is uncalibrated. Inspect the source and
                  confirm uncertain values.
                </p>
                {Object.entries(c.payload.extraction?.fields || {}).map(
                  ([k, f]: any) => (
                    <label className="field" key={k}>
                      <span>
                        {label(k)}
                        <em className={f.confidence < 0.85 ? "uncertain" : ""}>
                          {Math.round(f.confidence * 100)}%{" "}
                          {f.issue && "· " + label(f.issue)}
                        </em>
                      </span>
                      <input
                        value={fields[k] ?? f.value ?? ""}
                        disabled={!editable}
                        placeholder="Missing — correction required"
                        onChange={(e) =>
                          setFields({ ...fields, [k]: e.target.value })
                        }
                      />
                      <small>
                        {f.evidence
                          ?.map((e: any) => `p.${e.page}: ${e.text}`)
                          .join(" · ") || "No source evidence"}
                      </small>
                    </label>
                  ),
                )}
                {Object.keys(fields).length > 0 && (
                  <button
                    className="secondary"
                    disabled={busy}
                    onClick={() =>
                      action(
                        "/fields",
                        { fields, revision: c.revision },
                        "PATCH",
                      )
                    }
                  >
                    Save corrections & invalidate approval
                  </button>
                )}
              </div>
            </div>
          )}
          {editable && (
            <>
              <label>
                Review reason
                <textarea
                  value={reason}
                  maxLength={500}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="Reason for patient resolution or rejection"
                />
              </label>
              {c.state === "clarification" && (
                <>
                  <label>
                    Matching patients
                    <select
                      value={patient}
                      onChange={(e) => setPatient(e.target.value)}
                    >
                      <option value="">Choose after independent review</option>
                      {candidates.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name} · {p.dob} · {p.id}
                        </option>
                      ))}
                    </select>
                  </label>
                  <p>
                    {candidates.length
                      ? "Similar records require explicit pharmacist selection."
                      : "No exact match. Correct the patient name and date of birth from the source."}
                  </p>
                  <button
                    className="secondary"
                    disabled={!patient || reason.length < 5 || busy}
                    onClick={() =>
                      action("/resolve-patient", {
                        patient_id: patient,
                        reason,
                        revision: c.revision,
                      })
                    }
                  >
                    Resolve patient match
                  </button>
                </>
              )}
              <button
                className="text-button"
                disabled={reason.length < 5 || busy}
                onClick={() =>
                  action("/reject", { reason, revision: c.revision })
                }
              >
                Reject unexecuted draft
              </button>
            </>
          )}
          {c.state === "review" && user.role === "pharmacist" && (
            <div className="approval">
              <h3>Pharmacist review</h3>
              <p>
                Approval records an intake draft. It does not authorize
                dispensing.
              </p>
              <code>Action SHA-256: {c.action_hash}</code>
              <label className="check">
                <input
                  type="checkbox"
                  checked={attest}
                  onChange={(e) => setAttest(e.target.checked)}
                />
                I inspected the source and resolved uncertain fields for this
                exact draft.
              </label>
              <button
                className="primary"
                disabled={!attest || busy || Object.keys(fields).length > 0}
                onClick={() =>
                  action("/approve", {
                    action_hash: c.action_hash,
                    attested: attest,
                  })
                }
              >
                <ClipboardCheck size={17} />
                Approve exact draft
              </button>
            </div>
          )}
          {c.payload.extraction?.warnings?.length > 0 && (
            <p className="error">
              Document flags: {c.payload.extraction.warnings.join(", ")}
            </p>
          )}
          {c.result && (
            <div className="result">
              <Check />
              <div>
                <b>{label(c.result.status)}</b>
                <p>Persisted request: {c.result.id}</p>
              </div>
            </div>
          )}
          {c.payload.rejection && (
            <p className="notice">Rejected: {c.payload.rejection.reason}</p>
          )}
          {c.state === "escalated" &&
            ["pharmacist", "administrator"].includes(user.role) && (
              <button
                className="secondary"
                disabled={busy}
                onClick={() => action("/retry")}
              >
                Retry exhausted transaction
              </button>
            )}
          {![
            "completed",
            "escalated",
            "cancelled",
            "rejected",
            "timed_out",
            "execution",
            "verification",
          ].includes(c.state) && (
            <button className="text-button" onClick={() => action("/cancel")}>
              Cancel request
            </button>
          )}
          {c.payload.correction_history?.length > 0 && (
            <details>
              <summary>Field change history</summary>
              {c.payload.correction_history.map((h: any, i: number) => (
                <p key={i}>
                  <b>{label(h.field)}</b>: {h.before || "unknown"} → {h.after} ·{" "}
                  {h.reviewer} · {date(h.at)}
                </p>
              ))}
            </details>
          )}
          <h3>Case timeline</h3>
          <small>Correlation ID: {c.id}</small>
          <div className="timeline">
            {c.events?.map((e) => (
              <details key={e.id}>
                <summary>
                  <span className={"timeline-dot " + e.category} />
                  <div>
                    <b>{label(e.name)}</b>
                    <small>
                      {e.actor} · {date(e.created_at)} ·{" "}
                      {e.duration_ms.toFixed(0)} ms
                    </small>
                  </div>
                  <ChevronRight size={14} />
                </summary>
                <pre>{JSON.stringify(e.evidence, null, 2)}</pre>
                <code>OpenTelemetry trace: {e.trace_id}</code>
                {e.trace_url && (
                  <p>
                    <a href={e.trace_url} target="_blank" rel="noreferrer">
                      Open in configured Jaeger viewer
                    </a>
                  </p>
                )}
              </details>
            ))}
          </div>
          <h3>Retrieved policy evidence</h3>
          {c.payload.policy_summary && (
            <blockquote>
              <b>Cited workflow explanation</b>
              <p>{c.payload.policy_summary.text}</p>
              <small>{c.payload.policy_summary.citations.join(", ")}</small>
            </blockquote>
          )}
          {c.payload.citations?.map((p: any) => (
            <blockquote key={p.document_id}>
              <b>
                {p.document_id} · version {p.version}
              </b>
              <p>{p.passage}</p>
            </blockquote>
          ))}
          <details>
            <summary>Agent assessments and proposed action</summary>
            <pre>
              {JSON.stringify(
                {
                  action: c.action,
                  approval: c.payload.approval,
                  decisions: c.payload.agent_decisions,
                  mode: c.payload.usage?.mode,
                  tool_calls: c.tool_calls,
                },
                null,
                2,
              )}
            </pre>
          </details>
        </div>
      </section>
    </div>
  );
}

function PatientDesk({
  cases,
  act,
  open,
  mode,
}: {
  cases: Case[];
  act: any;
  open: (id: string) => void;
  mode: string;
}) {
  const [message, setMessage] = useState("I would like to request a refill."),
    [current, setCurrent] = useState<Case | null>(null),
    [dob, setDob] = useState(""),
    [code, setCode] = useState(""),
    [confirmed, setConfirmed] = useState(false),
    [rx, setRx] = useState(""),
    [rxConfirmed, setRxConfirmed] = useState(false),
    [options, setOptions] = useState<any[]>([]);
  const [recording, setRecording] = useState(false),
    [voiceBusy, setVoiceBusy] = useState(false),
    [notice, setNotice] = useState(""),
    [fault, setFault] = useState(false),
    [submitting, setSubmitting] = useState(false);
  const recorder = useRef<MediaRecorder | null>(null),
    stream = useRef<MediaStream | null>(null),
    requestKey = useRef(crypto.randomUUID()),
    submitLock = useRef(false),
    chunks = useRef<Blob[]>([]);
  useEffect(() => {
    if (current) {
      const c = cases.find((x) => x.id === current.id);
      if (c) setCurrent(c);
    }
  }, [cases]);
  useEffect(
    () => () => {
      stream.current?.getTracks().forEach((t) => t.stop());
    },
    [],
  );
  async function say(text: string) {
    try {
      if (mode === "fixture") {
        if ("speechSynthesis" in window)
          speechSynthesis.speak(new SpeechSynthesisUtterance(text));
        return;
      }
      const r = await fetch("/api/voice/speak", {
        method: "POST",
        headers: {
          Authorization: "Bearer " + bearer,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ text }),
      });
      if (!r.ok) throw new Error();
      const url = URL.createObjectURL(await r.blob());
      const audio = new Audio(url);
      audio.onended = () => URL.revokeObjectURL(url);
      audio.onerror = () => URL.revokeObjectURL(url);
      await audio.play();
    } catch {
      setNotice(
        "Speech playback unavailable. Continue with the text instructions.",
      );
    }
  }
  async function record() {
    if (recording) {
      recorder.current?.stop();
      setRecording(false);
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      setNotice(
        "Microphone unavailable. Use text; HTTPS or localhost is required.",
      );
      return;
    }
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({
        audio: true,
      });
    } catch {
      setNotice(
        "Microphone permission denied or device unavailable. You can type your request.",
      );
      return;
    }
    const r = new MediaRecorder(stream.current);
    recorder.current = r;
    chunks.current = [];
    r.ondataavailable = (e) => {
      if (e.data.size) chunks.current.push(e.data);
    };
    r.onstop = () => {
      stream.current?.getTracks().forEach((t) => t.stop());
      setRecording(false);
      setVoiceBusy(true);
      act(async () => {
        try {
          const blob = new Blob(chunks.current, {
            type: r.mimeType.split(";")[0],
          });
          if (blob.size < 12) {
            setNotice("No audio captured. Record again or type your request.");
            return;
          }
          const form = new FormData();
          form.append("file", blob, "recording.webm");
          const result = await api("/voice/transcribe", {
            method: "POST",
            body: form,
          });
          setMessage(result.text);
          setNotice(result.notice);
          await say(
            "Review and edit the transcript, then confirm your identity and prescription.",
          );
        } catch (e) {
          setNotice(
            "Transcription failed. Your text request is still available; retry recording or type instead.",
          );
          throw e;
        } finally {
          setVoiceBusy(false);
        }
      });
    };
    r.start();
    setRecording(true);
    setTimeout(() => {
      if (r.state === "recording") r.stop();
    }, 60000);
  }
  async function start() {
    if (submitLock.current) return;
    submitLock.current = true;
    setSubmitting(true);
    try {
      const c = await post("/refills", {
        message,
        request_key: requestKey.current,
        fault: fault ? "timeout_after_write" : null,
      });
      setCurrent(c);
      requestKey.current = crypto.randomUUID();
      setConfirmed(false);
      setRxConfirmed(false);
      await say(
        "Please confirm your synthetic date of birth and verification code.",
      );
    } finally {
      submitLock.current = false;
      setSubmitting(false);
    }
  }
  async function load(c: Case) {
    setCurrent(c);
    if (c.payload.identity_verified)
      setOptions(await api(`/cases/${c.id}/prescriptions`));
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">YOUR FICTIONAL PATIENT DESK</div>
          <h1>Let’s take the next step.</h1>
          <p>
            Request a refill by text or microphone. A pharmacist remains
            responsible for your prescription.
          </p>
        </div>
        <Badge state={mode + "_mode"} />
      </div>
      <div className="patient-grid">
        <section className="panel conversation">
          <div className="panel-title">
            <h2>
              <Activity />
              Refill assistant
            </h2>
          </div>
          <div className="chat-bubble">
            I can help record a synthetic refill request. We’ll confirm identity
            and prescription first.
          </div>
          <label>
            Your request
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              maxLength={2000}
            />
          </label>
          <div className="row">
            <button
              className="secondary"
              disabled={voiceBusy}
              onClick={() => act(record)}
            >
              {recording ? <Square size={18} /> : <Mic size={18} />}
              {recording ? "Stop recording" : "Use microphone"}
            </button>
            <button
              className="primary"
              disabled={submitting || recording || voiceBusy || !message.trim()}
              onClick={() => act(start)}
            >
              Start refill
              <ArrowUpRight size={17} />
            </button>
          </div>
          {voiceBusy && <p role="status">Transcribing recorded turn…</p>}
          {notice && (
            <p className="notice" role="status">
              {notice}
            </p>
          )}
          <small>
            You may correct the transcript in the request field. Text remains
            usable if audio fails.
          </small>
          <label className="check">
            <input
              type="checkbox"
              checked={fault}
              onChange={(e) => setFault(e.target.checked)}
            />
            Demo fault: lose the response after a successful write
          </label>
          {current && (
            <div className="patient-step">
              <Badge state={current.state} />
              {current.state === "identity_verification" && (
                <>
                  <h3>Confirm simulated identity</h3>
                  <p>
                    Fixture account: Avery Morgan · 1988-04-12 · code 246810.
                    Individual accounts use their assigned synthetic identity.
                  </p>
                  <label>
                    Date of birth
                    <input
                      type="date"
                      value={dob}
                      onChange={(e) => setDob(e.target.value)}
                    />
                  </label>
                  <label>
                    Demo verification code
                    <input
                      value={code}
                      inputMode="numeric"
                      onChange={(e) => setCode(e.target.value)}
                    />
                  </label>
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={confirmed}
                      onChange={(e) => setConfirmed(e.target.checked)}
                    />
                    I confirm these identifiers, including any voice
                    transcription.
                  </label>
                  <button
                    className="primary"
                    onClick={() =>
                      act(async () => {
                        const r = await post(`/cases/${current.id}/identity`, {
                          dob,
                          code,
                          confirmed,
                        });
                        setCurrent(r.case);
                        setOptions(r.prescriptions);
                      })
                    }
                  >
                    Verify identity
                  </button>
                </>
              )}
              {current.state === "clarification" &&
                current.payload.identity_verified && (
                  <>
                    <h3>Confirm the prescription</h3>
                    <label>
                      Prescription
                      <select
                        value={rx}
                        onChange={(e) => setRx(e.target.value)}
                      >
                        <option value="">Select a prescription</option>
                        {options.map((o) => (
                          <option key={o.id} value={o.id}>
                            {o.medication} · {o.strength} · {o.id}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="check">
                      <input
                        type="checkbox"
                        checked={rxConfirmed}
                        onChange={(e) => setRxConfirmed(e.target.checked)}
                      />
                      This is the prescription I am requesting.
                    </label>
                    <button
                      className="primary"
                      disabled={!rx || !rxConfirmed}
                      onClick={() =>
                        act(async () =>
                          setCurrent(
                            await post(`/cases/${current.id}/select`, {
                              prescription_id: rx,
                              confirmed: rxConfirmed,
                            }),
                          ),
                        )
                      }
                    >
                      Record refill request
                    </button>
                  </>
                )}
              {current.state === "completed" && (
                <>
                  <h3>Your request is recorded.</h3>
                  <p>
                    A pharmacist will process it. No medication has been
                    dispensed.
                  </p>
                </>
              )}
              {[
                "record_lookup",
                "preparation",
                "execution",
                "verification",
              ].includes(current.state) && (
                <p role="status">
                  Processing and checking saved state. You can leave and resume
                  from your requests.
                </p>
              )}
              {["escalated", "timed_out", "cancelled", "rejected"].includes(
                current.state,
              ) && (
                <p>
                  This request needs staff follow-up. Open its history for the
                  reason.
                </p>
              )}
              <button className="text-button" onClick={() => open(current.id)}>
                Inspect request history
              </button>
            </div>
          )}
        </section>
        <section className="panel conversation">
          <h2>Your requests</h2>
          {cases.length ? (
            cases.map((c) => (
              <div className="patient-request" key={c.id}>
                <b>PF-{short(c.id)}</b>
                <small>{date(c.created_at)}</small>
                <Badge state={c.state} />
                <button onClick={() => act(() => load(c))}>Resume</button>
                <button onClick={() => open(c.id)}>History</button>
              </div>
            ))
          ) : (
            <p>No requests yet. Start with text or microphone.</p>
          )}
          <p className="notice">
            <ShieldCheck />
            Synthetic records only. Identity confirmation never authorizes
            dispensing.
          </p>
        </section>
      </div>
    </>
  );
}

function Evaluations({
  runs,
  act,
  open,
  role,
}: {
  runs: any[];
  act: any;
  open: (id: string) => void;
  role: string;
}) {
  const [chosen, setChosen] = useState<any>(null),
    [sample, setSample] = useState(""),
    [score, setScore] = useState(3),
    [note, setNote] = useState(""),
    [agreement, setAgreement] = useState<any>(null);
  return (
    <section className="panel evaluation">
      <div className="panel-title">
        <h2>Evaluation evidence</h2>
        <Badge state="synthetic_evaluation" />
      </div>
      <p>
        Fixture tests, real transport acceptance and live model evidence are
        separate. Calibration remains pending without independent human labels
        and live judge outputs.
      </p>
      {!runs.length && (
        <p className="empty">No evaluation reports have been imported yet.</p>
      )}
      {runs.map((run) => (
        <details className="eval-run" key={run.id}>
          <summary>
            {date(run.created_at)} · {run.report.mode} ·{" "}
            {run.report.dataset_version || "Acceptance"}
          </summary>
          <p>{run.report.transport}</p>
          <pre>
            {JSON.stringify(run.report.summary || run.report.checks, null, 2)}
          </pre>
          <button
            className="secondary"
            onClick={() => {
              setChosen(run);
              setSample("");
              act(async () =>
                setAgreement(await api(`/evaluations/${run.id}/agreement`)),
              );
            }}
          >
            Inspect scenarios and labels
          </button>
        </details>
      ))}
      {chosen && (
        <div className="approval">
          <h3>Run {short(chosen.id)}</h3>
          <p>
            Agreement: {agreement?.calibration || "pending"} · paired labels:{" "}
            {agreement?.paired_labels ?? 0}
          </p>
          <label>
            Scenario
            <select value={sample} onChange={(e) => setSample(e.target.value)}>
              <option value="">Select a scenario</option>
              {chosen.report.rows?.map((r: any) => (
                <option
                  key={r.sample_id || r.scenario_id}
                  value={r.sample_id || r.scenario_id}
                >
                  {r.sample_id || r.scenario_id} ·{" "}
                  {r.success ? "passed" : "failed"}
                </option>
              ))}
            </select>
          </label>
          {sample &&
            (() => {
              const row = chosen.report.rows.find(
                (r: any) => (r.sample_id || r.scenario_id) === sample,
              );
              return (
                <>
                  <pre>{JSON.stringify(row, null, 2)}</pre>
                  {row.case_id && (
                    <button onClick={() => open(row.case_id)}>
                      Open contributing case
                    </button>
                  )}
                </>
              );
            })()}
          {["pharmacist", "administrator"].includes(role) && (
            <>
              <label>
                Independent communication score (1–5)
                <input
                  type="number"
                  min={1}
                  max={5}
                  value={score}
                  onChange={(e) => setScore(Number(e.target.value))}
                />
              </label>
              <label>
                Review notes
                <textarea
                  value={note}
                  maxLength={1000}
                  onChange={(e) => setNote(e.target.value)}
                />
              </label>
              <button
                className="primary"
                disabled={!sample}
                onClick={() =>
                  act(async () => {
                    await post(`/evaluations/${chosen.id}/labels`, {
                      scenario_id: sample,
                      score,
                      note,
                    });
                    setAgreement(
                      await api(`/evaluations/${chosen.id}/agreement`),
                    );
                  })
                }
              >
                Save attributable human label
              </button>
            </>
          )}
        </div>
      )}
    </section>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
