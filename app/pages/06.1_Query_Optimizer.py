"""
AI-Powered Query Optimizer
Contextual query analysis with historical data, cache awareness, and cost prediction
Provides optimized alternatives and "what-if" cost comparisons
"""

import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime
import sys
import os
import sqlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.snowflake_client import get_snowflake_client
from intelligence.query_optimizer import QueryOptimizer
from utils.formatters import format_duration_ms, format_bytes, get_risk_color
from utils.query_ui import render_interactive_query_inspector
from utils.styles import apply_global_styles, COLORS

st.set_page_config(
    page_title="AI Query Optimizer | Snowflake Ops",
    page_icon="🤖",
    layout="wide"
)

# Apply unified Snowflake design system
apply_global_styles()
from utils.styles import render_sidebar
render_sidebar()

st.title("🤖 AI-Powered Query Optimizer")
st.markdown("*Contextual query analysis with historical insights and cost prediction*")


client = get_snowflake_client()

if not client.session:
    st.error("⚠️ Could not connect to Snowflake")
    st.stop()

# Initialize optimizer
optimizer = QueryOptimizer(client)

# Main tabs
tab1, tab2, tab3, tab4 = st.tabs([
    "🔍 Query Analyzer",
    "📊 Historical Comparison",
    "💰 Cost Simulator",
    "📈 Query Log"
])

