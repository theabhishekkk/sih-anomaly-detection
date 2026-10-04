# Burn-in Intelligence — SIH 26170

Lot-calibrated outlier detection, 168-hour drift forecasting, evidence-based
explanations, and auditable QA decisions. Includes a local development setup and
an Azure Container Apps deployment path.

## Run locally

From the repository root, use Python 3.10 or newer:

```powershell
python -m venv backend\venv
backend\venv\Scripts\python -m pip install -r backend\requirements.txt
backend\venv\Scripts\python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. The API and dashboard are served from the same
origin. The **Load interactive demo** button calibrates a generated known-good
lot and screens a sample production lot; no sample data is silently treated as
real screening evidence. The hosted demo is read-only and can be loaded without
signing in; uploads and QA decisions still require an authorized account.

Run the backend tests from the repository root:

```powershell
backend\venv\Scripts\python -m pytest backend\tests -q
```

## CSV formats

Both uploads are UTF-8 CSV files with `device_id`, `value_0h`, and `value_24h`
columns. `parameter` defaults to `leakage_current` and `lot_id` is optional.
Reference files may additionally include `value_96h` and `value_168h`. A
reference row represents one device/parameter pair; those pairs must be unique.
Provide at least five known-good reference records per parameter to establish
robust 0h and 24h baselines. Files are limited to 5 MB and 5,000 rows.

Use known-good reference devices from the same measurement setup and comparable
lot conditions. Keep units consistent within a parameter (for example, do not
mix A and µA). At least ten reference rows with measured 168-hour values are
needed to fit the directional 90th/10th-percentile pinball-loss regression.
With fewer labels, the system reports and uses a conservative linear
extrapolation, with a one-sided residual margin when historical 168-hour
readings are available. No test set can validate forecast accuracy without
ground-truth 168-hour outcomes.

The reference calibration learns per-parameter medians and median absolute
deviation scales. Screening reports signed robust z-scores, a lot-relative
anomaly score, predicted 168-hour drift, and a safety-slope comparison. The
default anomaly cut-off is 3.5. A safety slope can be supplied in
parameter-units per hour; otherwise it is estimated from the known-good
reference cohort. Failure direction can be set to higher or lower readings.

The feature attributions are exact Shapley values for the detector's additive
squared robust-distance score relative to the calibrated median baseline.

## Free local AI with Ollama

The dashboard can run multi-turn, screening-evidence-grounded chat and device
explanations using a free local model. No API key, subscription, or external
AI provider is used. On Windows, from the repository root run:

```powershell
.\scripts\start-local-ai.ps1
```

The first run installs Ollama if needed and downloads `qwen3:4b`; allow a few
gigabytes of disk space and time for that download. Later runs reuse the model.
The script starts Ollama, sets `OLLAMA_MODEL=qwen3:4b`, and starts the dashboard
with the Ollama service on `http://127.0.0.1:11434`. The 4B model is intended as
a free, practical local default; larger Ollama models can be selected by setting
`OLLAMA_MODEL` and pulling that model first.

The AI panel supports follow-up questions about the current lot, forecast
limitations, risk evidence, and QA review steps. It sends only recent chat turns
and bounded screening evidence to Ollama. Answers are decision support: they do
not approve/reject devices, and qualified engineering review remains required.
If the model is unavailable, the app reports its state and the briefing routes
fall back to clearly labeled deterministic evidence; interactive chat does not
pretend that fallback is a generated AI answer.

On a machine where Ollama is already installed, the equivalent manual setup is:

