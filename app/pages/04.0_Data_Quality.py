"""
Data Quality Command Center V2 — Native DMF-powered quality monitoring.
Quality scoring, rule management, auto-suggest, freshness, schema drift,
PII scanning, and AI-powered anomaly detection.
"""
import streamlit as st
import pandas as pd
import json

st.set_page_config(page_title="Data Quality | SnowOps", page_icon="🛡️", layout="wide")

from utils.styles import apply_global_styles, render_sidebar
apply_global_styles()
render_sidebar()

def init():
    if 'snowflake_client' not in st.session_state:
        st.error("⚠️ Not connected. Return to the main dashboard."); st.stop()
    return st.session_state.snowflake_client

def get_engines(client):
    from utils.data_quality_engine import DataQualityEngine
    from utils.coco_client import CocoClient
    if 'dq_engine' not in st.session_state:
        e = DataQualityEngine(client); e.ensure_tables(); st.session_state.dq_engine = e
    coco = None
    try: coco = CocoClient(client.session)
    except: pass
    return st.session_state.dq_engine, coco

# ── Header ──
st.markdown("""
<style>
.dq-header { background: linear-gradient(135deg, #00D4AA 0%, #00B4D8 50%, #0077B6 100%); padding: 1.5rem 2rem; border-radius: 12px; margin-bottom: 1.5rem; }
.dq-header h1 { color: white; margin: 0; font-size: 1.8rem; }
.dq-header p { color: rgba(255,255,255,0.9); margin: 0.3rem 0 0; }
.score-card { text-align: center; padding: 1.5rem; border-radius: 12px; margin: 0.5rem 0; }
.score-high { background: linear-gradient(135deg, #00D4AA20, #00D4AA10); border: 1px solid #00D4AA; }
.score-med { background: linear-gradient(135deg, #FFB02020, #FFB02010); border: 1px solid #FFB020; }
.score-low { background: linear-gradient(135deg, #FF444420, #FF444410); border: 1px solid #FF4444; }
.score-number { font-size: 2.5rem; font-weight: 800; }
.rule-card { background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 1rem; margin: 0.5rem 0; }
.status-pass { color: #00D4AA; font-weight: 600; } .status-warn { color: #FFB020; font-weight: 600; }
.status-fail { color: #FF4444; font-weight: 600; } .status-error { color: #A0AEC0; }
</style>
<div class="dq-header">
    <h1>🛡️ Data Quality Command Center</h1>
    <p>Native quality monitoring with scoring, rules, anomaly detection & AI insights</p>
</div>
""", unsafe_allow_html=True)

client = init()
dq, coco = get_engines(client)

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Dashboard", "📏 Rules", "🔍 Profiler", "📢 Schema Drift", "🛡️ PII Guard"
])

# ════════════════════════════════════════════════════════════════
# TAB 1: Quality Dashboard
# ════════════════════════════════════════════════════════════════
with tab1:
    st.markdown("### 📊 Quality Overview")

    scores = dq.get_all_table_scores()
    rules = dq.list_rules()

    # Summary metrics
    mc1, mc2, mc3, mc4 = st.columns(4)
    total_rules = len(rules) if not rules.empty else 0
    passed = len(rules[rules['LAST_STATUS'] == 'PASS']) if not rules.empty and 'LAST_STATUS' in rules.columns else 0
    warned = len(rules[rules['LAST_STATUS'] == 'WARN']) if not rules.empty and 'LAST_STATUS' in rules.columns else 0
    failed = len(rules[rules['LAST_STATUS'] == 'FAIL']) if not rules.empty and 'LAST_STATUS' in rules.columns else 0
    avg_score = scores['SCORE'].mean() if not scores.empty and 'SCORE' in scores.columns else 100

    mc1.metric("📏 Total Rules", total_rules)
    mc2.metric("✅ Passing", passed)
    mc3.metric("⚠️ Warnings", warned)
    mc4.metric("❌ Failures", failed)

    # Overall score
    score_class = "score-high" if avg_score >= 80 else ("score-med" if avg_score >= 50 else "score-low")
    score_color = "#00D4AA" if avg_score >= 80 else ("#FFB020" if avg_score >= 50 else "#FF4444")
    st.markdown(f"""<div class="score-card {score_class}">
        <div class="score-number" style="color:{score_color}">{avg_score:.0f}</div>
        <div style="color:#A0AEC0">Overall Quality Score</div>
    </div>""", unsafe_allow_html=True)

    # Table scores
    if not scores.empty:
        st.markdown("#### Table Quality Scores")
        for _, row in scores.iterrows():
            s = row.get('SCORE', 0)
            icon = "🟢" if s >= 80 else ("🟡" if s >= 50 else "🔴")
            st.markdown(f"""{icon} **{row['TABLE_NAME']}** — Score: **{s:.0f}** | ✅ {row.get('PASSED',0)} ⚠️ {row.get('WARNED',0)} ❌ {row.get('FAILED',0)}""")
    else:
        st.info("No quality data yet. Add rules in the Rules tab and run them!")

    # Run all rules
    if total_rules > 0:
        if st.button("▶️ Run All Quality Checks", type="primary"):
            with st.spinner("Running all quality rules..."):
                results = dq.run_all_rules()
                passed_r = sum(1 for r in results if r.get('status') == 'PASS')
                st.success(f"✅ Completed: {passed_r}/{len(results)} passed")
                for r in results:
                    icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌", "ERROR": "💥"}.get(r.get('status'), "❓")
                    st.markdown(f"{icon} **{r.get('rule_type','')}**({r.get('column','')}) on `{r.get('table','')}` = {r.get('value','?')}")
                st.rerun()

