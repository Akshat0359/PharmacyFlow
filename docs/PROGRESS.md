# Implementation log

Scope: build in this folder only; no commits, pushes, or contributor attribution.
Repository inspection: local folder empty; GitHub contents API reports an empty repository.
Sapphire-specific instructions do not apply to this PharmacyFlow project.

## Milestones and gates
1. Durable refill vertical slice: typed state, tenant authentication, persistent queue, mock UI transaction, reconciliation test.
2. Multimodal intake and interfaces: evidence extraction, pharmacist correction/approval, patient text and recorded voice.
3. Agent boundary controls: MCP server/client, hybrid policy retrieval, adversarial checks, audit and tracing.
4. Reproducible quality: held-out scenarios, repeated baseline/multi-agent comparison, human judge calibration UI.
5. Delivery: Compose, migrations, CI, cloud instructions, full local acceptance and evidence matrix.

Execution environment: Windows, uv and Node available; Docker/npm absent on PATH at initial inspection.
Local SQLite development is an explicit fallback; Compose targets PostgreSQL/pgvector.
Do not report SQLite verification as PostgreSQL verification, or fixture results as live model results.

## Resumption snapshot — November 13, 2026

All five implementation milestones are delivered. Backend, React UI, mock pharmacy ledger, real MCP/Playwright integration, leased worker, evidence/review, hybrid retrieval, provider adapters, observability, adversarial tests, evaluations, deployment configuration and documentation are present. Locally executable checks pass; external infrastructure/provider verification remains explicitly pending.

Verified environment: bundled Python 3.12 in `.venv-bundled`; `.venv` was an unsuccessful Python 3.14 attempt and is ignored. Native DLL policy required a compatible locked LangGraph/checkpoint/serializer set. Do not upgrade those independently. `uv.lock` is generated with uv 0.12.18; Docker/CI use the same uv version. Node is available, npm is local at `.tools/npm/package/bin/npm-cli.js`. Chromium is in `.tools/browsers`. All generated project/runtime files stay in this folder.

Final evidence: **39 unit/integration tests passed**; **360 fixture evaluation runs passed expected outcomes**; extraction accuracy **69.44%** before scripted corrections. Retrieval-only 20-query run: recall@3 **100%**, MRR **0.95**, citation integrity **100%**. Optimistic concurrency prevents stale workers from overwriting cancellation. Judge pairing/calibration is tested with synthetic test labels, but real judge calibration remains pending.

**Full acceptance passed**, including uncertain successful write → timeout → killed/restarted worker → one persisted request; scanned pharmacist correction; adversarial document; expired sessions; changed selectors; staff queue/detail and sign-out; synthetic microphone capture/upload; explicit transcript/identity/prescription confirmation; completed patient refill; mobile layout; separate mock ledger. `reports/acceptance.json` is the authoritative final report. Screenshots are preserved in `docs/screenshots/`.

Finalization commands (use this Python environment on this machine):
```
.\.venv-bundled\Scripts\python.exe -m pytest -q --basetemp data\pytest-local --junitxml reports\tests.xml
.\.venv-bundled\Scripts\python.exe scripts\acceptance.py
.\.venv-bundled\Scripts\python.exe -m evaluation.run --trials 3
.\.venv-bundled\Scripts\python.exe -m evaluation.retrieval
.\.venv-bundled\Scripts\python.exe scripts\validate_deployment.py
.\.venv-bundled\Scripts\python.exe scripts\report_results.py
node .tools\npm\package\bin\npm-cli.js run build --prefix frontend
```

Windows sandbox blocks service sockets and the default pytest temp directory; previous authorized runs used escalation and project-local temp files. One earlier escalation failed due to approval-service usage limits; user resumed the task and later checks were authorized successfully.

No Docker executable is installed, so container/PostgreSQL/Jaeger execution cannot be claimed as locally verified. Live providers/judge and cloud provisioning require credentials/resources and remain unverified. Source has not been committed or pushed, and no contributor attribution was added.

The final TypeScript/Vite production build and static deployment validation passed. `docs/RESULTS.md` is generated from the actual JSON/XML reports. The local supervisor was started for user inspection at http://localhost:8000 (mock ledger at :8001); if stopped, rerun `scripts/dev.py` with the verified environment. Credentials remain in `.env` and were not printed into the chat.


## Continuation completion — November 15, 2026

