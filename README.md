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

## How to Install

This repository contains the Pro Edition source code. Deployment takes less than five minutes using Snowflake's Git Integration.

### Prerequisites

1. `ACCOUNTADMIN` access in your Snowflake environment.
2. A GitHub Personal Access Token with `Read` access to this private repository.

### Setup Guide

1. Log into your **Snowsight** web interface.
2. Open a new **SQL Worksheet**.
3. Open `setup/setup_git_deploy.sql` from this repository locally.
4. Locate the `CREATE OR REPLACE SECRET` block and replace `<YOUR_GITHUB_PERSONAL_ACCESS_TOKEN>` with your actual token:
   ```sql
   CREATE OR REPLACE SECRET APP_DATA.SNOWOPS_GIT_SECRET
     TYPE = PASSWORD
     PASSWORD = 'your_actual_token_here';
   ```
5. Paste the entire script into your worksheet and click **Run All**.
6. Navigate to **Projects > Streamlit** and launch the **SNOWOPS_INTEL_PRO** app.

## Support

For enterprise support, bug reports, or feature requests, please reach out through [snowops.aivon.io](https://snowops.aivon.io).
