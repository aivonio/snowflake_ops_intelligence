"""
Benchmark & Savings Page
Tracks query optimization effectiveness - compares predicted vs actual costs
and shows savings from optimizations
"""

import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime, timedelta
import hashlib
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.snowflake_client import get_snowflake_client
from utils.formatters import format_credits, format_duration_ms, dataframe_to_excel_bytes
from utils.styles import apply_global_styles, COLORS

st.set_page_config(
    page_title="Benchmark & Savings | Snowflake Ops",
    page_icon="📊",
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


@st.cache_data(ttl=60)
def get_benchmark_data(_client):
    """Get benchmark comparison data"""
    path = _client.get_schema_path("APP_ANALYTICS")
    query = f"""
    SELECT 
        BENCHMARK_ID,
        QUERY_TEXT,
        RUN_TYPE,
        PREDICTED_COST_CREDITS,
        ACTUAL_COST_CREDITS,
        PREDICTED_TIME_MS,
        ACTUAL_TIME_MS,
        BYTES_SCANNED,
        WAREHOUSE_USED,
        WAREHOUSE_SIZE,
        OPTIMIZATION_APPLIED,
        COST_SAVINGS_CREDITS,
        TIME_SAVINGS_MS,
        RUN_TIMESTAMP
    FROM {path}.QUERY_BENCHMARK
    ORDER BY RUN_TIMESTAMP DESC
    LIMIT 100
    """
    return _client.execute_query(query)


@st.cache_data(ttl=300)
def get_recent_queries(_client, hours=24):
    """Get recent queries for benchmarking"""
    query = f"""
    SELECT 
        QUERY_ID,
        QUERY_TEXT,
        QUERY_HASH,
        USER_NAME,
        WAREHOUSE_NAME,
        WAREHOUSE_SIZE,
        TOTAL_ELAPSED_TIME,
        EXECUTION_TIME,
        BYTES_SCANNED,
        CREDITS_USED_CLOUD_SERVICES,
        START_TIME
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE START_TIME >= DATEADD(hour, -{hours}, CURRENT_TIMESTAMP())
        AND QUERY_TYPE IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'MERGE', 'CREATE_TABLE_AS_SELECT')
        AND TOTAL_ELAPSED_TIME > 1000
        AND BYTES_SCANNED > 0
        AND WAREHOUSE_NAME IS NOT NULL
    ORDER BY BYTES_SCANNED DESC
    LIMIT 50
    """
    return _client.execute_query(query)


@st.cache_data(ttl=300)
def get_savings_summary(_client):
    """Get total savings summary"""
    path = _client.get_schema_path("APP_ANALYTICS")
    query = f"""
    SELECT 
        COUNT(*) as total_benchmarks,
        SUM(CASE WHEN RUN_TYPE = 'OPTIMIZED' THEN 1 ELSE 0 END) as optimized_runs,
        SUM(CASE WHEN RUN_TYPE = 'UNOPTIMIZED' THEN 1 ELSE 0 END) as unoptimized_runs,
        SUM(COST_SAVINGS_CREDITS) as total_cost_savings,
        SUM(TIME_SAVINGS_MS) as total_time_savings_ms,
        AVG(CASE WHEN PREDICTED_COST_CREDITS > 0 THEN 
            ABS(ACTUAL_COST_CREDITS - PREDICTED_COST_CREDITS) / PREDICTED_COST_CREDITS * 100 
            ELSE 0 END) as avg_prediction_accuracy
    FROM {path}.QUERY_BENCHMARK
    """
    return _client.execute_query(query)


@st.cache_data(ttl=300)
def get_burn_rate(_client, days=7):
    """Calculate credit burn rate"""
    query = f"""
    SELECT 
        DATE(START_TIME) as usage_date,
        SUM(CREDITS_USED) as daily_credits,
        COUNT(DISTINCT WAREHOUSE_NAME) as warehouses_used,
        SUM(SUM(CREDITS_USED)) OVER (ORDER BY DATE(START_TIME)) as cumulative_credits
    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
    WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
    GROUP BY DATE(START_TIME)
    ORDER BY usage_date
    """
    return _client.execute_query(query)


def estimate_query_cost(bytes_scanned: int, warehouse_size: str, execution_time_ms: int = None) -> dict:
    """Estimate query cost"""
    credits_per_hour = WAREHOUSE_CREDITS.get(str(warehouse_size).upper().replace('-', ''), 4)
    
    if execution_time_ms:
        hours = execution_time_ms / 3600000
        credits = credits_per_hour * hours
    else:
        gb_scanned = bytes_scanned / (1024 ** 3)
        estimated_seconds = max(gb_scanned / 0.2, 1)
        credits = (estimated_seconds / 3600) * credits_per_hour
    
    return {
        'estimated_credits': credits,
        'credits_per_hour': credits_per_hour
    }


def record_benchmark(_client, query_text: str, run_type: str, predicted_cost: float, 
                     actual_cost: float, predicted_time: float, actual_time: float,
                     bytes_scanned: int, warehouse: str, warehouse_size: str,
                     optimization_applied: str = None):
    """Record a benchmark result"""
    query_hash = hashlib.md5(query_text.encode()).hexdigest()
    
    cost_savings = max(0, predicted_cost - actual_cost) if run_type == 'OPTIMIZED' else 0
    time_savings = max(0, predicted_time - actual_time) if run_type == 'OPTIMIZED' else 0
    
    safe_query = query_text[:5000].replace("'", "''")
    safe_opt = (optimization_applied or '').replace("'", "''")
    
    path = _client.get_schema_path("APP_ANALYTICS")
    insert_query = f"""
    INSERT INTO {path}.QUERY_BENCHMARK (
        QUERY_TEXT, QUERY_HASH, RUN_TYPE, PREDICTED_COST_CREDITS, ACTUAL_COST_CREDITS,
        PREDICTED_TIME_MS, ACTUAL_TIME_MS, BYTES_SCANNED, WAREHOUSE_USED, WAREHOUSE_SIZE,
        OPTIMIZATION_APPLIED, COST_SAVINGS_CREDITS, TIME_SAVINGS_MS
    ) VALUES (
        '{safe_query}', '{query_hash}', '{run_type}', {predicted_cost}, {actual_cost},
        {predicted_time}, {actual_time}, {bytes_scanned}, '{warehouse}', '{warehouse_size}',
        '{safe_opt}', {cost_savings}, {time_savings}
    )
    """
    
    return _client.execute_write(insert_query)


def main():
    st.title("📊 Benchmark & Savings")
    st.markdown("*Track optimization effectiveness - compare predicted vs actual costs*")
    
    client = get_snowflake_client()
    
    if not client.session:
        st.error("⚠️ Could not connect to Snowflake")
        return
    
    # Tabs
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📈 Savings Overview",
        "🔥 Burn Rate",
        "⚖️ Size Comparator",
        "🧪 Run Benchmark",
        "📋 Benchmark History"
    ])
    
    with tab1:
        render_savings_overview(client)
    
    with tab2:
        render_burn_rate(client)

    with tab3:
        render_warehouse_comparator(client)
    
    with tab4:
        render_run_benchmark(client)
    
    with tab5:
        render_benchmark_history(client)


