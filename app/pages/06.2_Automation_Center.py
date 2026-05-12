"""
Automation Control Center — Server-side scheduling, alerts, and notifications.
Everything configured here runs on Snowflake compute even when the app is closed.
"""
import streamlit as st
import pandas as pd
import json

st.set_page_config(page_title="Automation | SnowOps", page_icon="⚙️", layout="wide")

def init():
    if 'snowflake_client' not in st.session_state:
        st.error("⚠️ Not connected."); st.stop()
    return st.session_state.snowflake_client

def get_engines(client):
    from utils.automation_engine import AutomationEngine
    if 'automation_engine' not in st.session_state:
        e = AutomationEngine(client); e.ensure_tables(); st.session_state.automation_engine = e
    return st.session_state.automation_engine

# ── Header ──
st.markdown("""
<style>
.auto-header { background: linear-gradient(135deg, #10B981 0%, #059669 50%, #047857 100%); padding: 1.5rem 2rem; border-radius: 12px; margin-bottom: 1.5rem; }
.auto-header h1 { color: white; margin: 0; font-size: 1.8rem; }
.auto-header p { color: rgba(255,255,255,0.9); margin: 0.3rem 0 0; }
.auto-card { background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 1rem; margin: 0.5rem 0; }
.auto-badge { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: 600; }
.badge-active { background: #10B98120; color: #10B981; border: 1px solid #10B981; }
.badge-suspended { background: #FFB02020; color: #FFB020; border: 1px solid #FFB020; }
.info-box { background: #1e3a5f; border: 1px solid #29B5E8; border-radius: 8px; padding: 1rem; margin: 0.5rem 0; }
</style>
<div class="auto-header">
    <h1>⚙️ Automation Control Center</h1>
    <p>Server-side scheduling, alerts & notifications — runs even when this app is closed</p>
</div>
""", unsafe_allow_html=True)

st.markdown("""<div class="info-box">
    💡 <strong>How it works:</strong> Everything configured here creates <strong>native Snowflake objects</strong>
    (Tasks, Alerts, Notification Integrations) that run on Snowflake's compute layer.
    They execute on schedule <strong>even when this Streamlit app is not open</strong>.
</div>""", unsafe_allow_html=True)

client = init()
auto = get_engines(client)

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📋 Jobs", "🔔 Alerts", "📨 Notifications", "🛡️ Watchdogs", "💰 Resource Monitors"
])

# ════════════════════════════════════════════════════════════════
# TAB 1: Automation Jobs Registry
# ════════════════════════════════════════════════════════════════
with tab1:
    st.markdown("### 📋 Automation Jobs")

    # Active jobs
    jobs = auto.list_jobs()
    if not jobs.empty:
        for _, j in jobs.iterrows():
            status = j.get('STATUS', 'UNKNOWN')
            badge = "badge-active" if status == 'ACTIVE' else "badge-suspended"
            st.markdown(f"""<div class="auto-card">
                <strong>{j.get('JOB_NAME','?')}</strong>
                <span class="auto-badge {badge}">{status}</span>
                <span class="auto-badge" style="background:#6366F120;color:#6366F1;border:1px solid #6366F1">{j.get('JOB_TYPE','?')}</span><br>
                <small>Schedule: {j.get('SCHEDULE','—')} | SF Object: <code>{j.get('SNOWFLAKE_OBJECT_NAME','—')}</code> | Created: {j.get('CREATED_AT','?')}</small>
            </div>""", unsafe_allow_html=True)
            if st.button("🗑️ Remove", key=f"del_job_{j['JOB_ID']}"):
                auto.delete_job(j['JOB_ID'])
                st.rerun()
    else:
        st.info("No automation jobs configured yet. Create alerts, watchdogs, or scheduled procedures below.")

    # Create scheduled procedure
    st.markdown("---")
    st.markdown("### ➕ Create Scheduled Procedure")
    with st.form("sched_proc"):
        sp1, sp2 = st.columns(2)
        proc_name = sp1.text_input("Procedure Name", placeholder="daily_cleanup")
        warehouse = sp2.text_input("Warehouse", value="COMPUTE_WH")
        schedule = st.text_input("Schedule", value="USING CRON 0 6 * * * UTC", help="Cron expression for when to run")
        proc_body = st.text_area("Procedure Body (SQL)", height=150,
            placeholder="DELETE FROM my_db.public.staging_data WHERE created_at < DATEADD(DAY, -30, CURRENT_DATE());\nINSERT INTO my_db.public.audit_log VALUES(CURRENT_TIMESTAMP(), 'cleanup', 'completed');")
        sp3, sp4 = st.columns(2)
        db = sp3.text_input("Database", placeholder="MY_DB")
        sch = sp4.text_input("Schema", value="PUBLIC")
        if st.form_submit_button("🚀 Create & Schedule", type="primary"):
            if proc_name and proc_body:
                r = auto.create_scheduled_procedure(proc_name, proc_body, schedule, warehouse, db or None, sch)
                if r['status'] == 'SUCCESS':
                    sf_name = f"{db}.{sch}.TASK_SCHED_{proc_name.upper()}" if db else f"TASK_SCHED_{proc_name.upper()}"
                    auto.register_job(proc_name, "SCHEDULED_PROC", schedule, {"warehouse": warehouse}, sf_name)
                    st.success(f"✅ Procedure created and scheduled!")
                    st.rerun()
                else:
                    st.error(f"❌ {r.get('error','')}")

