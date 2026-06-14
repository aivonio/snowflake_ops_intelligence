"""
Warehouse Intelligence Page
Real-time monitoring, load analysis, and optimization recommendations
"""

import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime
import sys
import os

try:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
except (NameError, TypeError):
    pass

from utils.snowflake_client import get_snowflake_client
from utils.formatters import format_duration_ms, format_credits, dataframe_to_excel_bytes, get_status_color
from utils.styles import apply_global_styles, COLORS

st.set_page_config(
    page_title="Warehouses | Snowflake Ops",
    page_icon="🏭",
    layout="wide"
)

# Apply unified Snowflake design system
apply_global_styles()
from utils.styles import render_sidebar
render_sidebar()

# Warehouse size credits per hour
WAREHOUSE_CREDITS = {
    'X-SMALL': 1, 'XSMALL': 1,
    'SMALL': 2,
    'MEDIUM': 4,
    'LARGE': 8,
    'X-LARGE': 16, 'XLARGE': 16,
    '2X-LARGE': 32, '2XLARGE': 32,
    '3X-LARGE': 64, '3XLARGE': 64,
    '4X-LARGE': 128, '4XLARGE': 128,
    '5X-LARGE': 256, '5XLARGE': 256,
    '6X-LARGE': 512, '6XLARGE': 512
}


@st.cache_data(ttl=60)
def get_resource_monitors(_client):
    """Get list of resource monitors"""
    try:
        return _client.execute_query("SHOW RESOURCE MONITORS")
    except:
        return pd.DataFrame()

def apply_warehouse_settings(client, warehouse_name, auto_suspend_mins, auto_resume):
    """Apply auto-suspend and auto-resume settings."""
    try:
        suspend_sec = int(auto_suspend_mins * 60)
        query = f"ALTER WAREHOUSE {warehouse_name} SET AUTO_SUSPEND = {suspend_sec} AUTO_RESUME = {str(auto_resume).upper()}"
        client.execute_query(query)
        return True, "Settings applied successfully!"
    except Exception as e:
        return False, str(e)