```powershell
ollama pull qwen3:4b
$env:OLLAMA_MODEL = "qwen3:4b"
$env:OLLAMA_URL = "http://127.0.0.1:11434"
backend\venv\Scripts\python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Ollama runs on the same machine as the app (or a private network endpoint you
control). The free Render service in this repository does not host Ollama or
have access to a model on your PC; its AI status will correctly report local
Ollama as unconfigured unless you separately provide a reachable private model
service. Do not expose Ollama's unauthenticated port directly to the public
internet. Without a reachable local model, the demo briefing remains
evidence-based and explicitly labeled.

## Dashboard capabilities

After sign-in, reviewers can calibrate and screen production CSVs, search/filter/
sort the device evidence, inspect measured and forecast values, export the
current report to CSV, revisit the latest 25 saved screening runs (100 are
retained), record auditable QA decisions, and use the multi-turn AI copilot with
the latest run's evidence. AI output never releases or rejects hardware
automatically.

## Persistence and operational limits

For a local SQLite run, the latest calibration, screening report, recent
screening history, and inspector decisions are stored in `backend/data/sih.db`;
set `SIH_DB_PATH` to change that path. For a local PostgreSQL stack, copy
`.env.example` to `.env`, change both
development secrets, and run:

```powershell
docker compose up --build
```

Development mode creates missing tables automatically. Production deliberately
does not: a separate, one-shot migration job initializes the least-privilege
application database role and applies Alembic migrations before the API rollout.
The application does not run schema migrations at startup.
The `backend/migrations/supabase-bootstrap.sql` script only creates the
least-privilege database role; it does not create application tables. Apply the
Alembic migrations using the controlled deployment workflow before starting
the production app. Readiness returns HTTP 503 and names missing tables when
the database is reachable but the migration has not been applied.

## Free-tier hosted demo (Render + Supabase)

This is the lowest-cost hosted option prepared for this project. It costs $0
while you stay inside both providers' free quotas; it is a demo/pilot, not
production-grade hosting. Render free web services sleep after inactivity, have
limited CPU/RAM and no persistent disk. Supabase Free currently includes a
500 MB database and pauses projects after one week of inactivity; it does not
include automatic backups. A sleeping or paused service can take time to wake,
and free tiers can change. Never upload sensitive hardware/customer data or rely
on this setup for flight or other safety-critical release decisions.

See the current [Render free-instance limits](https://render.com/docs/free) and
[Supabase Free plan limits](https://supabase.com/pricing) before deploying.

### A. Put the project in GitHub

1. Use the project repository at
   <https://github.com/theabhishekkk/sih-anomaly-detection> and deploy from its
   `main` branch. Do not include `.env`, database files, passwords, or access
   tokens.
2. Confirm GitHub Actions is enabled for the repository.

### B. Create the free Supabase database

1. Create a Supabase organization on the **Free** plan and create a project.
   Choose a region reasonably close to Render's Oregon region. Save the database
   password somewhere private; do not commit it.
2. In Supabase **SQL Editor**, open
   `backend/migrations/supabase-bootstrap.sql`. Replace
   `REPLACE_WITH_A_LONG_RANDOM_PASSWORD` with a unique random password of at
   least 24 characters, then run the SQL once. This creates a non-superuser
   database role for the app and its schema migrations. Do not reuse your
   Supabase administrator password.
3. In Supabase **Connect**, choose the **Session pooler** connection details
   (the IPv4-compatible option). Build a SQLAlchemy URL in this exact form,
   using the pooler host/port and database name shown by Supabase, and
   percent-encode special characters in the password:

   ```text
   postgresql://burnin_app.<PROJECT-REF>:<URL-ENCODED-PASSWORD>@<SESSION-POOLER-HOST>:5432/postgres?sslmode=require
   ```

   Keep the session-pooler username format `burnin_app.<PROJECT-REF>` shown
   above. Copy the actual pooler host from Supabase; do not guess it. Keep this
   URL private. Use it as `DATABASE_URL` in Render and as the GitHub Actions
   secret in section D. The app and migration runner map the generic PostgreSQL
   URL Supabase provides to the installed Psycopg 3 driver; the
   `postgresql+psycopg://` SQLAlchemy form is also accepted.

4. In Supabase **Authentication → Users**, create/invite each QA reviewer using
   the email address you plan to allow. Use these same exact emails in
   `AUTH_ALLOWED_EMAILS`; unlisted accounts are denied access even if they can
   authenticate with Supabase.

### C. Configure the Render web service

1. The repository already has `render.yaml`. If the Render web service at
   `https://sih-anomaly-detection.onrender.com` exists, open its **Environment**
   settings and configure these values there. Otherwise create the Blueprint
   from this GitHub repository. The Blueprint requests a **Free** Oregon
   service, builds from the repository root using its top-level `Dockerfile`,
   and disables automatic deploys so migrations can run before app deployment.
   If configuring an existing service manually, set **Root Directory** to
   blank/repository root and **Dockerfile Path** to `./Dockerfile`; the image
   build needs both `backend/` and `frontend/` in its build context.