# ════════════════════════════════════════════════════════════════
# TAB 2: Snowflake Alerts
# ════════════════════════════════════════════════════════════════
with tab2:
    st.markdown("### 🔔 Snowflake Native Alerts")
    st.caption("These alerts run entirely server-side. No app needed.")

    alerts = auto.list_alerts()
    if not alerts.empty:
        name_col = 'name' if 'name' in alerts.columns else 'NAME'
        state_col = 'state' if 'state' in alerts.columns else 'STATE'
        for _, a in alerts.iterrows():
            aname = a.get(name_col, '?')
            astate = a.get(state_col, '?')
            icon = "🟢" if astate in ['started', 'STARTED'] else "🟡"
            st.markdown(f"{icon} **{aname}** — {astate}")
            ac1, ac2, ac3 = st.columns([1,1,4])
            if astate in ['started', 'STARTED']:
                if ac1.button("⏸️ Suspend", key=f"sus_alert_{aname}"):
                    auto.suspend_alert(aname); st.rerun()
            else:
                if ac1.button("▶️ Resume", key=f"res_alert_{aname}"):
                    auto.resume_alert(aname); st.rerun()
            if ac2.button("🗑️ Drop", key=f"drop_alert_{aname}"):
                auto.drop_alert(aname); st.rerun()
    else:
        st.info("No native alerts found. Create one below or use the Watchdogs tab for pre-built templates.")

    st.markdown("---")
    st.markdown("### ➕ Custom Alert")
    with st.form("custom_alert"):
        ca1, ca2 = st.columns(2)
        aname = ca1.text_input("Alert Name", placeholder="high_error_rate")
        awh = ca2.text_input("Warehouse", value="COMPUTE_WH")
        asched = st.text_input("Check Interval", value="60 MINUTE")
        acond = st.text_area("Condition SQL (must return rows when alert should fire)", height=80,
            placeholder="SELECT 1 FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY WHERE EXECUTION_STATUS='FAIL' AND START_TIME >= DATEADD(HOUR,-1,CURRENT_TIMESTAMP()) HAVING COUNT(*)>10")
        aact = st.text_area("Action SQL (what to do when alert fires)", height=80,
            placeholder="CALL SYSTEM$SEND_EMAIL('my_email_int', 'team@example.com', 'Alert: High Error Rate', 'More than 10 queries failed in the last hour.')")
        if st.form_submit_button("🚀 Create Alert", type="primary"):
            if aname and acond and aact:
                r = auto.create_snowflake_alert(aname, awh, asched, acond, aact)
                if r['status'] == 'SUCCESS':
                    auto.register_job(aname, "ALERT", asched, {}, aname)
                    st.success(f"✅ Alert '{aname}' created and resumed!")
                    st.rerun()
                else:
                    st.error(f"❌ {r.get('error','')}")

