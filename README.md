# Azure Retirement Navigator

A self-hosted web dashboard that automatically discovers every upcoming Azure service retirement across one or more subscriptions and shows exactly which of your resources are affected — all without credentials, secrets, or manual data entry.

Live deployment: **https://azure-retirement-navigator.azurewebsites.net**

---

## For non-technical readers

### What problem does this solve?

Microsoft continuously retires older Azure features and services (e.g. "TLS 1.0 support for App Service will be retired on 31 October 2025"). These announcements are scattered across the Azure portal, emails, and blog posts. If you miss one, your workloads can silently break.

This tool answers two questions automatically:

1. **What is being retired, and when?**
2. **Do I have any resources that are actually affected?**

It reads directly from Azure Advisor — the same engine that powers Microsoft's own retirement alerts — and cross-references every retirement announcement with the actual inventory of resources in your subscription(s).

### What you see when you open it

A web page with:

- **Summary cards** — total upcoming retirements, how many affect your environment, total impacted resources, and the closest deadline.
- **Retirement cards** — one card per announced retirement, with the service name, description, recommended action, retirement date, days remaining, and a count of your affected resources.
- **Expandable resource table** — click a card to see the exact resource names, types, regions, resource groups, and subscription IDs that are at risk.
- **Filters** — narrow by service name, region, subscription, resource group, or impact level.

The data refreshes automatically every time the page loads and is cached for 5 minutes on the server.

### What this tool does NOT do

- It does not make any changes to your Azure environment.
- It does not store any data. Every page load queries Azure live.
- It does not send emails or create tickets.
- It only reads data (Reader permission on your subscriptions).

---

## Architecture overview

```
┌──────────────────────────────────────────────────────────────────┐
│  Browser                                                         │
│  index.html + app.js + styles.css (served from /static/)        │
│       │  GET /api/retirements                                    │
│       ▼                                                          │
│  Azure App Service B1 (Linux, Canada Central)                   │
│  Python 3.11 · FastAPI · gunicorn + uvicorn                     │
│       │  DefaultAzureCredential (system-assigned managed identity)│
│       ▼                                                          │
│  Azure Resource Graph API                                        │
│  ├── advisorresources (microsoft.advisor/metadata)              │
│  │   All ServiceUpgradeAndRetirement retirement announcements    │
│  └── advisorresources (microsoft.advisor/recommendations)       │
│      joined to resources table — per-resource impact data        │
└──────────────────────────────────────────────────────────────────┘

Infrastructure provisioned by Terraform (infra/)
CI/CD via GitHub Actions with OIDC (no stored secrets)
Monitored by Application Insights + Log Analytics workspace
```

No database. No storage account. No API keys. Authentication is entirely through Azure Managed Identity.

---

## Repository layout

```
.
├── app.py                          # FastAPI application — all server-side logic
├── requirements.txt                # Python dependencies
├── host.json                       # Legacy Azure Functions config (harmless, ignored by App Service)
├── function_app.py                 # Legacy Azure Functions code (harmless, ignored by App Service)
│
├── static/
│   ├── index.html                  # Single-page frontend
│   ├── styles.css                  # All styling
│   └── app.js                      # Frontend JS — fetch, filter, render
│
├── infra/                          # Terraform infrastructure-as-code
│   ├── main.tf                     # Provider config + resource group
│   ├── function_app.tf             # App Service plan + web app + RBAC
│   ├── monitoring.tf               # Log Analytics workspace + Application Insights
│   ├── variables.tf                # All input variable definitions
│   ├── outputs.tf                  # Deployment outputs (app URL, identity ID, etc.)
│   ├── terraform.tfvars            # !! gitignored — your local variable values
│   └── storage.tf                  # Empty — storage was removed (see design decisions)
│
└── .github/
    └── workflows/
        └── deploy.yml              # GitHub Actions: zip → deploy → smoke test
```

---

## How it works — technical deep dive

### Data pipeline (`app.py`)

On every request to `GET /api/retirements`, the server runs two KQL queries against the **Azure Resource Graph** API in parallel:

**Query 1 — `ALL_RETIREMENTS_QUERY`**

Targets `microsoft.advisor/metadata` rows with `recommendationSubCategory == "ServiceUpgradeAndRetirement"`. These are the *announcement* records — one per retirement event, subscription-independent. They contain the service name, retirement date, description, recommended action, and a "learn more" link.

**Query 2 — `IMPACTED_RESOURCES_QUERY`**