2. Set these Render environment variables (the Supabase publishable key is not
   returned to browsers; the database URL and session secret must remain private):
   - `APP_ENV`: `production` (Render is also automatically treated as
     production when `RENDER_EXTERNAL_URL` is present.)
   - `DATABASE_URL`: the Supabase session-pooler URL from section B.
   - `APP_SESSION_SECRET`: a new random value of at least 32 characters. Do
     not reuse a database password.
   - `SUPABASE_URL`: the single HTTPS project URL, for example
     `https://<your-project-ref>.supabase.co`. Do not include paths, whitespace,
     or multiple lines.
   - `SUPABASE_PUBLISHABLE_KEY`: the publishable key shown in your Supabase
     project API settings. Never use the Supabase `service_role` or secret key
     here. If a secret key was previously used in this variable, revoke it and
     create a new publishable key before deploying.
   - `AUTH_ALLOWED_EMAILS`: exact reviewer emails, comma-separated.
   - `WEB_CONCURRENCY`: `1` for the small free instance.
3. Save changes and trigger a Render deploy. Render injects
   `RENDER_EXTERNAL_URL`; no Next.js server helper or OAuth callback URL is
   needed for this same-origin FastAPI dashboard. Verify
   `https://sih-anomaly-detection.onrender.com/health/ready` returns
   `{"status":"ready"}`.
   If startup logs show a database IP beginning `2406:` and `Network is
   unreachable`, the service is using an IPv6-only database endpoint. In
   Supabase **Connect**, copy the **Session pooler** connection string (shared
   pooler, port `5432`) and update Render's `DATABASE_URL` with that pooler
   host; do not use the direct `db.<project-ref>.supabase.co` endpoint on
   Render's IPv4-only network. Use the same URL in GitHub's production
   `DATABASE_URL` secret so migrations reach the same database.
4. In Render service settings, create a **Deploy Hook**. Treat its URL as a
   secret and add it to GitHub in the next section.

### D. Enable migrations and controlled deploys

1. In GitHub **Settings → Environments**, create an environment named
   `production`.
2. Add these environment secrets to `production`:
   - `DATABASE_URL`: exactly the same Supabase app-role connection URL as
     Render's value.
   - `RENDER_DEPLOY_HOOK`: the private deploy hook URL from Render.
3. Add this environment variable to the `production` environment:
   - `APP_HEALTHCHECK_URL`: the Render base URL, for example
     `https://<your-render-service>.onrender.com`.
4. In repository **Settings → Secrets and variables → Actions → Variables**,
   add `RENDER_DEPLOY_ENABLED` with value `true` to permit deployment after
   validation. Leave it unset/false until Render environment values, the
   database role, and GitHub secrets are configured.
5. Run the **Free-tier deployment** workflow from GitHub **Actions**, selecting
   `main`. It always runs tests and a dependency audit. When
   `RENDER_DEPLOY_ENABLED` is `true`, it then applies the Alembic migration
   using the app role, triggers Render, and probes database readiness. Later
   pushes to `main` follow the same gated sequence.

If the dashboard reports `Could not load saved state: Request failed (500)` and
the logs say a relation such as `calibration` does not exist, the app role can
connect but the schema migration is missing (or the migration workflow used a
different database URL). Confirm GitHub's production `DATABASE_URL` matches
Render's, set `RENDER_DEPLOY_ENABLED` to `true`, and run the **Free-tier
deployment** workflow. Do not rerun `supabase-bootstrap.sql` as a table fix; it
only bootstraps the role.

If the workflow fails, inspect its failed step before retrying. If migration
fails, leave the old app deployed, correct the Supabase URL/role or migration
error, then rerun. Don't paste database URLs, deploy hooks, or OIDC secrets into
issues or chat.

The checked-in Render blueprint and workflow are [render.yaml](./render.yaml)
and [.github/workflows/render-free.yml](./.github/workflows/render-free.yml).
The Supabase least-privilege role template is
[supabase-bootstrap.sql](./backend/migrations/supabase-bootstrap.sql).
This repository is FastAPI plus a static JavaScript dashboard, not a Next.js
app. The Next.js `@supabase/ssr` helpers and `page.tsx` snippet are not used
here; the dashboard signs in through Supabase Auth's HTTPS API, keeps its
session in browser session storage, and sends a bearer token to FastAPI. The
server checks the token with Supabase Auth and enforces the email allowlist.

## Azure production deployment

