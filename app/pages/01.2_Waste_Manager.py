import streamlit as st
import pandas as pd
import altair as alt
from utils.snowflake_client import SnowflakeClient
from utils.styles import apply_global_styles, render_metric_card, render_sidebar

# Page Config
st.set_page_config(page_title="Snowflake Waste Manager", page_icon="🗑️", layout="wide")
apply_global_styles()
render_sidebar()

def get_zombie_warehouses(session):
    """
    Identify warehouses running without processing queries (Idle)
    """
    # Heuristic: Warehouse active (METERING) but consistent low/zero load (LOAD_HISTORY)
    # We look for hour-long blocks where credits > 0 but avg_running < 0.1
    query = """
        WITH hourly_stats AS (
        SELECT 
            DATE_TRUNC('HOUR', l.START_TIME) as hour_window,
            l.WAREHOUSE_NAME,
            SUM(m.CREDITS_USED) as credits,
            AVG(l.AVG_RUNNING) as running_load
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_LOAD_HISTORY l
        JOIN SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY m 
          ON l.WAREHOUSE_NAME = m.WAREHOUSE_NAME 
          AND DATE_TRUNC('HOUR', l.START_TIME) = DATE_TRUNC('HOUR', m.START_TIME)
        WHERE l.START_TIME >= DATEADD(day, -7, CURRENT_TIMESTAMP())
        GROUP BY 1, 2
    )
    SELECT 
        WAREHOUSE_NAME,
        COUNT(*) as idle_hours,
        SUM(credits) as wasted_credits,
        SUM(credits) * 3.0 as wasted_cost_usd -- approx $3/credit
    FROM hourly_stats
    WHERE credits > 0 AND running_load < 0.1
    GROUP BY 1
    ORDER BY wasted_credits DESC
    LIMIT 10
    """
    # Use snowflake_client wrapper if available or raw session
    # We'll use the client from main app flow usually
    return session.execute_query(query)

def get_cold_tables(session):
    """
    Identify tables > 1GB not queried in 90 days
    """
    # Requires ACCESS_HISTORY (Enterprise) or Q.History parsing. 
    # Fallback to Access History if available, else Last Altered heuristic
    
    # Check if access_history exists
    try:
        session.execute_query("SELECT 1 FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY LIMIT 1", log=False)
        has_access_history = True
    except:
        has_access_history = False

    if has_access_history:
        query = """
        WITH recent_access AS (
            SELECT DISTINCT 
                f.value:objectDomain::STRING as OBJECT_DOMAIN, 
                f.value:objectName::STRING as OBJECT_NAME 
            FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY,
            LATERAL FLATTEN(BASE_OBJECTS_ACCESSED) f
            WHERE QUERY_START_TIME >= DATEADD(day, -90, CURRENT_TIMESTAMP())
            AND f.value:objectDomain::STRING = 'Table'
        )
        SELECT 
            t.TABLE_CATALOG || '.' || t.TABLE_SCHEMA || '.' || t.TABLE_NAME as table_path,
            t.BYTES / 1024 / 1024 / 1024 as size_gb,
            t.LAST_ALTERED,
            t.ROW_COUNT
        FROM SNOWFLAKE.ACCOUNT_USAGE.TABLES t
        LEFT JOIN recent_access a 
          ON t.TABLE_NAME = a.OBJECT_NAME -- Name match simplification for now, ideally full path match needed
             AND t.TABLE_SCHEMA != 'INFORMATION_SCHEMA'
        WHERE t.DELETED IS NULL
          AND t.BYTES > 1024*1024*1024 -- > 1GB
          AND a.OBJECT_NAME IS NULL -- Not accessed
          AND t.TABLE_SCHEMA != 'ACCOUNT_USAGE'
        ORDER BY size_gb DESC
        LIMIT 20
        """
    else:
        # Fallback: Tables not altered in 90 days (Heuristic)
        query = """
        SELECT 
            TABLE_CATALOG || '.' || t.TABLE_SCHEMA || '.' || t.TABLE_NAME as table_path,
            BYTES / 1024 / 1024 / 1024 as size_gb,
            LAST_ALTERED,
            ROW_COUNT
        FROM SNOWFLAKE.ACCOUNT_USAGE.TABLES t
        WHERE DELETED IS NULL
          AND BYTES > 1024*1024*1024 -- > 1GB
          AND LAST_ALTERED < DATEADD(day, -90, CURRENT_TIMESTAMP())
          AND TABLE_SCHEMA != 'INFORMATION_SCHEMA'
        ORDER BY size_gb DESC
        LIMIT 20
        """
    return session.execute_query(query)