Targets `microsoft.advisor/recommendations` rows (same retirement category). These are the *per-resource* records — one row per resource that Advisor has flagged for a given retirement. The query does a `leftouter` join against the `resources` table to enrich each row with the resource's display name, type, region, resource group, and subscription.

> **Important KQL gotcha fixed here**: Azure Resource Graph `join` is case-sensitive, but resource IDs in `advisorresources` are stored lowercase while IDs in the `resources` table use the original mixed-case ARM casing. The query normalises both sides with `tolower()` before joining. Without this, the join silently misses every match, and Name/Type/Region columns come back null. A fallback `extend` also parses the name and type directly from the resource ID string for any resources that were deleted after the Advisor recommendation was generated.

**Merging (`build_retirement_dataset`)**

The two result sets are joined in Python by `recommendationTypeId` (a GUID that uniquely identifies a retirement event type). For each retirement announcement, all matching per-resource rows are grouped under it. Resources are deduplicated by `resourceId`. Aggregate fields (`regions`, `subscriptions`, `resourceGroups`, `resourceTypes`, counts) are computed and the full list of `impactedResources` is attached.

Retirements with no matching per-resource rows still appear in the output — `impactAnalysisAvailable: false` indicates that Advisor has not yet generated per-resource impact records for that retirement (common for retirements announced far in advance). This is a data gap in Advisor, not a bug.

Results are sorted by retirement date (soonest first, nulls last).

### Authentication (no secrets)

The App Service has a **system-assigned managed identity**. Terraform grants that identity the **Reader** role on every subscription listed in `AZURE_SUBSCRIPTION_IDS`. `DefaultAzureCredential` in `app.py` automatically uses the managed identity when running in Azure. When running locally, it falls through the credential chain to your `az login` session.

### Frontend (`static/app.js`)

Plain JavaScript — no framework, no build step. On page load it calls `GET /api/retirements`, processes the JSON, and renders retirement cards. Filters operate entirely client-side on the in-memory array. The resource table inside each card is a `<details>/<summary>` element (native HTML disclosure).

### Routes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Serves `static/index.html` |
| GET | `/static/*` | Static file mount (CSS, JS) |
| GET | `/api/retirements` | Main data endpoint — returns full retirement dataset as JSON. `Cache-Control: private, max-age=300` |
| GET | `/api/health` | Liveness probe — returns `{"status":"ok","timestamp":"..."}`. `Cache-Control: no-store` |

> **Order matters**: the `StaticFiles` mount is the last line in `app.py`. FastAPI routes are matched in registration order; if `mount("/static")` came first, it would intercept `/api/*` paths.

### Deployment pipeline (`.github/workflows/deploy.yml`)

1. **Checkout** — `actions/checkout@v4`
2. **Azure login** — keyless OIDC via `azure/login@v2.3.0` (Workload Identity Federation, no client secret stored in GitHub)
3. **Create zip** — source-only archive, excluding `infra/`, `.git/`, `.github/`, virtualenvs, and any existing zips
4. **Deploy** — `az webapp deploy --type zip --async true`. The `--async true` flag is required: Oryx's server-side pip install takes ~3 minutes, which would exhaust the CLI's 10-minute startup wait window before the app is ready.
5. **Smoke test** — polls `GET /api/health` every 30 seconds for up to 10 minutes (20 attempts), exits 0 on first HTTP 200.

Oryx (`SCM_DO_BUILD_DURING_DEPLOYMENT=true`, `ENABLE_ORYX_BUILD=true`) installs Python packages server-side during the zip deployment. This means the zip contains only source files — no `venv/` directory is ever committed or uploaded.

---

## Prerequisites

| Tool | Minimum version | Install |
|------|----------------|---------|
| Python | 3.11 | https://python.org |
| Terraform | 1.5 | https://developer.hashicorp.com/terraform/install |
| Azure CLI | Latest | `winget install Microsoft.AzureCLI` |
| Git | Any | https://git-scm.com |

Azure permissions required for the person provisioning infrastructure:

- **Contributor** on the target resource group (or subscription, to create a new RG)
- **User Access Administrator** on each subscription being monitored (to assign Reader to the managed identity)

---

## First-time setup

### 1 — Clone and configure

```bash
git clone https://github.com/mumustafa/azure-retirements-function.git
cd azure-retirements-function
```

Create `infra/terraform.tfvars` (this file is gitignored — never commit it):

```hcl
resource_group_name    = "azure-retirement-navigator-rg"
location               = "canadacentral"
function_app_name      = "azure-retirement-navigator"   # must be globally unique
azure_subscription_ids = ["<your-subscription-id>"]     # add more as a comma-separated list
python_version         = "3.11"
log_retention_days     = 30

tags = {
  project     = "azure-retirement-navigator"
  environment = "production"
}
```

