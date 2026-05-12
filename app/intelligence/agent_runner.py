"""
Autonomous Agent Runner & Observability
Implements the ReAct (Reason+Act) loop for Snowflake Agents using Cortex AI.
Enhanced with robust JSON parsing, expanded tool set, and notification support.
"""

import json
import re
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional
import pandas as pd
from .cortex_ai import CortexAI


# ──────────────────────────────────────────────
#  Agent Logger — Structured Observability
# ──────────────────────────────────────────────

class AgentLogger:
    """
    Handles structured logging of agent thoughts and actions to Snowflake tables.
    Provides observability into the 'Black Box' of AI reasoning.
    """

    def __init__(self, client):
        self.client = client
        self._ensure_logs_table()

    def _ensure_logs_table(self):
        """Ensure the agent logs and notifications tables exist"""
        try:
            self.client.execute_query("CREATE SCHEMA IF NOT EXISTS APP_CONTEXT", log=False)
            self.client.execute_query("""
            CREATE TABLE IF NOT EXISTS APP_CONTEXT.AGENT_LOGS (
                LOG_ID VARCHAR(50) PRIMARY KEY,
                AGENT_ID VARCHAR(50),
                RUN_ID VARCHAR(50),
                TIMESTAMP TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
                STEP_NUMBER INT,
                TYPE VARCHAR(20),
                CONTENT VARCHAR(16777216),
                METADATA VARIANT
            )
            """, log=False)
            # Notifications table for agent alerts
            self.client.execute_query("""
            CREATE TABLE IF NOT EXISTS APP_CONTEXT.AGENT_NOTIFICATIONS (
                NOTIFICATION_ID VARCHAR(50) PRIMARY KEY,
                AGENT_ID VARCHAR(50),
                RUN_ID VARCHAR(50),
                SEVERITY VARCHAR(20) DEFAULT 'INFO',
                TITLE VARCHAR(500),
                MESSAGE VARCHAR(16777216),
                IS_READ BOOLEAN DEFAULT FALSE,
                CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
            )
            """, log=False)
        except Exception as e:
            print(f"Failed to init agent tables: {e}")

    def log_step(self, agent_id: str, run_id: str, step_num: int,
                 log_type: str, content: str, metadata: Dict = None):
        """Write a log entry to Snowflake"""
        try:
            log_id = str(uuid.uuid4())
            content_escaped = content.replace("'", "''")
            meta_val = f"PARSE_JSON('{json.dumps(metadata)}')" if metadata else "NULL"

            sql = f"""
            INSERT INTO APP_CONTEXT.AGENT_LOGS
            (LOG_ID, AGENT_ID, RUN_ID, STEP_NUMBER, TYPE, CONTENT, METADATA)
            VALUES
            ('{log_id}', '{agent_id}', '{run_id}', {step_num}, '{log_type}', '{content_escaped}', {meta_val})
            """
            self.client.execute_query(sql, log=False)
        except Exception as e:
            print(f"Logging failed: {e}")

    def log_notification(self, agent_id: str, run_id: str,
                         severity: str, title: str, message: str):
        """Write a notification/alert from an agent"""
        try:
            nid = str(uuid.uuid4())
            safe_title = title.replace("'", "''")
            safe_msg = message.replace("'", "''")
            sql = f"""
            INSERT INTO APP_CONTEXT.AGENT_NOTIFICATIONS
            (NOTIFICATION_ID, AGENT_ID, RUN_ID, SEVERITY, TITLE, MESSAGE)
            VALUES
            ('{nid}', '{agent_id}', '{run_id}', '{severity}', '{safe_title}', '{safe_msg}')
            """
            self.client.execute_query(sql, log=False)
        except Exception as e:
            print(f"Notification log failed: {e}")

    def get_run_logs(self, run_id: str) -> pd.DataFrame:
        """Retrieve logs for a specific run"""
        sql = f"""
        SELECT * FROM APP_CONTEXT.AGENT_LOGS
        WHERE RUN_ID = '{run_id}'
        ORDER BY STEP_NUMBER ASC
        """
        return self.client.execute_query(sql)

    def get_notifications(self, limit: int = 50) -> pd.DataFrame:
        """Retrieve recent agent notifications"""
        sql = f"""
        SELECT * FROM APP_CONTEXT.AGENT_NOTIFICATIONS
        ORDER BY CREATED_AT DESC
        LIMIT {limit}
        """
        try:
            return self.client.execute_query(sql)
        except:
            return pd.DataFrame()

    def mark_notification_read(self, notification_id: str):
        """Mark a notification as read"""
        try:
            self.client.execute_query(
                f"UPDATE APP_CONTEXT.AGENT_NOTIFICATIONS SET IS_READ = TRUE WHERE NOTIFICATION_ID = '{notification_id}'",
                log=False
            )
        except:
            pass


