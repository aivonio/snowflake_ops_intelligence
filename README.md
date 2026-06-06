<div align="center">
  <img src="https://raw.githubusercontent.com/devbysatyam/snowflake_ops_intelligence/main/assets/banner.png" alt="SnowOps Intelligence Banner" width="100%" style="border-radius: 12px; border: 1px solid #333;">
  
  <h1>❄️ SnowOps Intelligence</h1>
  
  <p><strong>A native Snowflake cost, operations, and AI intelligence platform.</strong></p>

  <p>
    <a href="https://snowops.aivon.io" target="_blank">
      <img src="https://img.shields.io/badge/Website-snowops.aivon.io-blue?style=for-the-badge" alt="Website">
    </a>
  </p>
</div>

## What is it?

SnowOps Intelligence is an application that runs entirely inside your Snowflake account. It gives you deep visibility into exactly where your credits are going, provides AI-driven query optimization, and automatically enforces security benchmarks. 

Everything runs inside your existing perimeter. Zero data egress. No external SaaS vendors connecting to your warehouse.

## Why we built it

We built SnowOps because managing Snowflake at scale gets expensive and messy. Every data engineering team eventually hits a wall where credit usage spikes, rogue queries drain budgets, and figuring out what went wrong becomes a full-time job. 

We looked at the market and saw tools that required us to send our metadata and query history to third-party servers. We did not want that. We wanted a tool built by engineers for engineers that respected data privacy and ran natively where the data actually lives. That is why SnowOps Intelligence was built directly on top of the Snowflake Native App framework.

## Core Features

* **Cost Guardian:** Real-time burst protection that identifies runaway queries and suspends warehouses before they drain your budget.
* **Cortex AI Analyst:** Chat with your metadata. Ask questions in plain English to generate SQL or get optimization suggestions for slow queries.
* **Agent Builder:** Deploy autonomous agents to monitor your infrastructure and alert you in Slack or Teams.
* **Security & Governance:** Automated PII scanning and CIS benchmark scoring.
* **Custom BI Builder:** Drag-and-drop dashboarding to build your own specific operational views.

## 🚀 Getting Started (Deployment)

This repository contains the full, free, and open-source codebase. It takes less than 5 minutes to deploy entirely within Snowflake's perimeter.

### Prerequisites
1. `ACCOUNTADMIN` access in your Snowflake environment.

### SQL-Only Deploy (Zero Clone)
You can deploy the entire application directly from GitHub without cloning the repository or installing CLI tools.

1. Log into **Snowsight**.
2. Open a new **SQL Worksheet** and run the following to define your role:
   ```sql
   USE ROLE ACCOUNTADMIN;
   ```
3. Copy the contents of the [`setup/setup_git_deploy.sql`](setup/setup_git_deploy.sql) script.
4. Paste it into the worksheet and click **▶ Run All**.
5. Navigate to **Projects → Streamlit** and launch the **SNOWFLAKE_OPS_INTELLIGENCE** app.

## 📊 Telemetry

SnowOps Intelligence collects **anonymous usage telemetry** to help us improve the product. This is standard practice for open-source tools like VS Code, Next.js, and Homebrew.

**What we collect:** Page navigation events and error reports only — no query content, no data, no PII.

**How it works:** Telemetry is powered by [PostHog](https://posthog.com) and requires explicit setup via `setup/setup_posthog.sql`. It will not work unless your Snowflake admin configures the external access integration.

**Closed network compatibility:** If your organization blocks outbound connections, telemetry simply doesn't fire. The app works perfectly without it.

**How to disable:** Set `TELEMETRY_ENABLED` to `FALSE` in `APP_CONTEXT.PLATFORM_SETTINGS`:
```sql
UPDATE SNOWFLAKE_OPS_INTELLIGENCE.APP_CONTEXT.PLATFORM_SETTINGS
SET SETTING_VALUE = 'FALSE'
WHERE SETTING_KEY = 'TELEMETRY_ENABLED';
```

## Support

SnowOps is built and maintained by [Aivon.io](https://snowops.aivon.io).

For enterprise support, bug reports, or feature requests, please reach out through [snowops.aivon.io](https://snowops.aivon.io).
