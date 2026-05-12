"""
Snowflake Ops & Query Intelligence Platform
Main Streamlit Application Entry Point
"""


import streamlit as st
import pandas as pd
import os
import sys
from datetime import datetime, timedelta

# --- STANDALONE PATH FIX ---
# In Snowflake Standalone Streamlit (SiS), we need to ensure local modules are 
# in the path if they are in subdirectories.
try:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.append(current_dir)
    app_dir = os.path.join(current_dir, 'app')
    if os.path.exists(app_dir) and app_dir not in sys.path:
        sys.path.append(app_dir)
except (NameError, TypeError):
    pass

# Now we can import our local modules
try:
    from utils.snowflake_client import SnowflakeClient
    from utils.styles import apply_global_styles, render_metric_card, render_page_header, COLORS
    from utils.data_service import get_account_metrics, get_daily_credits, get_daily_credits_by_warehouse
except ImportError:
    # Fallback for different stage structures
    st.error("Error: Could not find 'utils' folder. Please ensure it is uploaded to the same stage.")
    st.stop()

# PostHog analytics (optional — fails gracefully)
try:
    from utils.analytics import track_page_view, track_session_start, track_feature_use
    _HAS_ANALYTICS = True
except ImportError:
    _HAS_ANALYTICS = False

import time

