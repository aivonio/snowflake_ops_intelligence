"""
Query Intelligence & Optimization Page
Analyze, optimize, and estimate costs for queries
"""

import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime
import sqlparse
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.snowflake_client import get_snowflake_client
from utils.formatters import (
    format_duration_ms, format_bytes, truncate_query, 
    get_risk_color, dataframe_to_excel_bytes
)
from utils.query_ui import render_interactive_query_inspector
from utils.styles import apply_global_styles, COLORS

st.set_page_config(
    page_title="Query Optimizer | Snowflake Ops",
    page_icon="🔍",
    layout="wide"
)

# Apply unified Snowflake design system
apply_global_styles()
from utils.styles import render_sidebar
render_sidebar()

# Warehouse credits per hour
WAREHOUSE_CREDITS = {
    'X-SMALL': 1, 'XSMALL': 1,
    'SMALL': 2,
    'MEDIUM': 4,
    'LARGE': 8,
    'X-LARGE': 16, 'XLARGE': 16,
    '2X-LARGE': 32, '2XLARGE': 32,
    '3X-LARGE': 64, '3XLARGE': 64,
    '4X-LARGE': 128, '4XLARGE': 128
}


@st.cache_data(ttl=300)
def get_query_history(_client, days=7, limit=500):
    """Get recent query history for analysis"""
    query = f"""
    SELECT 
        QUERY_ID,
        QUERY_TEXT,
        QUERY_TYPE,
        QUERY_HASH,
        QUERY_PARAMETERIZED_HASH,
        DATABASE_NAME,
        SCHEMA_NAME,
        USER_NAME,
        WAREHOUSE_NAME,
        WAREHOUSE_SIZE,
        EXECUTION_STATUS,
        START_TIME,
        END_TIME,
        TOTAL_ELAPSED_TIME,
        BYTES_SCANNED,
        BYTES_WRITTEN,
        ROWS_PRODUCED,
        COMPILATION_TIME,
        EXECUTION_TIME,
        QUEUED_PROVISIONING_TIME,
        QUEUED_OVERLOAD_TIME,
        PARTITIONS_SCANNED,
        PARTITIONS_TOTAL,
        PERCENTAGE_SCANNED_FROM_CACHE
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        AND QUERY_TYPE NOT IN ('DESCRIBE', 'SHOW', 'USE', 'COMMIT')
        AND TOTAL_ELAPSED_TIME > 0
    ORDER BY START_TIME DESC
    LIMIT {limit}
    """
    return _client.execute_query(query)


@st.cache_data(ttl=300)
def get_expensive_queries(_client, days=7, limit=20):
    """Get most expensive queries"""
    query = f"""
    SELECT 
        QUERY_ID,
        QUERY_TEXT,
        USER_NAME,
        WAREHOUSE_NAME,
        WAREHOUSE_SIZE,
        TOTAL_ELAPSED_TIME,
        BYTES_SCANNED,
        PARTITIONS_SCANNED,
        PARTITIONS_TOTAL,
        PERCENTAGE_SCANNED_FROM_CACHE,
        START_TIME
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        AND EXECUTION_STATUS = 'SUCCESS'
        AND QUERY_TYPE NOT IN ('DESCRIBE', 'SHOW', 'USE')
        AND BYTES_SCANNED > 0
    ORDER BY BYTES_SCANNED DESC
    LIMIT {limit}
    """
    return _client.execute_query(query)


@st.cache_data(ttl=300)
def get_slow_queries(_client, days=7, min_time_ms=60000, limit=20):
    """Get slowest queries"""
    query = f"""
    SELECT 
        QUERY_ID,
        QUERY_TEXT,
        USER_NAME,
        WAREHOUSE_NAME,
        WAREHOUSE_SIZE,
        TOTAL_ELAPSED_TIME,
        EXECUTION_TIME,
        COMPILATION_TIME,
        QUEUED_PROVISIONING_TIME,
        QUEUED_OVERLOAD_TIME,
        BYTES_SCANNED,
        START_TIME
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        AND EXECUTION_STATUS = 'SUCCESS'
        AND TOTAL_ELAPSED_TIME >= {min_time_ms}
    ORDER BY TOTAL_ELAPSED_TIME DESC
    LIMIT {limit}
    """
    return _client.execute_query(query)


@st.cache_data(ttl=300)
def get_failed_queries(_client, days=7, limit=20):
    """Get failed queries"""
    query = f"""
    SELECT 
        QUERY_ID,
        QUERY_TEXT,
        USER_NAME,
        WAREHOUSE_NAME,
        ERROR_CODE,
        ERROR_MESSAGE,
        START_TIME
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        AND EXECUTION_STATUS = 'FAIL'
    ORDER BY START_TIME DESC
    LIMIT {limit}
    """
    return _client.execute_query(query)