# ════════════════════════════════════════════════════════════════
# TAB 3: Notification Integrations
# ════════════════════════════════════════════════════════════════
with tab3:
    st.markdown("### 📨 Notification Channels")
    st.caption("Configure how alerts reach you — Email, Slack, Teams, PagerDuty.")

    integrations = auto.list_notification_integrations()
    if not integrations.empty:
        st.dataframe(integrations, use_container_width=True)
    else:
        st.info("No notification integrations found.")

    nc1, nc2 = st.columns(2)
    with nc1:
        st.markdown("#### 📧 Email Integration")
        with st.form("email_int"):
            ename = st.text_input("Integration Name", value="SNOWOPS_EMAIL_INT")
            erecip = st.text_input("Allowed Recipients (comma-sep)", placeholder="admin@company.com, alerts@company.com")
            if st.form_submit_button("Create Email Integration", type="primary"):
                recipients = [r.strip() for r in erecip.split(',')]
                r = auto.create_email_notification(ename, recipients)
                if r['status'] == 'SUCCESS':
                    st.success("✅ Email integration created!")
                else:
                    st.error(f"❌ {r.get('error','')} — Requires ACCOUNTADMIN or CREATE INTEGRATION privilege")

        st.markdown("#### 🧪 Test Email")
        with st.form("test_email"):
            te_int = st.text_input("Integration Name", value="SNOWOPS_EMAIL_INT", key="te_int")
            te_recip = st.text_input("Recipient", placeholder="you@company.com")
            if st.form_submit_button("📧 Send Test"):
                r = auto.send_test_email(te_int, te_recip)
                if r['status'] == 'SUCCESS': st.success("✅ Test email sent!")
                else: st.error(f"❌ {r.get('error','')}")

    with nc2:
        st.markdown("#### 🔗 Webhook Integration")
        with st.form("webhook_int"):
            wname = st.text_input("Integration Name", value="SNOWOPS_SLACK_INT")
            wtype = st.selectbox("Type", ["Slack", "Microsoft Teams", "PagerDuty", "Custom"])
            wurl = st.text_input("Webhook URL", type="password", placeholder="https://hooks.slack.com/services/...")
            if st.form_submit_button("Create Webhook Integration", type="primary"):
                r = auto.create_webhook_notification(wname, wurl, wtype.upper())
                if r['status'] == 'SUCCESS':
                    st.success(f"✅ {wtype} integration created!")
                else:
                    st.error(f"❌ {r.get('error','')}")

