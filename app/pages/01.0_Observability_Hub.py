"""
Unified Observability Hub — Four Golden Signals, SLO tracking,
alert management, credit/query trends, and AI root cause analysis.
"""
import streamlit as st
import pandas as pd
import json

st.set_page_config(page_title="Observability | SnowOps", page_icon="📡", layout="wide")

from utils.styles import apply_global_styles, render_sidebar
apply_global_styles()
render_sidebar()

def init():
    if 'snowflake_client' not in st.session_state:
        st.error("⚠️ Not connected."); st.stop()
    return st.session_state.snowflake_client

def get_engines(client):
    from utils.observability_engine import ObservabilityEngine
    from utils.cost_optimizer import CostOptimizer
    from utils.coco_client import CocoClient
    if 'obs_engine' not in st.session_state:
        e = ObservabilityEngine(client); e.ensure_tables(); st.session_state.obs_engine = e
    if 'cost_optimizer' not in st.session_state:
        st.session_state.cost_optimizer = CostOptimizer(client)
    coco = None
    try: coco = CocoClient(client.session)
    except: pass
    return st.session_state.obs_engine, st.session_state.cost_optimizer, coco

# ── Header ──
st.markdown("""
<style>
.obs-header { background: linear-gradient(135deg, #FF6B6B 0%, #FF8E53 50%, #FFA726 100%); padding: 1.5rem 2rem; border-radius: 12px; margin-bottom: 1.5rem; }
.obs-header h1 { color: white; margin: 0; font-size: 1.8rem; }
.obs-header p { color: rgba(255,255,255,0.9); margin: 0.3rem 0 0; }
.signal-card { background: #1e293b; border-radius: 12px; padding: 1.2rem; border: 1px solid #334155; text-align: center; }
.signal-value { font-size: 2rem; font-weight: 800; }
.signal-label { color: #94A3B8; font-size: 0.85rem; margin-top: 0.3rem; }
.alert-item { background: #1e293b; border-left: 4px solid #FF4444; border-radius: 8px; padding: 0.8rem 1rem; margin: 0.4rem 0; }
.alert-warn { border-left-color: #FFB020; }
.alert-info { border-left-color: #29B5E8; }
</style>
<div class="obs-header">
    <h1>📡 Observability Hub</h1>
    <p>Four Golden Signals • Alert Management • Cost Intelligence • AI Root Cause</p>
</div>
""", unsafe_allow_html=True)

client = init()
obs, cost, coco = get_engines(client)

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Signals", "🔔 Alerts", "💰 Cost Intel", "📈 Trends", "🤖 AI Diagnosis"
])

# ════════════════════════════════════════════════════════════════
# TAB 1: Four Golden Signals
# ════════════════════════════════════════════════════════════════
with tab1:
    st.markdown("### 📊 Four Golden Signals")
    hours = st.slider("Time window (hours)", 1, 168, 24, key="sig_hrs")

    sc1, sc2, sc3, sc4 = st.columns(4)

    # Error Rate
    error_rate = obs.get_error_rate(hours)
    er_color = "#00D4AA" if error_rate < 1 else ("#FFB020" if error_rate < 5 else "#FF4444")
    sc1.markdown(f"""<div class="signal-card">
        <div class="signal-value" style="color:{er_color}">{error_rate:.1f}%</div>
        <div class="signal-label">🚨 Error Rate</div>
    </div>""", unsafe_allow_html=True)

    # Latency
    latency = obs.get_latency(hours)
    if not latency.empty:
        avg_p95 = latency['P95_S'].mean() if 'P95_S' in latency.columns else 0
        lat_color = "#00D4AA" if avg_p95 < 10 else ("#FFB020" if avg_p95 < 60 else "#FF4444")
        sc2.markdown(f"""<div class="signal-card">
            <div class="signal-value" style="color:{lat_color}">{avg_p95:.1f}s</div>
            <div class="signal-label">⏱️ P95 Latency</div>
        </div>""", unsafe_allow_html=True)
    else:
        sc2.markdown("""<div class="signal-card"><div class="signal-value">—</div><div class="signal-label">⏱️ P95 Latency</div></div>""", unsafe_allow_html=True)

    # Traffic
    traffic = obs.get_traffic(hours)
    total_queries = traffic['QUERIES'].sum() if not traffic.empty and 'QUERIES' in traffic.columns else 0
    sc3.markdown(f"""<div class="signal-card">
        <div class="signal-value" style="color:#29B5E8">{total_queries:,}</div>
        <div class="signal-label">📊 Total Queries</div>
    </div>""", unsafe_allow_html=True)

    # Saturation
    sat = obs.get_saturation(7)
    total_credits = sat['TOTAL_CREDITS'].sum() if not sat.empty and 'TOTAL_CREDITS' in sat.columns else 0
    sc4.markdown(f"""<div class="signal-card">
        <div class="signal-value" style="color:#A855F7">{total_credits:.1f}</div>
        <div class="signal-label">💳 Credits (7d)</div>
    </div>""", unsafe_allow_html=True)

    # Detail sections
    if not latency.empty:
        st.markdown("#### ⏱️ Latency by Warehouse")
        st.dataframe(latency, use_container_width=True)

    if not traffic.empty:
        st.markdown("#### 📊 Query Traffic (Hourly)")
        st.line_chart(traffic.set_index('HOUR')['QUERIES'] if 'HOUR' in traffic.columns else traffic)

    errors = obs.get_errors(hours)
    if not errors.empty:
        st.markdown("#### 🚨 Top Errors")
        st.dataframe(errors.head(10), use_container_width=True)

