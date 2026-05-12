"""
AI Intelligence Hub
Combines Cortex AI, forecasting, and real-time monitoring
The future of Snowflake optimization
"""

import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.snowflake_client import get_snowflake_client
from intelligence.cortex_ai import CortexAI
from intelligence.forecasting import CostForecaster
from intelligence.realtime_monitor import RealtimeMonitor
from utils.formatters import format_credits, format_duration_ms, get_risk_color
from utils.styles import apply_global_styles, COLORS

st.set_page_config(
    page_title="AI Intelligence | Snowflake Ops",
    page_icon="🤖",
    layout="wide"
)

# Apply unified Snowflake design system
apply_global_styles()
from utils.styles import render_sidebar
render_sidebar()

st.title("🤖 AI Intelligence Hub")
st.markdown("*Advanced AI-powered insights, forecasting, and monitoring*")


client = get_snowflake_client()

if not client.session:
    st.error("⚠️ Could not connect to Snowflake")
    st.stop()

# Initialize AI modules
cortex = CortexAI(client)
forecaster = CostForecaster(client)
monitor = RealtimeMonitor(client)

# Check Cortex availability
availability_error = None
if not cortex.is_cortex_available():
    if getattr(cortex, '_needs_cross_region', False):
        availability_error = "REGION"
        st.info("""
        ✨ **Unlock Enterprise AI Intelligence**
        
        Cortex AI is available on your Enterprise account, but needs to be enabled for your region.
        
        **Run this as ACCOUNTADMIN to unlock:**
        ```sql
        ALTER ACCOUNT SET CORTEX_ENABLED_CROSS_REGION = 'ANY_REGION';
        ```
        """)
    elif getattr(cortex, '_edition_restricted', False):
        availability_error = "EDITION"
        st.error("""
        🛑 **Snowflake Cortex AI not available on current edition**
        
        Cortex AI features require **Snowflake Premier Edition** or higher. 
        """)
    else:
        availability_error = "GENERAL"
        st.caption("🤖 Cortex AI service not detected.")

# Final availability flag
cortex_available = (availability_error is None)

# Main tabs
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🤖 AI Assistant",
    "🔮 Forecasting",
    "❄️ Cortex Optimizer",
    "🔍 Anomaly Detection",
    "🎯 System Health"
])

