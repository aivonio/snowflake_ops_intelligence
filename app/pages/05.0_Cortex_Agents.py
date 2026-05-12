import streamlit as st
import pandas as pd
import json
import uuid
from datetime import datetime
import sys
import os

try:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
except (NameError, TypeError):
    pass

from utils.snowflake_client import get_snowflake_client
from utils.styles import apply_global_styles, render_sidebar, COLORS
from intelligence.agent_runner import AgentRunner, AgentLogger, TOOL_DESCRIPTIONS

st.set_page_config(
    page_title="Agent Builder | Snowflake Ops",
    page_icon="🤖",
    layout="wide"
)

apply_global_styles()
render_sidebar()

# ── All available capability names (matches TOOL_DESCRIPTIONS keys)
ALL_CAPABILITIES = list(TOOL_DESCRIPTIONS.keys())


def ensure_agents_table(client):
    """Ensure the agents table exists."""
    ddl = """
    CREATE TABLE IF NOT EXISTS APP_CONTEXT.AGENTS (
        AGENT_ID VARCHAR(50) PRIMARY KEY,
        AGENT_NAME VARCHAR(255),
        ROLE VARCHAR(100),
        GOAL VARCHAR(5000),
        CAPABILITIES VARCHAR(1000),
        KNOWLEDGE_SOURCES VARCHAR(1000),
        REASONING_ENGINE VARCHAR(50),
        SCHEDULE_TYPE VARCHAR(50),
        CRON_EXPRESSION VARCHAR(50),
        IS_ACTIVE BOOLEAN DEFAULT TRUE,
        CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
    )
    """
    try:
        client.execute_query("CREATE SCHEMA IF NOT EXISTS APP_CONTEXT", log=False)
        client.execute_query(ddl, log=False)
        try:
            check_col = client.execute_query(
                "SELECT * FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'APP_CONTEXT' AND TABLE_NAME = 'AGENTS' AND COLUMN_NAME = 'GUARDRAILS'",
                log=False
            )
            if check_col.empty:
                client.execute_query("ALTER TABLE APP_CONTEXT.AGENTS ADD COLUMN GUARDRAILS VARIANT", log=False)
        except:
            pass
    except Exception as e:
        st.error(f"Failed to initialize agent storage: {e}")


