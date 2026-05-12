"""
Settings & Context Configuration Page
User-defined context, preferences, and platform configuration
"""

import streamlit as st
import pandas as pd
import time
from datetime import datetime
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.snowflake_client import get_snowflake_client
from utils.formatters import dataframe_to_excel_bytes
from utils.styles import apply_global_styles, COLORS

st.set_page_config(
    page_title="Settings | Snowflake Ops",
    page_icon="⚙️",
    layout="wide"
)

# --- SECURITY: ADMIN ONLY ---
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.auth import verify_page_access
verify_page_access('ADMIN')
# ----------------------------

# Apply unified Snowflake design system
apply_global_styles()
from utils.styles import render_sidebar
render_sidebar()

st.markdown("""
<style>
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        height: 48px;
        white-space: pre-wrap;
        background-color: #0f1116;
        border-radius: 4px 4px 0px 0px;
        gap: 1px;
        padding-top: 10px;
        padding-bottom: 10px;
    }
    .stTabs [aria-selected="true"] {
        background-color: #1a1c24;
        border-bottom: 2px solid #29B5E8;
    }
    .setting-card {
        background-color: #1a1c24;
        padding: 20px;
        border-radius: 8px;
        border: 1px solid #2d3039;
        margin-bottom: 16px;
    }
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=60)
def get_warehouses(_client):
    """Get list of warehouses"""
    # Use SHOW WAREHOUSES instead of table function which doesn't exist
    try:
        df = _client.execute_query("SHOW WAREHOUSES")
        if df.empty:
            return pd.DataFrame()
            
        columns = [c.upper() for c in df.columns]
        df.columns = columns
        
        result_df = pd.DataFrame()
        result_df['WAREHOUSE_NAME'] = df['NAME']
        result_df['SIZE'] = df['SIZE']
        result_df['STATE'] = df['STATE']
        
        return result_df.sort_values('WAREHOUSE_NAME')
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def get_tables(_client):
    """Get list of tables"""
    query = """
    SELECT 
        TABLE_CATALOG as database_name,
        TABLE_SCHEMA as schema_name,
        TABLE_NAME,
        ROW_COUNT,
        BYTES / POWER(1024, 3) as size_gb,
        LAST_ALTERED
    FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_TYPE = 'BASE TABLE'
        AND TABLE_SCHEMA NOT IN ('INFORMATION_SCHEMA')
    ORDER BY BYTES DESC NULLS LAST
    LIMIT 200
    """
    return _client.execute_query(query)


@st.cache_data(ttl=300)
def get_users(_client):
    """Get list of users"""
    query = """
    SELECT 
        NAME as user_name,
        LOGIN_NAME,
        DISPLAY_NAME,
        DEFAULT_WAREHOUSE,
        DEFAULT_ROLE
    FROM SNOWFLAKE.ACCOUNT_USAGE.USERS
    WHERE DELETED_ON IS NULL
    ORDER BY NAME
    """
    return _client.execute_query(query)


def get_saved_warehouse_context(_client):
    """Get saved warehouse context from database"""
    try:
        path = _client.get_schema_path("APP_CONTEXT")
        query = f"SELECT * FROM {path}.WAREHOUSE_CONTEXT ORDER BY WAREHOUSE_NAME"
        return _client.execute_query(query)
    except Exception as e:
        # st.error(f"Debug Error: {e}") # Uncomment to debug
        print(f"Error fetching warehouse context: {e}")
        return pd.DataFrame()


def get_saved_table_context(_client):
    """Get saved table context from database"""
    try:
        path = _client.get_schema_path("APP_CONTEXT")
        query = f"SELECT * FROM {path}.TABLE_CONTEXT ORDER BY DATABASE_NAME, SCHEMA_NAME, TABLE_NAME"
        return _client.execute_query(query)
    except Exception:
        return pd.DataFrame()


def get_saved_team_attribution(_client):
    """Get saved team attribution from database"""
    try:
        path = _client.get_schema_path("APP_CONTEXT")
        query = f"SELECT * FROM {path}.TEAM_ATTRIBUTION ORDER BY USER_NAME"
        return _client.execute_query(query)
    except Exception:
        return pd.DataFrame()


def get_saved_budget_alerts(_client):
    """Get saved budget alerts from database"""
    try:
        path = _client.get_schema_path("APP_CONTEXT")
        query = f"SELECT * FROM {path}.BUDGET_ALERTS ORDER BY ALERT_NAME"
        return _client.execute_query(query)
    except Exception:
        return pd.DataFrame()


def main():
    st.title("⚙️ Settings & Context")
    st.markdown("*Configure user-defined context to enhance optimization recommendations*")
    
    client = get_snowflake_client()
    
    if not client.session:
        st.error("⚠️ Could not connect to Snowflake")
        return
    
    # Info box
    st.info("""
    **Why Context Matters**
    
    Snowflake optimizes queries technically. This platform optimizes them *contextually*.
    
    By providing information about your warehouse purposes, data freshness requirements, 
    and team assignments, you enable more accurate recommendations that Snowflake alone cannot provide.
    """)
    
    # Tabs
    # Tabs
    # Tabs
    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "🏭 Warehouse Context",
        "📊 Table Context", 
        "👥 Team Attribution",
        "💰 Budget Alerts",
        "🔧 Platform Settings",
        "🤖 Autopilot",
        "🧠 Cortex AI"
    ])
    
    with tab1:
        render_warehouse_context(client)
    
    with tab2:
        render_table_context(client)
    
    with tab3:
        render_team_attribution(client)
    
    with tab4:
        render_budget_alerts(client)
    
    with tab5:
        render_platform_settings(client)

    with tab6:
        render_autopilot_settings(client)

    with tab7:
        render_cortex_settings(client)


def render_warehouse_context(client):
    """Render warehouse context configuration"""
    st.markdown("### Warehouse Purpose Configuration")
    st.caption("*Define the purpose and preferences for each warehouse*")
    
    warehouses = get_warehouses(client)
    saved_context = get_saved_warehouse_context(client)
    
    if warehouses.empty:
        st.info("No warehouses found.")
        return
    
    if saved_context.empty:
        st.warning("⚠️ **Warehouse context table not found or empty.**")
        st.info("Please go to the **Platform Settings** tab and click **Initialize Database** to create the required tables.")
    
    # Helper function defined locally to ensure availability
    def save_warehouse_context_local(client, wh_name, purpose, profile, owner):
        try:
            path = client.get_schema_path("APP_CONTEXT")
            # Ensure table exists (idempotent check)
            client.execute_query(f"""
                CREATE TABLE IF NOT EXISTS {path}.WAREHOUSE_CONTEXT (
                    WAREHOUSE_NAME VARCHAR PRIMARY KEY,
                    PURPOSE VARCHAR,
                    SIZE VARCHAR,
                    COST_PROFILE VARCHAR,
                    CONCURRENCY_TOLERANCE VARCHAR,
                    OWNER_TEAM VARCHAR,
                    NOTES VARCHAR,
                    UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                )
            """, log=False)
            
            query = f"""
            MERGE INTO {path}.WAREHOUSE_CONTEXT AS target
            USING (SELECT '{wh_name}' AS WAREHOUSE_NAME, '{purpose}' AS PURPOSE, '{profile}' AS COST_PROFILE, '{owner}' AS OWNER_TEAM) AS source
            ON target.WAREHOUSE_NAME = source.WAREHOUSE_NAME
            WHEN MATCHED THEN UPDATE SET target.PURPOSE = source.PURPOSE, target.COST_PROFILE = source.COST_PROFILE, target.OWNER_TEAM = source.OWNER_TEAM, target.UPDATED_AT = CURRENT_TIMESTAMP()
            WHEN NOT MATCHED THEN INSERT (WAREHOUSE_NAME, PURPOSE, COST_PROFILE, OWNER_TEAM, UPDATED_AT) VALUES (source.WAREHOUSE_NAME, source.PURPOSE, source.COST_PROFILE, source.OWNER_TEAM, CURRENT_TIMESTAMP())
            """
            client.execute_query(query)
        except Exception as e:
            st.error(f"Error saving context: {e}")

    # Dedup warehouses to prevent key collisions
    if 'WAREHOUSE_NAME' in warehouses.columns:
        warehouses = warehouses.drop_duplicates(subset=['WAREHOUSE_NAME'])

    # Display current warehouses
    # Display current warehouses
    if not warehouses.empty:
         # Add global auto-populate button
         st.markdown("#### 🤖 AI Context")
         col_auto_1, col_auto_2 = st.columns([3, 1])
         with col_auto_1:
             st.info("Auto-fill warehouse context based on naming conventions (e.g., 'ETL_WH' -> 'ETL').")
         with col_auto_2:
             if st.button("✨ Auto-Populate", use_container_width=True, key="btn_auto_pop_context_v2"):
                 with st.spinner("Analyzing warehouse names..."):
                     count = 0
                     for _, wh in warehouses.iterrows():
                         name = wh['WAREHOUSE_NAME']
                         # Logic to guess purpose
                         guessed_purpose = 'GENERAL'
                         guessed_profile = 'BALANCED'
                         
                         if 'ETL' in name.upper() or 'LOAD' in name.upper():
                             guessed_purpose = 'ETL'
                             guessed_profile = 'PERFORMANCE'
                         elif 'ANALYTIC' in name.upper() or 'BI' in name.upper():
                             guessed_purpose = 'ANALYTICS'
                         elif 'REPORT' in name.upper():
                             guessed_purpose = 'REPORTING'
                             guessed_profile = 'BUDGET'
                         elif 'ADHOC' in name.upper():
                             guessed_purpose = 'ADHOC'
                         
                         save_warehouse_context_local(client, name, guessed_purpose, guessed_profile, '')
                         count += 1
                     st.success(f"Updated context for {count} warehouses!")
                     time.sleep(1)
                     st.rerun()

    for i, (_, wh) in enumerate(warehouses.iterrows()):
        wh_name = wh['WAREHOUSE_NAME']
        
        # Get saved context for this warehouse
        saved = saved_context[saved_context['WAREHOUSE_NAME'] == wh_name] if not saved_context.empty else pd.DataFrame()
        
        # Robust unique key using hash to ensure no collisions across renders
        import hashlib
        uid = hashlib.md5(f"{wh_name}_{i}".encode()).hexdigest()[:8]
        
        with st.expander(f"🏭 {wh_name} ({wh['SIZE']})", expanded=False):
            c1, c2 = st.columns(2)
            
            with c1:
                purpose = st.selectbox(
                    "Purpose",
                    options=['GENERAL', 'ETL', 'ANALYTICS', 'ADHOC', 'REPORTING'],
                    index=['GENERAL', 'ETL', 'ANALYTICS', 'ADHOC', 'REPORTING'].index(
                        saved['PURPOSE'].iloc[0] if not saved.empty and 'PURPOSE' in saved.columns and saved['PURPOSE'].iloc[0] in ['GENERAL', 'ETL', 'ANALYTICS', 'ADHOC', 'REPORTING'] else 'GENERAL'
                    ),
                    key=f"ctx_purpose_{uid}"
                )
                
                cost_profile = st.selectbox(
                    "Cost Profile",
                    options=['BUDGET', 'BALANCED', 'PERFORMANCE'],
                    index=['BUDGET', 'BALANCED', 'PERFORMANCE'].index(
                        saved['COST_PROFILE'].iloc[0] if not saved.empty and 'COST_PROFILE' in saved.columns and saved['COST_PROFILE'].iloc[0] in ['BUDGET', 'BALANCED', 'PERFORMANCE'] else 'BALANCED'
                    ),
                    key=f"ctx_profile_{uid}"
                )
            
            with c2:
                owner = st.text_input(
                    "Owner Team/Person",
                    value=saved['OWNER_TEAM'].iloc[0] if not saved.empty and 'OWNER_TEAM' in saved.columns else '',
                    key=f"ctx_owner_{uid}"
                )
                
                concurrency = st.selectbox(
                    "Concurrency Tolerance",
                    options=['LOW', 'MEDIUM', 'HIGH'],
                    index=['LOW', 'MEDIUM', 'HIGH'].index(
                        saved['CONCURRENCY_TOLERANCE'].iloc[0] if not saved.empty and 'CONCURRENCY_TOLERANCE' in saved.columns else 'MEDIUM'
                    ),
                    key=f"ctx_conc_{uid}"
                )

                # Save Button per warehouse
                if st.button("💾 Save", key=f"btn_save_{uid}"):
                    save_warehouse_context_local(client, wh_name, purpose, cost_profile, owner)
                    st.toast(f"Saved context for {wh_name}", icon="✅")
                    time.sleep(0.5)
                    st.rerun()
                
                owner_team = st.text_input(
                    "Owner Team",
                    value=saved['OWNER_TEAM'].iloc[0] if not saved.empty and 'OWNER_TEAM' in saved.columns else '',
                    key=f"team_{wh_name}"
                )
            
            notes = st.text_area(
                "Notes",
                value=saved['NOTES'].iloc[0] if not saved.empty and 'NOTES' in saved.columns and pd.notna(saved['NOTES'].iloc[0]) else '',
                key=f"notes_{wh_name}",
                height=80
            )
            
            if st.button("💾 Save", key=f"save_{wh_name}"):
                try:
                    # Save to database
                    path = client.get_schema_path("APP_CONTEXT")
                    merge_query = f"""
                    MERGE INTO {path}.WAREHOUSE_CONTEXT t
                    USING (SELECT '{wh_name}' as WAREHOUSE_NAME) s
                    ON t.WAREHOUSE_NAME = s.WAREHOUSE_NAME
                    WHEN MATCHED THEN UPDATE SET
                        PURPOSE = '{purpose}',
                        SIZE = '{wh['SIZE']}',
                        COST_PROFILE = '{cost_profile}',
                        CONCURRENCY_TOLERANCE = '{concurrency}',
                        OWNER_TEAM = '{owner_team}',
                        NOTES = '{notes.replace("'", "''")}',
                        UPDATED_AT = CURRENT_TIMESTAMP()
                    WHEN NOT MATCHED THEN INSERT (
                        WAREHOUSE_NAME, PURPOSE, SIZE, COST_PROFILE, 
                        CONCURRENCY_TOLERANCE, OWNER_TEAM, NOTES
                    ) VALUES (
                        '{wh_name}', '{purpose}', '{wh['SIZE']}', '{cost_profile}',
                        '{concurrency}', '{owner_team}', '{notes.replace("'", "''")}'
                    )
                    """
                    client.execute_write(merge_query)
                    st.success(f"✅ Saved context for {wh_name}")
                    st.cache_data.clear()
                except Exception as e:
                    st.error(f"Error saving: {e}")


def render_table_context(client):
    """Render table context configuration"""
    st.markdown("### Table Freshness & Priority")
    st.caption("*Define freshness requirements and mark critical tables*")
    
    tables = get_tables(client)
    saved_context = get_saved_table_context(client)
    
    if tables.empty:
        st.info("No tables found.")
        return
    
    # Filter controls
    col1, col2 = st.columns([1, 2])
    with col1:
        search = st.text_input("🔍 Search tables", "")
    
    # Filter tables
    if search:
        tables = tables[
            tables['TABLE_NAME'].str.contains(search, case=False, na=False) |
            tables['DATABASE_NAME'].str.contains(search, case=False, na=False)
        ]
    
    if tables.empty:
        st.info("No tables match your search.")
        return
    
    # Bulk configuration
    st.markdown("#### Quick Configuration")
    
    selected_tables = st.multiselect(
        "Select tables to configure",
        options=tables['TABLE_NAME'].tolist(),
        default=[]
    )
    
    if selected_tables:
        col1, col2, col3 = st.columns(3)
        
        with col1:
            bulk_freshness = st.selectbox(
                "Freshness Requirement",
                options=['REAL_TIME', 'HOURLY', 'DAILY', 'WEEKLY'],
                index=2,
                key="bulk_freshness"
            )
        
        with col2:
            bulk_access = st.selectbox(
                "Access Frequency",
                options=['HOT', 'WARM', 'COLD', 'UNKNOWN'],
                index=3,
                key="bulk_access"
            )
        
        with col3:
            bulk_critical = st.checkbox("Mark as Critical", key="bulk_critical")
        
        if st.button("💾 Apply to Selected Tables"):
            st.info(f"Would save settings for {len(selected_tables)} tables.")
            st.success("✅ Settings applied (demo mode)")
    
    st.divider()
    
    # Table list
    st.markdown("#### All Tables")
    
    display_df = tables[['DATABASE_NAME', 'SCHEMA_NAME', 'TABLE_NAME', 'ROW_COUNT', 'SIZE_GB', 'LAST_ALTERED']].copy()
    display_df.columns = ['Database', 'Schema', 'Table', 'Rows', 'Size (GB)', 'Last Modified']
    
    st.dataframe(
        display_df.head(50),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Rows": st.column_config.NumberColumn(format="%d"),
            "Size (GB)": st.column_config.NumberColumn(format="%.3f"),
            "Last Modified": st.column_config.DatetimeColumn(format="MMM DD, HH:mm")
        }
    )


def render_team_attribution(client):
    """Render team attribution configuration"""
    st.markdown("### Team Cost Attribution")
    st.caption("*Map users to teams for cost allocation and reporting*")
    
    users = get_users(client)
    saved_attribution = get_saved_team_attribution(client)
    
    if users.empty:
        st.info("No users found.")
        return
    
    # Add new mapping form
    st.markdown("#### Add/Update User Mapping")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        selected_user = st.selectbox(
            "User",
            options=users['USER_NAME'].tolist(),
            key="attr_user"
        )
    
    with col2:
        team = st.text_input("Team Name", key="attr_team")
        department = st.text_input("Department", key="attr_dept")
    
    with col3:
        cost_center = st.text_input("Cost Center", key="attr_cost")
        budget = st.number_input("Budget Limit (credits)", min_value=0.0, value=0.0, key="attr_budget")
    
    if st.button("💾 Save Attribution"):
        if team:
            try:
                path = client.get_schema_path("APP_CONTEXT")
                merge_query = f"""
                MERGE INTO {path}.TEAM_ATTRIBUTION t
                USING (SELECT '{selected_user}' as USER_NAME) s
                ON t.USER_NAME = s.USER_NAME
                WHEN MATCHED THEN UPDATE SET
                    TEAM_NAME = '{team}',
                    DEPARTMENT = '{department}',
                    COST_CENTER = '{cost_center}',
                    BUDGET_LIMIT_CREDITS = {budget if budget > 0 else 'NULL'},
                    UPDATED_AT = CURRENT_TIMESTAMP()
                WHEN NOT MATCHED THEN INSERT (
                    USER_NAME, TEAM_NAME, DEPARTMENT, COST_CENTER, BUDGET_LIMIT_CREDITS
                ) VALUES (
                    '{selected_user}', '{team}', '{department}', '{cost_center}', 
                    {budget if budget > 0 else 'NULL'}
                )
                """
                client.execute_write(merge_query)
                st.success(f"✅ Saved attribution for {selected_user}")
                st.cache_data.clear()
            except Exception as e:
                st.error(f"Error saving: {e}")
        else:
            st.warning("Please enter a team name")
    
    st.divider()
    
    # Current mappings
    st.markdown("#### Current Mappings")
    
    if not saved_attribution.empty:
        st.dataframe(saved_attribution, use_container_width=True, hide_index=True)
    else:
        st.info("No team attributions configured yet.")
    
    # All users
    st.markdown("#### All Users")
    st.dataframe(users, use_container_width=True, hide_index=True)


def render_budget_alerts(client):
    """Render budget alert configuration"""
    st.markdown("### Budget Alerts & Notifications")
    st.caption("*Set up alerts for credit consumption capabilities*")
    
    # --- Notification Setup Wizard ---
    from utils.notifications import NotificationService
    notifier = NotificationService(client)
    
    with st.expander("🔔 Configure External Notifications (Admin Setup)", expanded=False):
        st.markdown("""
        To receive emails, you must configure a **Notification Integration** in Snowflake.
        Run the SQL below in Snowsight (as ACCOUNTADMIN).
        """)
        
        setup_emails = st.text_input("Allowed Recipient Emails (comma separated)", "alerts@company.com")
        if setup_emails:
            recipients_list = [e.strip() for e in setup_emails.split(',')]
            sql_code = notifier.generate_setup_sql(recipients_list)
            st.code(sql_code, language="sql")
            st.caption("Copy and run this in a Snowflake Worksheet.")
    
    saved_alerts = get_saved_budget_alerts(client)
    
    # Add new alert
    st.divider()
    st.markdown("#### Create New Alert")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        alert_name = st.text_input("Alert Name", key="alert_name")
        alert_type = st.selectbox(
            "Alert Type",
            options=['ACCOUNT', 'WAREHOUSE', 'USER', 'TEAM'],
            key="alert_type"
        )
    
    with col2:
        target = st.text_input(
            "Target (leave empty for account-wide)", 
            key="alert_target",
            help="Warehouse name, user name, or team name"
        )
        threshold_credits = st.number_input(
            "Credit Threshold (daily)", 
            min_value=0.0, 
            value=10.0,
            key="alert_credits"
        )
    
    with col3:
        threshold_pct = st.slider(
            "Warning at % of threshold",
            min_value=50,
            max_value=100,
            value=80,
            key="alert_pct"
        )
        channel = st.selectbox(
            "Notification Channel",
            options=['DASHBOARD', 'EMAIL', 'SLACK (Webhook)', 'TEAMS (Webhook)'],
            key="alert_channel"
        )
        
    # Recipient Input (Conditional)
    recipients = ""
    if "EMAIL" in channel:
        recipients = st.text_input("Recipient Emails (comma separated)", key="alert_recipients", placeholder="admin@company.com")
    elif "WEBHOOK" in channel:
        recipients = st.text_input("Webhook URL", key="alert_webhook", placeholder="https://hooks.slack.com/...")
    
    if st.button("➕ Create Alert"):
        if alert_name:
            try:
                # Ensure Schema Healed (Add RECIPIENTS col if missing)
                from utils.init_db import init_database
                init_database(client)
                
                path = client.get_schema_path("APP_CONTEXT")
                insert_query = f"""
                INSERT INTO {path}.BUDGET_ALERTS (
                    ALERT_NAME, ALERT_TYPE, TARGET_NAME, THRESHOLD_CREDITS, 
                    THRESHOLD_PERCENTAGE, NOTIFICATION_CHANNEL, RECIPIENTS, IS_ACTIVE
                ) VALUES (
                    '{alert_name}', '{alert_type}', 
                    {f"'{target}'" if target else 'NULL'},
                    {threshold_credits}, {threshold_pct}, '{channel}', 
                    {f"'{recipients}'" if recipients else 'NULL'}, TRUE
                )
                """
                client.execute_write(insert_query)
                st.success(f"✅ Created alert: {alert_name}")
                st.cache_data.clear()
            except Exception as e:
                st.error(f"Error creating alert: {e}")
        else:
            st.warning("Please enter an alert name")
    
    st.divider()
    
    # Current alerts
    st.markdown("#### Active Alerts")
    
    if not saved_alerts.empty:
        for _, alert in saved_alerts.iterrows():
            col1, col2, col3 = st.columns([3, 2, 0.5])
            
            with col1:
                status = "🟢" if alert['IS_ACTIVE'] else "🔴"
                target_label = alert['TARGET_NAME'] if pd.notna(alert['TARGET_NAME']) else "Account-wide"
                st.markdown(f"""
                **{status} {alert['ALERT_NAME']}**  
                Type: `{alert['ALERT_TYPE']}` | Target: `{target_label}`  
                Threshold: **{alert['THRESHOLD_CREDITS']}** credits | Warn at: **{alert['THRESHOLD_PERCENTAGE']}%**
                """)
            
            with col2:
                recip_display = ""
                if 'RECIPIENTS' in alert and pd.notna(alert['RECIPIENTS']):
                    recip_display = f"| To: {alert['RECIPIENTS']}"
                st.markdown(f"Channel: **{alert['NOTIFICATION_CHANNEL']}** {recip_display}")
            
            with col3:
                if st.button("🗑️", key=f"del_{alert['ALERT_ID']}"):
                    try:
                        path = client.get_schema_path("APP_CONTEXT")
                        client.execute_write(f"""
                            DELETE FROM {path}.BUDGET_ALERTS
                            WHERE ALERT_ID = {alert['ALERT_ID']}
                        """)
                        st.success("Deleted")
                        st.cache_data.clear()
                        # st.rerun() # Commented out to prevent aggressive reruns, let user refresh or click again if needed
                        time.sleep(0.5) 
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")
            
            st.divider()
    else:
        st.info("No budget alerts configured yet.")


def render_autopilot_settings(client):
    """Render Autopilot configuration"""
    st.markdown("### 🤖 Warehouse Autopilot")
    st.caption("*Automated optimization engine (inspired by Select.dev)*")
    
    from intelligence.autopilot import AutopilotManager
    manager = AutopilotManager(client)
    
    status = manager.get_status() # STARTED, SUSPENDED, NOT_CONFIGURED
    
    # Status Indicator
    col1, col2 = st.columns([1, 3])
    with col1:
        if status == 'STARTED':
            st.success("✅ Autopilot Active")
        elif status == 'SUSPENDED':
            st.warning("⏸️ Autopilot Paused")
        else:
            st.error("❌ Not Configured")
            
    with col2:
        st.info("Autopilot optimizes warehouse 'Auto-Suspend' settings hourly based on usage patterns to save credits.")

    st.divider()
    
    # Controls
    c1, c2, c3 = st.columns(3)
    with c1:
        mode = st.radio("Optimization Mode", ["CONSERVATIVE", "AGGRESSIVE"], 
                       help="Conservative: target 5 mins. Aggressive: target 1 min.")
    
    with c2:
        if status != 'STARTED':
            if st.button("🚀 Enable Autopilot", type="primary"):
                with st.spinner("Deploying Intelligent Task..."):
                    if manager.deploy_autopilot(mode):
                        st.balloons()
                        st.rerun()
                    else:
                        st.error("Deployment failed")
        else:
            if st.button("🛑 Pause Autopilot"):
                manager.disable_autopilot()
                st.rerun()
                
    st.divider()
    
    # Logs
    st.markdown("#### 📜 Activity Log")
    logs = manager.get_logs()
    
    if not logs.empty:
        st.dataframe(
            logs, 
            use_container_width=True,
            column_config={
                "EVENT_TIME": st.column_config.DatetimeColumn(format="MMM DD, HH:mm"),
                "ACTION": st.column_config.TextColumn("Action"),
                "REASON": st.column_config.TextColumn("Reason")
            }
        )
    else:
        st.caption("No automated actions taken yet.")

    st.divider()
    
    # --- Advanced Intelligence ---
    st.markdown("### 🧠 Advanced Intelligence")
    st.caption("*Next-gen automated governance features.*")
    
    c1, c2 = st.columns(2)
    
    with c1:
        st.markdown("#### 🛡️ Budget Enforcer")
        st.info("Automatically kills queries if a team exceeds their budget.")
        if st.button("Deploy Enforcer"):
            from intelligence.budget_enforcer import BudgetEnforcer
            enforcer = BudgetEnforcer(client)
            if enforcer.deploy_enforcer():
                st.success("✅ deployed! Running in Safe Mode (Logging Only).")
                
    with c2:
        st.markdown("#### 🚨 Anomaly Sentinel")
        st.info("Daily scan for cost anomalies (>2x avg). Logs to analytics.")
        if st.button("Deploy Sentinel"):
            from intelligence.anomaly_monitor import AnomalyMonitor
            monitor = AnomalyMonitor(client)
            if monitor.deploy_monitor():
                st.success("✅ deployed! Running daily at 08:00 UTC.")


def render_platform_settings(client):
    """Render platform settings"""
    st.markdown("### Platform Settings")
    
    # Initialize database
    st.markdown("#### Database Initialization")
    st.caption("*Run this to create required tables if they don't exist*")
    
    if st.button("🔧 Initialize/Reset Database", type="primary"):
        with st.spinner("Initializing database..."):
            try:
                app_db = client.get_app_db()
                schemas = ["APP_CONTEXT", "APP_ANALYTICS"]
                
                # 1. Create schemas
                for schema in schemas:
                    client.execute_write(f"CREATE SCHEMA IF NOT EXISTS {app_db}.{schema}")
                
                context_path = f"{app_db}.APP_CONTEXT"
                analytics_path = f"{app_db}.APP_ANALYTICS"
                
                # 2. Create Core Tables
                tables_ddl = [
                    f"""CREATE TABLE IF NOT EXISTS {context_path}.WAREHOUSE_CONTEXT (
                        WAREHOUSE_NAME VARCHAR PRIMARY KEY,
                        PURPOSE VARCHAR DEFAULT 'GENERAL',
                        SIZE VARCHAR,
                        COST_PROFILE VARCHAR DEFAULT 'BALANCED',
                        CONCURRENCY_TOLERANCE VARCHAR DEFAULT 'MEDIUM',
                        OWNER_TEAM VARCHAR,
                        NOTES VARCHAR,
                        UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                    )""",
                    f"""CREATE TABLE IF NOT EXISTS {context_path}.TABLE_CONTEXT (
                        DATABASE_NAME VARCHAR,
                        SCHEMA_NAME VARCHAR,
                        TABLE_NAME VARCHAR,
                        FRESHNESS_REQUIREMENT VARCHAR DEFAULT 'DAILY',
                        ACCESS_FREQUENCY VARCHAR DEFAULT 'UNKNOWN',
                        IS_CRITICAL BOOLEAN DEFAULT FALSE,
                        PRIMARY KEY (DATABASE_NAME, SCHEMA_NAME, TABLE_NAME)
                    )""",
                    f"""CREATE TABLE IF NOT EXISTS {context_path}.TEAM_ATTRIBUTION (
                        USER_NAME VARCHAR PRIMARY KEY,
                        TEAM_NAME VARCHAR,
                        DEPARTMENT VARCHAR,
                        COST_CENTER VARCHAR,
                        BUDGET_LIMIT_CREDITS FLOAT,
                        UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                    )""",
                    f"""CREATE TABLE IF NOT EXISTS {context_path}.BUDGET_ALERTS (
                        ALERT_ID NUMBER AUTOINCREMENT PRIMARY KEY,
                        ALERT_NAME VARCHAR,
                        ALERT_TYPE VARCHAR,
                        TARGET_NAME VARCHAR,
                        THRESHOLD_CREDITS FLOAT,
                        THRESHOLD_PERCENTAGE FLOAT,
                        NOTIFICATION_CHANNEL VARCHAR DEFAULT 'DASHBOARD',
                        IS_ACTIVE BOOLEAN DEFAULT TRUE
                    )""",
                    f"""CREATE TABLE IF NOT EXISTS {context_path}.PLATFORM_SETTINGS (
                        SETTING_KEY VARCHAR PRIMARY KEY,
                        SETTING_VALUE VARCHAR,
                        DESCRIPTION VARCHAR,
                        UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                    )""",
                    f"""CREATE TABLE IF NOT EXISTS {analytics_path}.METADATA_CACHE (
                        CACHE_KEY VARCHAR PRIMARY KEY,
                        CACHE_VALUE VARIANT,
                        EXPIRY_TIME TIMESTAMP_NTZ
                    )"""
                ]
                
                for ddl in tables_ddl:
                    client.execute_write(ddl)
                
                st.success(f"✅ Database {app_db} initialized successfully!")
                st.info("All context and caching tables are now ready.")
            except Exception as e:
                st.error(f"Error: {e}")
    
    st.divider()
    
    # Danger Zone - Reset
    st.markdown("#### ⚠️ Danger Zone")
    st.caption("*Use this to completely reset all app data and start fresh.*")
    
    with st.expander("🔥 Reset All App Data (Destructive)"):
        st.warning("**This will DROP and RECREATE all app-related tables.** All your saved context, alerts, and benchmarks will be lost.")
        confirm_text = st.text_input("Type 'RESET' to confirm", key="reset_confirm")
        if st.button("💣 Perform Full Reset"):
            if confirm_text == "RESET":
                with st.spinner("Resetting all app data..."):
                    try:
                        app_db = client.get_app_db()
                        client.execute_write(f"DROP SCHEMA IF EXISTS {app_db}.APP_CONTEXT CASCADE")
                        client.execute_write(f"DROP SCHEMA IF EXISTS {app_db}.APP_ANALYTICS CASCADE")
                        st.success("All app data has been reset. Please refresh the page to run the Setup Wizard again.")
                        st.session_state.setup_complete = False
                    except Exception as e:
                        st.error(f"Reset failed: {e}")
            else:
                st.error("Please type 'RESET' to confirm.")
    
    st.markdown("---")
    st.markdown("""
    **Manual Account Cleanup (Run in Snowsight)**
    ```sql
    DROP DATABASE IF EXISTS SNOWFLAKE_OPS_APP_DATA;
    DROP APPLICATION IF EXISTS SNOWFLAKE_OPS_APP;
    DROP APPLICATION PACKAGE IF EXISTS SNOWFLAKE_OPS_PACKAGE;
    ```
    """)
    
    st.divider()



    
    # Export/Import
    st.markdown("#### Export Configuration")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("📥 Export All Settings"):
            config = {
                "export_date": datetime.now().isoformat(),
                "message": "Export functionality coming soon"
            }
            st.download_button(
                label="Download JSON",
                data=json.dumps(config, indent=2),
                file_name=f"snowflake_ops_config_{datetime.now().strftime('%Y%m%d')}.json",
                mime="application/json"
            )
    
    with col2:
        uploaded = st.file_uploader("Import Configuration", type=['json'])
        if uploaded:
            st.info("Import functionality coming soon")
    
    st.divider()
    
    # About
    st.markdown("#### About")
    st.markdown("""
    **Snowflake Ops & Query Intelligence Platform**
    
    Version: 1.0.0  
    Region: Asia Pacific (Singapore)
    
    ---
    
    *"Snowflake optimizes queries technically. We optimize them contextually."*
    
    This platform combines Snowflake metadata, historical patterns, and user-defined context
    to provide optimization recommendations that Snowflake alone cannot offer.
    
    **Features:**
    - 💰 Cost visibility and attribution
    - 🔍 Query analysis and optimization
    - 🏭 Warehouse monitoring and recommendations
    - 🔄 Pipeline health monitoring
    - 📊 Data freshness tracking
    - 📥 Excel export for all reports
    
    Built with ❤️ using Streamlit and Snowpark
    """)


# --- CORTEX CONFIGURATION ---
def render_cortex_settings(client):
    """Render Cortex AI Configuration"""
    st.markdown("### 🧠 Cortex & AI Configuration")
    st.caption("Manage Snowflake Cortex AI query engine settings.")
    
    # Fetch current settings
    current_settings = {}
    try:
        res = client.session.sql("SELECT SETTING_KEY, SETTING_VALUE FROM APP_CONTEXT.PLATFORM_SETTINGS WHERE SETTING_KEY LIKE 'CORTEX_%'").collect()
        for r in res:
            current_settings[r['SETTING_KEY']] = r['SETTING_VALUE']
    except:
        pass
        
    c1, c2 = st.columns(2)
    
    with c1:
        st.markdown("#### Global AI Settings")
        
        # Enable/Disable
        cortex_enabled = st.toggle(
            "Enable Cortex AI", 
            value=current_settings.get('CORTEX_ENABLED', 'TRUE') == 'TRUE',
            help="Master switch for all AI features in this app."
        )
        
        # Cross Region
        cross_region = st.toggle(
            "Allow Cross-Region Inference",
            value=current_settings.get('CORTEX_CROSS_REGION', 'FALSE') == 'TRUE',
            help="Allow using models hosted in other regions (may incur data transfer costs)."
        )
        
    with c2:
        st.markdown("#### Model Preferences")
        
        # models
        available_models = ['mistral-large', 'llama3-70b', 'llama3-8b', 'gemma-7b', 'reka-flash']
        current_model = current_settings.get('CORTEX_DEFAULT_MODEL', 'mistral-large')
        
        if current_model not in available_models:
            available_models.append(current_model)
            
        default_model = st.selectbox(
            "Default Large Language Model",
            options=available_models,
            index=available_models.index(current_model),
            help="Model used for general queries and analysis."
        )

    if st.button("💾 Save AI Settings", type="primary"):
        try:
            # Upsert settings
            settings_to_update = {
                'CORTEX_ENABLED': str(cortex_enabled).upper(),
                'CORTEX_CROSS_REGION': str(cross_region).upper(),
                'CORTEX_DEFAULT_MODEL': default_model
            }
            
            for k, v in settings_to_update.items():
                merge_sql = f"""
                MERGE INTO APP_CONTEXT.PLATFORM_SETTINGS AS target
                USING (SELECT '{k}' AS k, '{v}' AS v) AS source
                ON target.SETTING_KEY = source.k
                WHEN MATCHED THEN UPDATE SET SETTING_VALUE = source.v, UPDATED_AT = CURRENT_TIMESTAMP()
                WHEN NOT MATCHED THEN INSERT (SETTING_KEY, SETTING_VALUE, DESCRIPTION) VALUES (source.k, source.v, 'Updated via Settings')
                """
                client.session.sql(merge_sql).collect()
                
            st.success("✅ AI Settings Saved!")
            st.cache_data.clear()
            
        except Exception as e:
            st.error(f"Failed to save settings: {e}")

if __name__ == "__main__":
    main()
