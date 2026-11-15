# Required-area coverage matrix

Status distinguishes implementation from local execution. Commands use Python 3.12. The updated [continuation matrix](GAPS.md) records new controls, current evidence levels, measured weaknesses and remaining acceptance criteria; the table below also preserves the original architecture mapping.

| Area | Implemented code | Visible behavior | Verification evidence / boundary |
|---|---|---|---|
| 1. Multimodal AI | `providers.py`, upload/voice endpoints, fixture documents | Side-by-side source, values, confidence and evidence; corrections; recorded microphone and speech response adapters | Extraction/audio/source tests; scanned correction acceptance. Fixture scan lookup is deterministic; live OCR/audio calls unverified without credentials |
| 2. Agentic workflows | `workflow.py`, `worker.py`, `models.py`, LangGraph checkpoints | Explicit states, timeline, review resume, cancellation, retries, timeout and escalations | Lease/checkpoint/timeout tests; real timeout-after-write and process restart acceptance |
| 3. Multi-agent systems | Intake/Execution/Verification classes, typed contracts, scoped tool permissions; single controller mode | Agent actor names and evidence in timeline; baseline comparison | `evaluation.run --trials 3`; same data/tools/models. Fixture quality parity, not a demonstrated live-model improvement |
| 4. RAG | `retrieval.py`, versioned SOP corpus, PostgreSQL FTS/vector migration, `reindex.py`, cited `policy_summary` | Versioned passages and cited explanation in case drawer | `evaluation.retrieval`; outdated/missing/contradictory/modified corpus tests. SQLite fallback measured; PG/live embeddings pending |
| 5. MCP + computer use | `mcp_server.py`, `mcp_client.py`, `tool_service.py`, `browser.py`, `mock_app.py` | Separate mock transaction form and authenticated persisted ledger | Actual MCP Streamable HTTP + Chromium transactions/readback; expired sessions and changed selectors bounded; ambiguous match test |
| 6. Safety/security | `security.py`, authorization/approval gates, upload limits, telemetry allowlist, retention | Authenticated roles; source attestation; synthetic labels; escalations | Cross-tenant/patient, unauthorized write, injection, budget, approval, redaction, retention tests; `SECURITY.md` maps OWASP and gaps |
| 7. Deployment | Compose, Dockerfile, Alembic, seed, CI, Caddy cloud override | Health/readiness; persisted cases survive worker restart | `validate_deployment.py` static checks; local no-Docker runner. Docker/PG/Jaeger and cloud provisioning unverified on this host |
| 8. Monitoring | `telemetry.py`, event table, metrics endpoint, threshold alerts | Inspectable metric cards, contributing cases, actor/evidence/trace timeline, failures and queue age | Metrics test and acceptance audit/timing. Local OTel spans; Jaeger configuration not run here. Costs are estimates; speech/embedding billing excluded |
| 9. Evaluation | 60 held-out scenarios, repeated harness, retrieval-only harness, versioned judge rubric, labels API | Evaluation table, raw scenario result, human score and agreement | `reports/evaluation.json`, `reports/retrieval.json`, `reports/tests.xml`, `reports/acceptance.json`. Fixture and live labeled separately; judge calibration pending |

## Acceptance trace

`python scripts/acceptance.py` owns isolated services/ports (8010–8012) and its own worker process. It verifies:

1. Authenticated fictional patient → confirmed identity → explicit prescription selection.
2. Real MCP tools and visible mock UI write.
3. Deliberate response timeout **after** commit.
4. Kill the owned worker; restart a fresh process; load persistent state.
5. Reconcile saved action; assert exactly one request before and after restart.
6. Accurate patient status, attributable audit and timing.
7. Scanned prescription: premature approval rejected, pharmacist correction, approved exact draft, UI save/readback.
8. Adversarial document stays at review and causes no unauthorized tool use/write.
9. Expired UI session and changed selector stop after three attempts without a write.
10. Browser checks for staff queue/detail, sign-out, actual capture/upload from a synthetic Chromium microphone, transcript confirmation, patient refill completion, narrow viewport and mock ledger.

The report is authoritative: a passed subcheck does not imply the full command passed. Failed earlier exploratory runs were used to fix dependency compatibility, tool argument collision and browser-test synchronization; current reports are regenerated after fixes.

## Continuation verification

See `GAPS.md` for the current nine-area status. New executable evidence includes `test_unseen_documents.py`, `test_fencing_accounts.py`, `test_operational.py`, `test_migrations.py`, expanded provider contracts, and actual MCP scope rejection/browser fault acceptance. Current reports distinguish 720 repeated workflow runs from the 120 extraction-only trials; scripted pharmacist corrections are not independent human labels.