# ════════════════════════════════════════════════════════════════
# TAB 2: Rules Management
# ════════════════════════════════════════════════════════════════
with tab2:
    st.markdown("### 📏 Quality Rules")

    col_add, col_suggest = st.columns(2)
    with col_add:
        st.markdown("#### ➕ Add Rule")
        with st.form("add_rule"):
            table = st.text_input("Table Name", placeholder="DB.SCHEMA.TABLE")
            column = st.text_input("Column Name", placeholder="COLUMN_NAME (or * for table-level)")
            rule_type = st.selectbox("Rule Type", list(dq.SYSTEM_CHECKS.keys()))
            rc1, rc2 = st.columns(2)
            tw = rc1.number_input("Warn Threshold", value=0.0, step=1.0)
            te = rc2.number_input("Error Threshold", value=0.0, step=1.0)
            if st.form_submit_button("Add Rule", type="primary"):
                if table:
                    rid = dq.create_rule(table, column, rule_type, tw if tw else None, te if te else None)
                    st.success(f"✅ Rule created: {rid}")
                    st.rerun()

    with col_suggest:
        st.markdown("#### 🤖 Auto-Suggest Rules")
        suggest_table = st.text_input("Table to analyze", placeholder="DB.SCHEMA.TABLE", key="suggest_tbl")
        if st.button("🔍 Suggest Rules"):
            if suggest_table:
                with st.spinner("Analyzing table schema..."):
                    suggestions = dq.suggest_rules(suggest_table)
                    if suggestions:
                        for s in suggestions:
                            st.markdown(f"- **{s['rule_type']}** on `{s['column']}` (warn: {s.get('threshold_warn','N/A')}, error: {s.get('threshold_error','N/A')})")
                        if st.button("➕ Add All Suggested Rules"):
                            for s in suggestions:
                                dq.create_rule(suggest_table, s['column'], s['rule_type'],
                                             s.get('threshold_warn'), s.get('threshold_error'))
                            st.success(f"✅ Added {len(suggestions)} rules")
                            st.rerun()
                    else:
                        st.info("Could not analyze table. Check the table name.")

    # Existing rules
    st.markdown("#### 📋 Active Rules")
    rules = dq.list_rules()
    if not rules.empty:
        for _, rule in rules.iterrows():
            status = rule.get('LAST_STATUS', '—')
            icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(status, "⬜")
            val = rule.get('LAST_RESULT', '—')
            st.markdown(f"""<div class="rule-card">
                {icon} <strong>{rule['RULE_TYPE']}</strong> on <code>{rule.get('COLUMN_NAME','*')}</code> @ <code>{rule['TABLE_NAME']}</code><br>
                <small>Value: {val} | Warn: {rule.get('THRESHOLD_WARN','—')} | Error: {rule.get('THRESHOLD_ERROR','—')} | Last: {rule.get('LAST_RUN_AT','never')}</small>
            </div>""", unsafe_allow_html=True)
            bc1, bc2 = st.columns([1, 6])
            if bc1.button("▶️", key=f"run_{rule['RULE_ID']}"):
                r = dq.run_rule(rule['RULE_ID'])
                st.success(f"{r.get('status')}: {r.get('value', '?')}")
                st.rerun()
            if bc2.button("🗑️", key=f"del_{rule['RULE_ID']}"):
                dq.delete_rule(rule['RULE_ID'])
                st.rerun()
    else:
        st.info("No rules configured. Add rules above or use Auto-Suggest.")