@st.cache_data(ttl=300)
def get_repeated_queries(_client, days=7, min_count=5):
    """Get frequently repeated queries using parameterized hash"""
    query = f"""
    SELECT 
        QUERY_PARAMETERIZED_HASH,
        COUNT(*) as execution_count,
        AVG(TOTAL_ELAPSED_TIME) as avg_time_ms,
        SUM(BYTES_SCANNED) as total_bytes_scanned,
        AVG(BYTES_SCANNED) as avg_bytes_scanned,
        AVG(PERCENTAGE_SCANNED_FROM_CACHE) as avg_cache_hit,
        MIN(QUERY_TEXT) as sample_query
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        AND EXECUTION_STATUS = 'SUCCESS'
        AND QUERY_TYPE NOT IN ('DESCRIBE', 'SHOW', 'USE')
    GROUP BY QUERY_PARAMETERIZED_HASH
    HAVING COUNT(*) >= {min_count}
    ORDER BY execution_count DESC
    LIMIT 50
    """
    return _client.execute_query(query)


@st.cache_data(ttl=300)
def get_hourly_query_blame(_client, target_date, target_hour):
    """
    Drill down: Find WHO and WHICH queries caused load during a specific hour.
    """
    query = f"""
    SELECT 
        USER_NAME,
        QUERY_TYPE,
        WAREHOUSE_NAME,
        COUNT(*) as query_count,
        SUM(TOTAL_ELAPSED_TIME)/1000 as total_exec_sec,
        SUM(BYTES_SCANNED)/POWER(1024,3) as scanned_gb,
        ANY_VALUE(QUERY_TEXT) as sample_query
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE START_TIME BETWEEN '{target_date} {target_hour}:00:00' AND '{target_date} {target_hour}:59:59'
    GROUP BY USER_NAME, QUERY_TYPE, WAREHOUSE_NAME
    ORDER BY total_exec_sec DESC
    LIMIT 20
    """
    return _client.execute_query(query)


def analyze_query(query_text: str) -> dict:
    """Analyze a query and provide optimization suggestions"""
    analysis = {
        'issues': [],
        'suggestions': [],
        'risk_score': 0,
        'complexity': 'LOW'
    }
    
    if not query_text:
        return analysis
    
    query_upper = query_text.upper()
    
    # Check for SELECT *
    if re.search(r'\bSELECT\s+\*', query_upper):
        analysis['issues'].append("Uses SELECT * which retrieves all columns")
        analysis['suggestions'].append("Specify only the columns you need to reduce data transfer")
        analysis['risk_score'] += 15
    
    # Check for missing WHERE clause
    if 'WHERE' not in query_upper and 'LIMIT' not in query_upper:
        if 'SELECT' in query_upper and 'FROM' in query_upper:
            analysis['issues'].append("No WHERE clause or LIMIT - may scan entire table")
            analysis['suggestions'].append("Add filter conditions to reduce data scanned")
            analysis['risk_score'] += 25
    
    # Check for LIKE with leading wildcard
    if re.search(r"LIKE\s+'%", query_upper):
        analysis['issues'].append("LIKE with leading wildcard prevents index usage")
        analysis['suggestions'].append("Consider using CONTAINS() or restructuring the query")
        analysis['risk_score'] += 20
    
    # Check for ORDER BY without LIMIT
    if 'ORDER BY' in query_upper and 'LIMIT' not in query_upper:
        analysis['issues'].append("ORDER BY without LIMIT on large result sets")
        analysis['suggestions'].append("Add LIMIT clause or ensure this is intentional")
        analysis['risk_score'] += 10
    
    # Check for multiple JOINs
    join_count = len(re.findall(r'\bJOIN\b', query_upper))
    if join_count > 3:
        analysis['issues'].append(f"Complex query with {join_count} JOINs")
        analysis['suggestions'].append("Consider breaking into CTEs or materializing intermediate results")
        analysis['risk_score'] += join_count * 5
    
    # Check for subqueries in WHERE
    if re.search(r'WHERE.*\(\s*SELECT', query_upper):
        analysis['issues'].append("Subquery in WHERE clause")
        analysis['suggestions'].append("Consider using JOIN or CTE for better performance")
        analysis['risk_score'] += 15
    
    # Check for DISTINCT on many columns
    if 'DISTINCT' in query_upper:
        analysis['issues'].append("Using DISTINCT which requires additional processing")
        analysis['suggestions'].append("Verify DISTINCT is necessary or filter earlier")
        analysis['risk_score'] += 10
    
    # Check for functions on indexed columns
    if re.search(r'(DATE|YEAR|MONTH|UPPER|LOWER|TRIM)\s*\([^)]+\)\s*(=|>|<|IN)', query_upper):
        analysis['issues'].append("Function applied to column in filter condition")
        analysis['suggestions'].append("Functions on filtered columns prevent pruning. Transform data instead.")
        analysis['risk_score'] += 15
    
    # Check for UNION without ALL
    if re.search(r'\bUNION\b(?!\s+ALL)', query_upper):
        analysis['issues'].append("UNION removes duplicates (use UNION ALL if duplicates are acceptable)")
        analysis['suggestions'].append("UNION ALL is faster if you don't need duplicate removal")
        analysis['risk_score'] += 5
    
    # Determine complexity
    if analysis['risk_score'] < 20:
        analysis['complexity'] = 'LOW'
    elif analysis['risk_score'] < 50:
        analysis['complexity'] = 'MEDIUM'
    else:
        analysis['complexity'] = 'HIGH'
    
    # Cap risk score at 100
    analysis['risk_score'] = min(analysis['risk_score'], 100)
    
    return analysis