# --- TAB 1: INTERACTIVE AI ASSISTANT ---
with tab1:
    st.markdown("### 🤖 Cortex Data Analyst")
    st.caption("Ask questions about your data, costs, or performance. I can write SQL, run it, and visualize the results.")
    
    # Initialize Chat History (Isolated from full AI Analyst page)
    if "ai_hub_messages" not in st.session_state:
        st.session_state.ai_hub_messages = [{"role": "assistant", "content": "Hello! I'm your Snowflake AI Analyst. Ask me about your credit usage, expensive queries, or warehouse performance."}]

    # Display Chat History
    for msg in st.session_state.ai_hub_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            # If message contains SQL, show run options (re-render state)
            if msg.get("sql"):
                st.code(msg["sql"], language="sql")
                
                # Execution Result Container
                if msg.get("executed"):
                    with st.expander("⚡ Execution Result", expanded=True):
                        if msg.get("error"):
                            st.error(f"Execution Failed: {msg['error']}")
                        else:
                            # Show Data
                            df = pd.DataFrame(msg["data"])
                            st.dataframe(df, use_container_width=True)
                            
                            # Auto-Visualization Logic
                            if not df.empty and len(df) > 0:
                                numeric_cols = df.select_dtypes(include=['number']).columns
                                if len(numeric_cols) > 0:
                                    st.caption("📊 Auto-Visualization")
                                    # Heuristic: If date column exists -> Line Chart, else Bar Chart
                                    date_cols = [c for c in df.columns if 'DATE' in c.upper() or 'TIME' in c.upper()]
                                    if date_cols:
                                        st.line_chart(df, x=date_cols[0], y=numeric_cols[0])
                                    else:
                                        st.bar_chart(df, y=numeric_cols[0])

    # Chat Input
    if prompt := st.chat_input("Ask a question (e.g., 'What were my top 5 expensive queries last week?')"):
        # Add User Message
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Generate Assistant Response
        with st.chat_message("assistant"):
            with st.spinner("Thinking (Cortex)..."):
                try:
                    # Cortex Call
                    response = cortex.generate_sql_explanation(prompt)
                    sql_query = cortex.extract_sql(response) # Assuming cortex has this helper or we parse it
                    
                    # If helper missing, simple regex fallback
                    if not sql_query and "```sql" in response:
                        sql_query = response.split("```sql")[1].split("```")[0].strip()
                    
                    st.markdown(response.replace(sql_query if sql_query else "", "") if sql_query else response)
                    
                    if sql_query:
                        st.code(sql_query, language="sql")
                        
                        # Add Action Button (Requires Rerun to update state)
                        # We simulate "instant" run for this demo flow or add a button for next interaction
                        # Better UX: Add to history as unexecuted, let user click run
                        
                        msg_data = {
                            "role": "assistant", 
                            "content": response.replace(f"```sql\n{sql_query}\n```", ""), 
                            "sql": sql_query,
                            "executed": False
                        }
                        st.session_state.messages.append(msg_data)
                        
                        # Direct Execution (User requested "Fire query")
                        if st.button("▶ Run Query & Visualize", key=f"run_{len(st.session_state.messages)}"):
                             with st.spinner("Executing query..."):
                                df = client.execute_query(sql_query)
                                msg_data["executed"] = True
                                msg_data["data"] = df.to_dict('records') # Store as records for session state capability
                                st.rerun()
                                
                    else:
                        st.session_state.messages.append({"role": "assistant", "content": response})
                        
                except Exception as e:
                    st.error(f"AI Error: {e}")

# --- TAB 2: FORECASTING (Legacy Tab 1) ---
with tab2:
    st.markdown("### 🔮 Cost Forecasting")
    st.caption("*Predict future costs and resource needs*")
    
    col1, col2 = st.columns([1, 3])
    
    with col1:
        forecast_days = st.slider("Forecast Period (days)", 7, 90, 30)
        history_days = st.slider("Historical Data (days)", 14, 90, 30)
        
        if st.button("🔮 Generate Forecast", type="primary"):
            st.session_state['run_forecast'] = True
    
    if st.session_state.get('run_forecast', False):
        with st.spinner("Generating forecast..."):
            # Credit forecast
            credit_forecast = forecaster.forecast_daily_credits(history_days, forecast_days)
            
            if credit_forecast['success']:
                st.markdown("#### Daily Credit Forecast")
                
                forecast_df = credit_forecast['forecast']
                stats = credit_forecast['statistics']
                
                # Summary metrics
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Avg Daily Credits", f"{stats['avg_daily_credits']:.2f}")
                with col2:
                    trend_icon = "📈" if stats['trend'] == 'increasing' else "📉" if stats['trend'] == 'decreasing' else "➡️"
                    st.metric("Trend", f"{trend_icon} {stats['trend'].title()}")
                with col3:
                    st.metric("Trend %", f"{stats['trend_percentage']:.1f}%")
                with col4:
                    st.metric(f"Total ({forecast_days}d)", f"{stats['total_forecasted']:.1f}")
                
                # Chart
                chart = alt.Chart(forecast_df).mark_line(point=True).encode(
                    x=alt.X('usage_date:T', title='Date'),
                    y=alt.Y('forecasted_credits:Q', title='Credits'),
                    color=alt.Color('type:N', scale=alt.Scale(
                        domain=['historical', 'forecast'],
                        range=['#29B5E8', '#FFB020']
                    )),
                    strokeDash=alt.condition(
                        alt.datum.type == 'forecast',
                        alt.value([5, 5]),
                        alt.value([0])
                    ),
                    tooltip=[
                        alt.Tooltip('usage_date:T', title='Date'),
                        alt.Tooltip('forecasted_credits:Q', title='Credits', format='.2f'),
                        alt.Tooltip('type:N', title='Type')
                    ]
                ).properties(height=400)
                
                st.altair_chart(chart, use_container_width=True)
                
                # Budget exhaustion prediction
                st.markdown("#### Budget Prediction")
                
                budget = st.number_input("Total Budget (credits)", value=400.0, step=10.0)
                
                if st.button("Calculate Budget Exhaustion"):
                    budget_pred = forecaster.predict_budget_exhaustion(budget, history_days)
                    
                    if budget_pred['success']:
                        col1, col2, col3, col4 = st.columns(4)
                        
                        with col1:
                            st.metric("Total Used", f"{budget_pred['total_used']:.2f}")
                        with col2:
                            st.metric("Remaining", f"{budget_pred['remaining']:.2f}")
                        with col3:
                            st.metric("Daily Burn", f"{budget_pred['daily_burn_rate']:.2f}")
                        with col4:
                            days_left = budget_pred.get('days_remaining')
                            if days_left:
                                st.metric("Days Remaining", f"{int(days_left)}")
                            else:
                                st.metric("Days Remaining", "∞")
                        
                        # Risk alert
                        risk = budget_pred['risk_level']
                        risk_colors = {
                            'CRITICAL': '#FF4B4B',
                            'HIGH': '#FFB020',
                            'MEDIUM': '#29B5E8',
                            'LOW': '#00D4AA'
                        }
                        
                        st.markdown(f"""
                        <div style="background: {risk_colors[risk]}22; padding: 1rem; border-radius: 8px; border-left: 4px solid {risk_colors[risk]};">
                            <h4 style="margin: 0;">Risk Level: {risk}</h4>
                            <p style="margin: 0.5rem 0;">
                                {budget_pred['percentage_used']:.1f}% of budget used
                            </p>
                        </div>
                        """, unsafe_allow_html=True)
            else:
                st.error(f"Forecast failed: {credit_forecast.get('error', 'Unknown error')}")