# ──────────────────────────────────────────────
#  JSON Extraction Helper
# ──────────────────────────────────────────────

def extract_json_from_text(text: str) -> dict:
    """
    Robustly extract the first JSON object from LLM output.
    Uses brace-matching to handle trailing commentary.
    """
    text = text.strip()

    # Strategy 1: Find first { and match braces
    start = text.find('{')
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    candidate = text[start:i+1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

    # Strategy 2: Try the whole string
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strategy 3: Wrap raw text as summary
    return {"summary": text}


# ──────────────────────────────────────────────
#  Agent Runner — ReAct Loop with Expanded Tools
# ──────────────────────────────────────────────

TOOL_DESCRIPTIONS = {
    "Check Credit Usage": {
        "description": "Get total credit usage for a time period.",
        "input": '{"days": 7}',
        "example": "How many credits were used in the last 7 days?"
    },
    "Get Cost by Warehouse": {
        "description": "Break down credit usage per warehouse.",
        "input": '{"days": 7}',
        "example": "Which warehouse is burning the most credits?"
    },
    "Check Warehouse Status": {
        "description": "Get current status of all warehouses (STARTED, SUSPENDED, etc).",
        "input": '{}',
        "example": "Are there any active warehouses right now?"
    },
    "Analyze Query History": {
        "description": "Get recent queries with execution time and status.",
        "input": '{"limit": 10}',
        "example": "Show me the last 10 queries."
    },
    "Get Top Queries": {
        "description": "Find the slowest or most expensive queries.",
        "input": '{"days": 7, "metric": "duration"}',
        "example": "What are the slowest queries this week?"
    },
    "Get Active Users": {
        "description": "See which users ran queries recently.",
        "input": '{"days": 7}',
        "example": "Who is using Snowflake this week?"
    },
    "Read Metadata": {
        "description": "Get available tables and schemas in the account.",
        "input": '{}',
        "example": "What data sources are available?"
    },
    "Execute SQL": {
        "description": "Run a custom Snowflake SQL query (read-only by default).",
        "input": '{"sql": "SELECT CURRENT_TIMESTAMP()"}',
        "example": "Run a custom query."
    },
    "Suspend Warehouse": {
        "description": "Suspend an active warehouse to save credits.",
        "input": '{"warehouse": "COMPUTE_WH"}',
        "example": "Suspend the COMPUTE_WH warehouse."
    },
    "Send Notification": {
        "description": "Create an alert or notification for the user.",
        "input": '{"severity": "WARNING", "title": "High Credit Usage", "message": "Credits exceeded threshold."}',
        "example": "Alert the user about high spending."
    }
}


class AgentRunner:
    """
    Executes an autonomous agent loop (ReAct pattern).
    Uses Snowflake Cortex to reason about goals and select tools.
    """

    def __init__(self, client):
        self.client = client
        self.cortex = CortexAI(client)
        self.logger = AgentLogger(client)
        self.max_steps = 8

    def _get_system_prompt(self, role: str, capabilities: List[str]) -> str:
        """Build a detailed system prompt with tool descriptions."""
        tools_text = ""
        for cap in capabilities:
            info = TOOL_DESCRIPTIONS.get(cap, {})
            if info:
                tools_text += f"\n- **{cap}**: {info['description']}\n  Input format: {info['input']}\n"
            else:
                tools_text += f"\n- **{cap}**: General capability.\n"

        return f"""You are an autonomous Snowflake Operations Agent.
Role: {role}

You have access to these tools:
{tools_text}

Follow the ReAct reasoning process for EACH step:

THOUGHT: [Analyze what you know and what you need to do next]
ACTION: [Exact tool name from the list above, or "Final Answer" if done]
INPUT: [Single-line valid JSON matching the tool input format]

CRITICAL RULES:
1. INPUT must be a SINGLE LINE of valid JSON. No extra text after the JSON.
2. Use exact tool names from the list.
3. When you have enough information, use ACTION: Final Answer with INPUT: {{"summary": "your findings"}}
4. Do NOT repeat the same action more than 2 times.
5. If a tool returns an error, try a different approach or give a Final Answer with what you know.
6. For credit usage queries, always use "days" as the key (not "time_range").
"""

    def execute_tool(self, tool_name: str, tool_input: Dict,
                     guardrails: Dict = None, agent_id: str = "",
                     run_id: str = "") -> str:
        """Execute a requested tool with Guardrail checks."""

        forbidden = guardrails.get('forbidden_actions', []) if guardrails else []
        approval_req = guardrails.get('require_approval', False) if guardrails else False

        try:
            # ── Check Credit Usage ──
            if tool_name == "Check Credit Usage":
                days = tool_input.get('days', tool_input.get('time_range', 7))
                if isinstance(days, str):
                    # Parse "last 7 days" → 7
                    import re as _re
                    nums = _re.findall(r'\d+', str(days))
                    days = int(nums[0]) if nums else 7
                days = min(int(days), 90)

                q = f"""
                SELECT
                    SUM(CREDITS_USED) as TOTAL_CREDITS,
                    AVG(CREDITS_USED) as AVG_DAILY,
                    MAX(CREDITS_USED) as PEAK_DAY,
                    COUNT(DISTINCT DATE_TRUNC('day', START_TIME)) as ACTIVE_DAYS
                FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
                """
                res = self.client.execute_query(q)
                if not res.empty:
                    total = res.iloc[0]['TOTAL_CREDITS']
                    avg = res.iloc[0]['AVG_DAILY']
                    peak = res.iloc[0]['PEAK_DAY']
                    active = res.iloc[0]['ACTIVE_DAYS']
                    avg_daily = float(total or 0) / max(int(active or 1), 1)
                    return (f"Credit Usage Report (Last {days} days):\n"
                            f"• Total Credits: {total:.2f}\n"
                            f"• Average per Metering Event: {avg:.4f}\n"
                            f"• Peak Single Event: {peak:.4f}\n"
                            f"• Active Days: {active}\n"
                            f"• Average Daily Rate: {avg_daily:.2f} credits/day\n"
                            f"• Projected Monthly: {avg_daily * 30:.2f} credits")
                return "No credit usage data found."

            # ── Get Cost by Warehouse ──
            elif tool_name == "Get Cost by Warehouse":
                days = int(tool_input.get('days', 7))
                q = f"""
                SELECT
                    WAREHOUSE_NAME,
                    SUM(CREDITS_USED) as TOTAL_CREDITS,
                    ROUND(SUM(CREDITS_USED) * 3.0, 2) as EST_COST_USD
                FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
                GROUP BY WAREHOUSE_NAME
                ORDER BY TOTAL_CREDITS DESC
                """
                df = self.client.execute_query(q)
                if not df.empty:
                    lines = [f"Credit Breakdown by Warehouse (Last {days} days):"]
                    for _, r in df.iterrows():
                        lines.append(f"• {r['WAREHOUSE_NAME']}: {r['TOTAL_CREDITS']:.2f} credits (~${r['EST_COST_USD']})")
                    return "\n".join(lines)
                return "No warehouse cost data found."

            # ── Check Warehouse Status ──
            elif tool_name == "Check Warehouse Status":
                q = """
                SELECT
                    WAREHOUSE_NAME,
                    STATE,
                    TYPE,
                    SIZE
                FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSES
                WHERE DELETED IS NULL
                ORDER BY WAREHOUSE_NAME
                """
                df = self.client.execute_query(q)
                if not df.empty:
                    lines = ["Warehouse Status:"]
                    for _, r in df.iterrows():
                        emoji = "🟢" if r.get('STATE') == 'STARTED' else "⏸️"
                        lines.append(f"{emoji} {r['WAREHOUSE_NAME']}: {r.get('STATE', 'UNKNOWN')} ({r.get('SIZE', 'N/A')})")
                    return "\n".join(lines)
                return "No warehouse data found."

            # ── Analyze Query History ──
            elif tool_name == "Analyze Query History":
                limit = min(int(tool_input.get('limit', 10)), 25)
                q = f"""
                SELECT
                    QUERY_TEXT,
                    USER_NAME,
                    WAREHOUSE_NAME,
                    TOTAL_ELAPSED_TIME / 1000.0 as ELAPSED_SEC,
                    EXECUTION_STATUS,
                    START_TIME
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE START_TIME >= DATEADD(day, -7, CURRENT_TIMESTAMP())
                ORDER BY START_TIME DESC
                LIMIT {limit}
                """
                df = self.client.execute_query(q)
                if not df.empty:
                    lines = [f"Recent {len(df)} Queries:"]
                    for _, r in df.head(10).iterrows():
                        qt = str(r.get('QUERY_TEXT', ''))[:80]
                        lines.append(f"• [{r.get('EXECUTION_STATUS', '?')}] {qt}... ({r.get('ELAPSED_SEC', 0):.1f}s by {r.get('USER_NAME', '?')})")
                    return "\n".join(lines)
                return "No recent query data."

            # ── Get Top Queries ──
            elif tool_name == "Get Top Queries":
                days = int(tool_input.get('days', 7))
                metric = tool_input.get('metric', 'duration')
                order_col = 'TOTAL_ELAPSED_TIME' if metric == 'duration' else 'CREDITS_USED_CLOUD_SERVICES'
                q = f"""
                SELECT
                    QUERY_TEXT,
                    USER_NAME,
                    WAREHOUSE_NAME,
                    TOTAL_ELAPSED_TIME / 1000.0 as ELAPSED_SEC,
                    CREDITS_USED_CLOUD_SERVICES,
                    EXECUTION_STATUS
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
                  AND EXECUTION_STATUS = 'SUCCESS'
                ORDER BY {order_col} DESC
                LIMIT 5
                """
                df = self.client.execute_query(q)
                if not df.empty:
                    lines = [f"Top 5 Queries by {metric} (Last {days} days):"]
                    for i, (_, r) in enumerate(df.iterrows(), 1):
                        qt = str(r.get('QUERY_TEXT', ''))[:100]
                        lines.append(f"{i}. {qt}... ({r.get('ELAPSED_SEC', 0):.1f}s, user: {r.get('USER_NAME', '?')})")
                    return "\n".join(lines)
                return "No query data found."

            # ── Get Active Users ──
            elif tool_name == "Get Active Users":
                days = int(tool_input.get('days', 7))
                q = f"""
                SELECT
                    USER_NAME,
                    COUNT(*) as QUERY_COUNT,
                    SUM(TOTAL_ELAPSED_TIME) / 1000.0 as TOTAL_SEC
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
                GROUP BY USER_NAME
                ORDER BY QUERY_COUNT DESC
                LIMIT 10
                """
                df = self.client.execute_query(q)
                if not df.empty:
                    lines = [f"Active Users (Last {days} days):"]
                    for _, r in df.iterrows():
                        lines.append(f"• {r['USER_NAME']}: {r['QUERY_COUNT']} queries ({r['TOTAL_SEC']:.0f}s total)")
                    return "\n".join(lines)
                return "No user activity data found."

            # ── Read Metadata ──
            elif tool_name == "Read Metadata":
                return ("Available Data Sources:\n"
                        "• SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY — Credit usage per warehouse\n"
                        "• SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY — All queries with performance metrics\n"
                        "• SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY — User login events\n"
                        "• SNOWFLAKE.ACCOUNT_USAGE.STORAGE_USAGE — Storage consumption over time\n"
                        "• SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSES — Warehouse definitions and status\n"
                        "• SNOWFLAKE.ACCOUNT_USAGE.USERS — Account user list\n"
                        "• SNOWFLAKE.ACCOUNT_USAGE.ROLES — Role hierarchy")

            # ── Execute SQL ──
            elif tool_name == "Execute SQL":
                sql = tool_input.get('sql', '')
                if not sql:
                    return "Error: No SQL provided."

                # Guardrail: Check forbidden keywords
                if any(bad in sql.upper() for bad in forbidden):
                    return f"🚫 BLOCKED: SQL contains forbidden keyword."

                # Guardrail: Approval for writes
                if approval_req:
                    is_write = not sql.strip().upper().startswith(("SELECT", "SHOW", "DESCRIBE", "DESC"))
                    if is_write:
                        return f"✋ BLOCKED: Human approval required for write operations."

                res = self.client.execute_query(sql)
                return f"Result:\n{res.to_string()}" if not res.empty else "Query executed successfully (no rows returned)."

            # ── Suspend Warehouse ──
            elif tool_name == "Suspend Warehouse":
                wh = tool_input.get('warehouse', '')
                if not wh:
                    return "Error: No warehouse name provided."

                if "ALTER" in forbidden:
                    return "🚫 BLOCKED: ALTER operations are forbidden by guardrails."
                if approval_req:
                    return f"✋ BLOCKED: Human approval required. Warehouse '{wh}' suspension pending."

                sql = f"ALTER WAREHOUSE {wh} SUSPEND"
                self.client.execute_query(sql)
                return f"✅ Warehouse '{wh}' has been suspended."

            # ── Send Notification ──
            elif tool_name == "Send Notification":
                severity = tool_input.get('severity', 'INFO')
                title = tool_input.get('title', 'Agent Alert')
                message = tool_input.get('message', 'No details provided.')
                self.logger.log_notification(agent_id, run_id, severity, title, message)
                return f"✅ Notification sent: [{severity}] {title}"

            else:
                return f"Error: Tool '{tool_name}' is not available."

        except Exception as e:
            return f"Tool execution error: {e}"

    def run_agent(self, agent_id: str, name: str, role: str, goal: str,
                  capabilities: List[str], guardrails: Dict = None) -> str:
        """
        Run the agent loop for a given goal.
        Returns the Run ID.
        """
        run_id = str(uuid.uuid4())

        # Log start
        self.logger.log_step(agent_id, run_id, 0, "START",
                             f"Starting agent run for goal: {goal}")

        system_prompt = self._get_system_prompt(role, capabilities)
        history = f"Goal: {goal}\n"

        step = 1
        seen_actions = {}  # Track repeated actions

        while step <= self.max_steps:
            # Call LLM for next step
            prompt = f"{system_prompt}\n\nHistory:\n{history}\n\nWhat is your next step?"
            llm_response = ""

            try:
                esc_prompt = prompt.replace("'", "''")
                q = f"SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large', '{esc_prompt}')"
                res = self.client.execute_query(q)
                if not res.empty:
                    llm_response = res.iloc[0, 0]
            except Exception as e:
                self.logger.log_step(agent_id, run_id, step, "ERROR", f"LLM call failed: {e}")
                break

            self.logger.log_step(agent_id, run_id, step, "THOUGHT_PROCESS", llm_response)

            # Parse LLM output
            thought_match = re.search(r"THOUGHT:(.*?)(?=ACTION:|$)", llm_response, re.DOTALL)
            action_match = re.search(r"ACTION:(.*?)(?=INPUT:|$)", llm_response, re.DOTALL)
            input_match = re.search(r"INPUT:(.*)", llm_response, re.DOTALL)

            thought = thought_match.group(1).strip() if thought_match else "..."
            action = action_match.group(1).strip() if action_match else "Final Answer"
            input_str = input_match.group(1).strip() if input_match else "{}"

            # ── Final Answer ──
            if action == "Final Answer":
                parsed = extract_json_from_text(input_str)
                summary = parsed.get('summary', input_str[:500])
                self.logger.log_step(agent_id, run_id, step, "FINAL_ANSWER", summary)
                break

            # ── Detect loops (same action > 2 times) ──
            action_key = f"{action}:{input_str[:50]}"
            seen_actions[action_key] = seen_actions.get(action_key, 0) + 1
            if seen_actions[action_key] > 2:
                self.logger.log_step(agent_id, run_id, step, "ERROR",
                                     f"Loop detected: '{action}' called {seen_actions[action_key]} times. Forcing Final Answer.")
                self.logger.log_step(agent_id, run_id, step + 1, "FINAL_ANSWER",
                                     f"Agent stopped due to repeated action. Last observation available in history.")
                break

            # ── Parse tool input (robust JSON extraction) ──
            tool_result = ""
            try:
                tool_input = extract_json_from_text(input_str)
                self.logger.log_step(agent_id, run_id, step, "ACTION",
                                     f"Calling {action} with {json.dumps(tool_input)}")

                tool_result = self.execute_tool(action, tool_input, guardrails,
                                                agent_id, run_id)

                self.logger.log_step(agent_id, run_id, step, "OBSERVATION",
                                     tool_result[:2000])
            except Exception as e:
                tool_result = f"Error executing tool: {e}"
                self.logger.log_step(agent_id, run_id, step, "ERROR", tool_result)

            # Append to history for next turn
            history += f"\nStep {step}:\nThought: {thought}\nAction: {action}\nResult: {tool_result[:500]}\n"
            step += 1

        return run_id