def render_warehouse_comparator(client):
    """Render warehouse size comparison tool"""
    st.markdown("### ⚖️ Warehouse Size Comparator")
    st.caption("*Estimate performance and cost across different warehouse sizes*")
    
    col1, col2 = st.columns([2, 1])
    with col1:
        query_text = st.text_area("SQL Query for Comparison", height=150, placeholder="SELECT ...")
        
    with col2:
        gb_estimate = st.number_input("Estimated Scan Size (GB)", value=1.0, step=0.5)
        st.info("Uses heuristics to estimate run time reduction (linear scaling assumption).")
        
    if st.button("Compare Sizes", type="primary"):
        if not query_text:
            st.warning("Enter a query first.")
            return
            
        st.markdown("#### Estimated Results")
        
        # Comparison Logic
        sizes = ['X-SMALL', 'SMALL', 'MEDIUM', 'LARGE', 'X-LARGE', '2X-LARGE']
        results = []
        
        # Baseline (X-SMALL)
        base_credits = 1
        base_time_sec = max(gb_estimate / 0.05, 10) # 50MB/s per node assumption roughly
        
        for i, size in enumerate(sizes):
            factor = 2 ** i
            credits_per_hour = base_credits * factor
            
            # Assume 80% scaling efficiency
            est_time_sec = base_time_sec / (factor ** 0.8)
            
            cost = (est_time_sec / 3600) * credits_per_hour
            
            results.append({
                'Size': size,
                'Credits/Hr': credits_per_hour,
                'Est. Time (sec)': est_time_sec,
                'Est. Cost (Credits)': cost,
                'Speedup': (base_time_sec / est_time_sec)
            })
            
        df = pd.DataFrame(results)
        
        # Chart
        c1, c2 = st.columns(2)
        with c1:
            # Time vs Cost Chart
            base = alt.Chart(df).encode(x=alt.X('Size', sort=sizes))
            
            line_time = base.mark_line(color='#29B5E8').encode(y='Est. Time (sec)')
            line_cost = base.mark_line(color='#FFB020').encode(y='Est. Cost (Credits)')
            
            st.altair_chart(
                alt.layer(line_time, line_cost).resolve_scale(y='independent').properties(title="Time (Blue, left) vs Cost (Orange, right)"),
                use_container_width=True
            )
            
        with c2:
            st.dataframe(
                df,
                column_config={
                    "Est. Time (sec)": st.column_config.NumberColumn(format="%.1f s"),
                    "Est. Cost (Credits)": st.column_config.NumberColumn(format="%.6f"),
                    "Speedup": st.column_config.NumberColumn(format="%.1fx")
                },
                use_container_width=True
            )


