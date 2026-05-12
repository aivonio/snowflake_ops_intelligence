"""
Pipeline & Task Health Page
Monitor tasks, streams, dynamic tables, and data freshness
"""

import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.snowflake_client import get_snowflake_client
from utils.formatters import format_duration_ms, format_time_ago, get_status_color, dataframe_to_excel_bytes
from utils.styles import apply_global_styles, COLORS

st.set_page_config(
    page_title="Ops Control Center | Snowflake",
    page_icon="🛠️",
    layout="wide"
)

# Apply unified Snowflake design system
apply_global_styles()
from utils.styles import render_sidebar
render_sidebar()


@st.cache_data(ttl=60)
def get_task_history(_client, days=7):
    """Get task execution history"""
    query = f"""
    SELECT 
        NAME as task_name,
        DATABASE_NAME,
        SCHEMA_NAME,
        STATE,
        SCHEDULED_TIME,
        COMPLETED_TIME,
        ERROR_CODE,
        ERROR_MESSAGE,
        QUERY_ID,
        DATEDIFF('second', SCHEDULED_TIME, COMPLETED_TIME) as duration_sec
    FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
    WHERE SCHEDULED_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
    ORDER BY SCHEDULED_TIME DESC
    """
    return _client.execute_query(query)


@st.cache_data(ttl=300)
def get_task_summary(_client, days=7):
    """Get task summary statistics"""
    query = f"""
    SELECT 
        NAME as task_name,
        DATABASE_NAME,
        SCHEMA_NAME,
        COUNT(*) as total_runs,
        COUNT(CASE WHEN STATE = 'SUCCEEDED' THEN 1 END) as success_count,
        COUNT(CASE WHEN STATE = 'FAILED' THEN 1 END) as failure_count,
        AVG(DATEDIFF('second', SCHEDULED_TIME, COMPLETED_TIME)) as avg_duration_sec,
        MAX(SCHEDULED_TIME) as last_run
    FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
    WHERE SCHEDULED_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
    GROUP BY NAME, DATABASE_NAME, SCHEMA_NAME
    ORDER BY failure_count DESC, total_runs DESC
    """
    return _client.execute_query(query)


@st.cache_data(ttl=300)
def get_dynamic_tables(_client):
    """Get dynamic table information"""
    # Try SHOW DYNAMIC TABLES first (more reliable)
    query = """
    SHOW DYNAMIC TABLES
    """
    try:
        df = _client.execute_query(query)
        if not df.empty:
            # Standardize column names
            df.columns = [c.upper() for c in df.columns]
            # Select relevant columns if they exist
            cols_to_keep = []
            for col in ['NAME', 'DATABASE_NAME', 'SCHEMA_NAME', 'TARGET_LAG', 
                       'REFRESH_MODE', 'SCHEDULING_STATE', 'WAREHOUSE']:
                if col in df.columns:
                    cols_to_keep.append(col)
            if cols_to_keep:
                return df[cols_to_keep]
        return df
    except Exception as e:
        # Fallback to empty dataframe
        return pd.DataFrame()


@st.cache_data(ttl=300)
def get_stream_info(_client):
    """Get stream information"""
    # Use SHOW STREAMS instead of INFORMATION_SCHEMA
    query = """
    SHOW STREAMS
    """
    try:
        df = _client.execute_query(query)
        if not df.empty:
            # Standardize column names
            df.columns = [c.upper() for c in df.columns]
            # Select relevant columns if they exist
            cols_to_keep = []
            for col in ['NAME', 'DATABASE_NAME', 'SCHEMA_NAME', 'TABLE_NAME', 
                       'TYPE', 'STALE', 'STALE_AFTER', 'MODE']:
                if col in df.columns:
                    cols_to_keep.append(col)
            if cols_to_keep:
                return df[cols_to_keep]
        return df
    except Exception as e:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def get_table_freshness(_client):
    """Get table modification times for freshness tracking"""
    query = """
    SELECT 
        TABLE_CATALOG as database_name,
        TABLE_SCHEMA as schema_name,
        TABLE_NAME,
        ROW_COUNT,
        BYTES,
        LAST_ALTERED,
        CREATED
    FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_TYPE = 'BASE TABLE'
        AND TABLE_SCHEMA NOT IN ('INFORMATION_SCHEMA')
    ORDER BY LAST_ALTERED DESC NULLS LAST
    LIMIT 100
    """
    return _client.execute_query(query)