# Tab 3: Cortex Optimizer logic follows...

with tab3:
    st.markdown("### Snowflake Cortex AI")
    st.caption("*Natural language query analysis and optimization*")
    
    if not cortex_available:
        st.warning("Cortex AI not available in your region. See warning at top of page.")
    else:
        st.success("✅ Cortex AI is available!")
        
        # Query explanation
        st.markdown("#### Natural Language Query Explanation")
        
        query_to_explain = st.text_area(
            "Enter SQL Query",
            height=150,
            placeholder="SELECT * FROM orders WHERE order_date >= '2024-01-01'",
            key="cortex_query"
        )
        
        if st.button("🤖 Explain Query with AI"):
            if query_to_explain.strip():
                with st.spinner("Asking Cortex AI..."):
                    explanation = cortex.explain_query(query_to_explain)
                    
                    if explanation['available']:
                        st.markdown("#### AI Explanation")
                        st.info(explanation['explanation'])
                        st.caption(f"*Generated by {explanation['model']}*")
                    else:
                        st.error(f"Error: {explanation.get('error', 'Unknown error')}")
            else:
                st.warning("Please enter a query")
        
        # Optimization suggestions
        st.markdown("#### AI-Powered Optimization Suggestions")
        
        query_to_optimize = st.text_area(
            "Enter SQL Query",
            height=150,
            placeholder="SELECT * FROM large_table",
            key="cortex_optimize"
        )
        
        if st.button("💡 Get AI Suggestions"):
            if query_to_optimize.strip():
                with st.spinner("Generating suggestions..."):
                    suggestions = cortex.suggest_optimizations(query_to_optimize)
                    
                    if suggestions['available']:
                        st.markdown("#### Optimization Suggestions")
                        
                        for idx, sug in enumerate(suggestions['suggestions']):
                            st.markdown(f"**{idx+1}.** {sug['text']}")
                            if 'impact' in sug:
                                st.success(f"💰 {sug['impact']}")
                            st.divider()
                        
                        with st.expander("📝 Full AI Response"):
                            st.text(suggestions['raw_text'])
                    else:
                        st.error(f"Error: {suggestions.get('error', 'Unknown error')}")
            else:
                st.warning("Please enter a query")