def render_savings_overview(client):
    """Render savings overview dashboard"""
    st.markdown("### Optimization Savings Overview")
    
    savings = get_savings_summary(client)
    benchmark_data = get_benchmark_data(client)
    
    if savings.empty or savings.iloc[0]['TOTAL_BENCHMARKS'] == 0:
        st.info("""
        📊 **No benchmark data yet!**
        
        Run some benchmarks in the "Run Benchmark" tab to see:
        - Predicted vs Actual cost comparison
        - Total savings from optimizations
        - Prediction accuracy metrics
        """)
        
        # Show what the dashboard will look like with sample data
        st.markdown("### What You'll See:")
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Benchmarks", "0", help="Number of queries benchmarked")
        with col2:
            st.metric("Credits Saved", "0.00", help="Total credits saved through optimization")
        with col3:
            st.metric("Time Saved", "0s", help="Total execution time saved")
        with col4:
            st.metric("Prediction Accuracy", "N/A", help="How accurate our cost predictions are")
        
        return
    
    summary = savings.iloc[0]
    
    # Key metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            "Total Benchmarks",
            f"{int(summary['TOTAL_BENCHMARKS']):,}",
            help="Number of queries benchmarked"
        )
    
    with col2:
        cost_saved = summary['TOTAL_COST_SAVINGS'] or 0
        st.metric(
            "Credits Saved",
            f"{cost_saved:.4f}",
            help="Total credits saved through optimization"
        )
    
    with col3:
        time_saved = (summary['TOTAL_TIME_SAVINGS_MS'] or 0) / 1000
        st.metric(
            "Time Saved",
            f"{time_saved:.1f}s",
            help="Total execution time saved"
        )
    
    with col4:
        accuracy = summary['AVG_PREDICTION_ACCURACY'] or 0
        st.metric(
            "Prediction Accuracy",
            f"{100 - accuracy:.1f}%",
            help="How accurate our cost predictions are"
        )
    
    st.divider()
    
    # Comparison chart
    if not benchmark_data.empty:
        st.markdown("### Predicted vs Actual Cost")
        st.caption("Comparison of the estimated cost (before running) vs the actual credits consumed.")
        
        chart_data = benchmark_data[['BENCHMARK_ID', 'PREDICTED_COST_CREDITS', 'ACTUAL_COST_CREDITS', 'RUN_TYPE']].copy()
        chart_data = chart_data.melt(
            id_vars=['BENCHMARK_ID', 'RUN_TYPE'],
            value_vars=['PREDICTED_COST_CREDITS', 'ACTUAL_COST_CREDITS'],
            var_name='Type',
            value_name='Credits'
        )
        chart_data['Type'] = chart_data['Type'].replace({
            'PREDICTED_COST_CREDITS': 'Predicted',
            'ACTUAL_COST_CREDITS': 'Actual'
        })
        
        # Enhanced Grouped Bar Chart
        base = alt.Chart(chart_data).encode(
            x=alt.X('BENCHMARK_ID:O', title='Benchmark', axis=alt.Axis(labels=False)),
            xOffset='Type:N'
        )
        
        bar = base.mark_bar().encode(
            y=alt.Y('Credits:Q', title='Credits'),
            color=alt.Color('Type:N', scale=alt.Scale(
                domain=['Predicted', 'Actual'],
                range=[COLORS['warning'], COLORS['primary']]
            ), legend=alt.Legend(title="Cost Type")),
            tooltip=['BENCHMARK_ID', 'Type', 'Credits', 'RUN_TYPE']
        )
        
        st.altair_chart(bar, use_container_width=True)
        
        # Run type breakdown
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("#### By Run Type")
            type_counts = benchmark_data['RUN_TYPE'].value_counts().reset_index()
            type_counts.columns = ['Run Type', 'Count']
            
            pie = alt.Chart(type_counts).mark_arc(innerRadius=60, stroke="#1a1c24", strokeWidth=2).encode(
                theta='Count:Q',
                color=alt.Color('Run Type:N', scale=alt.Scale(
                    domain=['OPTIMIZED', 'UNOPTIMIZED'],
                    range=[COLORS['success'], COLORS['error']]
                )),
                tooltip=['Run Type', 'Count'],
                order=alt.Order("Count", sort="descending")
            ).properties(height=250)
            
            # Add text in middle
            text = alt.Chart(pd.DataFrame({'text': [f"{len(benchmark_data)}"]})).mark_text(
                align='center', 
                baseline='middle', 
                fontSize=20, 
                fontWeight='bold',
                color='white'
            ).encode(text='text')
            
            st.altair_chart(pie + text, use_container_width=True)
        
        with col2:
            st.markdown("#### Savings Distribution")
            if benchmark_data['COST_SAVINGS_CREDITS'].sum() > 0:
                savings_data = benchmark_data[benchmark_data['COST_SAVINGS_CREDITS'] > 0]
                
                bar = alt.Chart(savings_data).mark_bar(color=COLORS['success']).encode(
                    x=alt.X('BENCHMARK_ID:O', title='Benchmark', axis=alt.Axis(labels=False)),
                    y=alt.Y('COST_SAVINGS_CREDITS:Q', title='Credits Saved'),
                    tooltip=['BENCHMARK_ID', 'COST_SAVINGS_CREDITS', 'TIME_SAVINGS_MS']
                ).properties(height=250)
                
                st.altair_chart(bar, use_container_width=True)
            else:
                st.info("No savings recorded yet")