The provided Azure path uses Azure Container Apps, Azure Container Registry,
PostgreSQL Flexible Server, Key Vault, managed identity, Log Analytics, and
workspace-based Application Insights. The PostgreSQL server is configured for
zone-redundant high availability and 35-day geo-redundant backups. These settings
increase cost; select and validate the final region/SKUs and recovery objectives
against the subscription before provisioning.

Prerequisites: an Azure subscription with quota and permissions to create the
resources and role assignments; Azure CLI with Bicep support; a Microsoft Entra
single-tenant app registration; a real QA email allowlist; and a GitHub
repository with Actions enabled. Register the redirect URI
`https://<container-app-fqdn>/auth/callback` on the Entra app. The app URL is
printed by deployment and can be registered after the first infrastructure
deployment, before QA sign-in is enabled.

1. Set the non-secret deployment values in `infra/main.parameters.json`:
   region, Entra tenant/application IDs, and exact reviewer email addresses.
   `publicBaseUrl` is used as a bootstrap value; the release workflow changes it
   to the generated Container App HTTPS origin. Keep it aligned with the actual
   origin if you redeploy the infrastructure.
2. In a PowerShell process, set the deployment-only PostgreSQL administrator
   password, application database password, Entra client secret, and a random
   session secret of at least 32 characters as environment variables. Do not
   put credentials in the parameters file, source control, or command-line
   arguments. For example, generate a session secret locally with:

   ```powershell
   $bytes = New-Object byte[] 48
   $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
   $rng.GetBytes($bytes)
   $env:APP_SESSION_SECRET = [Convert]::ToBase64String($bytes)
   $rng.Dispose()
   ```

   Use unique, strong values for `POSTGRES_ADMIN_PASSWORD` and
   `APP_DATABASE_PASSWORD` (each at least 16 characters), and set
   `OIDC_CLIENT_SECRET` from the Entra app registration. Optionally set
   `POSTGRES_ADMIN_LOGIN` to a 3-32 character login beginning with a letter.
3. Authenticate with `az login`, check subscription quotas/region availability,
   then provision the Azure resources:

   ```powershell
   .\infra\deploy.ps1 -SubscriptionId "<subscription-id>" -ResourceGroupName "<resource-group>"
   ```

   The script compiles Bicep, creates the resource group, and supplies secrets
   through a short-lived local parameters file that it removes on exit.
4. Configure GitHub Actions repository secrets
   `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, and `AZURE_SUBSCRIPTION_ID`, plus
   repository variables `AZURE_RESOURCE_GROUP`, `ACR_NAME`,
   `CONTAINER_APP_NAME`, and `MIGRATION_JOB_NAME` from the deployment outputs.
   Configure a federated identity credential for the GitHub repository/branch
   and grant that identity `AcrPush` on the registry and the minimum required
   Container Apps update/job-execution permissions on the resource group.
   The workflow in `.github/workflows/production.yml` tests changes, builds an
   immutable image, runs database setup/migrations as a job, and only then
   deploys the API.
5. Register the emitted Container App HTTPS origin as the Entra redirect URI.
   Set the matching value in `infra/main.parameters.json` before subsequent
   infrastructure deployments. Confirm sign-in, readiness, database
   connectivity, and Application Insights ingestion before accepting traffic.

The API uses an explicit email allowlist, secure signed sessions, CSRF checks,
security headers, and PostgreSQL over TLS. The current template exposes public
network endpoints for the Container App, PostgreSQL, ACR, and both RBAC-protected
Key Vaults. PostgreSQL's Azure-services firewall rule and the vault network ACLs
are intentionally broad to permit this public-egress deployment; restrict these
or move the services to private networking before loading production data. The
API identity reads runtime secrets from its own Key Vault using read-only access.
The one-shot migration job has a separate identity and vault containing the
PostgreSQL administrator credential; the web API connects only with a separate
application database role.

## Screening validation and safety

This remains a decision-support system, not a certified reliability-screening
process. Validate thresholds, model calibration, measurement-system variation,
and false-negative performance against representative labeled hardware. The
forecast reports a model estimate; it is not proof of actual 168-hour behavior.
Have QA personnel review evidence and approve dispositions under an established
quality process. Test backup restoration, failover, identity lifecycle,
monitoring alerts, and incident response before using production or safety-
critical data. No Azure resources have been provisioned by this repository
change.