@st.cache_data(ttl=300)
def get_pipe_history(_client, days=7):
    """Get pipe loading history"""
    # Use COPY_HISTORY for detailed load errors and status
    query = f"""
    SELECT 
        PIPE_NAME,
        PIPE_SCHEMA_NAME as PIPE_SCHEMA,
        PIPE_CATALOG_NAME as DATABASE_NAME,
        FILE_NAME,
        ROW_COUNT as FILES_INSERTED, -- Treating row count as proxy or just counting files later
        FILE_SIZE as BYTES_INSERTED,
        STATUS as PIPE_STATUS,
        FIRST_ERROR_MESSAGE,
        LAST_LOAD_TIME
    FROM SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY
    WHERE PIPE_NAME IS NOT NULL
      AND LAST_LOAD_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
    ORDER BY LAST_LOAD_TIME DESC
    LIMIT 100
    """
    try:
        df = _client.execute_query(query)
        # Normalize columns if needed
        if not df.empty:
             df['FILES_INSERTED'] = 1 # Each row is a file
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def get_spillover_metrics(_client, days=7):
    """Get warehouse spillover metrics"""
    query = f"""
    SELECT 
        WAREHOUSE_NAME,
        COUNT(*) as spill_events,
        SUM(BYTES_SPILLED_TO_LOCAL_STORAGE) / 1024 / 1024 / 1024 as local_spill_gb,
        SUM(BYTES_SPILLED_TO_REMOTE_STORAGE) / 1024 / 1024 / 1024 as remote_spill_gb,
        AVG(TOTAL_ELAPSED_TIME) / 1000 as avg_duration_s
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
      AND (BYTES_SPILLED_TO_LOCAL_STORAGE > 0 OR BYTES_SPILLED_TO_REMOTE_STORAGE > 0)
    GROUP BY 1
    ORDER BY local_spill_gb DESC
    LIMIT 20
    """
    return _client.execute_query(query)


def main():
    st.title("🛠️ Ops Control Center")
    st.markdown("*Unified command center for Pipelines, Tasks, and Performance Health*")
    
    client = get_snowflake_client()
    
    if not client.session:
        st.error("⚠️ Could not connect to Snowflake")
        return
    
    # Quick health check at top
    render_health_summary(client)
    
    st.divider()
    
    # Tabs
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📥 Ingestion",
        "🔥 Spillover",
        "📋 Tasks",
        "📊 Dynamic Tables",
        "🌊 Streams",
        "🎯 Freshness"
    ])
    
    with tab1:
        render_ingestion(client)

    with tab2:
        render_spillover(client)

    with tab3:
        render_task_monitoring(client)
    
    with tab4:
        render_dynamic_tables(client)
    
    with tab5:
        render_streams(client)
    
    with tab6:
        render_data_freshness(client)