# ════════════════════════════════════════════════════════════════
# TAB 2: Alert Management
# ════════════════════════════════════════════════════════════════
with tab2:
    st.markdown("### 🔔 Alert Rules & History")

    ac1, ac2 = st.columns(2)
    with ac1:
        st.markdown("#### ➕ Create Alert Rule")
        with st.form("new_alert"):
            aname = st.text_input("Alert Name", placeholder="High Error Rate")
            aquery = st.text_area("Metric Query (must return single number)", height=80,
                placeholder="SELECT COUNT(*) FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY WHERE EXECUTION_STATUS='FAIL' AND START_TIME >= DATEADD(HOUR,-1,CURRENT_TIMESTAMP())")
            ac3, ac4 = st.columns(2)
            athresh = ac3.number_input("Threshold", value=10.0)
            acomp = ac4.selectbox("Comparison", ["gt", "lt", "eq"], format_func=lambda x: {"gt":">","lt":"<","eq":"="}.get(x,x))
            asev = st.selectbox("Severity", ["CRITICAL", "WARNING", "INFO"])
            if st.form_submit_button("Create Alert", type="primary"):
                if aname and aquery:
                    aid = obs.create_alert(aname, aquery, athresh, acomp, asev)
                    st.success(f"✅ Alert created: {aid}")
                    st.rerun()

    with ac2:
        st.markdown("#### 📋 Active Alerts")
        alerts = obs.list_alerts()
        if not alerts.empty:
            for _, a in alerts.iterrows():
                sev_icon = {"CRITICAL":"🔴","WARNING":"🟡","INFO":"🔵"}.get(a.get('SEVERITY',''),"⚪")
                st.markdown(f"{sev_icon} **{a['ALERT_NAME']}** — {a.get('SEVERITY','?')}")
        else:
            st.info("No alert rules configured.")

    # Check alerts
    if st.button("▶️ Check All Alerts Now", type="primary"):
        with st.spinner("Evaluating alert rules..."):
            triggered = obs.check_alerts()
            if triggered:
                for t in triggered:
                    sev_icon = {"CRITICAL":"🔴","WARNING":"🟡","INFO":"🔵"}.get(t.get('severity',''),"⚪")
                    st.error(f"{sev_icon} **{t['alert']}**: value={t['value']}")
            else:
                st.success("✅ All alerts clear!")

    # Alert history
    st.markdown("#### 📜 Alert History")
    history = obs.get_alert_history()
    if not history.empty:
        for _, h in history.head(20).iterrows():
            sev_class = "alert-item" + (" alert-warn" if h.get('SEVERITY') == 'WARNING' else (" alert-info" if h.get('SEVERITY') == 'INFO' else ""))
            st.markdown(f"""<div class="{sev_class}">
                <strong>{h.get('ALERT_NAME','?')}</strong> — Value: {h.get('METRIC_VALUE','?')} | {h.get('TRIGGERED_AT','?')}
            </div>""", unsafe_allow_html=True)
    else:
        st.info("No alerts have been triggered yet.")