def estimate_query_cost(bytes_scanned: int, warehouse_size: str, execution_time_ms: int = None) -> dict:
    """Estimate query cost based on data scanned and warehouse"""
    credits_per_hour = WAREHOUSE_CREDITS.get(warehouse_size.upper().replace('-', ''), 4)
    
    # If we have execution time, use it
    if execution_time_ms:
        hours = execution_time_ms / 3600000
        credits = credits_per_hour * hours
    else:
        # Estimate based on bytes scanned (rough: 200MB/second for small warehouse)
        gb_scanned = bytes_scanned / (1024 ** 3)
        estimated_seconds = max(gb_scanned / 0.2, 1)
        credits = (estimated_seconds / 3600) * credits_per_hour
    
    return {
        'estimated_credits': credits,
        'warehouse_cost_per_hour': credits_per_hour
    }


def main():
    st.title("🔍 Query Intelligence")
    st.markdown("*Analyze, optimize, and estimate costs for your Snowflake queries*")
    
    client = get_snowflake_client()
    
    if not client.session:
        st.error("⚠️ Could not connect to Snowflake")
        return
    
    # Tabs
    tab0, tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "🔎 ID Lookup",
        "🧪 Query Analyzer",
        "💰 Expensive Queries",
        "🐢 Slow Queries",
        "❌ Failed Queries",
        "🔄 Repeated Queries",
        "📊 Query Patterns"
    ])
    
    with tab0:
        render_query_lookup(client)

    with tab1:
        render_query_analyzer(client)
    
    with tab2:
        render_expensive_queries(client)
    
    with tab3:
        render_slow_queries(client)
    
    with tab4:
        render_failed_queries(client)
    
    with tab5:
        render_repeated_queries(client)
    
    with tab6:
        render_query_patterns(client)


def render_query_lookup(client):
    """Render tool to lookup details by Query ID"""
    st.markdown("### 🔎 Query ID Lookup")
    st.caption("Paste a Query ID to retrieve full details, cost, and metadata.")
    
    col1, col2 = st.columns([3, 1])
    with col1:
        query_id = st.text_input("Enter Query ID", placeholder="e.g. 01a2b3c4-d5e6-f7g8-h9i0-...)")
    
    if query_id:
        # Validate ID format roughly
        if len(query_id) < 10:
            st.warning("Invalid Query ID format.")
            return

        with st.spinner(f"Searching for {query_id}..."):
            # Fetch from ACCOUNT_USAGE.QUERY_HISTORY
            # We need to calculate EST_CREDITS similar to other views
            q = f"""
            SELECT 
                QUERY_ID,
                QUERY_TEXT,
                USER_NAME,
                ROLE_NAME,
                WAREHOUSE_NAME,
                WAREHOUSE_SIZE,
                EXECUTION_STATUS,
                ERROR_CODE,
                ERROR_MESSAGE,
                START_TIME,
                END_TIME,
                TOTAL_ELAPSED_TIME,
                EXECUTION_TIME,
                BYTES_SCANNED,
                PARTITIONS_SCANNED,
                PARTITIONS_TOTAL,
                CREDITS_USED_CLOUD_SERVICES,
                QUERY_TAG,
                -- Try to parse dbt info
                TRY_PARSE_JSON(QUERY_TAG):node::STRING as DBT_NODE,
                -- Estimate Credits
                (TOTAL_ELAPSED_TIME / 1000.0 / 3600.0) * 
                CASE 
                    WHEN WAREHOUSE_SIZE = 'X-Small' THEN 1
                    WHEN WAREHOUSE_SIZE = 'Small' THEN 2
                    WHEN WAREHOUSE_SIZE = 'Medium' THEN 4
                    WHEN WAREHOUSE_SIZE = 'Large' THEN 8
                    WHEN WAREHOUSE_SIZE = 'X-Large' THEN 16
                    WHEN WAREHOUSE_SIZE = '2X-Large' THEN 32
                    WHEN WAREHOUSE_SIZE = '3X-Large' THEN 64
                    WHEN WAREHOUSE_SIZE = '4X-Large' THEN 128
                    ELSE 1 
                END as EST_CREDITS
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE QUERY_ID = '{query_id}'
            """
            
            try:
                df = client.execute_query(q)
                if not df.empty:
                    st.success("Query found!")
                    # Use the standard inspector
                    # We might want to "auto-expand" or show it directly.
                    # The inspector expects a dataframe and renders a selector.
                    # Since we have only 1 row, it will default to selecting it if we set index=0?
                    # Actually `render_interactive_query_inspector` sets index=None by default.
                    # I should update `render_interactive_query_inspector` to default to 0 if only 1 row? 
                    # Or just tell user to select it.
                    # For a single ID lookup, "Select a query" is annoying.
                    # Let's manually trigger the details if only 1 row.
                    # But inspector logic is coupled. 
                    # Let's just use it as is, it's consistent.
                    render_interactive_query_inspector(df, "Query Details", key_prefix="lookup")
                    
                    # Additional dbt context if found
                    row = df.iloc[0]
                    if row['DBT_NODE']:
                        st.info(f"🧱 **dbt Model Detected**: `{row['DBT_NODE']}`")
                        
                else:
                    st.error(f"Query ID `{query_id}` not found in History (last 365 days).")
            except Exception as e:
                st.error(f"Error fetching query: {e}")