@st.cache_data(ttl=60)
def get_warehouse_status(_client):
    """Get current warehouse status using SHOW WAREHOUSES"""
    try:
        # Use SHOW WAREHOUSES for real-time status
        df = _client.execute_query("SHOW WAREHOUSES")
        
        if df.empty:
            return pd.DataFrame()
            
        # Standardize column names to uppercase
        df.columns = [c.upper() for c in df.columns]
        
        # Rename NAME to WAREHOUSE_NAME if present
        if 'NAME' in df.columns and 'WAREHOUSE_NAME' not in df.columns:
            df = df.rename(columns={'NAME': 'WAREHOUSE_NAME'})
        elif 'name' in df.columns and 'WAREHOUSE_NAME' not in df.columns:
             df = df.rename(columns={'name': 'WAREHOUSE_NAME'})
             
        # Ensure required columns exist
        required_cols = [
            'WAREHOUSE_NAME', 'STATE', 'TYPE', 'SIZE', 
            'MIN_CLUSTER_COUNT', 'MAX_CLUSTER_COUNT', 
            'RUNNING', 'QUEUED', 'AUTO_SUSPEND', 
            'AUTO_RESUME', 'RESOURCE_MONITOR'
        ]
        
        # Filter only existing columns from required list to avoid KeyError
        # But also fill gaps to ensure downstream code works
        final_df = pd.DataFrame()
        
        if 'WAREHOUSE_NAME' not in df.columns:
            # Last ditch: use first column if it looks like a name? No, too risky.
            # Only return empty to avoid crash
            st.error("Could not find WAREHOUSE_NAME column. Columns found: " + ", ".join(df.columns))
            return pd.DataFrame()

        # Copy existing columns
        for col in required_cols:
            if col in df.columns:
                final_df[col] = df[col]
            else:
                # Fill default
                if col in ['RUNNING', 'QUEUED', 'AUTO_SUSPEND', 'MIN_CLUSTER_COUNT', 'MAX_CLUSTER_COUNT']:
                    final_df[col] = 0
                else:
                    final_df[col] = 'UNKNOWN'
                
        return final_df.sort_values('WAREHOUSE_NAME')
        
    except Exception as e:
        # Fallback to empty dataframe if permission denied or other error
        st.error(f"Error reading warehouse status: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=300)
def get_warehouse_usage(_client, days=30):
    """Get warehouse usage metrics"""
    query = f"""
    SELECT 
        WAREHOUSE_NAME,
        DATE(START_TIME) as usage_date,
        SUM(CREDITS_USED) as credits_used,
        SUM(CREDITS_USED_COMPUTE) as compute_credits,
        SUM(CREDITS_USED_CLOUD_SERVICES) as cloud_credits
    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
    WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
    GROUP BY WAREHOUSE_NAME, DATE(START_TIME)
    ORDER BY usage_date DESC, credits_used DESC
    """
    return _client.execute_query(query)


@st.cache_data(ttl=300)
def get_warehouse_query_stats(_client, days=7):
    """Get query statistics per warehouse"""
    query = f"""
    SELECT 
        WAREHOUSE_NAME,
        COUNT(*) as query_count,
        AVG(TOTAL_ELAPSED_TIME) as avg_elapsed_ms,
        AVG(EXECUTION_TIME) as avg_execution_ms,
        AVG(QUEUED_PROVISIONING_TIME + QUEUED_OVERLOAD_TIME) as avg_queue_ms,
        SUM(BYTES_SCANNED) / POWER(1024, 4) as total_tb_scanned,
        AVG(PERCENTAGE_SCANNED_FROM_CACHE) as avg_cache_hit,
        COUNT(CASE WHEN EXECUTION_STATUS = 'FAIL' THEN 1 END) as failed_queries
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        AND WAREHOUSE_NAME IS NOT NULL
    GROUP BY WAREHOUSE_NAME
    ORDER BY query_count DESC
    """
    return _client.execute_query(query)


@st.cache_data(ttl=300)
def get_queue_analysis(_client, days=7):
    """Get queue time analysis by warehouse and hour"""
    query = f"""
    SELECT 
        WAREHOUSE_NAME,
        HOUR(START_TIME) as hour_of_day,
        COUNT(*) as query_count,
        AVG(QUEUED_PROVISIONING_TIME + QUEUED_OVERLOAD_TIME) as avg_queue_ms,
        MAX(QUEUED_PROVISIONING_TIME + QUEUED_OVERLOAD_TIME) as max_queue_ms
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        AND WAREHOUSE_NAME IS NOT NULL
        AND (QUEUED_PROVISIONING_TIME > 0 OR QUEUED_OVERLOAD_TIME > 0)
    GROUP BY WAREHOUSE_NAME, HOUR(START_TIME)
    ORDER BY avg_queue_ms DESC
    """
    return _client.execute_query(query)


@st.cache_data(ttl=300)
def get_auto_suspend_analysis(_client, days=7):
    """Analyze auto-suspend efficiency"""
    query = f"""
    SELECT 
        WAREHOUSE_NAME,
        COUNT(DISTINCT DATE(START_TIME)) as active_days,
        SUM(CREDITS_USED) as total_credits,
        MIN(START_TIME) as first_usage,
        MAX(END_TIME) as last_usage
    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
    WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
    GROUP BY WAREHOUSE_NAME
    """
    return _client.execute_query(query)


@st.cache_data(ttl=300)
def get_zombie_warehouses(_client, days=30):
    """
    Identify 'Zombie' warehouses:
    Warehouses that have CREDITS_USED but ZERO recorded queries in the same period.
    """
    query = f"""
    WITH credit_usage AS (
        SELECT 
            WAREHOUSE_NAME,
            SUM(CREDITS_USED) as total_credits,
            MAX(END_TIME) as last_active
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        GROUP BY WAREHOUSE_NAME
        HAVING total_credits > 1 -- Ignore minimal usage
    ),
    query_stats AS (
        SELECT 
            WAREHOUSE_NAME,
            COUNT(*) as query_count
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        GROUP BY WAREHOUSE_NAME
    )
    SELECT 
        c.WAREHOUSE_NAME,
        c.total_credits,
        ZEROIFNULL(q.query_count) as queries_run,
        c.last_active
    FROM credit_usage c
    LEFT JOIN query_stats q ON c.WAREHOUSE_NAME = q.WAREHOUSE_NAME
    WHERE ZEROIFNULL(q.query_count) = 0 OR (c.total_credits > 10 AND q.query_count < 10) -- Zombies or very low efficiency
    ORDER BY c.total_credits DESC
    """
    return _client.execute_query(query)


def calculate_sizing_recommendation(stats_row):
    """Calculate warehouse sizing recommendation based on usage stats"""
    recommendations = []
    
    avg_queue_ms = stats_row.get('AVG_QUEUE_MS', 0) or 0
    avg_elapsed_ms = stats_row.get('AVG_ELAPSED_MS', 0) or 0
    cache_hit = stats_row.get('AVG_CACHE_HIT', 0) or 0
    
    # High queue time suggests need for larger warehouse or multi-cluster
    if avg_queue_ms > 5000:  # More than 5 seconds of queue time
        recommendations.append({
            'type': 'SIZE_UP',
            'reason': f'High queue times ({avg_queue_ms/1000:.1f}s avg)',
            'suggestion': 'Consider a larger warehouse size or enabling multi-cluster'
        })
    
    # Very fast queries might benefit from smaller warehouse
    if avg_elapsed_ms < 1000 and avg_queue_ms < 500:
        recommendations.append({
            'type': 'SIZE_DOWN',
            'reason': f'Quick queries ({avg_elapsed_ms/1000:.1f}s avg) with low queue',
            'suggestion': 'Consider a smaller warehouse to save costs'
        })
    
    # Low cache hit rate
    if cache_hit < 20:
        recommendations.append({
            'type': 'CACHE',
            'reason': f'Low cache hit rate ({cache_hit:.1f}%)',
            'suggestion': 'Standardize query patterns to improve result cache usage'
        })
    
    if not recommendations:
        recommendations.append({
            'type': 'OK',
            'reason': 'Warehouse appears well-configured',
            'suggestion': 'No immediate changes recommended'
        })
    
    return recommendations


def main():
    st.title("🏭 Warehouse Intelligence")
    st.markdown("*Monitor performance, optimize sizing, and reduce costs*")
    
    client = get_snowflake_client()
    
    if not client.session:
        st.error("⚠️ Could not connect to Snowflake")
        return
    
    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 Status",
        "📈 Usage Trends",
        "⚡ Performance",
        "💡 Recommendations"
    ])
    
    with tab1:
        render_warehouse_status(client)
    
    with tab2:
        render_usage_trends(client)
    
    with tab3:
        render_performance_analysis(client)
    
    with tab4:
        render_recommendations(client)