with tab1:
    st.markdown("### Intelligent Query Analysis")
    st.caption("*Analyze queries with full contextual awareness: cache, history, partitions, and warehouses*")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        query_text = st.text_area(
            "Enter SQL Query",
            height=200,
            placeholder="""SELECT 
    customer_id,
    SUM(amount) as total_amount
FROM orders
WHERE order_date >= '2024-01-01'
GROUP BY customer_id
ORDER BY total_amount DESC
LIMIT 100;""",
            help="Paste your query here for comprehensive analysis"
        )
    
    with col2:
        st.markdown("#### Analysis Options")
        
        # Get warehouses
        warehouses = client.get_all_warehouses()
        if not warehouses.empty:
            warehouses.columns = [c.upper() for c in warehouses.columns]
            warehouse_names = warehouses['NAME'].tolist() if 'NAME' in warehouses.columns else []
        else:
            warehouse_names = ['COMPUTE_WH']
        
        selected_warehouse = st.selectbox(
            "Target Warehouse",
            options=warehouse_names,
            help="Warehouse where query will run"
        )
        
        # Get warehouse size
        if not warehouses.empty and 'NAME' in warehouses.columns and 'SIZE' in warehouses.columns:
            wh_row = warehouses[warehouses['NAME'] == selected_warehouse]
            if not wh_row.empty:
                warehouse_size = wh_row.iloc[0]['SIZE']
            else:
                warehouse_size = 'MEDIUM'
        else:
            warehouse_size = st.selectbox(
                "Warehouse Size",
                options=['X-SMALL', 'SMALL', 'MEDIUM', 'LARGE', 'X-LARGE', '2X-LARGE'],
                index=2
            )
        
        analyze_button = st.button("🔍 Analyze Query", type="primary", use_container_width=True)
    
    if analyze_button and query_text.strip():
        with st.spinner("Analyzing query with AI..."):
            # Comprehensive analysis
            analysis = optimizer.analyze_query_comprehensive(query_text, warehouse_size)
            
            # Store in session state
            st.session_state['last_analysis'] = analysis
            
            # Display results
            st.divider()
            
            # AI Insight Section (New)
            ai_analysis = analysis.get('ai_analysis', {})
            if ai_analysis.get('used_cortex'):
                st.markdown("### 🧠 Cortex AI Analysis")
                st.info(ai_analysis['explanation'])
            elif ai_analysis.get('message') and 'Cross-Region' in ai_analysis.get('message', ''):
                st.markdown("### 🧠 Cortex AI Analysis")
                st.warning(f"""
                **Cortex is not enabled for your region (Singapore).**
                
                To enable it, run this as ACCOUNTADMIN:
                ```sql
                ALTER ACCOUNT SET CORTEX_ENABLED_CROSS_REGION = 'AWS_APJ';
                ```
                """)
            
            # Summary cards
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                issues_count = len(analysis['issues'])
                high_severity = len([i for i in analysis['issues'] if i['severity'] == 'HIGH'])
                
                color = '#FF4B4B' if high_severity > 0 else '#FFB020' if issues_count > 0 else '#00D4AA'
                
                st.markdown(f"""
                <div style="background: #1E2530; padding: 1rem; border-radius: 8px; border-left: 4px solid {color};">
                    <h4 style="margin: 0;">Issues Found</h4>
                    <h2 style="color: {color}; margin: 0.5rem 0;">{issues_count}</h2>
                    <small>{high_severity} high severity</small>
                </div>
                """, unsafe_allow_html=True)
            
            with col2:
                st.markdown(f"""
                <div style="background: #1E2530; padding: 1rem; border-radius: 8px; border-left: 4px solid #29B5E8;">
                    <h4 style="margin: 0;">Estimated Cost</h4>
                    <h2 style="color: #29B5E8; margin: 0.5rem 0;">{cost:.4f}</h2>
                    <small>credits</small>
                </div>
                """, unsafe_allow_html=True)
            
            with col3:
                savings_pct = analysis['estimated_savings'].get('total_potential_savings_pct', 0)
                savings_credits = analysis['estimated_savings'].get('total_potential_credits', 0)
                
                st.markdown(f"""
                <div style="background: #1E2530; padding: 1rem; border-radius: 8px; border-left: 4px solid #00D4AA;">
                    <h4 style="margin: 0;">Potential Savings</h4>
                    <h2 style="color: #00D4AA; margin: 0.5rem 0;">{savings_pct:.0f}%</h2>
                    <small>{savings_credits:.4f} credits</small>
                </div>
                """, unsafe_allow_html=True)
            
            with col4:
                cached = analysis['cache_analysis'].get('cached', False)
                cache_pct = analysis['cache_analysis'].get('cache_percentage', 0)
                
                cache_color = '#00D4AA' if cached else '#A0AEC0'
                cache_status = 'CACHED' if cached else 'NOT CACHED'
                
                st.markdown(f"""
                <div style="background: #1E2530; padding: 1rem; border-radius: 8px; border-left: 4px solid {cache_color};">
                    <h4 style="margin: 0;">Cache Status</h4>
                    <h2 style="color: {cache_color}; margin: 0.5rem 0;">{cache_status}</h2>
                    <small>{cache_pct:.0f}% cache hit</small>
                </div>
                """, unsafe_allow_html=True)
            
            st.divider()
            
            # Detailed analysis sections
            col1, col2 = st.columns([1, 1])
            
            with col1:
                st.markdown("### 🚨 Issues & Recommendations")
                
                if analysis['optimizations']:
                    for rec in analysis['optimizations']:
                        priority_color = {
                            'HIGH': '#FF4B4B',
                            'MEDIUM': '#FFB020',
                            'LOW': '#29B5E8',
                            'INFO': '#00D4AA'
                        }.get(rec['priority'], '#A0AEC0')
                        

                        
                        # Add source label (Rule vs AI)
                        source = rec.get('source', 'Rule-Based')
                        title_prefix = "🤖" if source == 'AI' else "📏"
                        
                        with st.expander(f"{title_prefix} {rec['priority']} - {rec['title']}", expanded=rec['priority']=='HIGH'):
                            st.caption(f"Source: {source} | Category: {rec['category']}")
                            st.markdown(f"**Action:** {rec['action']}")
                            st.markdown(f"**Impact:** {rec['impact']}")
                            st.success(f"💰 Potential Savings: {rec['savings']}")
                else:
                    st.success("✅ No major issues found! Query looks well-optimized.")
            
            with col2:
                st.markdown("### 📊 Historical Insights")
                
                if analysis['historical_analysis'].get('has_history'):
                    hist = analysis['historical_analysis']
                    
                    st.info(f"""
                    **Historical Executions:** {hist['execution_count']}
                    
                    **Performance:**
                    - Avg Time: {hist['avg_time_ms']/1000:.2f}s
                    - Min Time: {hist['min_time_ms']/1000:.2f}s
                    - Max Time: {hist['max_time_ms']/1000:.2f}s
                    - Avg Cache Hit: {hist['avg_cache_hit']:.1f}%
                    
                    **Optimal Warehouse:** {hist['optimal_warehouse']}
                    """)
                    
                    # Best execution details
                    if 'best_execution' in hist:
                        best = hist['best_execution']
                        st.success(f"""
                        **Best Execution:**
                        - Query ID: `{best['query_id']}`
                        - Time: {best['time_ms']/1000:.2f}s
                        - Warehouse: {best['warehouse']} ({best['warehouse_size']})
                        - Cache Hit: {best['cache_hit']:.1f}%
                        """)
                else:
                    st.warning("No historical data for this query pattern. Run it once to build history!")
            
            # Alternative queries
            if analysis['alternative_queries']:
                st.divider()
                st.markdown("### 💡 Optimized Alternatives")
                
                for idx, alt in enumerate(analysis['alternative_queries']):
                    with st.expander(f"Alternative {idx+1}: {alt['name']}", expanded=idx==0):
                        st.markdown(f"**Benefit:** {alt['benefit']}")
                        st.markdown(f"**Estimated Savings:** {alt['estimated_savings']}")
                        st.markdown(f"**Use Case:** {alt['use_case']}")
                        
                        st.code(alt['query'], language='sql')
                        
                        col1, col2 = st.columns(2)
                        with col1:
                            if st.button(f"📋 Copy Query {idx+1}", key=f"copy_{idx}"):
                                st.code(alt['query'], language='sql')
                        with col2:
                            if st.button(f"🔍 Analyze Alternative {idx+1}", key=f"analyze_{idx}"):
                                st.info("Analyzing alternative...")
                                # Would trigger new analysis
            
            # Formatted query
            with st.expander("📝 Formatted Query", expanded=False):
                formatted = sqlparse.format(query_text, reindent=True, keyword_case='upper')
                st.code(formatted, language='sql')