def render_health_summary(client):
    """Render unified health check summary"""
    st.markdown("### 🩺 Unified Health Check")
    st.caption("*Check all your pipelines at a glance - no more checking multiple queries!*")
    
    # Get all data
    task_summary = get_task_summary(client, 1)  # Last 24 hours
    dynamic_tables = get_dynamic_tables(client)
    streams = get_stream_info(client)
    
    col1, col2, col3, col4 = st.columns(4)
    
    # Task health
    with col1:
        if not task_summary.empty:
            total_runs = task_summary['TOTAL_RUNS'].sum()
            failed_runs = task_summary['FAILURE_COUNT'].sum()
            success_rate = ((total_runs - failed_runs) / total_runs * 100) if total_runs > 0 else 100
            
            status = "✅" if failed_runs == 0 else "⚠️" if failed_runs < 5 else "❌"
            color = "#00D4AA" if failed_runs == 0 else "#FFB020" if failed_runs < 5 else "#FF4B4B"
            
            st.markdown(f"""
            <div style="background: #1E2530; padding: 1rem; border-radius: 8px; border-left: 4px solid {color};">
                <h4 style="margin: 0;">{status} Tasks (24h)</h4>
                <p style="margin: 0.5rem 0; font-size: 1.5rem; color: {color};">{success_rate:.1f}% Success</p>
                <small>{total_runs} runs, {failed_runs} failed</small>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.info("No task runs in last 24h")
    
    # Dynamic tables health
    with col2:
        if not dynamic_tables.empty:
            total_dt = len(dynamic_tables)
            suspended = len(dynamic_tables[dynamic_tables['SCHEDULING_STATE'] == 'SUSPENDED']) if 'SCHEDULING_STATE' in dynamic_tables.columns else 0
            
            status = "✅" if suspended == 0 else "⚠️"
            color = "#00D4AA" if suspended == 0 else "#FFB020"
            
            st.markdown(f"""
            <div style="background: #1E2530; padding: 1rem; border-radius: 8px; border-left: 4px solid {color};">
                <h4 style="margin: 0;">{status} Dynamic Tables</h4>
                <p style="margin: 0.5rem 0; font-size: 1.5rem; color: {color};">{total_dt} Tables</p>
                <small>{suspended} suspended</small>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div style="background: #1E2530; padding: 1rem; border-radius: 8px; border-left: 4px solid #A0AEC0;">
                <h4 style="margin: 0;">📊 Dynamic Tables</h4>
                <p style="margin: 0.5rem 0; font-size: 1.5rem; color: #A0AEC0;">None</p>
                <small>No dynamic tables found</small>
            </div>
            """, unsafe_allow_html=True)
    
    # Streams health
    with col3:
        if not streams.empty:
            total_streams = len(streams)
            stale = len(streams[streams['STALE'] == 'true']) if 'STALE' in streams.columns else 0
            
            status = "✅" if stale == 0 else "⚠️"
            color = "#00D4AA" if stale == 0 else "#FFB020"
            
            st.markdown(f"""
            <div style="background: #1E2530; padding: 1rem; border-radius: 8px; border-left: 4px solid {color};">
                <h4 style="margin: 0;">{status} Streams</h4>
                <p style="margin: 0.5rem 0; font-size: 1.5rem; color: {color};">{total_streams} Streams</p>
                <small>{stale} stale</small>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div style="background: #1E2530; padding: 1rem; border-radius: 8px; border-left: 4px solid #A0AEC0;">
                <h4 style="margin: 0;">🌊 Streams</h4>
                <p style="margin: 0.5rem 0; font-size: 1.5rem; color: #A0AEC0;">None</p>
                <small>No streams found</small>
            </div>
            """, unsafe_allow_html=True)
    
    # Overall status
    with col4:
        # Calculate overall health
        issues = 0
        if not task_summary.empty and task_summary['FAILURE_COUNT'].sum() > 0:
            issues += 1
        if not dynamic_tables.empty and 'SCHEDULING_STATE' in dynamic_tables.columns:
            if len(dynamic_tables[dynamic_tables['SCHEDULING_STATE'] == 'SUSPENDED']) > 0:
                issues += 1
        if not streams.empty and 'STALE' in streams.columns:
            if len(streams[streams['STALE'] == 'true']) > 0:
                issues += 1
        
        if issues == 0:
            st.markdown("""
            <div style="background: #1E2530; padding: 1rem; border-radius: 8px; border-left: 4px solid #00D4AA;">
                <h4 style="margin: 0;">✅ Overall Status</h4>
                <p style="margin: 0.5rem 0; font-size: 1.5rem; color: #00D4AA;">HEALTHY</p>
                <small>All systems operational</small>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div style="background: #1E2530; padding: 1rem; border-radius: 8px; border-left: 4px solid #FFB020;">
                <h4 style="margin: 0;">⚠️ Overall Status</h4>
                <p style="margin: 0.5rem 0; font-size: 1.5rem; color: #FFB020;">ATTENTION</p>
                <small>{issues} area(s) need review</small>
            </div>
            """, unsafe_allow_html=True)


def render_task_monitoring(client):
    """Render task monitoring section"""
    st.markdown("### Task Monitoring")
    
    col1, col2 = st.columns([1, 3])
    with col1:
        days = st.selectbox("Time Range", [1, 7, 14, 30], 
                           format_func=lambda x: f"Last {x} day(s)",
                           key="task_days")
    
    task_history = get_task_history(client, days)
    task_summary = get_task_summary(client, days)
    
    if task_history.empty:
        st.info("No task execution history found.")
        return
    
    # Summary metrics
    total_runs = len(task_history)
    succeeded = len(task_history[task_history['STATE'] == 'SUCCEEDED'])
    failed = len(task_history[task_history['STATE'] == 'FAILED'])
    success_rate = (succeeded / total_runs * 100) if total_runs > 0 else 0
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Runs", total_runs)
    with col2:
        st.metric("Succeeded", succeeded)
    with col3:
        st.metric("Failed", failed, delta="⚠️" if failed > 0 else None)
    with col4:
        st.metric("Success Rate", f"{success_rate:.1f}%")
    
    st.divider()
    
    # Task status chart
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### Runs by Status")
        
        status_counts = task_history['STATE'].value_counts().reset_index()
        status_counts.columns = ['Status', 'Count']
        
        pie = alt.Chart(status_counts).mark_arc(innerRadius=50).encode(
            theta='Count:Q',
            color=alt.Color('Status:N', scale=alt.Scale(
                domain=['SUCCEEDED', 'FAILED', 'SKIPPED', 'CANCELLED'],
                range=['#00D4AA', '#FF4B4B', '#FFB020', '#A0AEC0']
            )),
            tooltip=['Status', 'Count']
        ).properties(height=250)
        
        st.altair_chart(pie, use_container_width=True)
    
    with col2:
        st.markdown("#### Tasks by Run Count")
        
        if not task_summary.empty:
            bar = alt.Chart(task_summary.head(10)).mark_bar(color='#29B5E8').encode(
                x=alt.X('TOTAL_RUNS:Q', title='Runs'),
                y=alt.Y('TASK_NAME:N', title='', sort='-x'),
                tooltip=['TASK_NAME', 'TOTAL_RUNS', 'SUCCESS_COUNT', 'FAILURE_COUNT']
            ).properties(height=250)
            
            st.altair_chart(bar, use_container_width=True)
    
    # Failed tasks detail
    if failed > 0:
        st.markdown("#### ❌ Failed Tasks")
        
        failed_tasks = task_history[task_history['STATE'] == 'FAILED']
        
        for _, task in failed_tasks.head(10).iterrows():
            with st.expander(f"{task['TASK_NAME']} - {task['SCHEDULED_TIME']}"):
                st.error(f"**Error Code**: {task['ERROR_CODE']}")
                st.error(f"**Message**: {task['ERROR_MESSAGE']}")
                st.info(f"**Query ID**: {task['QUERY_ID']}")
    
    # Task summary table
    st.markdown("#### Task Summary")
    
    if not task_summary.empty:
        display_df = task_summary[['TASK_NAME', 'DATABASE_NAME', 'TOTAL_RUNS', 
                                   'SUCCESS_COUNT', 'FAILURE_COUNT', 'AVG_DURATION_SEC', 'LAST_RUN']].copy()
        display_df['SUCCESS_RATE'] = (display_df['SUCCESS_COUNT'] / display_df['TOTAL_RUNS'] * 100)
        display_df.columns = ['Task', 'Database', 'Runs', 'Success', 'Failed', 'Avg Duration (s)', 'Last Run', 'Success %']
        
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Avg Duration (s)": st.column_config.NumberColumn(format="%.1f"),
                "Success %": st.column_config.NumberColumn(format="%.1f"),
                "Last Run": st.column_config.DatetimeColumn(format="MMM DD, HH:mm")
            }
        )
        
        # Export
        col1, col2 = st.columns([3, 1])
        with col2:
            excel_data = dataframe_to_excel_bytes(task_summary, "Task_Summary")
            st.download_button(
                label="📥 Export to Excel",
                data=excel_data,
                file_name=f"task_summary_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )


def render_dynamic_tables(client):
    """Render dynamic tables monitoring"""
    st.markdown("### Dynamic Tables")
    st.caption("*Monitor refresh status and optimize TARGET_LAG settings*")
    
    dynamic_tables = get_dynamic_tables(client)
    
    if dynamic_tables.empty:
        st.info("No dynamic tables found in your account.")
        st.markdown("""
        **What are Dynamic Tables?**
        
        Dynamic Tables automatically refresh materialized query results based on a target freshness (lag).
        They're great for declarative data pipelines without managing tasks.
        
        ```sql
        CREATE DYNAMIC TABLE my_table
        TARGET_LAG = '1 hour'
        WAREHOUSE = my_warehouse
        AS
        SELECT * FROM source_table;
        ```
        """)
        return
    
    # Display dynamic tables
    st.dataframe(
        dynamic_tables,
        use_container_width=True,
        hide_index=True
    )
    
    # Optimization tips
    st.markdown("### 💡 Optimization Tips")
    
    st.info("""
    **Target Lag Recommendations:**
    - **Real-time dashboards**: 1-5 minutes
    - **Operational reports**: 15-60 minutes  
    - **Batch analytics**: 1-24 hours
    
    **Cost Optimization:**
    - Larger TARGET_LAG = fewer refreshes = lower cost
    - Suspend refreshes during off-peak hours to save up to 50%
    """)


def render_streams(client):
    """Render streams monitoring"""
    st.markdown("### Streams")
    st.caption("*Track change data capture streams*")
    
    streams = get_stream_info(client)
    
    if streams.empty:
        st.info("No streams found in your account.")
        st.markdown("""
        **What are Streams?**
        
        Streams track changes (inserts, updates, deletes) to tables for CDC pipelines.
        
        ```sql
        CREATE STREAM my_stream ON TABLE source_table;
        ```
        """)
        return
    
    # Check for stale streams
    if 'STALE' in streams.columns:
        stale_streams = streams[streams['STALE'] == 'true']
        if len(stale_streams) > 0:
            st.warning(f"""
            ⚠️ **{len(stale_streams)} Stale Stream(s) Detected**
            
            Stale streams have lost their change tracking position. They need to be recreated.
            """)
    
    st.dataframe(
        streams,
        use_container_width=True,
        hide_index=True
    )


def render_data_freshness(client):
    """Render data freshness tracking"""
    st.markdown("### Data Freshness")
    st.caption("*Track when tables were last updated*")
    
    freshness = get_table_freshness(client)
    
    if freshness.empty:
        st.info("No table data available.")
        return
    
    # Add computed columns
    freshness['SIZE_GB'] = freshness['BYTES'] / (1024 ** 3)
    
    # Fix timezone issue - ensure both datetimes are timezone-naive
    now_utc = pd.Timestamp.now(tz='UTC').tz_localize(None)
    freshness['LAST_ALTERED'] = pd.to_datetime(freshness['LAST_ALTERED'])
    
    # Remove timezone if present
    if freshness['LAST_ALTERED'].dt.tz is not None:
        freshness['LAST_ALTERED'] = freshness['LAST_ALTERED'].dt.tz_localize(None)
    
    freshness['HOURS_SINCE_UPDATE'] = (
        now_utc - freshness['LAST_ALTERED']
    ).dt.total_seconds() / 3600
    
    # Freshness summary
    very_fresh = len(freshness[freshness['HOURS_SINCE_UPDATE'] < 1])
    fresh = len(freshness[(freshness['HOURS_SINCE_UPDATE'] >= 1) & (freshness['HOURS_SINCE_UPDATE'] < 24)])
    stale = len(freshness[freshness['HOURS_SINCE_UPDATE'] >= 24])
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Updated < 1 hour", very_fresh, delta="Fresh")
    with col2:
        st.metric("Updated 1-24 hours", fresh)
    with col3:
        st.metric("Updated > 24 hours", stale, delta="May be stale" if stale > 0 else None)
    
    st.divider()
    
    # Freshness chart
    st.markdown("#### Recent Updates")
    
    recent = freshness.head(20).copy()
    recent['TABLE_FULL'] = recent['DATABASE_NAME'] + '.' + recent['SCHEMA_NAME'] + '.' + recent['TABLE_NAME']
    
    bar = alt.Chart(recent).mark_bar(color='#29B5E8').encode(
        x=alt.X('HOURS_SINCE_UPDATE:Q', title='Hours Since Update'),
        y=alt.Y('TABLE_FULL:N', title='', sort='x'),
        color=alt.condition(
            alt.datum.HOURS_SINCE_UPDATE > 24,
            alt.value('#FF4B4B'),
            alt.value('#29B5E8')
        ),
        tooltip=[
            alt.Tooltip('TABLE_NAME:N', title='Table'),
            alt.Tooltip('HOURS_SINCE_UPDATE:Q', title='Hours Ago', format=',.1f'),
            alt.Tooltip('SIZE_GB:Q', title='Size GB', format=',.2f'),
            alt.Tooltip('ROW_COUNT:Q', title='Rows', format=',')
        ]
    ).properties(height=400)
    
    st.altair_chart(bar, use_container_width=True)
    
    # Table
    display_df = freshness[['DATABASE_NAME', 'SCHEMA_NAME', 'TABLE_NAME', 
                            'ROW_COUNT', 'SIZE_GB', 'LAST_ALTERED', 'HOURS_SINCE_UPDATE']].copy()
    display_df.columns = ['Database', 'Schema', 'Table', 'Rows', 'Size (GB)', 'Last Modified', 'Hours Ago']
    
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Rows": st.column_config.NumberColumn(format="%d"),
            "Size (GB)": st.column_config.NumberColumn(format="%.3f"),
            "Hours Ago": st.column_config.NumberColumn(format="%.1f"),
            "Last Modified": st.column_config.DatetimeColumn(format="MMM DD, HH:mm")
        }
    )

def render_ingestion(client):
    """Render Snowpipe Ingestion History"""
    st.markdown("### 📥 Ingestion Intelligence (Snowpipe)")
    st.caption("*Monitor file loading performance and failures*")
    
    # Check if we have data for last 7 days
    pipes = get_pipe_history(client, 7)
    
    if pipes.empty:
        st.info("No Snowpipe usage detected in the last 7 days.")
        return

    # Metrics
    total_files = pipes['FILES_INSERTED'].sum() if 'FILES_INSERTED' in pipes.columns else 0
    total_bytes = pipes['BYTES_INSERTED'].sum() if 'BYTES_INSERTED' in pipes.columns else 0
    total_gb = total_bytes / (1024**3)
    
    col1, col2 = st.columns(2)
    col1.metric("Files Loaded (7d)", f"{total_files:,.0f}")
    col2.metric("Data Volume", f"{total_gb:,.2f} GB")
    
    st.divider()

    # Status Breakdown
    if 'PIPE_STATUS' in pipes.columns:
        st.markdown("#### Pipe Status")
        st.dataframe(
            pipes,
            use_container_width=True,
            column_config={
                "PIPE_NAME": "Pipe",
                "FILES_INSERTED": st.column_config.NumberColumn("Files"),
                "BYTES_INSERTED": st.column_config.NumberColumn("Bytes", format="%.0f"),
                "PIPE_STATUS": "Status",
                "LAST_LOAD_TIME": st.column_config.DatetimeColumn("Last Load")
            }
        )

def render_spillover(client):
    """Render Spillover Heatmap"""
    st.markdown("### 🔥 Memory Spillage (Performance Killer)")
    st.caption("*Identify warehouses that are running out of RAM (Spilling to Disk)*")
    
    spill = get_spillover_metrics(client, 7)
    
    if spill.empty:
        st.success("✅ No memory spillage detected in the last 7 days! Your warehouses are sized correctly.")
        return
        
    # Visualization
    total_local = spill['LOCAL_SPILL_GB'].sum()
    total_remote = spill['REMOTE_SPILL_GB'].sum()
    
    c1, c2 = st.columns(2)
    c1.metric("Local Spill (SSD)", f"{total_local:,.2f} GB", "Slower")
    c2.metric("Remote Spill (S3/Blob)", f"{total_remote:,.2f} GB", "Slowest (Critical)")
    
    if total_remote > 0:
        st.error("⚠️ Remote Spillage Detected! This severely impacts performance. Consider scaling up the Warehouse size.")
    elif total_local > 10:
        st.warning("⚠️ High Local Spillage. Queries are slowing down. Monitor closely.")
        
    st.markdown("#### Spillage by Warehouse")
    st.dataframe(
        spill, 
        use_container_width=True,
        column_config={
            "WAREHOUSE_NAME": "Warehouse",
            "SPILL_EVENTS": "Spill Events",
            "LOCAL_SPILL_GB": st.column_config.ProgressColumn("Local Spill (GB)", format="%.2f", max_value=max(spill['LOCAL_SPILL_GB'].max(), 1)),
            "REMOTE_SPILL_GB": st.column_config.ProgressColumn("Remote Spill (GB)", format="%.2f", max_value=max(spill['REMOTE_SPILL_GB'].max(), 1)),
            "AVG_DURATION_S": st.column_config.NumberColumn("Avg Duration (s)", format="%.1f")
        }
    )

if __name__ == "__main__":
    main()