def render_burn_rate(client):
    """Render credit burn rate analysis"""
    st.markdown("### Credit Burn Rate")
    st.caption("*Track your credit consumption pace and project when you'll run out*")
    
    col1, col2 = st.columns([1, 3])
    with col1:
        days = st.selectbox("Time Range", [7, 14, 30], format_func=lambda x: f"Last {x} days", key="burn_days")
        budget = st.number_input("Total Budget (credits)", value=400.0, step=10.0,
                                 help="Your total credit budget")
    
    burn_data = get_burn_rate(client, days)
    
    if burn_data.empty:
        st.info("No usage data available yet. Run some queries to see burn rate.")
        return
    
    # Calculate burn metrics
    total_used = burn_data['CUMULATIVE_CREDITS'].iloc[-1] if not burn_data.empty else 0
    remaining = budget - total_used
    avg_daily = burn_data['DAILY_CREDITS'].mean()
    
    # Estimate days until budget exhausted
    days_remaining = int(remaining / avg_daily) if avg_daily > 0 else float('inf')
    
    # Metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            "Total Used",
            f"{total_used:.2f}",
            help="Credits used in selected period"
        )
    
    with col2:
        st.metric(
            "Remaining",
            f"{remaining:.2f}",
            delta=f"{(remaining/budget)*100:.0f}% left" if remaining > 0 else "Budget exceeded!",
            delta_color="normal" if remaining > budget * 0.2 else "inverse"
        )
    
    with col3:
        st.metric(
            "Avg Daily Burn",
            f"{avg_daily:.3f}",
            help="Average credits used per day"
        )
    
    with col4:
        if days_remaining < float('inf'):
            st.metric(
                "Days Until Empty",
                f"{days_remaining}",
                delta="Plan ahead!" if days_remaining < 30 else None,
                delta_color="inverse" if days_remaining < 30 else "normal"
            )
        else:
            st.metric("Days Until Empty", "∞", help="Very low burn rate!")
    
    st.divider()
    
    # Burn rate chart
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### Daily Credit Usage")
        
        bar = alt.Chart(burn_data).mark_bar(color='#29B5E8').encode(
            x=alt.X('USAGE_DATE:T', title='Date'),
            y=alt.Y('DAILY_CREDITS:Q', title='Credits'),
            tooltip=[
                alt.Tooltip('USAGE_DATE:T', title='Date'),
                alt.Tooltip('DAILY_CREDITS:Q', title='Credits', format=',.4f'),
                alt.Tooltip('WAREHOUSES_USED:Q', title='Warehouses')
            ]
        ).properties(height=250)
        
        # Add average line
        avg_line = alt.Chart(burn_data).mark_rule(color='#FF4B4B', strokeDash=[5,5]).encode(
            y='mean(DAILY_CREDITS):Q'
        )
        
        st.altair_chart(bar + avg_line, use_container_width=True)
    
    with col2:
        st.markdown("#### Cumulative Usage")
        
        # Create projection data
        if avg_daily > 0:
            last_date = pd.to_datetime(burn_data['USAGE_DATE'].iloc[-1])
            projection_days = min(days_remaining, 30)
            
            projection = pd.DataFrame({
                'USAGE_DATE': pd.date_range(last_date + timedelta(days=1), periods=projection_days),
                'CUMULATIVE_CREDITS': [total_used + avg_daily * (i+1) for i in range(projection_days)],
                'TYPE': 'Projected'
            })
            
            actual_data = burn_data[['USAGE_DATE', 'CUMULATIVE_CREDITS']].copy()
            actual_data['TYPE'] = 'Actual'
            
            combined = pd.concat([actual_data, projection], ignore_index=True)
        else:
            combined = burn_data[['USAGE_DATE', 'CUMULATIVE_CREDITS']].copy()
            combined['TYPE'] = 'Actual'
        
        line = alt.Chart(combined).mark_line().encode(
            x=alt.X('USAGE_DATE:T', title='Date'),
            y=alt.Y('CUMULATIVE_CREDITS:Q', title='Cumulative Credits'),
            color=alt.Color('TYPE:N', scale=alt.Scale(
                domain=['Actual', 'Projected'],
                range=['#29B5E8', '#FFB020']
            )),
            strokeDash=alt.condition(
                alt.datum.TYPE == 'Projected',
                alt.value([5, 5]),
                alt.value([0])
            )
        ).properties(height=250)
        
        # Add budget line
        budget_line = alt.Chart(pd.DataFrame({'y': [budget]})).mark_rule(
            color='#FF4B4B',
            strokeDash=[10, 5]
        ).encode(y='y:Q')
        
        st.altair_chart(line + budget_line, use_container_width=True)
    
    # Recommendations
    st.markdown("### 💡 Burn Rate Recommendations")
    
    if avg_daily > budget / 30:
        st.warning(f"""
        ⚠️ **High Burn Rate Detected**
        
        At current pace ({avg_daily:.3f} credits/day), you'll exhaust your budget in ~{days_remaining} days.
        
        **Recommendations:**
        - Review expensive queries in the Query Optimizer
        - Enable auto-suspend on all warehouses (60-120 seconds)
        - Use smaller warehouse sizes for simple queries
        - Schedule batch jobs during off-peak hours
        """)
    elif days_remaining < 60:
        st.info(f"""
        💡 **Budget Monitoring**
        
        You have approximately {days_remaining} days of credits remaining at current usage.
        
        Consider optimizing high-cost queries to extend your budget.
        """)
    else:
        st.success(f"""
        ✅ **Healthy Burn Rate**
        
        At current pace, your credits will last approximately {days_remaining} days.
        """)