with tab4:
    st.markdown("### Anomaly Detection")
    st.caption("*Automatically detect unusual cost patterns*")
    
    col1, col2 = st.columns([1, 3])
    
    with col1:
        anomaly_days = st.slider("Analysis Period (days)", 7, 90, 30, key="anomaly_days")
        threshold = st.slider("Sensitivity (std deviations)", 1.5, 3.0, 2.0, 0.1)
        
        if st.button("🔍 Detect Anomalies"):
            st.session_state['run_anomaly'] = True
    
    if st.session_state.get('run_anomaly', False):
        with st.spinner("Detecting anomalies..."):
            anomalies = forecaster.detect_anomalies(anomaly_days, threshold)
            
            if anomalies['success']:
                stats = anomalies['statistics']
                anomaly_df = anomalies['anomalies']
                
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Anomalies Found", stats['anomaly_count'])
                with col2:
                    st.metric("Total Days", stats['total_days'])
                with col3:
                    st.metric("Mean Credits", f"{stats['mean']:.2f}")
                with col4:
                    st.metric("Std Dev", f"{stats['std']:.2f}")
                
                if not anomaly_df.empty:
                    st.markdown("#### Detected Anomalies")
                    
                    # Chart
                    chart = alt.Chart(anomaly_df).mark_bar(color='#FF4B4B').encode(
                        x=alt.X('usage_date:T', title='Date'),
                        y=alt.Y('daily_credits:Q', title='Credits'),
                        tooltip=[
                            alt.Tooltip('usage_date:T', title='Date'),
                            alt.Tooltip('daily_credits:Q', title='Credits', format='.2f'),
                            alt.Tooltip('z_score:Q', title='Z-Score', format='.2f')
                        ]
                    ).properties(height=300)
                    
                    st.altair_chart(chart, use_container_width=True)
                    
                    # Table
                    display_df = anomaly_df[['usage_date', 'daily_credits', 'z_score']].copy()
                    display_df.columns = ['Date', 'Credits', 'Z-Score']
                    st.dataframe(display_df, use_container_width=True, hide_index=True)
                else:
                    st.success("✅ No anomalies detected - spending is consistent!")
            else:
                st.error(f"Error: {anomalies.get('error', 'Unknown error')}")