def render_query_analyzer(client):
    """Render the query analyzer tool"""
    st.markdown("### Query Analyzer")
    st.caption("*Paste a query to get optimization recommendations and cost estimates*")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        query_text = st.text_area(
            "Enter your SQL query",
            height=200,
            placeholder="SELECT * FROM my_table WHERE ..."
        )
    
    with col2:
        warehouse = st.selectbox(
            "Target Warehouse Size",
            options=['X-SMALL', 'SMALL', 'MEDIUM', 'LARGE', 'X-LARGE', '2X-LARGE', '3X-LARGE', '4X-LARGE'],
            index=2
        )
        
        estimated_bytes = st.number_input(
            "Estimated GB to scan",
            min_value=0.0,
            value=1.0,
            step=0.1,
            help="Approximate data size to be scanned"
        )
    
    if st.button("🔍 Analyze Query", type="primary"):
        if query_text.strip():
            with st.spinner("Analyzing query..."):
                # Format query
                formatted_query = sqlparse.format(
                    query_text, 
                    reindent=True, 
                    keyword_case='upper'
                )
                
                # Analyze
                analysis = analyze_query(query_text)
                
                # Estimate cost
                bytes_to_scan = int(estimated_bytes * 1024 ** 3)
                cost_estimate = estimate_query_cost(bytes_to_scan, warehouse)
                
                # Display results
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    risk_color = get_risk_color(analysis['risk_score'])
                    st.markdown(f"""
                    <div style="background: #1E2530; padding: 1rem; border-radius: 8px; border-left: 4px solid {risk_color};">
                        <h4 style="margin: 0;">Risk Score</h4>
                        <h2 style="color: {risk_color}; margin: 0.5rem 0;">{analysis['risk_score']}/100</h2>
                        <small>Complexity: {analysis['complexity']}</small>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col2:
                    st.markdown(f"""
                    <div style="background: #1E2530; padding: 1rem; border-radius: 8px; border-left: 4px solid #29B5E8;">
                        <h4 style="margin: 0;">Estimated Cost</h4>
                        <h2 style="color: #29B5E8; margin: 0.5rem 0;">{cost_estimate['estimated_credits']:.4f} credits</h2>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col3:
                    st.markdown(f"""
                    <div style="background: #1E2530; padding: 1rem; border-radius: 8px; border-left: 4px solid #00D4AA;">
                        <h4 style="margin: 0;">Warehouse</h4>
                        <h2 style="color: #00D4AA; margin: 0.5rem 0;">{warehouse}</h2>
                        <small>{cost_estimate['warehouse_cost_per_hour']} credits/hour</small>
                    </div>
                    """, unsafe_allow_html=True)
                
                st.divider()
                
                # Issues and suggestions
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown("### ⚠️ Issues Found")
                    if analysis['issues']:
                        for issue in analysis['issues']:
                            st.warning(issue)
                    else:
                        st.success("No major issues detected!")
                
                with col2:
                    st.markdown("### 💡 Suggestions")
                    if analysis['suggestions']:
                        for suggestion in analysis['suggestions']:
                            st.info(suggestion)
                    else:
                        st.success("Query looks well-optimized!")
                
                # Formatted query
                with st.expander("📝 Formatted Query", expanded=False):
                    st.code(formatted_query, language='sql')
        else:
            st.warning("Please enter a query to analyze")


def render_expensive_queries(client):
    """Render expensive queries analysis"""
    st.markdown("### Most Expensive Queries (by Data Scanned)")
    
    col1, col2 = st.columns([1, 3])
    with col1:
        days = st.selectbox("Time Range", [7, 14, 30], format_func=lambda x: f"Last {x} days", key="expensive_days")
    
    queries = get_expensive_queries(client, days)
    
    if queries.empty:
        st.info("No query data available for the selected period.")
        return
    
    # Add cost column
    queries['GB_SCANNED'] = queries['BYTES_SCANNED'] / (1024 ** 3)
    queries['PRUNING_EFFICIENCY'] = (
        (queries['PARTITIONS_TOTAL'] - queries['PARTITIONS_SCANNED']) / 
        queries['PARTITIONS_TOTAL'].replace(0, 1) * 100
    )
    
    # Chart Selection for Copying ID
    selection = alt.selection_point(fields=['QUERY_ID'])
    
    chart = alt.Chart(queries.head(10)).mark_bar(color='#FF4B4B').encode(
        x=alt.X('GB_SCANNED:Q', title='GB Scanned'),
        y=alt.Y('QUERY_ID:N', title='', sort='-x'),
        opacity=alt.condition(selection, alt.value(1), alt.value(0.6)),
        tooltip=[
            alt.Tooltip('QUERY_ID', title='Query ID'),
            alt.Tooltip('USER_NAME:N', title='User'),
            alt.Tooltip('WAREHOUSE_NAME:N', title='Warehouse'),
            alt.Tooltip('GB_SCANNED:Q', title='GB Scanned', format=',.2f'),
            alt.Tooltip('PERCENTAGE_SCANNED_FROM_CACHE:Q', title='Cache Hit %', format=',.1f')
        ]
    ).add_params(
        selection
    ).properties(height=300)
    
    # Render with selection event
    event = st.altair_chart(chart, use_container_width=True, on_select="rerun")
    
    # Handle Selection
    if event and len(event.get("selection", {}).get("param_1", [])) > 0:
        try:
             selected_points = event["selection"][list(event["selection"].keys())[0]]
             if selected_points:
                 q_id = selected_points[0]["QUERY_ID"]
                 
                 # Look up the full row
                 selected_row = queries[queries['QUERY_ID'] == q_id]
                 
                 if not selected_row.empty:
                     st.divider()
                     st.markdown(f"#### 🎯 Drill Down: Query `{q_id}`")
                     # Render the detailed view for this specific query
                     render_interactive_query_inspector(selected_row, "Selected Query Details", key_prefix=f"drill_{q_id}")
                     
        except Exception as e:
            st.warning(f"Could not load details: {e}")
    
    # Table
    display_df = queries[['USER_NAME', 'WAREHOUSE_NAME', 'WAREHOUSE_SIZE', 'GB_SCANNED', 
                          'PERCENTAGE_SCANNED_FROM_CACHE', 'PRUNING_EFFICIENCY', 'START_TIME']].copy()
    display_df.columns = ['User', 'Warehouse', 'Size', 'GB Scanned', 'Cache %', 'Pruning %', 'Time']
    
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "GB Scanned": st.column_config.NumberColumn(format="%.2f"),
            "Cache %": st.column_config.NumberColumn(format="%.1f"),
            "Pruning %": st.column_config.NumberColumn(format="%.1f"),
            "Time": st.column_config.DatetimeColumn(format="MMM DD, HH:mm")
        }
    )
    
    # Export
    col1, col2 = st.columns([3, 1])
    with col2:
        excel_data = dataframe_to_excel_bytes(queries, "Expensive_Queries")
        st.download_button(
            label="📥 Export to Excel",
            data=excel_data,
            file_name=f"expensive_queries_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    # Detailed Interactive List for Expensive Queries
    render_interactive_query_inspector(queries, "⚡ Cost Optimization Analysis", "expensive")


def render_slow_queries(client):
    """Render slow queries analysis"""
    st.markdown("### Slowest Queries")
    
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        days = st.selectbox("Time Range", [7, 14, 30], format_func=lambda x: f"Last {x} days", key="slow_days")
    with col2:
        min_time = st.selectbox("Min Execution Time", [30, 60, 120, 300], 
                                format_func=lambda x: f"{x} seconds", index=1, key="min_time")
    
    queries = get_slow_queries(client, days, min_time * 1000)
    
    if queries.empty:
        st.info("No slow queries found for the selected criteria.")
        return
    
    # Add formatted columns
    queries['TOTAL_TIME_SEC'] = queries['TOTAL_ELAPSED_TIME'] / 1000
    queries['QUEUE_TIME_SEC'] = (queries['QUEUED_PROVISIONING_TIME'] + queries['QUEUED_OVERLOAD_TIME']) / 1000
    queries['QUEUE_PERCENT'] = queries['QUEUE_TIME_SEC'] / queries['TOTAL_TIME_SEC'] * 100
    
    # Time breakdown chart
    st.markdown("#### Time Breakdown (Top 10)")
    
    top_queries = queries.head(10).copy()
    top_queries['EXEC_TIME_SEC'] = top_queries['EXECUTION_TIME'] / 1000
    top_queries['COMPILE_TIME_SEC'] = top_queries['COMPILATION_TIME'] / 1000
    
    # Create stacked bar chart data
    time_data = pd.melt(
        top_queries[['QUERY_ID', 'EXEC_TIME_SEC', 'COMPILE_TIME_SEC', 'QUEUE_TIME_SEC']],
        id_vars=['QUERY_ID'],
        var_name='Time Type',
        value_name='Seconds'
    )
    time_data['Time Type'] = time_data['Time Type'].replace({
        'EXEC_TIME_SEC': 'Execution',
        'COMPILE_TIME_SEC': 'Compilation',
        'QUEUE_TIME_SEC': 'Queue'
    })
    
    # Chart Selection
    selection = alt.selection_point(fields=['QUERY_ID'])

    chart = alt.Chart(time_data).mark_bar().encode(
        x=alt.X('Seconds:Q', title='Seconds'),
        y=alt.Y('QUERY_ID:N', title='', sort='-x'),
        color=alt.Color('Time Type:N', scale=alt.Scale(
            domain=['Execution', 'Compilation', 'Queue'],
            range=['#29B5E8', '#00D4AA', '#FFB020']
        )),
        opacity=alt.condition(selection, alt.value(1), alt.value(0.6)),
        tooltip=['QUERY_ID', 'Time Type', 'Seconds']
    ).add_params(
        selection
    ).properties(height=300)
    
    event = st.altair_chart(chart, use_container_width=True, on_select="rerun")
    
    # Handle Selection
    if event and len(event.get("selection", {}).get("param_1", [])) > 0:
        try:
             selected_points = event["selection"][list(event["selection"].keys())[0]]
             if selected_points:
                 q_id = selected_points[0]["QUERY_ID"]
                 
                 # Look up the full row
                 selected_row = queries[queries['QUERY_ID'] == q_id]
                 
                 if not selected_row.empty:
                     st.divider()
                     st.markdown(f"#### 🐢 Drill Down: Slow Query `{q_id}`")
                     render_interactive_query_inspector(selected_row, "Selected Query Details", key_prefix=f"slow_{q_id}")
                     
        except Exception as e:
            st.warning(f"Could not load details: {e}")
    
    # High queue time warning
    high_queue = queries[queries['QUEUE_PERCENT'] > 20]
    if len(high_queue) > 0:
        st.warning(f"""
        ⏳ **{len(high_queue)} queries** spent >20% of time in queue.
        
        **Suggestion**: Consider using larger warehouses or multi-cluster warehouses to reduce queue times.
        """)
    
    # Table
    display_df = queries[['USER_NAME', 'WAREHOUSE_NAME', 'WAREHOUSE_SIZE', 
                          'TOTAL_TIME_SEC', 'QUEUE_TIME_SEC', 'QUEUE_PERCENT', 'START_TIME']].copy()
    display_df.columns = ['User', 'Warehouse', 'Size', 'Total (sec)', 'Queue (sec)', 'Queue %', 'Time']
    
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Total (sec)": st.column_config.NumberColumn(format="%.1f"),
            "Queue (sec)": st.column_config.NumberColumn(format="%.1f"),
            "Queue %": st.column_config.NumberColumn(format="%.1f"),
            "Time": st.column_config.DatetimeColumn(format="MMM DD, HH:mm")
        }
    )

    # Detailed Interactive List with AI Optimization
    render_interactive_query_inspector(queries, "⚡ Detailed Analysis & Optimization", "slow")