> To monitor multiple subscriptions: `azure_subscription_ids = ["sub-id-1", "sub-id-2"]`. Terraform will assign Reader on each.

### 2 — Provision infrastructure

```bash
cd infra
az login
terraform init
terraform plan -out tfplan
terraform apply tfplan
```

Terraform creates:

| Resource | Description |
|----------|-------------|
| Resource Group | Container for all resources |
| App Service Plan (B1 Linux) | Dedicated compute (cheapest plan with always-on) |
| App Service (Linux Web App) | Hosts the FastAPI app |
| System-assigned Managed Identity | Auto-created with the web app |
| Reader role assignment(s) | One per subscription in `azure_subscription_ids` |
| Log Analytics Workspace | Log storage for Application Insights |
| Application Insights | APM, live metrics, request tracing |

After `apply`, note the outputs:

```
app_url                = "https://azure-retirement-navigator.azurewebsites.net"
app_name               = "azure-retirement-navigator"
managed_identity_principal_id = "<guid>"
```

### 3 — Create the GitHub OIDC app registration

The CI/CD pipeline authenticates to Azure without any stored password or client secret — it uses OpenID Connect (OIDC) Workload Identity Federation.

```bash
# Create the app registration
az ad app create --display-name "azure-retirement-navigator-ghactions"

# Note the appId from the output, then create a service principal
az ad sp create --id <appId>

# Assign Contributor on the resource group
az role assignment create \
  --assignee <appId> \
  --role Contributor \
  --scope /subscriptions/<subscription-id>/resourceGroups/azure-retirement-navigator-rg

# Add the federated identity credential
az ad app federated-credential create \
  --id <appId> \
  --parameters '{
    "name": "github-main",
    "issuer": "https://token.actions.githubusercontent.com",
    "subject": "repo:mumustafa/azure-retirements-function:ref:refs/heads/main",
    "audiences": ["api://AzureADTokenExchange"]
  }'
```

> Adjust `subject` if your repository path or branch name differs.

### 4 — Add GitHub repository secrets

In your GitHub repository → Settings → Secrets and variables → Actions, add:

| Secret name | Value |
|-------------|-------|
| `AZURE_CLIENT_ID` | App registration `appId` (client ID) |
| `AZURE_TENANT_ID` | Your Azure AD tenant ID (`az account show --query tenantId`) |
| `AZURE_SUBSCRIPTION_ID` | The subscription where the App Service lives |

### 5 — Deploy

Push to `main` (or trigger the workflow manually from the Actions tab). The pipeline deploys the code and waits for the health check to pass.

---

## Local development

```bash
# Create a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Log in to Azure (DefaultAzureCredential uses your az login session locally)
az login
az account set --subscription <your-subscription-id>

# Set the required environment variable
$env:AZURE_SUBSCRIPTION_IDS = "<your-subscription-id>"   # PowerShell
# export AZURE_SUBSCRIPTION_IDS="<your-subscription-id>"  # bash

# Run the development server
uvicorn app:app --reload --port 8000
```

Open http://localhost:8000. The app will query Azure live using your `az login` credentials.

> The first load takes 10–30 seconds because it runs two Resource Graph queries across your subscriptions. Subsequent loads within 5 minutes are served from the browser cache (`Cache-Control: max-age=300`).

---

## Configuration reference

All runtime configuration is via environment variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `AZURE_SUBSCRIPTION_IDS` | Yes | Comma-separated list of subscription IDs to query. Example: `"sub1,sub2,sub3"` |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | No | Auto-set by Terraform. Enables live metrics and distributed tracing in Application Insights. |

In production (App Service), both are set via `app_settings` in Terraform — no manual portal configuration needed.

---

## Infrastructure details

### Why App Service B1, not Azure Functions Consumption?

The original implementation used Azure Functions. It was migrated to App Service B1 because the tenant enforces `publicNetworkAccess=Disabled` on all storage accounts. The Azure Functions Consumption host requires data-plane access to its own storage account at every cold start (for the host coordinator lock). With public network access disabled and no VNet integration configured, every cold start failed with a `403 AuthorizationFailure` before any function code ran.

App Service B1 has zero storage dependency — it runs as a plain web server. This is the correct hosting tier for a web app that simply needs to be "always on" and has no event-trigger requirements.

### Why `storage_use_azuread = true` in the Terraform provider?

