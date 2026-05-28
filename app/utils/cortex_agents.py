"""
Cortex Agents V2 — Native Snowflake Cortex Agents integration.
Wraps the Cortex Agents REST API for creating, running, and monitoring
AI agents with tool execution, multi-turn sessions, guardrails,
and 8 agent templates including migration, compliance, performance tuning.
"""
import streamlit as st
import json, uuid
import pandas as pd
from typing import Optional, Dict, List
from datetime import datetime


class CortexAgentManager:
    """Native Cortex Agents framework integration with tool execution."""

    def __init__(self, client):
        self.client = client
        self._app_db = None

    @property
    def app_db(self):
        if not self._app_db:
            self._app_db = self.client.get_app_db() if hasattr(self.client, 'get_app_db') else 'SNOWFLAKE_OPS_INTELLIGENCE'
        return self._app_db

    def ensure_tables(self):
        ddls = [
            f"""CREATE TABLE IF NOT EXISTS {self.app_db}.APP_CONTEXT.CORTEX_AGENTS (
                AGENT_ID VARCHAR(50) PRIMARY KEY,
                AGENT_NAME VARCHAR(255),
                DESCRIPTION VARCHAR(2000),
                SYSTEM_PROMPT VARCHAR(10000),
                TOOLS VARIANT,
                CAPABILITIES VARIANT,
                MODEL VARCHAR(100) DEFAULT 'mistral-large',
                MAX_TURNS NUMBER DEFAULT 5,
                GUARDRAILS VARIANT,
                SCHEDULE VARCHAR(255),
                STATUS VARCHAR(20) DEFAULT 'ACTIVE',
                CREATED_BY VARCHAR(255),
                CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP())""",
            f"""CREATE TABLE IF NOT EXISTS {self.app_db}.APP_CONTEXT.AGENT_SESSIONS (
                SESSION_ID VARCHAR(50) PRIMARY KEY,
                AGENT_ID VARCHAR(50),
                USER_NAME VARCHAR(255),
                MESSAGES VARIANT,
                STATUS VARCHAR(20) DEFAULT 'ACTIVE',
                CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
                UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP())""",
            f"""CREATE TABLE IF NOT EXISTS {self.app_db}.APP_CONTEXT.AGENT_RUNS (
                RUN_ID VARCHAR(50) PRIMARY KEY,
                AGENT_ID VARCHAR(50),
                SESSION_ID VARCHAR(50),
                USER_QUERY VARCHAR(10000),
                AGENT_RESPONSE VARCHAR(50000),
                TOOLS_USED VARIANT,
                TOKENS_USED NUMBER,
                DURATION_MS NUMBER,
                STATUS VARCHAR(20),
                ERROR_MESSAGE VARCHAR(5000),
                CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP())""",
        ]
        for d in ddls:
            try:
                self.client.execute_query(d, log=False)
            except:
                pass

    # ── Agent Templates (8 total) ──
    TEMPLATES = {
        "cost_watchdog": {
            "name": "💰 Cost Watchdog",
            "description": "Monitors credit consumption, detects anomalies, suggests optimizations",
            "system_prompt": "You are a Snowflake Cost Optimization Agent. Monitor credit usage, detect spending anomalies, and suggest warehouse right-sizing and query optimizations. Alert when budgets are at risk.",
            "tools": ["query_history", "warehouse_metering", "cost_forecast"],
            "capabilities": ["cost_analysis", "anomaly_detection", "budget_alerts"],
        },
        "security_auditor": {
            "name": "🔒 Security Auditor",
            "description": "Audits access controls, detects risky patterns, ensures compliance",
            "system_prompt": "You are a Snowflake Security Agent. Audit role hierarchies, privilege grants, network policies, and data access patterns. Flag potential security risks and recommend fixes.",
            "tools": ["access_history", "login_history", "grant_analysis"],
            "capabilities": ["security_audit", "compliance_check", "risk_detection"],
        },
        "pipeline_monitor": {
            "name": "🔄 Pipeline Monitor",
            "description": "Monitors pipeline health, detects failures, auto-remediates",
            "system_prompt": "You are a Data Pipeline Monitor Agent. Track task executions, dynamic table refreshes, and stream health. Diagnose failures and suggest fixes. Alert on SLA breaches.",
            "tools": ["task_history", "dynamic_table_status", "error_analysis"],
            "capabilities": ["pipeline_monitoring", "failure_diagnosis", "sla_tracking"],
        },
        "data_quality": {
            "name": "🧪 Data Quality Guardian",
            "description": "Monitors data freshness, completeness, and integrity",
            "system_prompt": "You are a Data Quality Agent. Monitor data freshness, null rates, duplicate rates, and referential integrity. Alert on quality degradation and suggest fixes.",
            "tools": ["table_metadata", "quality_checks", "freshness_monitor"],
            "capabilities": ["quality_monitoring", "anomaly_detection", "freshness_checks"],
        },
        # ── NEW V2 Templates ──
        "migration_assistant": {
            "name": "🚀 Migration Assistant",
            "description": "Helps migrate schemas, data, and queries from other databases to Snowflake",
            "system_prompt": "You are a Database Migration Agent. Help migrate from PostgreSQL, MySQL, Oracle, SQL Server, Redshift, and BigQuery to Snowflake. Convert DDL, DML, stored procedures, and data types. Identify compatibility issues and suggest Snowflake-native alternatives.",
            "tools": ["schema_analysis", "query_history", "table_metadata"],
            "capabilities": ["ddl_conversion", "data_type_mapping", "procedure_migration", "compatibility_check"],
        },
        "schema_architect": {
            "name": "🏗️ Schema Architect",
            "description": "Designs and optimizes table structures, clustering, and partitioning",
            "system_prompt": "You are a Snowflake Schema Design Agent. Design optimal table structures considering clustering keys, data types, compression, and access patterns. Recommend micro-partitioning strategies and materialized views.",
            "tools": ["table_metadata", "query_history", "storage_analysis"],
            "capabilities": ["schema_design", "clustering_optimization", "type_recommendation", "normalization_analysis"],
        },
        "compliance_reporter": {
            "name": "📋 Compliance Reporter",
            "description": "Generates compliance, audit, and governance reports",
            "system_prompt": "You are a Compliance and Governance Agent. Generate reports on data access patterns, role privilege analysis, sensitive data exposure, and regulatory compliance (SOC2, GDPR, HIPAA). Track data lineage and ownership.",
            "tools": ["access_history", "login_history", "grant_analysis", "table_metadata"],
            "capabilities": ["compliance_reporting", "access_audit", "sensitive_data_scan", "lineage_tracking"],
        },
        "performance_tuner": {
            "name": "⚡ Performance Tuner",
            "description": "Continuous query performance optimization and warehouse tuning",
            "system_prompt": "You are a Snowflake Performance Tuning Agent. Analyze slow queries, recommend clustering keys, suggest warehouse right-sizing, identify cache misses, and optimize join strategies. Monitor p50/p95/p99 latencies.",
            "tools": ["query_history", "warehouse_metering", "table_metadata"],
            "capabilities": ["query_optimization", "warehouse_sizing", "cache_analysis", "latency_tracking"],
        },
    }

    # ── Tool Registry ──
    TOOL_QUERIES = {
        "query_history": "SELECT COUNT(*) AS total_queries, SUM(CASE WHEN EXECUTION_STATUS='FAIL' THEN 1 ELSE 0 END) AS failed, AVG(TOTAL_ELAPSED_TIME)/1000 AS avg_duration_s, SUM(BYTES_SCANNED)/1e9 AS gb_scanned FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY WHERE START_TIME >= DATEADD(DAY,-1,CURRENT_TIMESTAMP())",
        "warehouse_metering": "SELECT WAREHOUSE_NAME, SUM(CREDITS_USED) AS credits, COUNT(*) AS queries FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY WHERE START_TIME >= DATEADD(DAY,-7,CURRENT_TIMESTAMP()) GROUP BY 1 ORDER BY 2 DESC LIMIT 10",
        "task_history": "SELECT NAME, STATE, COUNT(*) AS runs, AVG(TIMESTAMPDIFF('SECOND', QUERY_START_TIME, COMPLETED_TIME)) AS avg_duration_s FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY WHERE SCHEDULED_TIME >= DATEADD(DAY,-1,CURRENT_TIMESTAMP()) GROUP BY 1,2",
        "access_history": "SELECT USER_NAME, COUNT(*) AS queries FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY WHERE QUERY_START_TIME >= DATEADD(DAY,-1,CURRENT_TIMESTAMP()) GROUP BY 1 ORDER BY 2 DESC LIMIT 10",
        "login_history": "SELECT USER_NAME, IS_SUCCESS, COUNT(*) AS attempts FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY WHERE EVENT_TIMESTAMP >= DATEADD(DAY,-1,CURRENT_TIMESTAMP()) GROUP BY 1,2",
        "cost_forecast": "SELECT DATE_TRUNC('DAY', START_TIME) AS day, SUM(CREDITS_USED) AS daily_credits FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY WHERE START_TIME >= DATEADD(DAY,-30,CURRENT_TIMESTAMP()) GROUP BY 1 ORDER BY 1",
        "dynamic_table_status": "SELECT TABLE_NAME, SCHEDULING_STATE, TARGET_LAG, DATA_TIMESTAMP FROM SNOWFLAKE.ACCOUNT_USAGE.DYNAMIC_TABLE_REFRESH_HISTORY WHERE REFRESH_START_TIME >= DATEADD(DAY,-1,CURRENT_TIMESTAMP())",
        "error_analysis": "SELECT ERROR_CODE, ERROR_MESSAGE, COUNT(*) AS occurrences FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY WHERE EXECUTION_STATUS = 'FAIL' AND START_TIME >= DATEADD(DAY,-1,CURRENT_TIMESTAMP()) GROUP BY 1,2 ORDER BY 3 DESC LIMIT 10",
        "table_metadata": "SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, ROW_COUNT, BYTES, LAST_ALTERED FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA != 'INFORMATION_SCHEMA' ORDER BY LAST_ALTERED DESC LIMIT 20",
        "schema_analysis": "SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA != 'INFORMATION_SCHEMA' ORDER BY TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION LIMIT 100",
        "storage_analysis": "SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, ACTIVE_BYTES, TIME_TRAVEL_BYTES, FAILSAFE_BYTES, TABLE_CREATED FROM SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS WHERE TABLE_CATALOG = CURRENT_DATABASE() ORDER BY ACTIVE_BYTES DESC LIMIT 20",
        "grant_analysis": "SELECT GRANTEE_NAME, PRIVILEGE, TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, GRANTED_BY FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES WHERE DELETED_ON IS NULL ORDER BY CREATED_ON DESC LIMIT 50",
    }

    # ── Agent CRUD ──
    def create_agent(self, name: str, description: str, system_prompt: str,
                     tools: List[str] = None, capabilities: List[str] = None,
                     model: str = "mistral-large", guardrails: Dict = None,
                     schedule: str = None) -> str:
        aid = str(uuid.uuid4())[:8]
        safe = lambda s: s.replace("'", "''") if s else ""
        tools_json = json.dumps(tools or []).replace("'", "''")
        caps_json = json.dumps(capabilities or []).replace("'", "''")
        guards_json = json.dumps(guardrails or {
            "max_tokens": 4096, "blocked_topics": [], "allowed_schemas": [],
            "budget_limit_credits": 10
        }).replace("'", "''")
        sched = f"'{safe(schedule)}'" if schedule else "NULL"
        self.client.execute_query(f"""
            INSERT INTO {self.app_db}.APP_CONTEXT.CORTEX_AGENTS
            (AGENT_ID, AGENT_NAME, DESCRIPTION, SYSTEM_PROMPT, TOOLS, CAPABILITIES, MODEL, GUARDRAILS, SCHEDULE, CREATED_BY)
            VALUES ('{aid}', '{safe(name)}', '{safe(description)}', '{safe(system_prompt)}',
                    PARSE_JSON('{tools_json}'), PARSE_JSON('{caps_json}'), '{safe(model)}',
                    PARSE_JSON('{guards_json}'), {sched}, CURRENT_USER())
        """)
        return aid

    def create_from_template(self, template_key: str) -> str:
        t = self.TEMPLATES.get(template_key)
        if not t:
            return None
        return self.create_agent(
            t['name'], t['description'], t['system_prompt'],
            t['tools'], t['capabilities']
        )

    def list_agents(self) -> pd.DataFrame:
        return self.client.execute_query(
            f"SELECT * FROM {self.app_db}.APP_CONTEXT.CORTEX_AGENTS ORDER BY CREATED_AT DESC"
        )

    def get_agent(self, aid: str) -> Optional[Dict]:
        df = self.client.execute_query(
            f"SELECT * FROM {self.app_db}.APP_CONTEXT.CORTEX_AGENTS WHERE AGENT_ID = '{aid}'"
        )
        if df.empty:
            return None
        d = df.iloc[0].to_dict()
        for k in ['TOOLS', 'CAPABILITIES', 'GUARDRAILS']:
            if d.get(k) and isinstance(d[k], str):
                try:
                    d[k] = json.loads(d[k])
                except:
                    pass
        return d

    def delete_agent(self, aid: str):
        safe = aid.replace("'", "''")
        self.client.execute_query(f"DELETE FROM {self.app_db}.APP_CONTEXT.AGENT_RUNS WHERE AGENT_ID = '{safe}'")
        self.client.execute_query(f"DELETE FROM {self.app_db}.APP_CONTEXT.AGENT_SESSIONS WHERE AGENT_ID = '{safe}'")
        self.client.execute_query(f"DELETE FROM {self.app_db}.APP_CONTEXT.CORTEX_AGENTS WHERE AGENT_ID = '{safe}'")

    # ── Agent Execution ──
    def run_agent(self, agent_id: str, query: str, session_id: str = None) -> Dict:
        """Execute a query against an agent using Cortex COMPLETE with guardrails and tool execution."""
        agent = self.get_agent(agent_id)
        if not agent:
            return {"status": "ERROR", "response": "Agent not found"}

        model = agent.get('MODEL', 'mistral-large')
        system = agent.get('SYSTEM_PROMPT', '')
        tools = agent.get('TOOLS', [])
        guardrails = agent.get('GUARDRAILS', {})
        if isinstance(guardrails, str):
            try:
                guardrails = json.loads(guardrails)
            except:
                guardrails = {}

        # ── Enforce guardrails ──
        blocked_topics = guardrails.get('blocked_topics', [])
        if blocked_topics:
            query_lower = query.lower()
            for topic in blocked_topics:
                if topic.lower() in query_lower:
                    return {
                        "status": "BLOCKED",
                        "response": f"Query blocked: topic '{topic}' is restricted by agent guardrails.",
                        "session_id": session_id or "",
                    }

        budget_limit = guardrails.get('budget_limit_credits', 0)
        if budget_limit and budget_limit > 0:
            try:
                usage_df = self.client.execute_query(f"""
                    SELECT COALESCE(SUM(TOKENS_USED), 0) AS total_tokens
                    FROM {self.app_db}.APP_CONTEXT.AGENT_RUNS
                    WHERE AGENT_ID = '{agent_id}'
                      AND CREATED_AT >= DATEADD(hour, -24, CURRENT_TIMESTAMP())
                """, log=False)
                if not usage_df.empty:
                    total_tokens = float(usage_df.iloc[0].get('TOTAL_TOKENS', 0) or 0)
                    estimated_credits = total_tokens / 1_000_000
                    if estimated_credits >= budget_limit:
                        return {
                            "status": "BLOCKED",
                            "response": f"Agent budget exceeded: {estimated_credits:.4f} credits used (limit: {budget_limit}). Resets in 24h.",
                            "session_id": session_id or "",
                        }
            except:
                pass

        max_tokens = guardrails.get('max_tokens', 4096)
        if max_tokens:
            max_chars = int(max_tokens) * 4
            if len(query) > max_chars:
                query = query[:max_chars]

        # Build enriched prompt with tool context
        tool_context = self._gather_tool_context(tools)
        full_prompt = f"[SYSTEM]\n{system}\n\n"
        if tool_context:
            full_prompt += f"[DATA CONTEXT]\n{tool_context}\n\n"

        # Multi-turn: load session history
        messages = []
        sid = session_id or str(uuid.uuid4())[:8]
        if session_id:
            messages = self._load_session_messages(session_id)
        if messages:
            history = "\n".join([f"[{m['role'].upper()}] {m['content']}" for m in messages[-6:]])
            full_prompt += f"[CONVERSATION HISTORY]\n{history}\n\n"
        full_prompt += f"[USER QUERY]\n{query}"

        start = datetime.now()
        try:
            safe = full_prompt.replace("'", "''")
            result = self.client.execute_query(
                f"SELECT SNOWFLAKE.CORTEX.COMPLETE('{model}', '{safe}') AS response", log=False
            )
            response = result.iloc[0]['RESPONSE'] if not result.empty else "No response"
            duration = int((datetime.now() - start).total_seconds() * 1000)

            # Estimate tokens from prompt + response length
            estimated_tokens = (len(full_prompt) + len(str(response))) // 4

            # Save to session
            messages.append({"role": "user", "content": query})
            messages.append({"role": "assistant", "content": str(response)[:5000]})
            self._save_session(sid, agent_id, messages)

            # Log the run with token estimate
            rid = str(uuid.uuid4())[:8]
            safe_q = query.replace("'", "''")[:5000]
            safe_r = str(response).replace("'", "''")[:10000]
            tools_json = json.dumps(tools).replace("'", "''")
            self.client.execute_query(f"""
                INSERT INTO {self.app_db}.APP_CONTEXT.AGENT_RUNS
                (RUN_ID, AGENT_ID, SESSION_ID, USER_QUERY, AGENT_RESPONSE,
                 TOOLS_USED, TOKENS_USED, DURATION_MS, STATUS)
                VALUES ('{rid}', '{agent_id}', '{sid}', '{safe_q}', '{safe_r}',
                        PARSE_JSON('{tools_json}'), {estimated_tokens}, {duration}, 'SUCCESS')
            """, log=False)

            return {
                "status": "SUCCESS", "response": response, "duration_ms": duration,
                "session_id": sid, "model": model, "tools_used": tools,
                "tokens_used": estimated_tokens,
            }
        except Exception as e:
            return {"status": "ERROR", "response": str(e)}

    def _gather_tool_context(self, tools: List[str]) -> str:
        """Gather context data from registered tools."""
        context_parts = []
        for tool in tools:
            q = self.TOOL_QUERIES.get(tool)
            if q:
                try:
                    df = self.client.execute_query(q, log=False)
                    if not df.empty:
                        context_parts.append(f"\n--- {tool.upper()} ---\n{df.head(20).to_string()}")
                except:
                    pass
        return "\n".join(context_parts) if context_parts else ""

    # ── Session Management ──
    def _load_session_messages(self, session_id: str) -> List[Dict]:
        try:
            df = self.client.execute_query(
                f"SELECT MESSAGES FROM {self.app_db}.APP_CONTEXT.AGENT_SESSIONS WHERE SESSION_ID = '{session_id}'",
                log=False
            )
            if not df.empty:
                msgs = df.iloc[0]['MESSAGES']
                if isinstance(msgs, str):
                    return json.loads(msgs)
                return msgs if isinstance(msgs, list) else []
        except:
            pass
        return []

    def _save_session(self, session_id: str, agent_id: str, messages: List[Dict]):
        msgs_json = json.dumps(messages[-20:], default=str).replace("'", "''")
        try:
            existing = self.client.execute_query(
                f"SELECT 1 FROM {self.app_db}.APP_CONTEXT.AGENT_SESSIONS WHERE SESSION_ID = '{session_id}'",
                log=False
            )
            if existing.empty:
                self.client.execute_query(f"""
                    INSERT INTO {self.app_db}.APP_CONTEXT.AGENT_SESSIONS
                    (SESSION_ID, AGENT_ID, USER_NAME, MESSAGES)
                    VALUES ('{session_id}', '{agent_id}', CURRENT_USER(), PARSE_JSON('{msgs_json}'))
                """, log=False)
            else:
                self.client.execute_query(f"""
                    UPDATE {self.app_db}.APP_CONTEXT.AGENT_SESSIONS
                    SET MESSAGES = PARSE_JSON('{msgs_json}'), UPDATED_AT = CURRENT_TIMESTAMP()
                    WHERE SESSION_ID = '{session_id}'
                """, log=False)
        except:
            pass

    def get_agent_history(self, agent_id: str, limit: int = 20) -> pd.DataFrame:
        return self.client.execute_query(f"""
            SELECT * FROM {self.app_db}.APP_CONTEXT.AGENT_RUNS
            WHERE AGENT_ID = '{agent_id}'
            ORDER BY CREATED_AT DESC LIMIT {limit}
        """)

    def get_agent_metrics(self, agent_id: str) -> Dict:
        try:
            df = self.client.execute_query(f"""
                SELECT COUNT(*) AS total_runs,
                       AVG(DURATION_MS) AS avg_duration,
                       SUM(CASE WHEN STATUS='SUCCESS' THEN 1 ELSE 0 END) AS successes,
                       SUM(CASE WHEN STATUS='ERROR' THEN 1 ELSE 0 END) AS errors
                FROM {self.app_db}.APP_CONTEXT.AGENT_RUNS
                WHERE AGENT_ID = '{agent_id}'
            """, log=False)
            return df.iloc[0].to_dict() if not df.empty else {}
        except:
            return {}

    def get_all_agent_metrics(self) -> pd.DataFrame:
        """Get aggregated metrics for all agents."""
        try:
            return self.client.execute_query(f"""
                SELECT a.AGENT_ID, a.AGENT_NAME, a.STATUS,
                       COUNT(r.RUN_ID) AS total_runs,
                       AVG(r.DURATION_MS) AS avg_duration_ms,
                       SUM(CASE WHEN r.STATUS='SUCCESS' THEN 1 ELSE 0 END) AS successes,
                       SUM(CASE WHEN r.STATUS='ERROR' THEN 1 ELSE 0 END) AS errors
                FROM {self.app_db}.APP_CONTEXT.CORTEX_AGENTS a
                LEFT JOIN {self.app_db}.APP_CONTEXT.AGENT_RUNS r ON a.AGENT_ID = r.AGENT_ID
                GROUP BY 1,2,3
                ORDER BY total_runs DESC
            """, log=False)
        except:
            return pd.DataFrame()


def get_agent_manager(client=None):
    if client is None and "snowflake_client" in st.session_state:
        client = st.session_state.snowflake_client
    if client is None:
        return None
    if 'agent_manager' not in st.session_state:
        mgr = CortexAgentManager(client)
        mgr.ensure_tables()
        st.session_state.agent_manager = mgr
    return st.session_state.agent_manager