def get_failed_query_cost(session):
    """
    Calculate credits wasted on failed queries
    """
    query = """
    SELECT 
        USER_NAME,
        COUNT(*) as failed_count,
        SUM(TOTAL_ELAPSED_TIME)/1000/60 as failed_minutes,
        -- Estimation: X-Small (1 credit/hr) * hours. 
        -- Precise would need warehouse size join.
        SUM(
          CASE 
            WHEN WAREHOUSE_SIZE = 'X-Small' THEN 1
            WHEN WAREHOUSE_SIZE = 'Small' THEN 2
            WHEN WAREHOUSE_SIZE = 'Medium' THEN 4
            WHEN WAREHOUSE_SIZE = 'Large' THEN 8
            WHEN WAREHOUSE_SIZE = 'X-Large' THEN 16
            WHEN WAREHOUSE_SIZE = '2X-Large' THEN 32
            WHEN WAREHOUSE_SIZE = '3X-Large' THEN 64
            ELSE 1 
          END * (TOTAL_ELAPSED_TIME/1000/3600)
        ) as estimated_wasted_credits
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE EXECUTION_STATUS != 'SUCCESS'
      AND START_TIME >= DATEADD(day, -30, CURRENT_TIMESTAMP())
      AND TOTAL_ELAPSED_TIME > 0
      AND WAREHOUSE_SIZE IS NOT NULL
    GROUP BY 1
    ORDER BY estimated_wasted_credits DESC
    LIMIT 10
    """
    return session.execute_query(query)

def run():
    # Header
    st.markdown("""
    <div style="padding: 20px; background: linear-gradient(90deg, #1e293b, #0f172a); border-radius: 12px; margin-bottom: 25px; border: 1px solid #334155;">
        <h1 style="color: white; margin: 0; font-size: 2.2rem; display: flex; align-items: center; gap: 10px;">
            🗑️ Waste Manager
        </h1>
        <p style="color: #94a3b8; margin: 5px 0 0 0; font-size: 1.1rem;">
            Identify and eliminate unused resources, idle warehouses, and failed operations.
        </p>
    </div>
    """, unsafe_allow_html=True)

    # Initialize Client
    client = SnowflakeClient()
    if not client.session:
        st.error("Please login to Snowflake first.")
        return

    # Tabs
    tab_zombie, tab_cold, tab_failed = st.tabs(["🧟 Zombie Warehouses", "🧊 Cold Data", "❌ Failed Queries"])

    with tab_zombie:
        st.subheader("Warehouses Running Idle")
        st.info("Warehouses that consumed credits but had < 10% load (last 7 days).")
        
        df_zombie = get_zombie_warehouses(client)
        if not df_zombie.empty:
            # Metrics
            total_waste = df_zombie['WASTED_CREDITS'].sum()
            col1, col2 = st.columns(2)
            with col1:
                render_metric_card("Total Wasted Credits", f"{total_waste:,.1f}", "Last 7 Days", "negative")
            with col2:
                render_metric_card("Est. Wasted Cost", f"${total_waste*3:,.2f}", "@ $3/credit", "negative")
            
            st.dataframe(
                df_zombie,
                column_config={
                    "WAREHOUSE_NAME": "Warehouse",
                    "IDLE_HOURS": "Idle Hours",
                    "WASTED_CREDITS": st.column_config.NumberColumn("Wasted Credits", format="%.1f"),
                    "WASTED_COST_USD": st.column_config.NumberColumn("Est. Cost ($)", format="$%.2f")
                },
                use_container_width=True
            )
            
            # Action
            st.warning("👉 Recommendation: Reduce Auto-Suspend to 60 seconds (1 min) for these warehouses.")
        else:
            st.success("No Zombie Warehouses detected! 🎉")

    with tab_cold:
        st.subheader("Cold Tables (> 1GB, Unused > 90 Days)")
        st.info("Tables consuming storage costs but not being queried.")
        
        df_cold = get_cold_tables(client)
        if not df_cold.empty:
            total_gb = df_cold['SIZE_GB'].sum()
            render_metric_card("Total Cold Storage", f"{total_gb:,.1f} GB", "Potential Archival Candidates", "warning")
            
            st.dataframe(
                df_cold,
                column_config={
                    "TABLE_PATH": "Table",
                    "SIZE_GB": st.column_config.NumberColumn("Size (GB)", format="%.2f GB"),
                    "LAST_ALTERED": st.column_config.DatetimeColumn("Last Altered"),
                    "ROW_COUNT": st.column_config.NumberColumn("Rows")
                },
                use_container_width=True
            )
        else:
            st.success("No large cold tables found! Analysis based on available history.")

    with tab_failed:
        st.subheader("Cost of Failure")
        st.info("Credits consumed by queries that ultimately failed (Syntax, Timeout, etc).")
        
        df_failed = get_failed_query_cost(client)
        if not df_failed.empty:
            total_failed_cost = df_failed['ESTIMATED_WASTED_CREDITS'].sum()
            render_metric_card("Credits Burned on Failures", f"{total_failed_cost:,.2f}", "Last 30 Days", "negative")
            
            st.dataframe(
                df_failed,
                column_config={
                    "USER_NAME": "User",
                    "FAILED_COUNT": "Fail Count",
                    "FAILED_MINUTES": st.column_config.NumberColumn("Minutes Wasted", format="%.1f min"),
                    "ESTIMATED_WASTED_CREDITS": st.column_config.NumberColumn("Est. Credits Lost", format="%.2f")
                },
                use_container_width=True
            )
        else:
            st.success("No significant failed query costs detected.")

if __name__ == "__main__":
    run()