with tab2:
    st.markdown("### Historical Query Comparison")
    st.caption("*Compare current query with historical executions to find optimization opportunities*")
    
    query_for_history = st.text_area(
        "Query to Compare",
        height=150,
        key="history_query",
        placeholder="Enter query to find similar historical executions..."
    )
    
    if st.button("🔍 Find Similar Queries") and query_for_history.strip():
        import hashlib
        query_hash = hashlib.md5(query_for_history.encode()).hexdigest()
        
        similar = client.get_similar_queries(query_hash, limit=50)
        
        if not similar.empty:
            st.success(f"Found {len(similar)} similar executions")
            
            # Summary stats
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Avg Time", f"{similar['TOTAL_ELAPSED_TIME'].mean()/1000:.2f}s")
            with col2:
                st.metric("Avg Bytes", format_bytes(similar['BYTES_SCANNED'].mean()))
            with col3:
                st.metric("Avg Cache Hit", f"{similar['PERCENTAGE_SCANNED_FROM_CACHE'].mean():.1f}%")
            with col4:
                st.metric("Avg Credits", f"{similar['CREDITS_USED_CLOUD_SERVICES'].mean():.4f}")
            
            # Time series chart
            st.markdown("#### Execution Time Over Time")
            
            similar['START_TIME'] = pd.to_datetime(similar['START_TIME'])
            similar['TIME_SEC'] = similar['TOTAL_ELAPSED_TIME'] / 1000
            
            chart = alt.Chart(similar).mark_line(point=True, color='#29B5E8').encode(
                x=alt.X('START_TIME:T', title='Time'),
                y=alt.Y('TIME_SEC:Q', title='Execution Time (seconds)'),
                tooltip=[
                    alt.Tooltip('START_TIME:T', title='Time'),
                    alt.Tooltip('TIME_SEC:Q', title='Seconds', format='.2f'),
                    alt.Tooltip('WAREHOUSE_NAME:N', title='Warehouse'),
                    alt.Tooltip('PERCENTAGE_SCANNED_FROM_CACHE:Q', title='Cache %', format='.1f')
                ]
            ).properties(height=300)
            
            st.altair_chart(chart, use_container_width=True)
            
            # Warehouse comparison
            st.markdown("#### Performance by Warehouse")
            
            wh_perf = similar.groupby('WAREHOUSE_SIZE').agg({
                'TOTAL_ELAPSED_TIME': 'mean',
                'BYTES_SCANNED': 'mean',
                'CREDITS_USED_CLOUD_SERVICES': 'mean',
                'QUERY_ID': 'count'
            }).reset_index()
            wh_perf.columns = ['Warehouse Size', 'Avg Time (ms)', 'Avg Bytes', 'Avg Credits', 'Count']
            
            st.dataframe(wh_perf, use_container_width=True, hide_index=True)
            
            # Detailed history
            with st.expander("📋 Detailed Execution History"):
                st.dataframe(similar, use_container_width=True, hide_index=True)
        else:
            st.warning("No similar queries found in history. This query hasn't been run before.")

