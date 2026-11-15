# Local and cloud deployment

## Full local stack

Prerequisites: Docker Engine/Desktop with Compose v2 and a browser. No paid model credentials are needed in fixture mode.

```sh
python scripts/setup.py
docker compose up --build -d
```

`setup.py` creates local random secrets without printing them. On a machine without Python, copy `.env.example` to `.env` and set random `APP_SECRET`, `DEMO_PASSWORD`, and a URL-safe `POSTGRES_PASSWORD`. Never commit `.env`. Do not use punctuation needing URL encoding in the PostgreSQL password unless you encode the connection URL yourself.

Open http://localhost:8000, use a role username (`patient`, `staff`, `pharmacist`, `administrator`) and the local `DEMO_PASSWORD`. The mock landing page is http://localhost:8001. Jaeger is http://localhost:16686. Ports bind to loopback; database and MCP are internal. Health endpoints are `/health` and `/ready`. Database health gates migration; successful migration gates service startup.

```sh
docker compose ps
docker compose exec api python scripts/postgres_check.py
docker compose logs --tail 100 worker
docker compose stop worker
docker compose start worker
```

Named volumes persist application documents, database/checkpoints, reports and traces. `docker compose down` preserves them; do not add `-v` unless intentionally discarding the demo. SIGTERM finishes the current worker step; a forced interruption recovers after the lease expires.

## Concrete cloud path: Ubuntu 24.04 VM + Compose + Caddy

Use a dedicated Ubuntu 24.04 LTS VM (for example an AWS EC2 instance) with at least 4 vCPU, 8 GiB RAM and 30 GiB encrypted disk. This is a single-host demonstration deployment, not a highly available clinical service. Creating a host, DNS and a model account can incur charges; none was provisioned during this build.

1. Install Docker using [Docker's official Ubuntu instructions](https://docs.docker.com/engine/install/ubuntu/). Create a dedicated deploy user. Allow SSH only from your administration IP and public TCP 80/443. Do not expose 5432, 8001, 8002, 4318 or 16686.
2. Copy this source tree or a reviewed release archive to `/opt/pharmacyflow`. The project does not require a Git push. Build a release-tagged image and preserve the prior image before updating.
3. Copy an environment file from your secret manager at deploy time, with permissions `0600`. Set fresh secrets, `DOMAIN=demo.example.com`, `PROVIDER_MODE=fixture`, `ALLOW_FAULT_INJECTION=false`. If enabling live providers, inject `OPENAI_API_KEY` from the secret manager. Docker environment variables are visible to host administrators; production secret isolation would need stronger infrastructure.
4. Point the DNS A/AAAA record to the host. Caddy requires a reachable public hostname and ACME access. HTTPS is required for browser microphone access away from localhost.
5. Run the following from the project root:

```sh
docker compose -f compose.yaml -f deploy/compose.cloud.yaml config --quiet
docker compose -f compose.yaml -f deploy/compose.cloud.yaml build
docker compose -f compose.yaml -f deploy/compose.cloud.yaml up -d
docker compose exec api python scripts/postgres_check.py
curl --fail https://demo.example.com/ready
```

The override exposes Caddy on 80/443 while API ports remain loopback. See [Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https) and [Compose startup ordering](https://docs.docker.com/compose/how-tos/startup-order/).

## Migrations, backup and rollback

Before an update, stop the worker and use `pg_dump` for **both** application and mock databases. Snapshot document/trace volumes consistently with the database. Preserve `.env` in the secret manager, not the source archive. Backups contain synthetic case evidence and must still be access-controlled.

```sh
docker compose stop worker
docker compose exec -T db pg_dump -U pharmacy -Fc pharmacyflow > pharmacyflow-before.dump
docker compose exec -T db pg_dump -U pharmacy -Fc mockpharmacy > mock-before.dump
docker compose run --rm migrate
docker compose up -d api mock mcp worker
```

Use forward-compatible migrations. If application code must roll back, point the app image to the preserved release and restart. If the schema is incompatible, stop all writers and restore both dumps plus the matching documents snapshot into fresh databases/volumes, then point the previous release at them. Do not blindly downgrade the initial migration: it drops tables. After restoration, reconcile pending external requests using their original keys before accepting new work.

Maintenance: `docker compose exec api python -m pharmacyflow.retention` previews eligible cases; append `--apply` for authorized retention. Rotate secrets and restart services to invalidate old capabilities. The demo's shared role password is intentionally unsuitable for a public multi-user deployment; the cloud override disables those accounts. Provision individual synthetic-demo accounts using `python -m pharmacyflow.accounts`; managed identity/MFA and clinical production controls remain separate work.

## Validation status

`reports/deployment.json` records actual local validation. The Windows environment used for this project has no Docker executable, so image build, PostgreSQL/pgvector/checkpoint execution and Jaeger startup are **unverified locally**. CI contains a separate PostgreSQL Compose job, but no remote workflow has been run because nothing was pushed. Static YAML, required service topology, readiness dependencies and configuration presence are checked locally. Cloud provisioning, DNS, HTTPS issuance, backup restore and paid provider calls remain unverified.

## Added verification and public-demo controls

The cloud override sets DEMO_MODE=false and ALLOW_FAULT_INJECTION=false on all application services. Old seeded demo accounts remain in the database for history but cannot authenticate. Provision individual usernames/passwords through the prompted accounts command in README. JWT sessions expire and logout revokes account sessions. Mock/MCP/database/Jaeger remain internal or loopback; no trace link is advertised in the public configuration. Resource limits are included.

Migrations 002–004 are additive and forward-only. `tests/test_migrations.py` executes upgrade twice against a legacy schema and verifies existing records/hashes survive. Migration failure prevents dependent services from starting through Compose's completion gate. Never delete volumes to resolve a migration failure.

`acceptance.py --postgres` creates uniquely named test application/mock databases on the configured server; it needs CREATEDB privileges on a test server. It executes the same MCP, Chromium, checkpoint/restart and reconciliation sequence. CI runs this inside the application image, restarts services, then quiesces writers and invokes the host-side backup checker. CI configuration has not been executed remotely.

`python scripts/postgres_backup_check.py` never overwrites the original databases. It preserves uniquely named restored databases for inspection and compares counts plus canonical record checksums. It requires a running Docker stack and quiesced writers; document-volume backup restoration is still a separate operator check.
