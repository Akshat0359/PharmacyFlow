# Security model and OWASP mapping

This is a synthetic-data demonstration, not a production pharmacy, regulated medical system, or security certification. Pharmacists retain responsibility for prescription verification and dispensing decisions. No real patient data is needed or appropriate.

Mapping reviewed against the official [OWASP GenAI LLM Top 10 2026](https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/) and [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/), consulted November 12–13, 2026. The controls and gaps below describe this implementation, not an OWASP endorsement.

## LLM risks

| Risk | Implemented control | Evidence | Remaining gap |
|---|---|---|---|
| LLM01 Prompt injection | Documents/passages are data; models receive no tools; mandatory code gates | adversarial acceptance document; `test_missing_conflicting_and_injection` | Live model adversarial evaluation unverified |
| LLM02 Sensitive disclosure | Authenticated tenant/patient scope; allowlisted telemetry; no raw browser network archives | cross-patient/tenant and audit-redaction tests | Individual deployable accounts with Argon2 and revocation; no managed identity/MFA or encrypted application fields |
| LLM04 Supply chain | Python/npm locks; versioned corpus; reproducible container inputs | `uv.lock`, `package-lock.json`, CI | Images/actions use version tags, not verified digests; no SBOM/signing pipeline |
| LLM05 Poisoning | Released policy hash allowlist; missing/modified corpus fails closed | modified, missing and contradictory policy tests | A compromised source release can change both content and trusted hashes |
| LLM10 Output handling | Pydantic validation; React escaping; escaped mock HTML; source quote checks | malicious uploads, source mismatch, invalid citation tests | No independent malware scanning service or image OCR verifier |
| LLM03 Excessive agency | Agent-specific tools; per-case budget; exact action approval; fixed browser origin | tool-budget, role, approval and mock write tests | Worker signing secret is shared across trusted services |
| LLM08 Hidden context exposure | No credentials in prompts; credentials remain server-side | provider contract captures and trace allowlist | A model may disclose non-secret prompt text; this is not an authorization boundary |
| LLM09 Vector/embedding weaknesses | Tenant/version filters; trusted corpus hashes; explicit embedding reindex | retrieval tests and separate retrieval report | PostgreSQL/live embedding path not locally executed |
| LLM07 Misinformation | Null/uncertain extraction; evidence beside source; mandatory intake review; safe status wording | extraction accuracy report and correction acceptance | No clinical accuracy guarantee; fixture model results do not predict live accuracy |
| LLM06 Unbounded consumption | Upload/pixel/page limits, model output limits, queue attempts, case tool budget, spend alerts | malicious upload/audio, retries, budget tests | Persistent voice/login limits and conservative call reservations implemented; provider invoices can exceed an incorrectly configured reservation, so provider-side limits are still required |

## Agentic risks

| Risk | Implemented control and evidence | Remaining gap |
|---|---|---|
| ASI01 Goal hijack | Fixed state graph and no document-driven tool dispatch; injection stays at review in acceptance | No guarantee against all model-generated misleading explanations |
| ASI02 Tool misuse | MCP signed case/agent capabilities; read-only tools cannot write; mock permits only signed exact actions | MCP secret compromise gives trusted-service authority |
| ASI03 Identity/privilege abuse | Server resolves users; patient cannot select another patient's prescription; short-lived capabilities | Synthetic DOB/code verification is intentionally not real identity assurance |
| ASI04 Agentic supply chain | No dynamic skill/plugin installation; dependencies locked; policy release integrity checked | Dependency vulnerability scanning/signatures remain deployment work |
| ASI05 Unexpected code execution | No eval/shell tools; fixed browser origin; unsafe HTML/PDF active content rejected | File parsers and Chromium still require patching and isolation |
| ASI06 Memory/context poisoning | Case-scoped durable state; trusted policy versions; no cross-case conversational memory | Host/database administrator can alter stored state |
| ASI07 Inter-agent communication | Typed messages, signed tenant/case context, restricted MCP tools, correlation audit | Internal Compose traffic uses HTTP; no service mTLS |
| ASI08 Cascading failures | Bounded retries, leases, deadlines, escalation, durable reconciliation; actual killed-worker acceptance | Single-host database outage stops the whole demo; no HA or circuit-breaker service |
| ASI09 Human-agent trust exploitation | Synthetic labels, source review, explicit attestation, action-digest approval, transparent fixture metrics | UI cannot prevent inattentive review; judge calibration awaits human labels |
| ASI10 Rogue agents | Fixed responsibilities, tool budgets, no self-modification, post-write independent verifier | Single-agent fixture parity does not validate autonomous agent containment |

## Boundaries and operational notes

- Never expose `.env`, database ports, MCP, trace storage or scoped transaction tokens publicly. Cloud Caddy publishes only the application. Mock viewer cookies are local demo sessions; use HTTPS and secure cookies if exposing that service elsewhere.
- Local DEMO_MODE=true enables generated role accounts. The cloud override sets DEMO_MODE=false, rejecting those accounts even if they remain in an upgraded database. Individual accounts use Argon2 hashes; logout revokes all app/viewer sessions for that account through a version counter. Login-source and voice limits share database counters. MFA and managed identity remain absent. The mock viewer remains internal and read-only.
- Approval allows a draft/request to be recorded, never medication dispensing. An exact pending action digest prevents duplicate pending mock requests even if a client sends a second idempotency key. Because the mock has no fulfilment lifecycle, the same pending action cannot be requested again until it is retired; real pharmacies need richer reconciliation rules.
- Retention removes expired terminal case data/checkpoints and preserves a minimal purge event. Backups and exported evaluation reports need an operator-defined retention policy. Trace/log files contain allowlisted metadata. Provider usage rows follow configured retention; operators must rotate exported JSONL and process logs.
- Tenant scoping is enforced in application code. PostgreSQL row-level security, separate database credentials per service, immutable audit storage and an independent authorization service remain hardening work.
- All locally observed verification is recorded in `reports/`. Do not infer a completed cloud deployment or successful live provider call from configuration or mocked contract tests.

## Continuation verification

The 2026 LLM guidance changes risk ordering and broadens hidden-context exposure; this matrix uses that edition, not the previous 2025 identifiers. Reviewed official PDF: https://genai.owasp.org/download/56857/?tmstv=1785822482 (consulted November 13, 2026). Risk names are attributed to OWASP; implementation descriptions and tests are project-specific. No endorsement or certification is implied.

New controls: job ownership is fenced at MCP invocation, graph commit and mock write; the mock holds the application lease lock through its own atomic idempotent commit. Approvals bind case, action hash, revision, reviewer and expiry; expiry returns an unexecuted intake to review. Browser requests are restricted to the configured mock origin. Schema-validated live execution and verification assessments have no direct tools.

Evidence: `test_fencing_accounts.py` covers competing claims, stale graph results, stale browser capabilities, concurrent approvals, expired approvals and individual-account revocation. `test_operational.py` covers atomic spend reservations, unpriced usage, redaction, invalid vectors, policy effective dates and alert recovery. Actual MCP acceptance tests reject wrong tenant, wrong role, wrong agent and expired capability. Expanded browser acceptance includes wrong patient, slow page, absent element, browser disconnect and successful write with a lost response.

Known limits: unknown-image fixture extraction is deliberately absent; live image/audio injection outcomes are unverified until paid evaluations run. Source screenshots require human inspection. The mock shares trusted service secrets and database access; it demonstrates invariants rather than a production pharmacy security architecture.