def render_run_benchmark(client):
    """Render benchmark runner"""
    st.markdown("### Run Benchmark Test")
    st.caption("*Execute queries and track predicted vs actual costs*")
    
    # Get recent expensive queries
    recent_queries = get_recent_queries(client, 24)
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("#### Enter Query to Benchmark")
        
        query_text = st.text_area(
            "SQL Query",
            height=150,
            placeholder="SELECT * FROM your_table WHERE condition..."
        )
    
    with col2:
        warehouse_size = st.selectbox(
            "Warehouse Size",
            ['X-SMALL', 'SMALL', 'MEDIUM', 'LARGE', 'X-LARGE'],
            index=2
        )
        
        run_type = st.radio(
            "Run Type",
            ['UNOPTIMIZED', 'OPTIMIZED'],
            help="Mark whether this is an unoptimized baseline or an optimized version"
        )
        
        optimization_applied = st.text_input(
            "Optimization Applied",
            placeholder="e.g., Added WHERE clause, smaller warehouse",
            disabled=run_type == 'UNOPTIMIZED'
        )
    
    if st.button("🚀 Run Benchmark", type="primary"):
        if query_text.strip():
            with st.spinner("Running benchmark..."):
                # Estimate cost
                estimated_bytes = 1024 * 1024 * 1024  # 1GB default estimate
                cost_estimate = estimate_query_cost(estimated_bytes, warehouse_size)
                predicted_credits = cost_estimate['estimated_credits']
                
                # Record as pending
                st.info(f"""
                **Predicted Cost:** {predicted_credits:.6f} credits
                
                Query would be executed here to measure actual cost.
                For demo purposes, recording with estimated values.
                """)
                
                # Simulate actual results (in real app, execute query and measure)
                actual_credits = predicted_credits * (0.8 if run_type == 'OPTIMIZED' else 1.1)
                actual_time = 5000  # 5 seconds simulated
                
                # Record benchmark
                success = record_benchmark(
                    client,
                    query_text,
                    run_type,
                    predicted_credits,
                    actual_credits,
                    10000,  # predicted time
                    actual_time,
                    estimated_bytes,
                    'COMPUTE_WH',
                    warehouse_size,
                    optimization_applied if run_type == 'OPTIMIZED' else None
                )
                
                if success:
                    st.success("✅ Benchmark recorded!")
                    st.cache_data.clear()
                else:
                    st.error("Failed to record benchmark")
        else:
            st.warning("Please enter a query")
    
    st.divider()
    
    # Show recent expensive queries for benchmarking
    st.markdown("#### Recent Expensive Queries (Last 24h)")
    st.caption("*Click to use as benchmark*")
    
    if not recent_queries.empty:
        display_df = recent_queries[['USER_NAME', 'WAREHOUSE_NAME', 'WAREHOUSE_SIZE', 
                                     'TOTAL_ELAPSED_TIME', 'BYTES_SCANNED', 'START_TIME']].copy()
        display_df['TIME_SEC'] = display_df['TOTAL_ELAPSED_TIME'] / 1000
        display_df['GB_SCANNED'] = display_df['BYTES_SCANNED'] / (1024**3)
        display_df = display_df[['USER_NAME', 'WAREHOUSE_NAME', 'TIME_SEC', 'GB_SCANNED', 'START_TIME']]
        display_df.columns = ['User', 'Warehouse', 'Time (sec)', 'GB Scanned', 'Time']
        
        st.dataframe(
            display_df.head(10),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Time (sec)": st.column_config.NumberColumn(format="%.1f"),
                "GB Scanned": st.column_config.NumberColumn(format="%.3f"),
                "Time": st.column_config.DatetimeColumn(format="HH:mm")
            }
        )
    else:
        st.info("No queries in the last 24 hours to benchmark")