The same tenant policy also disables shared access key authentication (`shared_access_key_enabled=false`) on all storage accounts. Without `storage_use_azuread = true`, Terraform's AzureRM provider falls back to key-based auth for storage operations and fails at plan time. This setting tells the provider to use Entra ID tokens for all storage data-plane calls.

### Remote Terraform state (optional, recommended for teams)

The state file is currently stored locally in `infra/`. For team use, uncomment the `backend "azurerm"` block in `infra/main.tf` and point it at a storage account + container where you want state stored:

```hcl
backend "azurerm" {
  resource_group_name  = "tfstate-rg"
  storage_account_name = "tfstateXXXXXXXX"
  container_name       = "tfstate"
  key                  = "azure-retirement-navigator.terraform.tfstate"
}
```

---

## Troubleshooting

### All resource Name / Type / Region columns show `—`

This was caused by a case-sensitivity bug in the KQL `join` (Resource IDs in `advisorresources` are lowercase; IDs in the `resources` table use the original ARM mixed-case). Fixed in the `IMPACTED_RESOURCES_QUERY` with `tolower()` on both join keys. If you see this after a fresh deploy, wait for the Oryx build to finish (~4 minutes) and hard-refresh the page.

### Some retirements show zero impacted resources

This is expected. Azure Advisor populates per-resource impact records asynchronously, sometimes days or weeks after the global retirement announcement. A count of `—` means impact analysis is not yet available for that retirement, not that your environment is unaffected. The notice banner on the page explains this.

### `az webapp deploy` times out in CI

The `--async true` flag is required. Without it, the CLI waits up to 10 minutes for the app to start after deploy. The Oryx build (server-side pip install) takes ~3 minutes, leaving only 7 minutes for startup — which is routinely exhausted if the previous container exited with an error and triggered a platform-side cooldown. The smoke test step handles readiness polling instead.

### `ModuleNotFoundError: No module named 'six'`

`azure-mgmt-resourcegraph==8.0.0` has an undeclared transitive dependency on `six`. It is pinned explicitly in `requirements.txt` as `six>=1.16.0`. Do not remove it.

### App shows "Failed to load data" in the browser

Check App Service logs in the Azure portal (App Service → Log stream, or Application Insights → Failures). Common causes:

1. `AZURE_SUBSCRIPTION_IDS` is not set — verify in App Service → Configuration → Application settings.
2. The managed identity has not been granted Reader — run `terraform apply` again or check the role assignment in the Azure portal.
3. A cold start is in progress — wait 30 seconds and refresh.

### Terraform plan shows drift after manual portal changes

Do not make manual changes to the App Service through the portal. Terraform will detect drift and may overwrite settings on the next `apply`. All configuration lives in `infra/`.

---

## API reference

### `GET /api/retirements`

Returns the full retirement dataset. Response is JSON with `Cache-Control: private, max-age=300`.

**Response shape:**

```jsonc
{
  "generatedAt": "2026-07-24T10:30:00+00:00",
  "source": "Azure Advisor and Azure Resource Graph",
  "notice": "...",
  "items": [
    {
      "id": "<recommendationTypeId guid>",
      "service": "Azure Kubernetes Service — Kubernetes version 1.27",
      "retirementDate": "2024-07-31T00:00:00+00:00",
      "link": "https://aka.ms/...",
      "description": "Kubernetes 1.27 is being retired.",
      "solution": "Upgrade your cluster to a supported version.",
      "impactAnalysisAvailable": true,
      "impactedCount": 3,
      "regions": ["canadacentral", "eastus"],
      "subscriptions": ["29455385-..."],
      "resourceGroups": ["my-aks-rg"],
      "resourceTypes": ["microsoft.containerservice/managedclusters"],
      "impactedResources": [
        {
          "recommendationId": "/subscriptions/.../providers/Microsoft.Advisor/recommendations/...",
          "recommendationTypeId": "<guid>",
          "resourceId": "/subscriptions/.../resourcegroups/my-aks-rg/providers/...",
          "resourceName": "my-aks-cluster",
          "resourceType": "microsoft.containerservice/managedclusters",
          "region": "canadacentral",
          "resourceGroup": "my-aks-rg",
          "subscriptionId": "29455385-...",
          "impact": "High",
          "recommendationStatus": "Active",
          "tags": {}
        }
      ]
    }
  ]
}
```

### `GET /api/health`

Returns `{"status":"ok","timestamp":"..."}` with HTTP 200. Used by the CI/CD smoke test and any external health monitoring. `Cache-Control: no-store`.