def render_failed_queries(client):
    """Render failed queries analysis"""
    st.markdown("### Failed Queries")
    
    col1, col2 = st.columns([1, 3])
    with col1:
        days = st.selectbox("Time Range", [7, 14, 30], format_func=lambda x: f"Last {x} days", key="failed_days")
    
    queries = get_failed_queries(client, days)
    
    if queries.empty:
        st.success("✅ No failed queries in the selected period!")
        return
    
    st.error(f"❌ {len(queries)} failed queries found")
    
    # Error distribution
    error_counts = queries.groupby('ERROR_CODE').size().reset_index(name='count')
    
    # Chart Selection
    selection = alt.selection_point(fields=['ERROR_CODE'])

    chart = alt.Chart(error_counts).mark_bar(color='#FF4B4B').encode(
        x=alt.X('count:Q', title='Count'),
        y=alt.Y('ERROR_CODE:N', title='Error Code', sort='-x'),
        opacity=alt.condition(selection, alt.value(1), alt.value(0.6)),
        tooltip=['ERROR_CODE', 'count']
    ).add_params(
        selection
    ).properties(height=200)
    
    event = st.altair_chart(chart, use_container_width=True, on_select="rerun")
    
    # Handle Selection
    if event and len(event.get("selection", {}).get("param_1", [])) > 0:
        try:
             selected_points = event["selection"][list(event["selection"].keys())[0]]
             if selected_points:
                 err_code = selected_points[0]["ERROR_CODE"]
                 
                 # Filter queries by Error Code
                 filtered_queries = queries[queries['ERROR_CODE'] == err_code]
                 
                 if not filtered_queries.empty:
                     st.divider()
                     st.markdown(f"#### ❌ Drill Down: Error `{err_code}`")
                     st.caption(f"Found {len(filtered_queries)} queries with this error.")
                     # Render list
                     render_interactive_query_inspector(filtered_queries, "Queries with this Error", key_prefix=f"err_{err_code}")

        except Exception as e:
            st.warning(f"Could not load details: {e}")
    
    # Summary Table
    st.dataframe(
        queries[['QUERY_TEXT', 'USER_NAME', 'ERROR_CODE', 'ERROR_MESSAGE', 'START_TIME']],
        use_container_width=True,
        hide_index=True,
        column_config={
           "START_TIME": st.column_config.DatetimeColumn(format="MMM DD, HH:mm")
        }
    )

    # Detailed Interactive List
    render_interactive_query_inspector(queries, "🪄 AI Error Resolution", "failed")