# ════════════════════════════════════════════════════════════════
# TAB 4: Pre-built Watchdogs
# ════════════════════════════════════════════════════════════════
with tab4:
    st.markdown("### 🛡️ Watchdog Templates")
    st.caption("One-click server-side monitoring — runs on Snowflake even when the app is closed.")

    wd_type = st.selectbox("Watchdog Type", ["💰 Cost Watchdog", "📊 Quality Watchdog", "❌ Failure Watchdog"])

    if wd_type == "💰 Cost Watchdog":
        st.markdown("**Monitors daily credit consumption and emails you when it exceeds a limit.**")
        with st.form("cost_wd"):
            cw1, cw2 = st.columns(2)
            cwname = cw1.text_input("Watchdog Name", value="COST_WATCHDOG")
            cwwh = cw2.text_input("Warehouse", value="COMPUTE_WH")
            cwlimit = st.number_input("Daily Credit Limit", value=50.0, step=10.0)
            cwint = st.text_input("Notification Integration", value="SNOWOPS_EMAIL_INT")
            cwemail = st.text_input("Alert Email", placeholder="admin@company.com")
            cwfreq = st.selectbox("Check Frequency", ["30 MINUTE", "60 MINUTE", "120 MINUTE"])
            if st.form_submit_button("🚀 Deploy Cost Watchdog", type="primary"):
                r = auto.create_cost_watchdog(cwname, cwwh, cwlimit, cwint, cwemail, cwfreq)
                if r['status'] == 'SUCCESS':
                    auto.register_job(cwname, "ALERT", cwfreq, {"limit": cwlimit}, cwname, "Cost watchdog")
                    st.success("✅ Cost watchdog deployed!")
                    st.rerun()
                else:
                    st.error(f"❌ {r.get('error','')}")

    elif wd_type == "📊 Quality Watchdog":
        st.markdown("**Monitors a table's null percentage and alerts when it exceeds a threshold.**")
        with st.form("qual_wd"):
            qw1, qw2 = st.columns(2)
            qwname = qw1.text_input("Watchdog Name", value="QUALITY_WATCHDOG")
            qwwh = qw2.text_input("Warehouse", value="COMPUTE_WH")
            qwtable = st.text_input("Table to Monitor", placeholder="DB.SCHEMA.TABLE")
            qwnull = st.number_input("Max Null %", value=5.0, step=1.0)
            qwint = st.text_input("Notification Integration", value="SNOWOPS_EMAIL_INT")
            qwemail = st.text_input("Alert Email", placeholder="data-team@company.com")
            if st.form_submit_button("🚀 Deploy Quality Watchdog", type="primary"):
                r = auto.create_quality_watchdog(qwname, qwwh, qwtable, qwnull, qwint, qwemail)
                if r['status'] == 'SUCCESS':
                    auto.register_job(qwname, "ALERT", "60 MINUTE", {"table": qwtable}, qwname, "Quality watchdog")
                    st.success("✅ Quality watchdog deployed!")
                    st.rerun()
                else:
                    st.error(f"❌ {r.get('error','')}")

    elif wd_type == "❌ Failure Watchdog":
        st.markdown("**Monitors a specific Task for failures and sends an alert.**")
        with st.form("fail_wd"):
            fw1, fw2 = st.columns(2)
            fwname = fw1.text_input("Watchdog Name", value="FAILURE_WATCHDOG")
            fwwh = fw2.text_input("Warehouse", value="COMPUTE_WH")
            fwtask = st.text_input("Task to Monitor", placeholder="DB.SCHEMA.MY_ETL_TASK")
            fwint = st.text_input("Notification Integration", value="SNOWOPS_EMAIL_INT")
            fwemail = st.text_input("Alert Email", placeholder="oncall@company.com")
            if st.form_submit_button("🚀 Deploy Failure Watchdog", type="primary"):
                r = auto.create_failure_watchdog(fwname, fwwh, fwtask, fwint, fwemail)
                if r['status'] == 'SUCCESS':
                    auto.register_job(fwname, "ALERT", "15 MINUTE", {"task": fwtask}, fwname, "Failure watchdog")
                    st.success("✅ Failure watchdog deployed!")
                    st.rerun()
                else:
                    st.error(f"❌ {r.get('error','')}")

# ════════════════════════════════════════════════════════════════
# TAB 5: Resource Monitors
# ════════════════════════════════════════════════════════════════
with tab5:
    st.markdown("### 💰 Resource Monitors")
    st.caption("Hard credit limits that auto-suspend warehouses when budgets are exceeded.")

    monitors = auto.list_resource_monitors()
    if not monitors.empty:
        st.dataframe(monitors, use_container_width=True)
    else:
        st.info("No resource monitors configured.")

    st.markdown("---")
    with st.form("new_monitor"):
        rm1, rm2 = st.columns(2)
        rmname = rm1.text_input("Monitor Name", placeholder="MONTHLY_BUDGET")
        rmquota = rm2.number_input("Monthly Credit Quota", value=500, step=50)
        rmwh = st.text_input("Warehouses to attach (comma-sep)", placeholder="COMPUTE_WH, ETL_WH")
        rm3, rm4, rm5 = st.columns(3)
        n75 = rm3.checkbox("Notify at 75%", value=True)
        s90 = rm4.checkbox("Suspend at 90%", value=True)
        s100 = rm5.checkbox("Suspend immediately at 100%", value=True)
        if st.form_submit_button("🚀 Create Resource Monitor", type="primary"):
            if rmname:
                whs = [w.strip() for w in rmwh.split(',') if w.strip()] if rmwh else None
                r = auto.create_resource_monitor(rmname, rmquota, whs, n75, s90, s100)
                if r['status'] == 'SUCCESS':
                    st.success(f"✅ Resource monitor '{rmname}' created!")
                    st.rerun()
                else:
                    st.error(f"❌ {r.get('error','')} — May require ACCOUNTADMIN")