with tab5:
    st.markdown("### Real-Time Monitoring & Alerts")
    st.caption("*Monitor queries, warehouses, and costs in near real-time*")
    
    if st.button("🔄 Refresh Alerts", key="refresh_monitoring"):
        st.rerun()
    
    with st.spinner("Checking for alerts..."):
        # Get health report
        health = monitor.generate_health_report()
        
        if health['success']:
            # Summary metrics
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Health Score", f"{health['health_score']}/100")
            with col2:
                st.metric("Active Queries", health['summary']['active_queries'])
            with col3:
                st.metric("Failed Queries", health['summary']['failed_queries'])
            with col4:
                st.metric("Total Alerts", len(health['alerts']))
            
            # Show Alerts
            if health['alerts']:
                for alert in health['alerts'][:5]: # Show top 5
                    st.warning(f"**{alert['severity']}**: {alert['message']}")

    st.divider()
    
    # --- HOLISTIC OPTIMIZATION REPORT ---
    st.markdown("### 🚀 Holistic Optimization Report")
    st.caption("*Aggregated insights across Security, Cost, and Performance*")
    
    from intelligence.recommendation_engine import RecommendationEngine
    
    if st.button("🔄 Generate Full Report"):
        with st.spinner("Analyzing entire Snowflake account..."):
            rec_engine = RecommendationEngine(client)
            report = rec_engine.generate_holistic_report()
            
            # Score
            score = report['score']
            color = "#00D4AA" if score >= 80 else "#FFB020" if score >= 50 else "#FF4B4B"
            
            c1, c2, c3 = st.columns([1, 1, 2])
            with c1:
                st.metric("Optimization Score", f"{score}/100")
            with c2:
                st.metric("Action Items", len(report['recommendations']))
                
            # Breakdown by Category
            st.markdown("#### Action Items by Category")
            summary = report['summary']
            cols = st.columns(3)
            cols[0].metric("🛡️ Security", summary['security_issues'])
            cols[1].metric("🏭 Warehouses", summary['warehouse_issues'])
            cols[2].metric("⚡ Performance", summary['performance_issues'])
            
            if report['recommendations']:
                st.markdown("#### Top Recommendations")
                for rec in report['recommendations']:
                    icon = "🛡️" if rec['domain'] == 'SECURITY' else "💰" if rec['domain'] == 'COST' else "⚡"
                    severity_color = "red" if rec['severity'] == 'CRITICAL' else "orange" if rec['severity'] == 'HIGH' else "blue"
                    
                    with st.expander(f"{icon} [{rec['severity']}] {rec['title']}"):
                        st.markdown(f"**Issue:** {rec['message']}")
                        st.info(f"👉 **Action:** {rec['action']}")
            else:
                st.success("🎉 No critical issues found! Your account is optimized.")

    st.divider()
    st.markdown("### System Health Dashboard")
    st.caption("*Comprehensive health monitoring*")
    
    if st.button("🔄 Refresh Dashboard"):
        st.rerun()
    
    with st.spinner("Loading health data..."):
        health = monitor.generate_health_report()
        
        if health['success']:
            # Overall health
            score = health['health_score']
            status = health['health_status']
            
            status_colors = {
                'HEALTHY': '#00D4AA',
                'WARNING': '#FFB020',
                'CRITICAL': '#FF4B4B'
            }
            
            st.markdown(f"""
            <div style="background: {status_colors[status]}22; padding: 2rem; border-radius: 12px; border-left: 6px solid {status_colors[status]}; text-align: center;">
                <h2 style="margin: 0;">System Health: {status}</h2>
                <h1 style="color: {status_colors[status]}; margin: 1rem 0; font-size: 4rem;">{score}/100</h1>
                <p style="margin: 0;">Last updated: {health['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}</p>
            </div>
            """, unsafe_allow_html=True)
            
            st.divider()
            
            # Metrics grid
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric("Active Queries", health['summary']['active_queries'])
            with col2:
                st.metric("Running Queries", health['summary']['running_queries'])
            with col3:
                st.metric("Failed Queries", health['summary']['failed_queries'])
            with col4:
                st.metric("Slow Queries", health['summary']['slow_queries'])
            
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric("High Queue", health['summary']['high_queue_queries'])
            with col2:
                st.metric("Warehouse Alerts", health['summary']['warehouse_alerts'])
            with col3:
                st.metric("Credit Alerts", health['summary']['credit_alerts'])
            with col4:
                st.metric("Total Alerts", len(health['alerts']))
            
            # Detailed sections
            st.divider()
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("#### Warehouse Load")
                wh_load = health['details']['warehouse_load']['warehouse_load']
                if not wh_load.empty:
                    st.dataframe(wh_load, use_container_width=True, hide_index=True)
                else:
                    st.info("No warehouse activity")
            
            with col2:
                st.markdown("#### Credit Burn Rate")
                credit_burn = health['details']['credit_burn']
                if credit_burn['success']:
                    st.metric("Credits/Hour", f"{credit_burn['credits_per_hour']:.2f}")
                    st.metric("Warehouses Active", credit_burn['warehouses_used'])
                else:
                    st.info("No credit data")

# Footer
st.divider()
st.markdown("""
<div style="text-align: center; color: #A0AEC0; font-size: 0.85rem;">
    <p>🤖 AI Intelligence Hub | Powered by Snowflake Cortex AI</p>
    <p><em>The future of intelligent Snowflake optimization</em></p>
</div>
""", unsafe_allow_html=True)