# Page configuration
st.set_page_config(
    page_title="Snowflake Ops Intelligence",
    page_icon="❄️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Track session start (PostHog)
if _HAS_ANALYTICS:
    track_session_start()
    track_page_view("Dashboard")

# Apply Snowflake Design System
apply_global_styles()

# LOGIN & AUTH LOGIC
def login_page():
    st.markdown("<div style='text-align: center; margin-top: 50px;'>", unsafe_allow_html=True)
    st.markdown("<h1>❄️ Snowflake Ops Intelligence</h1>", unsafe_allow_html=True)
    st.markdown("<p style='color: var(--snow-text-muted);'>Secure Intelligence Platform</p>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("login_form"):
            st.markdown("### 🔐 Secure Login")
            auth_method = st.radio("Authentication Method", ["Snowflake OAuth (SSO)", "Account Credentials"])
            
            if auth_method == "Account Credentials":
                account = st.text_input("Account Identifier")
                user = st.text_input("Username")
                password = st.text_input("Password", type="password")
            
            submitted = st.form_submit_button("Sign In to Snowflake", use_container_width=True, type="primary")
            
            if submitted:
                with st.spinner("Authenticating..."):
                    client = SnowflakeClient()
                    # For demo/local, we use secrets if fields empty, or inputs if provided
                    # In a real app, you'd pass creds to client
                    session = client.session 
                    
                    if session:
                        ctx = client.get_current_user_context()
                        st.session_state.authenticated = True
                        st.session_state.user_context = ctx
                        st.session_state.snowflake_client = client
                        st.success(f"Welcome back, {ctx.get('user')}!")
                        
                        # --- SELF HEALING / INIT ---
                        from utils.init_db import init_database
                        with st.spinner("Checking system integrity..."):
                            init_database(client)
                        # ---------------------------
                        
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("Authentication Failed.")

def check_access(role_needed):
    """Capability-based Access Control"""
    caps = st.session_state.get('user_context', {}).get('capabilities', {})
    
    if role_needed == 'ADMIN':
        # Admin features generally require Account Usage access
        return caps.get('account_usage', False)
        
    return True

# --- Main Entry Logic ---

if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

# Try Auto-Login (In-Snowflake Mode)
if not st.session_state.authenticated:
    try:
        from snowflake.snowpark.context import get_active_session
        native_session = get_active_session()
        if native_session:
            client = SnowflakeClient() # Will auto-pick up the native session
            ctx = client.get_current_user_context()
            st.session_state.authenticated = True
            st.session_state.user_context = ctx
            st.session_state.snowflake_client = client
            st.session_state.is_native_app = True # Flag for UI adjustments
            
            # --- SELF HEALING / INIT (Native App Mode) ---
            try:
                from utils.init_db import init_database
                with st.spinner("Checking system integrity..."):
                    init_database(client)
            except:
                pass
            # ---------------------------
    except:
        pass # Not a native app, proceed to login page

if not st.session_state.authenticated:
    login_page()
    st.stop()

# --- FIRST-RUN SETUP WIZARD ---
def check_first_run(_client) -> bool:
    """Check if the app has been set up by testing for a known table."""
    if _client.session is None:
        return True # Assume first run if no session
    try:
        app_db = _client.get_app_db()
        _client.session.sql(f"SELECT 1 FROM {app_db}.APP_CONTEXT.PLATFORM_SETTINGS LIMIT 1").collect()
        return False # Table exists, not first run
    except:
        return True # Table doesn't exist, is first run

def run_setup_wizard(_client):
    """Display a setup wizard and create required database objects."""
    st.title("🚀 Welcome to Snowflake Ops Intelligence")
    st.markdown("---")
    st.info("It looks like this is your first time running the app. Let's set things up!")
    
    app_db = _client.get_app_db()
    
    st.markdown(f"**Target Database**: `{app_db}`")
    
    if st.button("🔧 Initialize Database & Tables", type="primary"):
        with st.spinner("Creating database and tables..."):
            try:
                session = _client.session
                # 1. Create Database & Schemas
                session.sql(f"CREATE DATABASE IF NOT EXISTS {app_db}").collect()
                session.sql(f"CREATE SCHEMA IF NOT EXISTS {app_db}.APP_CONTEXT").collect()
                session.sql(f"CREATE SCHEMA IF NOT EXISTS {app_db}.APP_ANALYTICS").collect()
                
                # 2. Create Core Tables
                tables_ddl = [
                    f"""CREATE TABLE IF NOT EXISTS {app_db}.APP_CONTEXT.PLATFORM_SETTINGS (
                        SETTING_KEY VARCHAR PRIMARY KEY, SETTING_VALUE VARCHAR, DESCRIPTION VARCHAR,
                        UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP())""",
                    f"""CREATE TABLE IF NOT EXISTS {app_db}.APP_CONTEXT.WAREHOUSE_CONTEXT (
                        WAREHOUSE_NAME VARCHAR PRIMARY KEY, PURPOSE VARCHAR DEFAULT 'GENERAL', SIZE VARCHAR,
                        COST_PROFILE VARCHAR DEFAULT 'BALANCED', CONCURRENCY_TOLERANCE VARCHAR DEFAULT 'MEDIUM',
                        OWNER_TEAM VARCHAR, NOTES VARCHAR, UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP())""",
                    f"""CREATE TABLE IF NOT EXISTS {app_db}.APP_CONTEXT.TABLE_CONTEXT (
                        DATABASE_NAME VARCHAR, SCHEMA_NAME VARCHAR, TABLE_NAME VARCHAR,
                        FRESHNESS_REQUIREMENT VARCHAR DEFAULT 'DAILY', ACCESS_FREQUENCY VARCHAR DEFAULT 'UNKNOWN',
                        IS_CRITICAL BOOLEAN DEFAULT FALSE, PRIMARY KEY (DATABASE_NAME, SCHEMA_NAME, TABLE_NAME))""",
                    f"""CREATE TABLE IF NOT EXISTS {app_db}.APP_CONTEXT.TEAM_ATTRIBUTION (
                        USER_NAME VARCHAR PRIMARY KEY, TEAM_NAME VARCHAR, DEPARTMENT VARCHAR,
                        COST_CENTER VARCHAR, BUDGET_LIMIT_CREDITS FLOAT, UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP())""",
                    f"""CREATE TABLE IF NOT EXISTS {app_db}.APP_CONTEXT.BUDGET_ALERTS (
                        ALERT_ID NUMBER AUTOINCREMENT PRIMARY KEY, ALERT_NAME VARCHAR, ALERT_TYPE VARCHAR,
                        TARGET_NAME VARCHAR, THRESHOLD_CREDITS FLOAT, THRESHOLD_PERCENTAGE FLOAT,
                        NOTIFICATION_CHANNEL VARCHAR DEFAULT 'DASHBOARD', IS_ACTIVE BOOLEAN DEFAULT TRUE)""",
                    f"""CREATE TABLE IF NOT EXISTS {app_db}.APP_ANALYTICS.METADATA_CACHE (
                        CACHE_KEY VARCHAR PRIMARY KEY, CACHE_VALUE VARIANT, EXPIRY_TIME TIMESTAMP_NTZ)""",
                    f"""CREATE TABLE IF NOT EXISTS {app_db}.APP_ANALYTICS.QUERY_BENCHMARK (
                        BENCHMARK_ID NUMBER AUTOINCREMENT PRIMARY KEY, QUERY_TEXT VARCHAR, QUERY_HASH VARCHAR,
                        RUN_TYPE VARCHAR, PREDICTED_COST_CREDITS FLOAT, ACTUAL_COST_CREDITS FLOAT,
                        PREDICTED_TIME_MS NUMBER, ACTUAL_TIME_MS NUMBER, BYTES_SCANNED NUMBER,
                        WAREHOUSE_USED VARCHAR, WAREHOUSE_SIZE VARCHAR, OPTIMIZATION_APPLIED VARCHAR,
                        COST_SAVINGS_CREDITS FLOAT, TIME_SAVINGS_MS NUMBER, RUN_TIMESTAMP TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP())"""
                ]
                for ddl in tables_ddl:
                    session.sql(ddl).collect()
                
                st.success("✅ Setup Complete! All tables created successfully.")
                st.session_state.setup_complete = True
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"Setup Failed: {e}")
                st.info("Please ensure you have `CREATE DATABASE` / `CREATE TABLE` privileges.")
    st.stop()

# --- CHECK FOR FIRST RUN ---
client = st.session_state.snowflake_client
if st.session_state.get('setup_complete') is not True:
    if check_first_run(client):
        run_setup_wizard(client)

# --- APP CONTENT ---
user_ctx = st.session_state.user_context

user_role = user_ctx.get('role', 'UNKNOWN')

# Sidebar Navigation Logic
# Sidebar Navigation Logic
from utils.styles import render_sidebar


@st.cache_data(ttl=300)
def get_account_overview(_session):
    """Get high-level account metrics with robust error handling."""
    result = {
        'total_credits': 0, 'compute_credits': 0, 'cloud_credits': 0, 
        'warehouse_count': 0, 'query_count': 0, 'failed_queries': 0,
        'storage_tb': 0, 'active_users': 0, 'is_restricted': False, 'error_detail': ''
    }
    
    try:
        # 1. Credits (Last 30 Days)
        credits_df = _session.sql("""
        SELECT 
            COALESCE(SUM(CREDITS_USED), 0) as total_credits,
            COALESCE(SUM(CREDITS_USED_COMPUTE), 0) as compute_credits,
            COALESCE(SUM(CREDITS_USED_CLOUD_SERVICES), 0) as cloud_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
        WHERE START_TIME >= DATEADD(day, -30, CURRENT_TIMESTAMP())
        """).to_pandas()
        result['total_credits'] = float(credits_df.iloc[0, 0]) if not credits_df.empty else 0
        result['compute_credits'] = float(credits_df.iloc[0, 1]) if not credits_df.empty else 0
        result['cloud_credits'] = float(credits_df.iloc[0, 2]) if not credits_df.empty else 0
    except Exception as e:
        result['error_detail'] += f"Credits: {e}; "
        
    try:
        # 2. Warehouses (count from SHOW is more reliable)
        wh_df = _session.sql("SHOW WAREHOUSES").to_pandas()
        result['warehouse_count'] = len(wh_df) if not wh_df.empty else 0
    except Exception as e:
        result['error_detail'] += f"Warehouses: {e}; "

    try:
        # 3. Queries (Last 30 Days) - Use COALESCE for NULL safety
        query_df = _session.sql("""
        SELECT 
            COALESCE(COUNT(*), 0) as total_queries,
            COALESCE(COUNT(CASE WHEN EXECUTION_STATUS != 'SUCCESS' THEN 1 END), 0) as failed_queries
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD(day, -30, CURRENT_TIMESTAMP())
        """).to_pandas()
        result['query_count'] = int(query_df.iloc[0, 0]) if not query_df.empty else 0
        result['failed_queries'] = int(query_df.iloc[0, 1]) if not query_df.empty else 0
    except Exception as e:
        result['error_detail'] += f"Queries: {e}; "
        result['is_restricted'] = True # Mark as restricted if query history fails
        
    try:
        # 4. Storage (Current)
        storage_df = _session.sql("""
        SELECT 
            COALESCE(SUM(AVERAGE_DATABASE_BYTES + AVERAGE_STAGE_BYTES + AVERAGE_FAILSAFE_BYTES) / 1e12, 0) as tb_total
        FROM SNOWFLAKE.ACCOUNT_USAGE.STORAGE_USAGE
        WHERE USAGE_DATE = (SELECT MAX(USAGE_DATE) FROM SNOWFLAKE.ACCOUNT_USAGE.STORAGE_USAGE)
        """).to_pandas()
        result['storage_tb'] = float(storage_df.iloc[0, 0]) if not storage_df.empty else 0
    except Exception as e:
        result['error_detail'] += f"Storage: {e}; "
        
    try:
        # 5. Active Users (Last 30 Days)
        users_df = _session.sql("""
        SELECT COALESCE(COUNT(DISTINCT USER_NAME), 0) as active_users
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD(day, -30, CURRENT_TIMESTAMP())
        """).to_pandas()
        result['active_users'] = int(users_df.iloc[0, 0]) if not users_df.empty else 0
        result['active_users'] = int(users_df.iloc[0, 0]) if not users_df.empty else 0
    except Exception as e:
        result['error_detail'] += f"Users: {e}; "
        
    try:
        # 6. Active Alerts (Custom)
        alerts_df = _session.sql("SELECT COUNT(*) FROM APP_CONTEXT.BUDGET_ALERTS WHERE IS_ACTIVE = TRUE").to_pandas()
        result['active_alerts'] = int(alerts_df.iloc[0, 0]) if not alerts_df.empty else 0
    except Exception:
        result['active_alerts'] = 0
    
    return result


@st.cache_data(ttl=300)
def get_daily_credits(_session, days=30):
    """Get daily credit usage trend"""
    try:
        query = f"""
        SELECT 
            DATE(START_TIME) as usage_date,
            SUM(CREDITS_USED) as credits_used
        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
        WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        GROUP BY DATE(START_TIME)
        ORDER BY usage_date
        """
        return _session.sql(query).to_pandas()
    except Exception as e:
        st.warning(f"Could not fetch daily credits: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=300)
def get_top_users(_session, limit=5):
    """Get top users by query count"""
    try:
        query = f"""
        SELECT 
            USER_NAME,
            COUNT(*) as query_count,
            SUM(CREDITS_USED_CLOUD_SERVICES) as credits_approx
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD(day, -7, CURRENT_TIMESTAMP())
        GROUP BY 1
        ORDER BY 2 DESC
        LIMIT {limit}
        """
        return _session.sql(query).to_pandas()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def get_storage_trend(_session, days=30):
    """Get storage usage trend TB"""
    try:
        query = f"""
        SELECT 
            USAGE_DATE,
            AVERAGE_DATABASE_BYTES / 1e12 as db_tb,
            AVERAGE_STAGE_BYTES / 1e12 as stage_tb,
            AVERAGE_FAILSAFE_BYTES / 1e12 as failsafe_tb
        FROM SNOWFLAKE.ACCOUNT_USAGE.STORAGE_USAGE
        WHERE USAGE_DATE >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        ORDER BY USAGE_DATE
        """
        return _session.sql(query).to_pandas()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def get_workload_metrics(_session, days=7):
    """Get top workloads (grouped by Query Tag or Pattern)"""
    try:
        query = f"""
        SELECT 
            COALESCE(NULLIF(QUERY_TAG, ''), LEFT(QUERY_TEXT, 40)) as workload,
            'Query' as type,
            COUNT(DISTINCT USER_NAME) as users,
            COUNT(DISTINCT WAREHOUSE_NAME) as warehouses,
            AVG(TOTAL_ELAPSED_TIME)/1000 as avg_duration_s,
            COUNT(*) as run_count
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            AND TOTAL_ELAPSED_TIME > 0
        GROUP BY 1, 2
        ORDER BY run_count DESC
        LIMIT 10
        """
        return _session.sql(query).to_pandas()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60)
def get_warehouse_status(_client):
    """Get current warehouse status using the client's normalized execution."""
    # Use client.execute_query instead of _session.sql to get normalized columns
    df = _client.execute_query("SHOW WAREHOUSES")
    
    if not df.empty:
        # Map columns robustly
        if 'NAME' in df.columns:
            df['WAREHOUSE_NAME'] = df['NAME']
        
        if 'STATUS' in df.columns:
            df['STATE'] = df['STATUS']
        elif 'STATE' not in df.columns:
            df['STATE'] = 'UNKNOWN'
            
        return df
    return pd.DataFrame()


# render_metric_card is now imported from utils.styles



# --- Main Dashboard Logic ---

def run_dashboard():
    """Main application entry point for Authenticated Users"""
    session = st.session_state.snowflake_client.session
    user_ctx = st.session_state.user_context
    caps = user_ctx.get('capabilities', {})
    
    if not session:
        st.error("Session lost. Please reload.")
        return

    render_sidebar()

    # 1. Top Action Bar
    col_head, col_action = st.columns([3, 1])
    with col_head:
        # Breadcrumbs style header
        st.markdown(f"""
        <div style="font-size: 0.9rem; color: var(--snow-text-muted); margin-bottom: 4px;">Home / Dashboard</div>
        <div style="font-size: 1.8rem; font-weight: 700; color: var(--snow-text-main); margin-bottom: 5px;">❄️ Snowflake Ops Intelligence</div>
        <div style="font-size: 2.5rem; color: #29B5E8; margin-bottom: 25px; font-weight: 800; letter-spacing: -1px;">DevBySatyam X Anktechsol</div>
        """, unsafe_allow_html=True)

    with col_action:
        # Quick Actions
        st.markdown('<div style="text-align: right; padding-top: 10px;">', unsafe_allow_html=True)
        if st.button("Refresh Data", use_container_width=True):
             st.cache_data.clear() # Clear all cached data
             st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("---")

    # 2. Metric Stat Cards - Use centralized data service
    overview = get_account_metrics(session)
    is_restricted = overview.get('is_restricted', False)
    
    # Interactive metric card with dialog popup
    def render_interactive_card(col, label, value, sub_label, dialog_key, chart_func=None):
        with col:
            render_metric_card(label, value, sub_label)
            if st.button("📊 Details", key=f"btn_{dialog_key}", use_container_width=True):
                st.session_state[f"show_{dialog_key}"] = True
    
    # --- DIALOG POPUPS FOR METRICS ---
    @st.dialog("Credit Consumption History", width="large")
    def show_credits_dialog():
        daily = get_daily_credits(session, days=30)
        if not daily.empty:
            import altair as alt
            chart = alt.Chart(daily).mark_area(
                line={'color': COLORS['primary']}, 
                color=alt.Gradient(gradient='linear', stops=[
                    alt.GradientStop(color=COLORS['primary'], offset=0),
                    alt.GradientStop(color='transparent', offset=1)
                ], x1=1, x2=1, y1=1, y2=0)
            ).encode(x='USAGE_DATE:T', y='CREDITS_USED:Q').properties(height=300)
            st.altair_chart(chart, use_container_width=True)
        else:
            st.info("No credit data available.")
    
    @st.dialog("Query Performance History")
    def show_queries_dialog():
        st.markdown("### Query Statistics (Last 30 Days)")
        col1, col2 = st.columns(2)
        col1.metric("Total Queries", f"{overview['query_count']:,}")
        col2.metric("Failed Queries", f"{overview['failed_queries']:,}")
        st.markdown("---")
        st.info("For detailed query analysis, go to **Query Analyzer** page.")
    
    @st.dialog("Warehouse Utilization", width="large")
    def show_warehouse_dialog():
        st.markdown("### Active Warehouses")
        try:
            # Use the robust existing function that handles column mapping
            # Note: We need to use session_state.snowflake_client
            wh_df = get_warehouse_status(st.session_state.snowflake_client)
            if not wh_df.empty:
                # Ensure we display available columns
                cols_to_show = [c for c in ['WAREHOUSE_NAME', 'STATE', 'TYPE', 'SIZE'] if c in wh_df.columns]
                st.dataframe(wh_df[cols_to_show], use_container_width=True)
            else:
                 st.info("No warehouse data returned.")
        except Exception as e:
            st.info(f"Could not fetch warehouse details: {str(e)}")
    
    # Check if dialogs should be shown
    if st.session_state.get("show_credits"):
        show_credits_dialog()
        st.session_state["show_credits"] = False
    if st.session_state.get("show_queries"):
        show_queries_dialog()
        st.session_state["show_queries"] = False
    if st.session_state.get("show_warehouses"):
        show_warehouse_dialog()
        st.session_state["show_warehouses"] = False
    
    # First row: Credits & Warehouse (Now with Cost)
    row1_c1, row1_c2, row1_c3, row1_c4, row1_c5 = st.columns(5)
    with row1_c1:
        val = "🔒" if is_restricted else f"{overview['total_credits']:,.1f}"
        render_metric_card("Total Credits", val, "Last 30 Days")
        if st.button("📊 Trend", key="btn_credits", use_container_width=True):
            st.session_state["show_credits"] = True
            st.rerun()
    with row1_c2:
        # Estimated Daily Burn
        daily_burn = overview['total_credits'] / 30
        val_burn = "🔒" if is_restricted else f"{daily_burn:,.1f}"
        render_metric_card("Daily Burn", val_burn, "Avg Credits/Day")
    with row1_c3:
        val = "🔒" if is_restricted else f"{overview['compute_credits']:,.1f}"
        render_metric_card("Compute Cost", val, "Credits")
    with row1_c4:
        val = "🔒" if is_restricted else f"{overview['cloud_credits']:,.1f}"
        render_metric_card("Cloud Services", val, "Credits")
    with row1_c5:
        render_metric_card("Warehouses", f"{overview['warehouse_count']}", "Provisioned")
        if st.button("📋 View", key="btn_wh", use_container_width=True):
            st.session_state["show_warehouses"] = True
            st.rerun()

            st.session_state["show_warehouses"] = True
            st.rerun()

    # Second row: Health & Activity & Projections
    row2_c1, row2_c2, row2_c3, row2_c4 = st.columns(4)
    with row2_c1:
        # Projected Cost
        import calendar
        today = datetime.now()
        day_of_month = today.day
        last_day = calendar.monthrange(today.year, today.month)[1]
        
        # Simple linear projection
        if day_of_month > 0:
             est_total = (overview['total_credits'] / day_of_month) * last_day
             delta_val = est_total - overview['total_credits']
             render_metric_card("Projected Cost", f"{est_total:,.1f}", f"+{delta_val:,.1f} by EOM")
        else:
             render_metric_card("Projected Cost", "N/A", "Start of Month")
             
    with row2_c2:
        # Efficiency Score (Simple Heuristic)
        # Start at 100, deduct for failed queries ratio
        success_ratio = 1.0
        if overview['query_count'] > 0:
            success_ratio = 1.0 - (overview['failed_queries'] / overview['query_count'])
        
        score = int(success_ratio * 100)
        color = "var(--snow-success)" if score > 90 else "#FF6C37"
        
        st.markdown(f"""
        <div style="background-color: #1a1c24; padding: 16px; border-radius: 8px; border: 1px solid var(--snow-border); height: 100%;">
            <div style="color: var(--snow-text-muted); font-size: 0.85rem; font-weight: 500;">Efficiency Score</div>
            <div style="font-size: 1.8rem; font-weight: 700; color: {color};">{score}/100</div>
            <div style="font-size: 0.8rem; color: var(--snow-text-muted);">Based on query success</div>
        </div>
        """, unsafe_allow_html=True)

    with row2_c3:
         render_metric_card("Active Alerts", f"{overview.get('active_alerts', 0)}", "Monitored Rules")
         
    with row2_c4:
        avg_time = overview.get('avg_query_time_ms', 0) / 1000 # Use placeholder or calculate if query modified
        # Re-calc from existing data if possible, or just use Failed Queries card again if needed
        # Let's use Failed Queries here as it's critical
        render_metric_card("Failed Queries", f"{overview['failed_queries']:,}", f"{(overview['failed_queries']/max(1, overview['query_count'])*100):.1f}% Rate")

    
    # Third row: Storage & Top Warehouse
    row3_c1, row3_c2, row3_c3, row3_c4 = st.columns(4)
    with row3_c1:
        render_metric_card("Storage Usage", f"{overview['storage_tb']:.2f} TB", "Account Total")
    with row3_c2:
        top_wh = overview.get('top_warehouse', 'N/A')
        top_credits = overview.get('top_warehouse_credits', 0)
        render_metric_card("Top Warehouse", top_wh, f"{top_credits:,.1f} Credits")
    with row3_c3:
        success_rate = 100 - (overview['failed_queries'] / max(overview['query_count'], 1) * 100)
        render_metric_card("Success Rate", f"{success_rate:.1f}%", "Query Health")
    with row3_c4:
        render_metric_card("Data Freshness", "✅", "Up to Date")
    
    # Show diagnostic info if errors occurred
    if overview.get('error_detail'):
        with st.expander("ℹ️ Diagnostic Info (some metrics may be incomplete)", expanded=False):
            st.caption(f"**Issues during data fetch:** {overview['error_detail']}")
            st.info("This is often caused by ACCOUNT_USAGE data latency (up to 45 mins) or missing privileges. Try clicking 'Refresh Data' after a few minutes.")

    # 3. Main Chart Area
    st.markdown("<br>", unsafe_allow_html=True)
    c1, c2 = st.columns([2, 1])
    
    with c1:
        st.markdown("#### 📈 Credit Consumption")
        if is_restricted:
             st.info(f"⚠️ **Restricted View**: {overview.get('error_detail', 'Admin privileges required.')}")
             st.caption("If you are an Admin, ensure the application has 'IMPORTED PRIVILEGES' on the SNOWFLAKE database.")
        else:
             # Chart Toggle
             chart_mode = st.radio(
                 "View Mode", 
                 ["Warehouse Breakdown", "Total Trend"], 
                 horizontal=True,
                 label_visibility="collapsed"
             )

             if chart_mode == "Warehouse Breakdown":
                 daily_credits = get_daily_credits_by_warehouse(session, days=30)
                 if not daily_credits.empty:
                     import altair as alt
                     chart = alt.Chart(daily_credits).mark_area(
                         interpolate='monotone',
                         fillOpacity=0.9
                     ).encode(
                         x=alt.X('USAGE_DATE:T', title=None, axis=alt.Axis(format='%b %d', domain=False, tickSize=0)),
                         y=alt.Y('CREDITS_USED:Q', title=None, axis=None, stack=True),
                         color=alt.Color('WAREHOUSE_GROUP:N', title='Warehouse', legend=alt.Legend(orient='bottom', columns=3)),
                         tooltip=[
                             alt.Tooltip('USAGE_DATE', title='Date', format='%b %d, %Y'),
                             alt.Tooltip('WAREHOUSE_GROUP', title='Warehouse'),
                             alt.Tooltip('CREDITS_USED', title='Credits', format=',.2f')
                         ]
                     ).configure_view(strokeWidth=0).properties(height=350)
                     st.altair_chart(chart, use_container_width=True)
                 else:
                     st.info("No credit consumption data available.")
             else:
                 # Total Trend (Simple Chart)
                 daily_credits = get_daily_credits(session, days=30)
                 if not daily_credits.empty:
                     import altair as alt
                     chart = alt.Chart(daily_credits).mark_area(
                         interpolate='monotone',
                         fillOpacity=0.3,
                         line={'color': '#29B5E8'}
                     ).encode(
                         x=alt.X('USAGE_DATE:T', title=None, axis=alt.Axis(format='%b %d', domain=False, tickSize=0)),
                         y=alt.Y('CREDITS_USED:Q', title=None, axis=None),
                         tooltip=['USAGE_DATE', 'CREDITS_USED']
                     ).configure_view(strokeWidth=0).properties(height=300)
                     st.altair_chart(chart, use_container_width=True)
                 else:
                     st.info("No credit consumption data available.")
    
    with c2:
        st.markdown("#### 🏭 Warehouse Health")
        wh_df = get_warehouse_status(client) # Pass client now
        if not wh_df.empty:
            for _, wh in wh_df.iterrows():
                name = wh.get('WAREHOUSE_NAME', wh.get('NAME', 'Unknown'))
                state = wh.get('STATE', 'UNKNOWN')
                color = "var(--snow-success)" if state in ['STARTED', 'RUNNING'] else "#525252"
                st.markdown(f"""
                <div style="display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--snow-border);">
                    <div style="font-weight: 500; font-size: 0.9rem;">{name}</div>
                    <div style="font-size: 0.8rem; color: {color};">● {state}</div>
                </div>
                """, unsafe_allow_html=True)
    # 5. NEW: Workloads & Storage - Enhanced Layout
    st.markdown("<br>", unsafe_allow_html=True)
    
    # Row 3: Workloads (Select.dev Style)
    st.markdown("#### 📦 Top Workloads (7d)")
    workloads = get_workload_metrics(session)
    if not workloads.empty:
        st.dataframe(
            workloads,
            column_config={
                "WORKLOAD": "Workload",
                "TYPE": "Type",
                "USERS": st.column_config.NumberColumn("Users", format="%d 👤"),
                "WAREHOUSES": st.column_config.NumberColumn("Warehouses", format="%d 🏭"),
                "AVG_DURATION_S": st.column_config.NumberColumn("Avg Duration", format="%.1fs"),
                "RUN_COUNT": st.column_config.ProgressColumn("Volume", format="%d", min_value=0, max_value=int(workloads['RUN_COUNT'].max())),
            },
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No workload data available.")

    st.markdown("<br>", unsafe_allow_html=True)
    
    # Row 4: Storage & Users
    low_c1, low_c2 = st.columns([1, 1])
    
    with low_c1:
        st.markdown("#### 💾 Storage Intelligence (TB)")
        storage_trend = get_storage_trend(session)
        if not storage_trend.empty:
            # Metrics
            latest = storage_trend.iloc[-1]
            s1, s2, s3 = st.columns(3)
            s1.metric("Database", f"{latest['DB_TB']:.2f} TB")
            s2.metric("Stage", f"{latest['STAGE_TB']:.2f} TB")
            s3.metric("Failsafe", f"{latest['FAILSAFE_TB']:.2f} TB", help="Non-recoverable storage cost")
            
            chart_st = alt.Chart(storage_trend).mark_area(
                color=alt.Gradient(gradient='linear', stops=[
                    alt.GradientStop(color='#00D4AA', offset=0),
                    alt.GradientStop(color='transparent', offset=1)
                ], x1=1, x2=1, y1=1, y2=0),
                line={'color': '#00D4AA'}
            ).encode(
                x=alt.X('USAGE_DATE:T', title=None),
                y=alt.Y('DB_TB:Q', title='Terabytes'),
                tooltip=['USAGE_DATE', 'DB_TB']
            ).properties(height=180)
            st.altair_chart(chart_st, use_container_width=True)
        else:
            st.caption("Storage metrics restricted or unavailable.")
            
    with low_c2:
        st.markdown("#### 👥 Top Account Users (7d)")
        top_users = get_top_users(session)
        if not top_users.empty:
            st.dataframe(
                top_users, 
                column_config={
                    "USER_NAME": "User",
                    "QUERY_COUNT": "Queries",
                    "CREDITS_APPROX": st.column_config.NumberColumn("Credits (est)", format="%.2f")
                },
                use_container_width=True,
                hide_index=True
            )
        else:
            st.caption("User metrics restricted or unavailable.")

    # 5. Cost Optimization CTA
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("#### 🎯 Cost Optimization Opportunities")
    opt_c1, opt_c2 = st.columns([3, 1])
    with opt_c1:
        st.info("ℹ️ **Waste Manager**: Identify 'Zombie Warehouses' (idle running) and 'Cold Data' (unused tables) to reduce monthly spend.")
    with opt_c2:
         st.markdown("<div style='padding-top: 15px;'>", unsafe_allow_html=True)
         st.page_link("pages/01.2_Waste_Manager.py", label="🚀 Launch Waste Manager", icon="🗑️", use_container_width=True)
         st.markdown("</div>", unsafe_allow_html=True)

    # 4. Status Bar (Fixed Footer)
    # Render global status bar
    from utils.styles import render_status_bar
    user = user_ctx.get('user', 'UNKNOWN')
    role = user_ctx.get('role', 'UNKNOWN')
    warehouse = user_ctx.get('warehouse', 'N/A')
    render_status_bar(user, role, warehouse)


if __name__ == "__main__":
    run_dashboard()