This snapshot supersedes the earlier implementation-complete statement where evidence or controls changed. The user explicitly selected **fixture results and documented live steps**. No paid calls, commits, pushes, or contributor attribution were made. This remains the only project folder used.

Audit: original reports copied unchanged to `reports/historical/original-v1/`; original 39-test suite, frontend build, retrieval and acceptance reproduced. Docker remains absent (`reports/runtime.json`). Source was not a Git checkout. Sapphire-only instructions do not apply to this project.

Delivered since that snapshot:
- Content-only live document preparation with bounded rasterization, mixed digital/scanned pages, rotation/EXIF normalization, strict schema, source quote checks and PDF-derived boxes. Known-hash answers isolated in `fixture_provider.py`. Fingerprint/context deduplication, reviewer/value history, explicit patient ambiguity resolution, rejection and approval expiry.
- Unique claim tokens and lease fencing at MCP, final graph commit and mock write. Competing workers, stale browser/worker results, concurrent approvals and expired approval tests. Retrieval runs off the worker event loop so live embedding waits do not starve lease heartbeats.
- Model-driven live execution/verification assessments with validated contracts and no model tool authority. Mandatory application gates apply in both architectures.
- Individual deployable accounts, Argon2, session-version revocation, disabled demo accounts in cloud configuration, persistent voice/login limits, additive migrations 002–004, stronger PDF active-content rejection and fixed browser-origin routing.
- Versioned/effective policy ingestion, 64-dimensional finite vector checks, provider reindex, expanded retrieval negatives; cost ledger and persistent total/run reservations with explicit unknown pricing; stage/review/correction/queue metrics, tested alerts, common case trace correlation and Jaeger links.
- Original 60-scenario evaluation preserved; added 60 workflow scenarios and 60 unseen documents. Fixture/live/real-transport evidence levels and explicit live skip reports. PostgreSQL acceptance and isolated two-database restore checks wired into CI but unexecuted here.

Final measured checks: **60 tests passed**; TypeScript/Vite build and Ruff passed. **Full acceptance passed**, including four actual MCP rejection scopes, runtime-generated unseen digital intake, scan correction, adversarial document, post-write timeout/restart reconciliation, six bounded UI failure conditions, synthetic microphone capture and desktop/mobile screens. Acceptance cases/events imported into the main dashboard successfully. Screenshots refreshed in `docs/screenshots/`.

Evaluation: **720/720 expected workflow outcomes** across original and v2 suites. Before scripted corrections: original **69.44%**, v2 **47.22%** field accuracy. No measured multi-agent quality gain. Separate unseen extraction: **120 trials**, explicitly poor fixture performance on unsupported image/layout inputs. Retrieval: 40 positive queries, **90% recall@3**, MRR **0.8417**, citation integrity **100%**; 20 negatives, **65% abstention**. Do not hide those failures or extrapolate to live/clinical quality. Judge calibration remains pending.

Recovered failures: deduplication initially reused identical scan images across evaluation trials; distinct encounter contexts now isolate trials. The failed intermediate evaluation is retained in `reports/historical/dedup-context-regression.json`. MCP tool rejections were wrapped by AnyIO task groups; the client now raises its application rejection after transport cleanup, verified over real MCP. Isolated acceptance imports now use run-scoped document contexts. A Windows encoding failure during a UI edit was repaired and the final UI rebuilt/browser-verified.

Remaining external verification: Docker image startup, PostgreSQL/pgvector/checkpoint restart, Jaeger, cloud/TLS and backup restoration; paid provider quality/audio/judge runs; independent human labels. `docs/GAPS.md` gives precise acceptance criteria and commands. No credentials are needed for the verified fixture path. Do not enable paid calls without a new explicit user budget authorization.

Resume with Python 3.12 `.venv-bundled` on this host, local npm `.tools/npm/package/bin/npm-cli.js`, and Chromium `.tools/browsers`. Primary README setup remains portable. Run additive migrations before starting `scripts/dev.py`. Source locks were reused; no dependency upgrade was needed. Windows socket tests require permitted execution and project-local pytest basetemp. Current reports, not old prose totals, are authoritative.

Final handoff: updated local supervisor restarted; API /health and /ready return fixture mode, demo_accounts=true and SQLite ready, and mock /health passes. The final monitoring/reliability subset also passed (15 tests). Open http://localhost:8000; credentials remain in .env. No paid calls were made.
