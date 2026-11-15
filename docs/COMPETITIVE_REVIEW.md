# Competitive review and improvement roadmap

Reviewed 2026-11-15. Scope: a representative comparison of related public GitHub repositories, not an exhaustive search of GitHub or a ranking of the owner's other projects. Competitor observations below come from their published READMEs; their software and benchmarks were not independently run. Feature descriptions are not verified performance claims.

## Related projects

| Project and source | Documented emphasis | Implication for PharmacyFlow |
| --- | --- | --- |
| [PharmaOps](https://github.com/FacuEM/pharmaops) | Spanish shortage feeds, CIMA retrieval, conversational agents and purchase orders; describes 30 evaluation examples | A focused operational story and real reference-data integration are useful differentiators. PharmacyFlow currently uses fictional procedures and a mock pharmacy. |
| [PharmaChat](https://github.com/El-denary/PharmaChat) | Four-agent image/text medicine assistant, local embeddings and persistent conversations | Make agent activity visible and conversational interactions understandable; backend agent count alone does not demonstrate value. |
| [g-scan-rx](https://github.com/daniel-caso-github/g-scan-rx) | Prescription extraction, catalog verification, hybrid retrieval/reranking, MCP and explicit human confirmation | Field review and MCP are shared capabilities, not unique advantages. Reliable extraction and measured abstention matter more than feature count. |
| [Agentic-AI-Pharmacy-System](https://github.com/Amolika123/Agentic-AI-Pharmacy-System) | Conversational ordering, OCR, refill prediction, tracing, CSV-backed records | PharmacyFlow's durable transactional workflow and recovery demonstration are useful portfolio distinctions; this does not establish better conversation quality. |

## Evidence-based assessment

PharmacyFlow is a substantial synthetic workflow-engineering portfolio project. Its strongest demonstrated scenario is a real browser write followed by timeout, worker interruption, status reconciliation and duplicate avoidance. Real MCP permission checks, review-bound approvals, source evidence and inspectable reports support that story.

It is not demonstrably the best project overall. Local tests passed (60), and two fixture workflow suites produced 720 expected outcomes, but those outcomes include scripted pharmacist corrections. Original and v2 pre-correction field accuracy were 69.4% and 47.2%. Retrieval recall@3 was 90%; negative-query abstention was only 65%. The same fixture scenarios showed no multi-agent quality advantage. Live provider evaluations and human judge calibration are pending. PostgreSQL/Compose and cloud operation have not been verified on the local host. See [results](RESULTS.md) and [gaps](GAPS.md).

## Prioritized next work

1. **Prove reproducibility.** Run the published CI on a fresh Linux checkout, including PostgreSQL checkpoints, actual MCP/browser acceptance, interrupted workers and backup/restore. Resolve failures and link the successful run and commit. Local SQLite success is insufficient evidence for the production-shaped stack.
2. **Make the agent behavior obvious.** Add a visible Intake / Execution / Verification progress view with each agent's input summary, allowed tool, result, evidence and next action. Provide a three-minute narrated demo of the timeout/restart scenario. Keep fixture/live labels prominent. Success: a new reviewer can explain the handoffs and approval boundary without reading source.
3. **Measure real model behavior when separately authorized.** Use the existing budget-controlled live commands on held-out documents and workflows, including actual microphone-to-transcription-to-speech. Record exact models, prompts, token usage, costs, latency and failures. Do not substitute fixture scores for model performance. No paid calls are authorized for this publication.
4. **Improve extraction and abstention.** Use a separate development set for layout variation, blur, conflicting fields and off-topic retrieval. Investigate OCR/layout fallback, evidence validation and calibrated retrieval thresholds or reranking. Freeze changes before running a new held-out set. Suggested targets, not current results: at least 95% negative-query abstention while retaining at least 90% recall@3; report confidence intervals and field-level extraction error/correction rates.
5. **Justify multiple agents.** Compare identical tools, permissions, model settings and scenarios. Report paired outcome differences, escalation precision, latency and cost. Keep the simpler baseline if separation does not improve quality or containment; do not manufacture a winning benchmark.
6. **Obtain independent review.** Collect attributable human labels using the review interface and versioned rubric, then compute judge agreement and disagreement examples. Until then label calibration pending.
7. **Publish a dependable synthetic demo.** Validate HTTPS deployment, individual reviewer accounts, monitoring, recovery and restore instructions. Provide a resettable synthetic dataset, clear uptime/error states, screenshots and demo walkthrough. Choose a license explicitly before advertising unrestricted reuse. Cloud resources require separate credentials and spending authorization.

The strongest positioning is a reproducible, auditable prescription-intake and refill workflow laboratory with honest failure measurements. Clinical use, real patient data and dispensing decisions remain outside this demonstration.