# ════════════════════════════════════════════════════════════════
# TAB 3: Deep Profiler
# ════════════════════════════════════════════════════════════════
with tab3:
    st.markdown("### 🔍 Deep Data Profiler")
    st.caption("Statistical analysis: Nulls, Distinct Values, Min/Max for all columns.")

    try:
        dbs = client.session.sql("SHOW DATABASES").collect()
        db_names = [r['name'] for r in dbs]
        sel_db = st.selectbox("Database", db_names, key="prof_db2")
        if sel_db:
            schemas = client.session.sql(f"SHOW SCHEMAS IN DATABASE {sel_db}").collect()
            sch_names = [r['name'] for r in schemas if r['name'] != 'INFORMATION_SCHEMA']
            sel_sch = st.selectbox("Schema", sch_names, key="prof_sch2")
            if sel_sch:
                tables = client.session.sql(f"SHOW TABLES IN SCHEMA {sel_db}.{sel_sch}").collect()
                tbl_names = [r['name'] for r in tables]
                sel_tbl = st.selectbox("Table", tbl_names, key="prof_tbl2")
                if sel_tbl and st.button("📊 Profile Table"):
                    full_name = f"{sel_db}.{sel_sch}.{sel_tbl}"
                    with st.spinner("Profiling..."):
                        cols = client.session.sql(f"DESC TABLE {full_name}").collect()
                        selects = []
                        for c in cols[:10]:
                            col = c['name']; dtype = c['type']
                            selects.append(f"COUNT({col}) as \"{col}_COUNT\"")
                            selects.append(f"COUNT(DISTINCT {col}) as \"{col}_DISTINCT\"")
                            if any(t in dtype for t in ['CHAR','TEXT','NUMBER','FLOAT','DATE','INT']):
                                selects.append(f"MIN({col}) as \"{col}_MIN\"")
                                selects.append(f"MAX({col}) as \"{col}_MAX\"")
                        selects.append("COUNT(*) as TOTAL_ROWS")
                        rows = client.session.sql(f"SELECT {', '.join(selects)} FROM {full_name}").collect()
                        if rows:
                            res = rows[0].asDict()
                            total = res['TOTAL_ROWS']
                            st.metric("Total Rows", f"{total:,}")
                            profile = []
                            for c in cols[:10]:
                                col = c['name']
                                non_null = res[f"{col}_COUNT"]
                                profile.append({
                                    "Column": col, "Type": c['type'],
                                    "Null %": round((total - non_null) / max(total, 1) * 100, 1),
                                    "Distinct": res[f"{col}_DISTINCT"],
                                    "Min": str(res.get(f"{col}_MIN", "N/A"))[:30],
                                    "Max": str(res.get(f"{col}_MAX", "N/A"))[:30],
                                })
                            st.dataframe(pd.DataFrame(profile), use_container_width=True)

                    # Quality gate check
                    gate = dq.check_quality_gate(full_name)
                    if gate['score'] > 0:
                        icon = "✅" if gate['passed'] else "❌"
                        st.markdown(f"{icon} **Quality Gate**: Score {gate['score']:.0f} (min: {gate['min_required']})")
    except Exception as e:
        st.error(f"Error: {e}")

# ════════════════════════════════════════════════════════════════
# TAB 4: Schema Drift
# ════════════════════════════════════════════════════════════════
with tab4:
    st.markdown("### 📢 Schema Drift Monitor")
    days = st.slider("Look back (days)", 1, 30, 7)
    try:
        drift = client.execute_query(f"""
            SELECT c.TABLE_SCHEMA, c.TABLE_NAME, c.COLUMN_NAME, c.DATA_TYPE, c.IS_NULLABLE, t.LAST_ALTERED
            FROM SNOWFLAKE.ACCOUNT_USAGE.COLUMNS c
            JOIN SNOWFLAKE.ACCOUNT_USAGE.TABLES t
              ON c.TABLE_CATALOG = t.TABLE_CATALOG
              AND c.TABLE_SCHEMA = t.TABLE_SCHEMA
              AND c.TABLE_NAME = t.TABLE_NAME
            WHERE c.DELETED IS NULL AND c.TABLE_SCHEMA != 'INFORMATION_SCHEMA'
              AND t.DELETED IS NULL
              AND t.LAST_ALTERED >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
            ORDER BY t.LAST_ALTERED DESC LIMIT 50""")
        if not drift.empty:
            st.warning(f"⚠️ {len(drift)} schema changes in the last {days} days")
            st.dataframe(drift, use_container_width=True)
        else:
            st.success("✅ No recent schema drift detected.")
    except:
        st.info("Schema drift data requires ACCOUNT_USAGE access.")

# ════════════════════════════════════════════════════════════════
# TAB 5: PII Guard
# ════════════════════════════════════════════════════════════════
with tab5:
    st.markdown("### 🛡️ Privacy Guard & PII Monitor")
    if st.button("🔎 Scan for PII Risks"):
        with st.spinner("Scanning metadata for PII patterns..."):
            try:
                pii = client.execute_query("""
                    SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE
                    FROM SNOWFLAKE.ACCOUNT_USAGE.COLUMNS
                    WHERE DELETED IS NULL AND TABLE_SCHEMA != 'INFORMATION_SCHEMA'
                      AND (COLUMN_NAME LIKE '%EMAIL%' OR COLUMN_NAME LIKE '%PHONE%'
                           OR COLUMN_NAME LIKE '%SSN%' OR COLUMN_NAME LIKE '%PASSWORD%'
                           OR COLUMN_NAME LIKE '%SECRET%' OR COLUMN_NAME LIKE '%CREDIT_CARD%')
                    ORDER BY TABLE_SCHEMA, TABLE_NAME LIMIT 100""")
                if not pii.empty:
                    st.warning(f"⚠️ Found {len(pii)} potentially sensitive columns")
                    st.dataframe(pii, use_container_width=True)
                    st.info("💡 Apply Dynamic Masking Policies to protect these columns.")
                else:
                    st.success("✅ No obvious PII column names found.")
            except Exception as e:
                st.error(f"Scan failed: {e}")