# ════════════════════════════════════════════════════════════════
# TAB 3: Cost Intelligence
# ════════════════════════════════════════════════════════════════
with tab3:
    st.markdown("### 💰 Cost Intelligence & FinOps")

    # Credit forecast
    forecast = cost.get_credit_forecast()
    fc1, fc2, fc3 = st.columns(3)
    fc1.metric("📊 Daily Avg Credits", f"{forecast.get('daily_avg',0):.1f}")
    fc2.metric("📅 7-Day Forecast", f"{forecast.get('forecast_total',0):.1f}")
    fc3.metric("📆 Monthly Forecast", f"{forecast.get('forecast_monthly',0):.1f}")

    # Warehouse utilization
    st.markdown("#### 🏭 Warehouse Utilization")
    util = cost.get_warehouse_utilization()
    if not util.empty:
        st.dataframe(util, use_container_width=True)

    # Rightsizing recommendations
    recs = cost.get_rightsizing_recommendations()
    if recs:
        st.markdown("#### 💡 Rightsizing Recommendations")
        for r in recs:
            icon = {"DOWNSIZE":"⬇️","UPSIZE":"⬆️","SUSPEND":"⏸️"}.get(r['recommendation'],"ℹ️")
            st.markdown(f"{icon} **{r['warehouse']}** ({r['current_size']}) → **{r['recommendation']}**: {r['reason']}")

    # Idle warehouses
    idle = cost.detect_idle_warehouses()
    if not idle.empty:
        st.markdown("#### 🚨 Idle Warehouses (consuming credits with no queries)")
        st.dataframe(idle, use_container_width=True)

    # Cloud services ratio
    cs = cost.get_cloud_services_ratio()
    if cs.get('ratio', 0) > 0:
        st.markdown(f"#### ☁️ Cloud Services: **{cs['ratio']:.1f}%** of total credits")
        if cs.get('exceeds_threshold'):
            st.warning("⚠️ Cloud services exceed 10% threshold — consider query optimization.")

    # Cost by user
    st.markdown("#### 👤 Cost Attribution by User")
    by_user = cost.get_cost_by_user()
    if not by_user.empty:
        st.dataframe(by_user.head(20), use_container_width=True)

# ════════════════════════════════════════════════════════════════
# TAB 4: Trends
# ════════════════════════════════════════════════════════════════
with tab4:
    st.markdown("### 📈 Trend Analysis")
    days = st.slider("Days to analyze", 7, 90, 30, key="trend_days")

    tc1, tc2 = st.columns(2)
    with tc1:
        st.markdown("#### 💳 Credit Trend")
        credit_trend = obs.get_credit_trend(days)
        if not credit_trend.empty:
            st.line_chart(credit_trend.set_index('DAY')['CREDITS'] if 'DAY' in credit_trend.columns else credit_trend)
        else:
            st.info("No credit data available.")

    with tc2:
        st.markdown("#### 📊 Query Volume Trend")
        query_trend = obs.get_query_volume_trend(days)
        if not query_trend.empty:
            st.line_chart(query_trend.set_index('DAY')['QUERIES'] if 'DAY' in query_trend.columns else query_trend)
        else:
            st.info("No query data available.")

# ════════════════════════════════════════════════════════════════
# TAB 5: AI Diagnosis
# ════════════════════════════════════════════════════════════════
with tab5:
    st.markdown("### 🤖 AI Root Cause Analysis")
    st.caption("Use Cortex AI to diagnose issues from your observability data.")

    if coco and coco.is_available:
        issue = st.text_area("Describe the issue", height=100,
            placeholder="Queries are running 5x slower than usual on the ETL_WH warehouse since yesterday...")
        if st.button("🔍 Diagnose", type="primary"):
            if issue:
                with st.spinner("AI analyzing..."):
                    result = coco.explain_error(issue)
                    if result:
                        st.markdown(result)
                    else:
                        st.error("AI analysis failed.")
    else:
        st.info("Cortex AI not available. Connect to a Snowflake account with Cortex enabled.")