def render_warehouse_status(client):
    """Render current warehouse status"""
    st.markdown("### Current Warehouse Status")
    
    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("🔄 Refresh", key="refresh_status"):
            st.cache_data.clear()
            st.rerun()
    
    warehouses = get_warehouse_status(client)
    
    if warehouses.empty:
        st.info("No warehouses found.")
        return
    
    # Summary metrics
    total_warehouses = len(warehouses)
    active_warehouses = len(warehouses[warehouses['STATE'] == 'STARTED'])
    running_queries = int(warehouses['RUNNING'].sum()) if 'RUNNING' in warehouses.columns else 0
    queued_queries = int(warehouses['QUEUED'].sum()) if 'QUEUED' in warehouses.columns else 0
    
    # Render Metrics (Select.dev Style)
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("🏭 Total Warehouses", total_warehouses)
    with col2:
        st.metric("🟢 Active State", active_warehouses, f"{active_warehouses/total_warehouses:.0%} utilization")
    with col3:
        st.metric("🏃 Running Queries", int(running_queries), help="Currently executing across all warehouses")
    with col4:
        st.metric("zzz Queued Queries", int(queued_queries), 
                  delta="Warning" if queued_queries > 0 else "Optimal",
                  delta_color="inverse" if queued_queries > 0 else "normal",
                  help="Waiting for resources (Potential bottleneck)")
    
    st.divider()
    
    # 2 Charts: State Distribution & Size Distribution
    c1, c2 = st.columns(2)
    
    with c1:
        st.markdown("#### Warehouse Status")
        status_chart = alt.Chart(warehouses).mark_arc(innerRadius=60).encode(
            theta=alt.Theta('count():Q'),
            color=alt.Color('STATE:N', scale=alt.Scale(domain=['STARTED', 'SUSPENDED', 'UNKNOWN'], range=['#00D4AA', '#586A84', '#FF6C37'])),
            tooltip=['STATE', 'count():Q']
        ).properties(height=350)
        st.altair_chart(status_chart, use_container_width=True)
        
    with c2:
        st.markdown("#### Size Distribution")
        size_chart = alt.Chart(warehouses).mark_bar(color='#29B5E8').encode(
            x=alt.X('count():Q', title='Count'),
            y=alt.Y('SIZE:N', sort=['X-SMALL', 'SMALL', 'MEDIUM', 'LARGE', 'X-LARGE', '2X-LARGE', '3X-LARGE', '4X-LARGE']),
            tooltip=['SIZE', 'count():Q']
        ).properties(height=350)
        st.altair_chart(size_chart, use_container_width=True)
    
    # Warehouse cards
    for _, wh in warehouses.iterrows():
        # Handle null STATE values
        state = wh.get('STATE', 'UNKNOWN')
        if state is None or pd.isna(state):
            state = 'UNKNOWN'
        
        status_color = get_status_color(state)
        credits_per_hour = WAREHOUSE_CREDITS.get(str(wh['SIZE']).upper().replace('-', ''), 0)
        
        col1, col2, col3, col4, col5 = st.columns([2, 1, 1, 1, 1])
        
        with col1:
            st.markdown(f"""
            <div style="padding: 0.5rem;">
                <strong style="font-size: 1.1rem;">{wh['WAREHOUSE_NAME']}</strong>
                <span style="background: {status_color}33; color: {status_color}; padding: 2px 8px; border-radius: 12px; margin-left: 8px; font-size: 0.8rem;">{state}</span>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"**Size:** {wh['SIZE']}")
        
        with col3:
            st.markdown(f"**Running:** {int(wh['RUNNING'])}")
        
        with col4:
            st.markdown(f"**Queued:** {int(wh['QUEUED'])}")
        
        with col5:
            st.markdown(f"**{credits_per_hour}** credits/hr")
        
        st.divider()
    
    # Detailed table
    with st.expander("📋 Detailed View"):
        display_df = warehouses.copy()
        display_df['CREDITS_PER_HOUR'] = display_df['SIZE'].apply(
            lambda x: WAREHOUSE_CREDITS.get(str(x).upper().replace('-', ''), 0)
        )
        
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True
        )


def render_usage_trends(client):
    """Render warehouse usage trends"""
    st.markdown("### Usage Trends")
    
    col1, col2 = st.columns([1, 3])
    with col1:
        days = st.selectbox("Time Range", [7, 14, 30, 60], 
                           format_func=lambda x: f"Last {x} days",
                           key="usage_days")
    
    usage = get_warehouse_usage(client, days)
    
    if usage.empty:
        st.info("No usage data available.")
        return
    
    # Get unique warehouses
    warehouses = usage['WAREHOUSE_NAME'].unique().tolist()
    
    selected_warehouses = st.multiselect(
        "Select Warehouses",
        options=warehouses,
        default=warehouses[:5] if len(warehouses) > 5 else warehouses
    )
    
    if not selected_warehouses:
        st.warning("Please select at least one warehouse.")
        return
    
    filtered_usage = usage[usage['WAREHOUSE_NAME'].isin(selected_warehouses)]
    
    # Line chart
    chart = alt.Chart(filtered_usage).mark_line(point=True).encode(
        x=alt.X('USAGE_DATE:T', title='Date'),
        y=alt.Y('CREDITS_USED:Q', title='Credits Used'),
        color=alt.Color('WAREHOUSE_NAME:N', 
                       legend=alt.Legend(title='Warehouse'),
                       scale=alt.Scale(scheme='category10')),
        tooltip=[
            alt.Tooltip('WAREHOUSE_NAME:N', title='Warehouse'),
            alt.Tooltip('USAGE_DATE:T', title='Date'),
            alt.Tooltip('CREDITS_USED:Q', title='Credits', format=',.2f')
        ]
    ).properties(height=400)
    
    st.altair_chart(chart, use_container_width=True)
    
    # Summary by warehouse
    st.markdown("### Total Credits by Warehouse")
    
    summary = usage.groupby('WAREHOUSE_NAME').agg({
        'CREDITS_USED': 'sum',
        'COMPUTE_CREDITS': 'sum',
        'CLOUD_CREDITS': 'sum',
        'USAGE_DATE': 'nunique'
    }).reset_index()
    summary.columns = ['Warehouse', 'Total Credits', 'Compute', 'Cloud Services', 'Active Days']
    summary = summary.sort_values('Total Credits', ascending=False)
    
    st.dataframe(
        summary,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Total Credits": st.column_config.NumberColumn(format="%.2f"),
            "Compute": st.column_config.NumberColumn(format="%.2f"),
            "Cloud Services": st.column_config.NumberColumn(format="%.4f")
        }
    )
    
    # Export
    col1, col2 = st.columns([3, 1])
    with col2:
        excel_data = dataframe_to_excel_bytes(usage, "Warehouse_Usage")
        st.download_button(
            label="📥 Export to Excel",
            data=excel_data,
            file_name=f"warehouse_usage_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )


def render_performance_analysis(client):
    """Render warehouse performance analysis"""
    st.markdown("### Performance Analysis")
    
    query_stats = get_warehouse_query_stats(client, 7)
    queue_analysis = get_queue_analysis(client, 7)
    
    if query_stats.empty:
        st.info("No performance data available.")
        return
    
    # Add computed columns
    query_stats['AVG_ELAPSED_SEC'] = query_stats['AVG_ELAPSED_MS'] / 1000
    query_stats['AVG_QUEUE_SEC'] = query_stats['AVG_QUEUE_MS'] / 1000
    
    # Performance summary
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### Query Count by Warehouse")
        
        bar = alt.Chart(query_stats.head(10)).mark_bar(color='#29B5E8').encode(
            x=alt.X('QUERY_COUNT:Q', title='Query Count'),
            y=alt.Y('WAREHOUSE_NAME:N', title='', sort='-x'),
            tooltip=['WAREHOUSE_NAME', 'QUERY_COUNT']
        ).properties(height=300)
        
        st.altair_chart(bar, use_container_width=True)
    
    with col2:
        st.markdown("#### Average Execution Time")
        
        bar = alt.Chart(query_stats.head(10)).mark_bar(color='#00D4AA').encode(
            x=alt.X('AVG_ELAPSED_SEC:Q', title='Avg Time (seconds)'),
            y=alt.Y('WAREHOUSE_NAME:N', title='', sort='-x'),
            tooltip=['WAREHOUSE_NAME', alt.Tooltip('AVG_ELAPSED_SEC:Q', format=',.1f')]
        ).properties(height=300)
        
        st.altair_chart(bar, use_container_width=True)
    
    # Queue time analysis
    if not queue_analysis.empty:
        st.markdown("#### Queue Time Heatmap")
        st.caption("*High queue times indicate overloaded warehouses*")

        # Cast to numeric to handle decimal.Decimal from Snowflake
        queue_analysis['AVG_QUEUE_MS'] = pd.to_numeric(queue_analysis['AVG_QUEUE_MS'], errors='coerce')

        # Limit to top warehouses by queue time
        top_wh = queue_analysis.groupby('WAREHOUSE_NAME')['AVG_QUEUE_MS'].mean().nlargest(5).index.tolist()
        filtered_queue = queue_analysis[queue_analysis['WAREHOUSE_NAME'].isin(top_wh)]
        
        if not filtered_queue.empty:
            filtered_queue['AVG_QUEUE_SEC'] = pd.to_numeric(filtered_queue['AVG_QUEUE_MS'], errors='coerce') / 1000
            
            heatmap = alt.Chart(filtered_queue).mark_rect().encode(
                x=alt.X('HOUR_OF_DAY:O', title='Hour of Day'),
                y=alt.Y('WAREHOUSE_NAME:N', title=''),
                color=alt.Color('AVG_QUEUE_SEC:Q', 
                               scale=alt.Scale(scheme='reds'),
                               legend=alt.Legend(title='Queue (sec)')),
                tooltip=[
                    alt.Tooltip('WAREHOUSE_NAME:N', title='Warehouse'),
                    alt.Tooltip('HOUR_OF_DAY:O', title='Hour'),
                    alt.Tooltip('AVG_QUEUE_SEC:Q', title='Avg Queue (sec)', format=',.1f'),
                    alt.Tooltip('QUERY_COUNT:Q', title='Queries')
                ]
            ).properties(height=200)
            
            st.altair_chart(heatmap, use_container_width=True)
    
    # Detailed stats table
    st.markdown("#### Detailed Statistics")
    
    display_df = query_stats[['WAREHOUSE_NAME', 'QUERY_COUNT', 'AVG_ELAPSED_SEC', 
                              'AVG_QUEUE_SEC', 'TOTAL_TB_SCANNED', 'AVG_CACHE_HIT', 'FAILED_QUERIES']].copy()
    display_df.columns = ['Warehouse', 'Queries', 'Avg Time (sec)', 'Avg Queue (sec)', 
                          'TB Scanned', 'Cache %', 'Failed']
    
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Avg Time (sec)": st.column_config.NumberColumn(format="%.2f"),
            "Avg Queue (sec)": st.column_config.NumberColumn(format="%.2f"),
            "TB Scanned": st.column_config.NumberColumn(format="%.3f"),
            "Cache %": st.column_config.NumberColumn(format="%.1f")
        }
    )


def render_recommendations(client):
    """Render warehouse optimization recommendations with Cortex AI"""
    st.markdown("### 🧠 AI-Powered Optimization")
    st.caption("*Optimization recommendations based on Load, Spillage, and Cost patterns from the last 7 days.*")
    
    try:
        # Fetch comprehensive stats including SPILLAGE
        wh_stats = client.get_warehouse_utilization_stats(days=7)
        
        if wh_stats.empty:
            st.info("No warehouse data available for analysis.")
            return

        # Filter for relevant warehouses
        active_wh = wh_stats[
            (wh_stats['TOTAL_CREDITS'] > 0) | 
            (wh_stats['MAX_RUNNING'] > 0)
        ].sort_values('TOTAL_CREDITS', ascending=False)
        
        if active_wh.empty:
            st.info("No active usage found in the last 7 days.")
            return

        for _, row in active_wh.iterrows():
            wh_name = row['WAREHOUSE_NAME']
            size = row['SIZE']
            spill_gb = row.get('TOTAL_SPILL_BYTES', 0) / (1024**3)
            
            # Status Flags
            has_spill = spill_gb > 1
            has_queue = row['MAX_QUEUED'] > 0
            is_expensive = row['TOTAL_CREDITS'] > 50
            
            # Icon logic
            icon = "✅"
            if has_spill: icon = "⚠️" 
            elif has_queue: icon = "🐌"
            
            with st.expander(f"{icon} {wh_name} ({size}) - {row['TOTAL_CREDITS']:.1f} Credits"):
                
                # Metric Dashboard
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Max Concurrency", f"{row['MAX_RUNNING']:.1f}")
                c2.metric("Queue Depth", f"{row['MAX_QUEUED']:.1f}", 
                         delta="Bottleneck" if has_queue else None, delta_color="inverse")
                c3.metric("Data Spilled", f"{spill_gb:.2f} GB",
                         delta="Memory Pressure" if has_spill else None, delta_color="inverse")
                c4.metric("Auto-Suspend", f"{int(row['AUTO_SUSPEND'])}s")
                
                # --- INSTANT RECOMMENDATIONS CALCULATION ---
                instant_recs = []
                if spill_gb > 1:
                     instant_recs.append(f"⚠️ **Spillage Alert**: {spill_gb:.1f}GB spilling. Consider moving to **{client.get_next_size_up(size)}**.")
                if row['MAX_QUEUED'] > 0:
                     instant_recs.append(f"🐌 **Queue Alert**: Queries are waiting. Consider **Multi-cluster** (Min > 1).")
                if row['TOTAL_CREDITS'] > 1 and row['MAX_RUNNING'] == 0:
                     instant_recs.append(f"🧟 **Zombie Alert**: Credits burned but no queries. **Suspend immediately**.")

                # --- NEW: Instant Recommendations ---
                from intelligence.recommendation_engine import RecommendationEngine
                rec_engine = RecommendationEngine(client)
                
                # AUTOMATION TAB
                tabs = st.tabs(["💡 Recommendations", "⚙️ Automation & Config", "💰 Automated Savings"])
                
                with tabs[0]:
                    # Using Instant Recommendations
                    if instant_recs:
                         st.markdown("#### ⚡ Instant Optimizations")
                         for rec in instant_recs:
                            st.warning(rec)
                    else:
                        st.success("✅ Configuration looks optimal based on recent usage.")


                with tabs[1]:
                    st.markdown("#### Warehouse Automation")
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        new_suspend = st.number_input(f"Auto-Suspend (mins) ##{wh_name}", value=int(row.get('AUTO_SUSPEND', 600)/60), min_value=1, max_value=120)
                    with c2:
                        new_resume = st.checkbox(f"Auto-Resume ##{wh_name}", value=bool(row.get('AUTO_RESUME', True)))
                    with c3:
                        st.markdown("<br>", unsafe_allow_html=True)
                        if st.button(f"Update Config ##{wh_name}", type="primary"):
                            success, msg = apply_warehouse_settings(client, wh_name, new_suspend, new_resume)
                            if success: st.toast(msg, icon="✅")
                            else: st.error(msg)
                    
                    st.divider()
                    st.markdown("#### Resource Monitors")
                    # Simplified Monitor check
                    if row.get('RESOURCE_MONITOR') and row['RESOURCE_MONITOR'] != 'null':
                        st.info(f"Protected by Monitor: **{row['RESOURCE_MONITOR']}**")
                    else:
                        st.caption("No resource monitor attached.")
                        # Future: Add create monitor UI here

                with tabs[2]:
                    st.markdown("#### 💰 Automated Savings")
                    st.info("Continuous automated right-sizing identifies idle and oversized warehouses and corrects them to yield immediate savings with zero effort.")
                    st.markdown("<div style='padding-top: 5px;'>", unsafe_allow_html=True)
                    st.page_link("pages/07.0_Settings.py", label="⚙️ Enable Automated Savings (AutoPilot)", icon="🤖", use_container_width=True)
                    st.markdown("</div>", unsafe_allow_html=True)
                
                # --- AI Analysis Button (Existing) ---
                st.markdown("#### 🧠 Deep Analysis")
                if st.button(f"Analyze {wh_name} with Cortex AI", key=f"ai_opt_{wh_name}"):
                    with st.spinner(f"Analyzing {wh_name} with Cortex AI..."):
                        try:
                            prompt = f"""
                            You are a Senior Snowflake Performance Architect.
                            Analyze this warehouse configuration against its actual usage metrics.
                            
                            WAREHOUSE: {wh_name}
                            
                            CONFIGURATION:
                            - Size: {size}
                            - Auto-Suspend: {int(row['AUTO_SUSPEND'])} seconds
                            - Min/Max Clusters: {int(row['MIN_CLUSTER_COUNT'])} / {int(row['MAX_CLUSTER_COUNT'])}
                            - Scaling Policy: {row['SCALING_POLICY']}
                            
                            PERFORMANCE METRICS (7 Days):
                            - Max Concurrent Queries: {row['MAX_RUNNING']:.1f}
                            - Avg Concurrent Queries: {row['AVG_RUNNING']:.2f}
                            - Max Queue Depth: {row['MAX_QUEUED']:.1f} (Queries waiting for resources)
                            - Total Data Spilled to Disk: {spill_gb:.2f} GB (Indicates memory pressure)
                            - Total Cost: {row['TOTAL_CREDITS']:.2f} Credits
                            
                            Required Output:
                            1. **Diagnosis**: Is it Oversized? Undersized? Leaking memory (spill)? or Well-tuned?
                            2. **Actionable Recommendations**:
                               - Resize Guidance (Up/Down)
                               - Multi-cluster Tuning (Increase max_clusters?)
                               - Auto-suspend Tuning
                            3. **Impact**: Estimated cost/performance impact of changes.
                            """
                            
                            prompt_escaped = prompt.replace("'", "''")
                            cortex_query = f"SELECT SNOWFLAKE.CORTEX.COMPLETE('llama3-70b', '{prompt_escaped}')"
                            result = client.execute_query(cortex_query, log=False)
                            
                            if not result.empty:
                                st.markdown(result.iloc[0, 0])
                            
                        except Exception as e:
                            st.error(f"AI Analysis Failed: {e}")
                            
    except Exception as e:
        st.error(f"Optimization module error: {e}")


if __name__ == "__main__":
    main()