def render_repeated_queries(client):
    """Render repeated queries analysis for caching opportunities"""
    st.markdown("### Frequently Repeated Queries")
    st.caption("*Queries with the same pattern that could benefit from caching or materialization*")
    
    col1, col2 = st.columns([1, 3])
    with col1:
        min_count = st.slider("Min Executions", 5, 100, 10)
    
    queries = get_repeated_queries(client, 7, min_count)
    
    if queries.empty:
        st.info(f"No queries executed {min_count}+ times in the last 7 days.")
        return
    
    # Add computed columns
    queries['TOTAL_GB'] = queries['TOTAL_BYTES_SCANNED'] / (1024 ** 3)
    queries['AVG_TIME_SEC'] = queries['AVG_TIME_MS'] / 1000
    
    # Optimization opportunities
    low_cache = queries[queries['AVG_CACHE_HIT'] < 50]
    if len(low_cache) > 0:
        st.warning(f"""
        💡 **{len(low_cache)} repeated query patterns** have <50% cache hit rate.
        
        **Suggestions**:
        - Standardize query text to improve cache hits
        - Consider materializing results as a table or view
        - Use result caching with consistent query patterns
        """)
    
    # Display repeated queries
    st.markdown("### 🔄 Repeated Queries Analysis")
    st.caption("Identify frequent queries that could be cached or optimized.")
    
    if not queries.empty:
        st.dataframe(
            queries, 
            use_container_width=True,
            column_config={
                "EXECUTION_COUNT": st.column_config.NumberColumn("Executions", format="%d"),
                "AVERAGE_ELAPSED_TIME": st.column_config.NumberColumn("Avg Time (ms)", format="%.0f"),
                "AVERAGE_PERCENTAGE_SCANNED_FROM_CACHE": st.column_config.NumberColumn("Cache Hit %", format="%.1f%%"),
                "QUERY_TEXT": "Query Pattern"
            }
        )
    else:
        st.info("No frequent repeated queries found.")

    st.divider()

    # QUERY BLAME TOOL
    st.markdown("### 🔥 Query Blame (Root Cause Analysis)")
    st.caption("Drill down into specific hours to see who caused load spikes.")
    
    c1, c2, c3 = st.columns([1,1,2])
    with c1:
        blame_date = st.date_input("Target Date", datetime.today())
    with c2:
        blame_hour = st.selectbox("Hour (0-23)", range(24), index=datetime.now().hour)
    with c3:
        st.write("") # Spacer
        if st.button("🔎 Analyze Spikes"):
            blame_res = get_hourly_query_blame(client, blame_date, blame_hour)
            if not blame_res.empty:
                st.markdown(f"**Load Analysis for {blame_date} @ {blame_hour}:00**")
                
                # Top Users Bar Chart
                chart = alt.Chart(blame_res).mark_bar().encode(
                    x=alt.X('TOTAL_EXEC_SEC:Q', title='Seconds Running'),
                    y=alt.Y('USER_NAME:N', sort='-x'),
                    color='USER_NAME',
                    tooltip=['USER_NAME', 'QUERY_COUNT', 'TOTAL_EXEC_SEC']
                ).properties(height=200)
                st.altair_chart(chart, use_container_width=True)
                
                st.dataframe(blame_res, use_container_width=True)
            else:
                st.info("No visible load for this hour.")
    st.markdown("#### 🧠 Caching & Materialization Analysis")
    st.info("Expand to see if these frequent queries should be cached or materialized.")

    for _, row in queries.iterrows():
        # Use SAMPLE_QUERY as the text
        query_text = row['SAMPLE_QUERY']
        query_hash = row['QUERY_PARAMETERIZED_HASH']
        
        with st.expander(f"🔁 {row['EXECUTION_COUNT']} Executions - Avg {row['AVG_TIME_SEC']:.2f}s"):
            st.code(query_text, language='sql')
            
            # Metrics
            m1, m2, m3 = st.columns(3)
            m1.metric("Total Executions", row['EXECUTION_COUNT'])
            m2.metric("Avg Cache Hit", f"{row['AVG_CACHE_HIT']:.1f}%")
            m3.metric("Avg Duration", f"{row['AVG_TIME_SEC']:.2f}s")

            # Optimization Button
            if st.button(f"🧠 Analyze Caching Strategy", key=f"opt_rep_{query_hash}"):
                with st.spinner("Analyzing caching opportunities..."):
                    try:
                        prompt = f"""
                        You are a Snowflake Performance Architect.
                        This query has been executed {row['EXECUTION_COUNT']} times recently.
                        
                        STATS:
                        - Avg Duration: {row['AVG_TIME_SEC']} s
                        - Avg Cache Hit: {row['AVG_CACHE_HIT']}%
                        - Total Data Scanned: {row['TOTAL_GB']:.2f} GB
                        
                        QUERY:
                        {query_text}
                        
                        Advise on:
                        1. Should we enable Result Caching? (Is it deterministic?)
                        2. Should we create a Materialized View? (Is it an aggregation?)
                        3. Should we verify warehouse size?
                        """
                        
                        prompt_escaped = prompt.replace("'", "''")
                        cortex_query = f"SELECT SNOWFLAKE.CORTEX.COMPLETE('llama3-70b', '{prompt_escaped}')"
                        result = client.execute_query(cortex_query, log=False)
                        
                        if not result.empty:
                            st.markdown("### 🧠 Architecture Advice")
                            st.markdown(result.iloc[0, 0])
                        else:
                            st.warning("No response from Cortex.")
                            
                    except Exception as e:
                        st.error(f"Analysis failed: {e}")