def main():
    client = get_snowflake_client()
    if not client.session:
        st.error("Please log in.")
        return

    st.title("🤖 Agent Builder")
    st.caption("Create autonomous AI agents to monitor and optimize your Snowflake environment.")

    ensure_agents_table(client)

    # Initialize Runner & Logger
    runner = AgentRunner(client)
    logger = AgentLogger(client)

    # ── Initialize session state for guardrails ──
    if 'gr_credits' not in st.session_state:
        st.session_state['gr_credits'] = 10.0
    if 'gr_actions' not in st.session_state:
        st.session_state['gr_actions'] = ["DROP", "DELETE", "ALTER"]
    if 'gr_approval' not in st.session_state:
        st.session_state['gr_approval'] = True

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "🏗️ Builder",
        "🧪 Test Playground",
        "📋 My Agents",
        "🔔 Notifications",
        "👁️ Observability"
    ])

    # ═══════════════════════════════════════════
    #  TAB 1: BUILDER
    # ═══════════════════════════════════════════
    with tab1:
        st.markdown("### Create New Agent")

        c1, c2 = st.columns([2, 1])

        with c1:
            name = st.text_input("Agent Name", placeholder="e.g. Daily Cost Watchdog")
            role = st.selectbox("Role / Persona", [
                "Cost Analyst", "Security Guard", "Performance Tuner",
                "Data Steward", "Warehouse Manager"
            ])

            goal = st.text_area(
                "Goal & Instructions",
                placeholder="Check for warehouses running > 2 hours and alert me if they are idle...",
                height=150
            )

            st.markdown("#### Capabilities")
            caps = st.multiselect(
                "Allowed Actions",
                ALL_CAPABILITIES,
                default=["Read Metadata", "Check Credit Usage", "Get Cost by Warehouse", "Send Notification"]
            )

            st.markdown("#### Knowledge Base (RAG)")
            kb = st.multiselect(
                "Connect Cortex Knowledge Services",
                ["Internal Documentation", "Jira Tickets", "Confluence Pages", "Slack History"],
                help="Allows the agent to search these sources for context."
            )

            # Integration Configuration
            from utils.config_manager import ConfigManager
            config_mgr = ConfigManager(client)

            jira_token = config_mgr.get_config('JIRA_API_TOKEN') or ""
            slack_token = config_mgr.get_config('SLACK_BOT_TOKEN') or ""

            with st.expander("⚙️ Configure Integrations"):
                st.caption("Manage connection secrets and Cortex Services")
                new_jira = st.text_input("Jira API Token", value=jira_token, type="password",
                                         help="Enter your Jira Personal Access Token")
                new_slack = st.text_input("Slack Bot Token", value=slack_token, type="password",
                                          help="Enter your Slack Bot User OAuth Token (xoxb-...)")

                if st.button("💾 Save Credentials"):
                    s1 = config_mgr.set_config('JIRA_API_TOKEN', new_jira, 'INTEGRATION', 'Jira Access Token')
                    s2 = config_mgr.set_config('SLACK_BOT_TOKEN', new_slack, 'INTEGRATION', 'Slack Bot Token')
                    if s1 and s2:
                        st.toast("Integration credentials saved successfully!", icon="🔐")
                        st.cache_data.clear()

            if jira_token:
                st.success("✅ Jira Connected")
            if slack_token:
                st.success("✅ Slack Connected")

        with c2:
            st.markdown("#### Agent Logic")
            reasoning = st.radio("Reasoning Engine", [
                "Multi-Step Planner (Recommended)",
                "Single-Step (Fast)"
            ])

            st.markdown("#### Schedule")
            schedule_type = st.radio("Run Trigger", ["On Demand", "Scheduled"])

            cron = None
            if schedule_type == "Scheduled":
                cron = st.selectbox("Frequency", ["Daily (8 AM)", "Hourly", "Weekly (Mon)", "Custom Cron"])
                if cron == "Custom Cron":
                    cron = st.text_input("Cron Expression", "0 8 * * *")

            st.info("Agents run as Snowflake Tasks within the Native App context.")

            with st.expander("🛡️ Guardrails (Governance)", expanded=True):
                gr_credits = st.number_input("Max Daily Credits", min_value=1.0, value=st.session_state['gr_credits'],
                                             step=1.0, help="Stop agent if it burns > X credits.")
                gr_actions = st.multiselect("Forbidden Actions",
                                            ["DROP", "DELETE", "ALTER", "UPDATE", "INSERT"],
                                            default=st.session_state['gr_actions'],
                                            help="Keywords the agent is NOT allowed to execute.")
                gr_approval = st.checkbox("Require Human Approval for Writes",
                                          value=st.session_state['gr_approval'])

                # Persist to session state
                st.session_state['gr_credits'] = gr_credits
                st.session_state['gr_actions'] = gr_actions
                st.session_state['gr_approval'] = gr_approval

        if st.button("🚀 Deploy Agent", type="primary"):
            if not name or not goal:
                st.warning("Agent Name and Goal are required.")
            else:
                agent_id = str(uuid.uuid4())
                caps_str = ",".join(caps)
                kb_str = ",".join(kb)
                cron_val = cron if cron else "NULL"

                guardrails_json = json.dumps({
                    "max_daily_credits": gr_credits,
                    "forbidden_actions": gr_actions,
                    "require_approval": gr_approval
                })

                safe_name = name.replace("'", "''")
                safe_goal = goal.replace("'", "''")

                sql = f"""
                INSERT INTO APP_CONTEXT.AGENTS
                (AGENT_ID, AGENT_NAME, ROLE, GOAL, CAPABILITIES, KNOWLEDGE_SOURCES, REASONING_ENGINE, SCHEDULE_TYPE, CRON_EXPRESSION, GUARDRAILS)
                VALUES
                ('{agent_id}', '{safe_name}', '{role}', '{safe_goal}', '{caps_str}', '{kb_str}', '{reasoning}', '{schedule_type}', '{cron_val}', PARSE_JSON('{guardrails_json}'))
                """
                try:
                    client.execute_query(sql)
                    st.toast("Agent deployed successfully! 🚀", icon="🚀")
                except Exception as e:
                    st.error(f"Deployment failed: {e}")

    # ═══════════════════════════════════════════
    #  TAB 2: TEST PLAYGROUND
    # ═══════════════════════════════════════════
    with tab2:
        st.markdown("### 🧪 Agent Test Playground")
        st.caption("Interactively test your agent's reasoning and tool usage before deploying.")

        col_test_1, col_test_2 = st.columns([1, 1])

        with col_test_1:
            test_role = st.selectbox("Test Persona", [
                "Cost Analyst", "Security Guard", "Performance Tuner",
                "Data Steward", "Warehouse Manager"
            ], key="test_role")

            test_caps = st.multiselect(
                "Test Capabilities",
                ALL_CAPABILITIES,
                default=["Check Credit Usage", "Get Cost by Warehouse", "Check Warehouse Status", "Send Notification"],
                key="test_caps"
            )

            st.markdown("#### Quick Prompts")
            quick_prompts = {
                "📊 Credit Analysis": "Analyze credit usage for the last 7 days. Tell me if it's high, which warehouse uses the most, and calculate the average daily rate.",
                "🏭 Warehouse Check": "Check the status of all warehouses. Are any running that shouldn't be? Suspend any idle warehouses.",
                "⚡ Query Performance": "Find the top 5 slowest queries from the last 7 days and tell me who ran them.",
                "👥 User Activity": "Who are the most active Snowflake users this week? How many queries did each run?"
            }

            selected_prompt = st.selectbox("Quick Prompt Templates", ["Custom..."] + list(quick_prompts.keys()))

            if selected_prompt != "Custom...":
                default_goal = quick_prompts[selected_prompt]
            else:
                default_goal = "Analyze credit usage for the last 7 days and tell me if it's high."

            test_goal = st.text_area("Test Goal", default_goal, height=120, key="test_goal_input")

            if st.button("▶️ Run Test Agent", type="primary"):
                with st.spinner("Agent is reasoning..."):
                    temp_id = f"test_{uuid.uuid4().hex[:8]}"
                    run_id = runner.run_agent(
                        temp_id,
                        "Test Agent",
                        test_role,
                        test_goal,
                        test_caps,
                        guardrails={
                            'max_daily_credits': st.session_state.get('gr_credits', 10.0),
                            'forbidden_actions': st.session_state.get('gr_actions', ['DROP', 'DELETE', 'ALTER']),
                            'require_approval': st.session_state.get('gr_approval', True)
                        }
                    )
                    st.session_state['last_run_id'] = run_id
                    st.success("✅ Test complete! See reasoning trace →")

        with col_test_2:
            st.markdown("#### Live Reasoning Trace")
            if 'last_run_id' in st.session_state:
                run_id = st.session_state['last_run_id']
                logs = logger.get_run_logs(run_id)

                if not logs.empty:
                    for _, log in logs.iterrows():
                        step_type = log.get('TYPE', '')
                        content = log.get('CONTENT', '')

                        icon_map = {
                            "START": "🤔",
                            "THOUGHT_PROCESS": "🧠",
                            "ACTION": "⚡",
                            "OBSERVATION": "👀",
                            "FINAL_ANSWER": "✅",
                            "ERROR": "❌"
                        }
                        icon = icon_map.get(step_type, "📝")

                        with st.chat_message("assistant", avatar=icon):
                            st.markdown(f"**{step_type}**")
                            if step_type == "FINAL_ANSWER":
                                st.success(content)
                            elif step_type == "ERROR":
                                st.error(content)
                            elif step_type == "OBSERVATION":
                                st.code(content, language="text")
                            else:
                                st.markdown(content[:1000])
                else:
                    st.info("No logs found for this run.")
            else:
                st.info("Run a test to see the agent's thought process here.")

    # ═══════════════════════════════════════════
    #  TAB 3: MY AGENTS
    # ═══════════════════════════════════════════
    with tab3:
        st.markdown("### Deployed Agents")
        try:
            agents_df = client.execute_query("SELECT * FROM APP_CONTEXT.AGENTS ORDER BY CREATED_AT DESC")
            if not agents_df.empty:
                for _, row in agents_df.iterrows():
                    with st.expander(f"🤖 {row['AGENT_NAME']} ({row['ROLE']})", expanded=False):
                        st.write(f"**Goal**: {row['GOAL']}")
                        st.markdown(f"**Capabilities**: `{row.get('CAPABILITIES', '')}`")
                        st.markdown(f"**Schedule**: {row['SCHEDULE_TYPE']} — {row.get('CRON_EXPRESSION', 'N/A')}")

                        if row.get('GUARDRAILS'):
                            try:
                                gr = json.loads(row['GUARDRAILS']) if isinstance(row['GUARDRAILS'], str) else row['GUARDRAILS']
                                st.markdown(f"**🛡️ Guardrails**: Max {gr.get('max_daily_credits', 10)} credits. Banned: `{', '.join(gr.get('forbidden_actions', []))}`")
                            except:
                                pass

                        col_run, col_del = st.columns([1, 1])
                        with col_run:
                            if st.button("▶️ Run Now", key=f"run_{row['AGENT_ID']}"):
                                with st.spinner("Running agent..."):
                                    caps_list = row.get('CAPABILITIES', '').split(',')
                                    gr_data = None
                                    if row.get('GUARDRAILS'):
                                        try:
                                            gr_data = json.loads(row['GUARDRAILS']) if isinstance(row['GUARDRAILS'], str) else row['GUARDRAILS']
                                        except:
                                            pass
                                    rid = runner.run_agent(
                                        row['AGENT_ID'],
                                        row['AGENT_NAME'],
                                        row['ROLE'],
                                        row['GOAL'],
                                        caps_list,
                                        guardrails=gr_data
                                    )
                                    st.toast(f"Agent completed! Run ID: {rid[:8]}...", icon="✅")
                        with col_del:
                            if st.button("🗑️ Delete", key=f"term_{row['AGENT_ID']}"):
                                safe_id = row['AGENT_ID'].replace("'", "''")
                                client.execute_query(f"DELETE FROM APP_CONTEXT.AGENTS WHERE AGENT_ID = '{safe_id}'")
                                st.rerun()
            else:
                st.info("No agents deployed yet. Use the Builder tab to create one.")
        except Exception as e:
            st.error(f"Error fetching agents: {e}")

    # ═══════════════════════════════════════════
    #  TAB 4: NOTIFICATIONS
    # ═══════════════════════════════════════════
    with tab4:
        st.markdown("### 🔔 Agent Notifications")
        st.caption("Alerts and notifications generated by your AI agents.")

        notifications_df = logger.get_notifications(limit=50)

        if not notifications_df.empty:
            # Summary metrics
            m1, m2, m3, m4 = st.columns(4)
            unread = notifications_df[~notifications_df.get('IS_READ', pd.Series([False]*len(notifications_df)))].shape[0] if 'IS_READ' in notifications_df.columns else len(notifications_df)

            with m1:
                st.metric("Total Alerts", len(notifications_df))
            with m2:
                st.metric("Unread", unread)
            with m3:
                warnings = len(notifications_df[notifications_df.get('SEVERITY', pd.Series()) == 'WARNING']) if 'SEVERITY' in notifications_df.columns else 0
                st.metric("⚠️ Warnings", warnings)
            with m4:
                criticals = len(notifications_df[notifications_df.get('SEVERITY', pd.Series()) == 'CRITICAL']) if 'SEVERITY' in notifications_df.columns else 0
                st.metric("🔴 Critical", criticals)

            st.markdown("---")

            for _, notif in notifications_df.iterrows():
                severity = notif.get('SEVERITY', 'INFO')
                color_map = {"CRITICAL": "#FF4B4B", "WARNING": "#FFB020", "INFO": "#29B5E8"}
                color = color_map.get(severity, "#29B5E8")
                is_read = notif.get('IS_READ', False)
                opacity = "0.6" if is_read else "1.0"

                st.markdown(f"""
                <div style="border-left: 4px solid {color}; padding: 12px 16px; margin-bottom: 8px;
                            background: {color}11; border-radius: 4px; opacity: {opacity};">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <strong style="color: {color};">[{severity}] {notif.get('TITLE', 'Alert')}</strong>
                        <span style="font-size: 0.8em; color: #888;">{notif.get('CREATED_AT', '')}</span>
                    </div>
                    <p style="margin: 4px 0 0 0; color: #ccc;">{notif.get('MESSAGE', '')}</p>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No notifications yet. Agents can generate alerts using the 'Send Notification' capability.")

    # ═══════════════════════════════════════════
    #  TAB 5: OBSERVABILITY
    # ═══════════════════════════════════════════
    with tab5:
        st.markdown("### 👁️ Agent Observability")
        st.caption("Deep dive into agent execution history and reasoning.")

        try:
            log_query = """
            SELECT
                RUN_ID,
                MAX(TIMESTAMP) as LAST_ACTIVE,
                MAX(AGENT_ID) as AGENT_ID,
                COUNT(*) as STEPS
            FROM APP_CONTEXT.AGENT_LOGS
            GROUP BY RUN_ID
            ORDER BY LAST_ACTIVE DESC
            LIMIT 50
            """
            runs_df = client.execute_query(log_query)

            if not runs_df.empty:
                # Metrics row
                m1, m2, m3 = st.columns(3)
                with m1:
                    st.metric("Total Runs", len(runs_df))
                with m2:
                    avg_steps = runs_df['STEPS'].mean()
                    st.metric("Avg Steps/Run", f"{avg_steps:.1f}")
                with m3:
                    st.metric("Latest Run", str(runs_df.iloc[0].get('LAST_ACTIVE', 'N/A'))[:19])

                st.markdown("---")

                selected_run = st.selectbox(
                    "Select Run",
                    runs_df['RUN_ID'].tolist(),
                    format_func=lambda x: f"{x[:12]}... ({runs_df[runs_df['RUN_ID']==x].iloc[0].get('STEPS', '?')} steps)"
                )

                if selected_run:
                    st.markdown("#### Execution Trace")
                    logs = logger.get_run_logs(selected_run)

                    for _, log in logs.iterrows():
                        step_type = log.get('TYPE', '')
                        icon_map = {"START": "🟢", "THOUGHT_PROCESS": "🧠", "ACTION": "⚡",
                                    "OBSERVATION": "👀", "FINAL_ANSWER": "✅", "ERROR": "❌"}
                        icon = icon_map.get(step_type, "📝")

                        with st.expander(f"{icon} Step {log.get('STEP_NUMBER', '?')}: {step_type}", expanded=(step_type in ["FINAL_ANSWER", "ERROR"])):
                            content = log.get('CONTENT', '')
                            if step_type == "OBSERVATION":
                                st.code(content, language="text")
                            elif step_type == "FINAL_ANSWER":
                                st.success(content)
                            elif step_type == "ERROR":
                                st.error(content)
                            else:
                                st.markdown(content[:2000])
            else:
                st.info("No agent runs recorded yet. Test an agent in the Playground to generate logs.")

        except Exception as e:
            st.error(f"Failed to load logs: {e}")


if __name__ == "__main__":
    main()