def render_benchmark_history(client):
    """Render benchmark history"""
    st.markdown("### Benchmark History")
    
    benchmark_data = get_benchmark_data(client)
    
    if benchmark_data.empty:
        st.info("No benchmarks recorded yet. Use the 'Run Benchmark' tab to start tracking.")
        return
    
    # Summary
    st.markdown("#### Summary")
    
    optimized = benchmark_data[benchmark_data['RUN_TYPE'] == 'OPTIMIZED']
    unoptimized = benchmark_data[benchmark_data['RUN_TYPE'] == 'UNOPTIMIZED']
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Optimized Runs", len(optimized))
    with col2:
        st.metric("Unoptimized Runs", len(unoptimized))
    with col3:
        total_savings = optimized['COST_SAVINGS_CREDITS'].sum() if not optimized.empty else 0
        st.metric("Total Savings", f"{total_savings:.4f} credits")
    
    st.divider()
    
    # Full history table
    st.markdown("#### All Benchmarks")
    
    display_df = benchmark_data[[
        'RUN_TYPE', 'PREDICTED_COST_CREDITS', 'ACTUAL_COST_CREDITS',
        'COST_SAVINGS_CREDITS', 'WAREHOUSE_SIZE', 'RUN_TIMESTAMP'
    ]].copy()
    display_df.columns = ['Type', 'Predicted', 'Actual', 'Savings', 'Warehouse', 'Time']
    
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Type": st.column_config.TextColumn(),
            "Predicted": st.column_config.NumberColumn(format="%.6f"),
            "Actual": st.column_config.NumberColumn(format="%.6f"),
            "Savings": st.column_config.NumberColumn(format="%.6f"),
            "Time": st.column_config.DatetimeColumn(format="MMM DD, HH:mm")
        }
    )
    
    # Export
    col1, col2 = st.columns([3, 1])
    with col2:
        excel_data = dataframe_to_excel_bytes(benchmark_data, "Benchmarks")
        st.download_button(
            label="📥 Export to Excel",
            data=excel_data,
            file_name=f"benchmarks_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )


if __name__ == "__main__":
    main()