def render_query_patterns(client):
    """Render query pattern analytics"""
    st.markdown("### Query Patterns & Statistics")
    
    queries = get_query_history(client, 7, 1000)
    
    if queries.empty:
        st.info("No query history available.")
        return
    
    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Queries", f"{len(queries):,}")
    with col2:
        avg_time = queries['TOTAL_ELAPSED_TIME'].mean() / 1000
        st.metric("Avg Execution Time", f"{avg_time:.1f}s")
    with col3:
        success_rate = (queries['EXECUTION_STATUS'] == 'SUCCESS').mean() * 100
        st.metric("Success Rate", f"{success_rate:.1f}%")
    with col4:
        avg_cache = queries['PERCENTAGE_SCANNED_FROM_CACHE'].mean()
        st.metric("Avg Cache Hit", f"{avg_cache:.1f}%")
    
    st.divider()
    
    # Query type distribution
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### Query Types")
        type_counts = queries['QUERY_TYPE'].value_counts().reset_index()
        type_counts.columns = ['Query Type', 'Count']
        
        pie = alt.Chart(type_counts).mark_arc(innerRadius=50).encode(
            theta='Count:Q',
            color=alt.Color('Query Type:N', scale=alt.Scale(scheme='blues')),
            tooltip=['Query Type', 'Count']
        ).properties(height=250)
        
        st.altair_chart(pie, use_container_width=True)
    
    with col2:
        st.markdown("#### By Warehouse")
        wh_counts = queries['WAREHOUSE_NAME'].value_counts().reset_index()
        wh_counts.columns = ['Warehouse', 'Count']
        
        bar = alt.Chart(wh_counts.head(10)).mark_bar(color='#29B5E8').encode(
            x=alt.X('Count:Q'),
            y=alt.Y('Warehouse:N', sort='-x'),
            tooltip=['Warehouse', 'Count']
        ).properties(height=250)
        
        st.altair_chart(bar, use_container_width=True)
    
    # Queries over time
    st.markdown("#### Query Volume Over Time")
    
    queries['HOUR'] = pd.to_datetime(queries['START_TIME']).dt.floor('H')
    hourly = queries.groupby('HOUR').size().reset_index(name='count')
    
    line = alt.Chart(hourly).mark_line(color='#29B5E8').encode(
        x=alt.X('HOUR:T', title='Time'),
        y=alt.Y('count:Q', title='Query Count'),
        tooltip=['HOUR:T', 'count:Q']
    ).properties(height=250)
    
    st.altair_chart(line, use_container_width=True)


if __name__ == "__main__":
    main()