with tab4:
    st.markdown("### 📈 Recent Optimization History")
    
    # Get history from session state or simple query history if we had a persistent store
    # For now, let's show the user's recent queries from standard history as a proxy
    # or if we had a dedicated 'OPTIMIZATION_LOG' table.
    
    # Let's show standard query history for now, filtered by user
    query = f"""
    SELECT 
        QUERY_ID, 
        QUERY_TEXT, 
        USER_NAME, 
        WAREHOUSE_NAME, 
        EXECUTION_STATUS,
        TOTAL_ELAPSED_TIME, 
        BYTES_SCANNED 
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY 
    WHERE USER_NAME = CURRENT_USER()
    ORDER BY START_TIME DESC 
    LIMIT 50
    """
    try:
        history_df = client.execute_query(query)
        render_interactive_query_inspector(history_df, "Your Recent Queries", "opt_history")
        
    except Exception as e:
        st.error(f"Could not load history: {e}")

with tab3:
    st.markdown("### Cost Simulator")
    st.caption("*Compare costs across different warehouses and configurations*")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        sim_query = st.text_area(
            "Query to Simulate",
            height=150,
            key="sim_query",
            placeholder="Enter query for cost simulation..."
        )
    
    with col2:
        st.markdown("#### Simulation Options")
        
        warehouse_sizes = ['X-SMALL', 'SMALL', 'MEDIUM', 'LARGE', 'X-LARGE', '2X-LARGE', '3X-LARGE', '4X-LARGE']
        selected_sizes = st.multiselect(
            "Warehouse Sizes to Compare",
            options=warehouse_sizes,
            default=['SMALL', 'MEDIUM', 'LARGE']
        )
    
    if st.button("💰 Run Cost Simulation") and sim_query.strip() and selected_sizes:
        with st.spinner("Simulating costs across warehouses..."):
            results = []
            
            for size in selected_sizes:
                cost_est = client.estimate_query_cost(sim_query, size)
                results.append({
                    'Warehouse Size': size,
                    'Credits/Hour': cost_est['credits_per_hour'],
                    'Estimated Credits': cost_est['estimated_credits'],
                    'Estimated Time (s)': cost_est['estimated_time_ms'] / 1000,
                    'Based on History': cost_est['based_on_history']
                })
            
            results_df = pd.DataFrame(results)
            
            # Find optimal
            optimal_idx = results_df['Estimated Credits'].idxmin()
            optimal_size = results_df.loc[optimal_idx, 'Warehouse Size']
            optimal_cost = results_df.loc[optimal_idx, 'Estimated Credits']
            
            st.success(f"💡 **Optimal Warehouse:** {optimal_size} ({optimal_cost:.4f} credits)")
            
            # Cost comparison chart
            chart = alt.Chart(results_df).mark_bar(color='#29B5E8').encode(
                x=alt.X('Warehouse Size:N', title='Warehouse Size', sort=warehouse_sizes),
                y=alt.Y('Estimated Credits:Q', title='Estimated Credits'),
                color=alt.condition(
                    alt.datum['Warehouse Size'] == optimal_size,
                    alt.value('#00D4AA'),
                    alt.value('#29B5E8')
                ),
                tooltip=[
                    'Warehouse Size',
                    alt.Tooltip('Estimated Credits:Q', format='.4f'),
                    alt.Tooltip('Estimated Time (s):Q', format='.2f')
                ]
            ).properties(height=300, title='Credit Comparison Across Warehouses')
            
            st.altair_chart(chart, use_container_width=True)
            
            # Detailed table
            st.dataframe(results_df, use_container_width=True, hide_index=True)

with tab4:
    st.markdown("### Query Execution Log")
    st.caption("*Track all queries executed through this app for analysis*")
    
    query_log = client.get_query_log()
    
    if query_log:
        log_df = pd.DataFrame(query_log)
        
        # Summary metrics
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Queries", len(log_df))
        with col2:
            success_rate = (log_df['success'].sum() / len(log_df) * 100) if len(log_df) > 0 else 0
            st.metric("Success Rate", f"{success_rate:.1f}%")
        with col3:
            avg_time = log_df['execution_time_ms'].mean()
            st.metric("Avg Time", f"{avg_time:.0f}ms")
        with col4:
            total_rows = log_df['rows_returned'].sum()
            st.metric("Total Rows", f"{total_rows:,}")
        
        # Display log
        st.dataframe(log_df, use_container_width=True, hide_index=True)
        
        # Export
        excel_data = pd.DataFrame(log_df).to_csv(index=False)
        st.download_button(
            "📥 Export Query Log",
            data=excel_data,
            file_name=f"query_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv"
        )
    else:
        st.info("No queries logged yet. Execute some queries to see them here!")
