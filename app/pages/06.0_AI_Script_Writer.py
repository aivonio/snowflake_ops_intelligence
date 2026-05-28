"""
AI Script Writer V2 — Generate, optimize, debug, migrate, and build
stored procedures, DMFs, semantic models, and cost-annotated SQL.
Powered by Cortex AI (CoCo).
"""
import streamlit as st

st.set_page_config(page_title="AI Script Writer", page_icon="✍️", layout="wide")

from utils.styles import apply_global_styles, render_sidebar
apply_global_styles()
render_sidebar()

def init():
    if 'snowflake_client' not in st.session_state:
        st.error("⚠️ Not connected."); st.stop()
    return st.session_state.snowflake_client

def get_coco(client):
    from utils.coco_client import CocoClient
    try: return CocoClient(client.session)
    except: return None

# ── Header ──
st.markdown("""
<style>
.sw-header { background: linear-gradient(135deg, #0EA5E9 0%, #06B6D4 50%, #14B8A6 100%); padding: 1.5rem 2rem; border-radius: 12px; margin-bottom: 1.5rem; }
.sw-header h1 { color: white; margin: 0; font-size: 1.8rem; }
.sw-header p { color: rgba(255,255,255,0.9); margin: 0.3rem 0 0; }
.gen-card { background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 1rem; margin: 0.5rem 0; }
</style>
<div class="sw-header">
    <h1>✍️ AI Script Writer</h1>
    <p>Generate, optimize, debug & migrate Snowflake SQL — powered by Cortex AI</p>
</div>
""", unsafe_allow_html=True)

client = init()
coco = get_coco(client)

if not coco or not coco.is_available:
    st.warning("⚠️ Cortex AI is not available in your environment. Some features will be limited.")
    coco_ready = False
else:
    coco_ready = True

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "✨ Generate", "⚡ Optimize", "🐛 Debug", "🔄 Migrate", "🔧 Procedures", "📊 DMF Builder"
])

# ════════════════════════════════════════════════════════════════
# TAB 1: Script Generator
# ════════════════════════════════════════════════════════════════
with tab1:
    st.markdown("### ✨ Script Generator")
    st.markdown("Describe what you need in plain English — CoCo will write the SQL.")

    with st.form("gen_form"):
        prompt = st.text_area("What do you need?", height=120,
            placeholder="Create a stored procedure that archives orders older than 90 days from ANALYTICS.PUBLIC.ORDERS to ANALYTICS.ARCHIVE.ORDERS, then deletes them from the source. Include logging and error handling.")
        gc1, gc2 = st.columns(2)
        script_type = gc1.selectbox("Script Type", [
            "ETL Procedure", "DDL Migration", "Data Quality Check",
            "Access Policy", "Masking Policy", "Resource Monitor",
            "Security Audit", "Warehouse Management", "Task Graph",
            "Dynamic Table", "Stream + Task", "Custom"
        ])
        target_objects = gc2.text_input("Target Objects (optional)", placeholder="DB.SCHEMA.TABLE")
        generate = st.form_submit_button("✨ Generate Script", type="primary")

    if generate and prompt:
        if not coco_ready: st.error("Cortex AI not available."); st.stop()
        with st.spinner("🤖 CoCo is writing your script..."):
            result = coco.write_script(prompt, script_type.lower().replace(" ", "_"))
            if result: st.session_state.generated_script = result
            else: st.error("Generation failed.")

    if st.session_state.get('generated_script'):
        st.markdown("#### Generated Script")
        script = st.session_state.generated_script
        edited = st.text_area("Edit before executing", value=script, height=400)
        ec1, ec2, ec3 = st.columns(3)
        if ec1.button("▶️ Execute", type="primary"):
            try:
                client.execute_query(edited)
                st.success("✅ Script executed successfully!")
            except Exception as e:
                st.error(f"❌ Execution failed: {e}")
                if coco_ready:
                    with st.expander("🤖 AI Fix Suggestion"):
                        fix = coco.explain_error(str(e), edited)
                        if fix: st.markdown(fix)
        if ec2.button("📋 Copy"):
            st.code(edited, language='sql')
            st.info("Use Ctrl+A then Ctrl+C to copy")
        if ec3.button("🗑️ Clear"):
            st.session_state.generated_script = None; st.rerun()

    # Quick templates
    st.markdown("---")
    st.markdown("### 📝 Quick Templates")
    templates = {
        "🔒 Row Access Policy": "Create a row access policy that restricts access to rows based on the user's role and department",
        "🎭 Data Masking": "Create a masking policy for PII columns (email, phone, SSN) that shows full data to ADMIN role and masks for others",
        "📊 Resource Monitor": "Create a resource monitor that alerts at 75% and suspends at 100% of a 1000 credit monthly quota",
        "🔍 Data Quality": "Create a stored procedure that checks for nulls, duplicates, and referential integrity across all tables in a schema",
        "📦 Archive Pipeline": "Create a procedure that moves data older than X days to an archive table, with logging",
        "🔐 Security Audit": "Generate a security audit script that checks role hierarchy, privilege grants, and network policies",
    }
    cols = st.columns(3)
    for i, (name, desc) in enumerate(templates.items()):
        with cols[i % 3]:
            if st.button(name, key=f"tmpl_{i}", use_container_width=True):
                if coco_ready:
                    with st.spinner(f"Generating {name}..."):
                        result = coco.write_script(desc)
                        if result:
                            st.session_state.generated_script = result
                            st.rerun()

# ════════════════════════════════════════════════════════════════
# TAB 2: Optimizer
# ════════════════════════════════════════════════════════════════
with tab2:
    st.markdown("### ⚡ SQL Optimizer")
    with st.form("opt_form"):
        input_sql = st.text_area("Paste SQL to optimize", height=250,
            placeholder="SELECT * FROM big_table t1\nJOIN other_table t2 ON t1.id = t2.id\nWHERE t1.created_at > '2024-01-01'\nORDER BY t1.amount DESC")
        oc1, oc2 = st.columns(2)
        duration = oc1.number_input("Execution Duration (ms)", value=0)
        bytes_scanned = oc2.number_input("Bytes Scanned", value=0)
        optimize = st.form_submit_button("⚡ Optimize", type="primary")

    if optimize and input_sql:
        if not coco_ready: st.error("Cortex AI not available."); st.stop()
        profile = {}
        if duration: profile['duration_ms'] = duration
        if bytes_scanned: profile['bytes_scanned'] = bytes_scanned
        with st.spinner("🤖 Analyzing query..."):
            result = coco.optimize_sql(input_sql, profile if profile else None)
            if result: st.markdown("#### Optimization Report"); st.markdown(result)
            else: st.error("Optimization failed.")

    st.markdown("---")
    st.markdown("#### 🔍 Optimize from Query History")
    if st.button("Load Slowest Queries"):
        try:
            slow = client.execute_query("""
                SELECT QUERY_TEXT, TOTAL_ELAPSED_TIME, BYTES_SCANNED, PARTITIONS_SCANNED, PARTITIONS_TOTAL
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE EXECUTION_STATUS = 'SUCCESS' AND TOTAL_ELAPSED_TIME > 10000
                ORDER BY TOTAL_ELAPSED_TIME DESC LIMIT 10""", log=False)
            if not slow.empty:
                for _, q in slow.iterrows():
                    with st.expander(f"⏱️ {q['TOTAL_ELAPSED_TIME']/1000:.1f}s — {str(q['QUERY_TEXT'])[:80]}..."):
                        st.code(str(q['QUERY_TEXT'])[:2000], language='sql')
                        if st.button("⚡ Optimize This", key=f"opt_{_}"):
                            with st.spinner("Optimizing..."):
                                fix = coco.optimize_sql(str(q['QUERY_TEXT']),
                                    {"duration_ms": q['TOTAL_ELAPSED_TIME'], "bytes_scanned": q['BYTES_SCANNED']})
                                if fix: st.markdown(fix)
            else: st.info("No slow queries found (>10s).")
        except Exception as e: st.warning(f"Could not load: {e}")

# ════════════════════════════════════════════════════════════════
# TAB 3: Debugger
# ════════════════════════════════════════════════════════════════
with tab3:
    st.markdown("### 🐛 SQL Debugger")
    with st.form("debug_form"):
        error_msg = st.text_area("Error Message", height=80,
            placeholder="SQL compilation error: Object 'DB.SCHEMA.TABLE' does not exist or not authorized.")
        failed_sql = st.text_area("Failed SQL (optional)", height=200)
        debug = st.form_submit_button("🐛 Diagnose", type="primary")

    if debug and error_msg:
        if not coco_ready: st.error("Cortex AI not available."); st.stop()
        with st.spinner("🤖 Diagnosing..."):
            diagnosis = coco.explain_error(error_msg, failed_sql if failed_sql else None)
            if diagnosis: st.markdown("#### 🔍 Diagnosis"); st.markdown(diagnosis)
            else: st.error("Diagnosis failed.")

    st.markdown("---")
    st.markdown("#### 🔴 Recent Failed Queries")
    if st.button("Load Failed Queries"):
        try:
            fails = client.execute_query("""
                SELECT QUERY_TEXT, ERROR_MESSAGE, START_TIME, USER_NAME
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE EXECUTION_STATUS = 'FAIL' AND START_TIME >= DATEADD(HOUR, -24, CURRENT_TIMESTAMP())
                ORDER BY START_TIME DESC LIMIT 20""", log=False)
            if not fails.empty:
                for _, f in fails.iterrows():
                    with st.expander(f"❌ {str(f.get('ERROR_MESSAGE',''))[:60]}... ({f.get('USER_NAME','?')})"):
                        st.code(str(f.get('QUERY_TEXT',''))[:1000], language='sql')
                        st.markdown(f"**Error:** {f.get('ERROR_MESSAGE','')}")
                        if st.button("🤖 Fix", key=f"dbg_{_}"):
                            with st.spinner("Analyzing..."):
                                fix = coco.explain_error(str(f.get('ERROR_MESSAGE','')), str(f.get('QUERY_TEXT','')))
                                if fix: st.markdown(fix)
            else: st.success("✅ No failed queries in the last 24 hours!")
        except Exception as e: st.warning(f"Could not load: {e}")

# ════════════════════════════════════════════════════════════════
# TAB 4: Migration
# ════════════════════════════════════════════════════════════════
with tab4:
    st.markdown("### 🔄 SQL Migration Assistant")
    with st.form("migrate_form"):
        dialect = st.selectbox("Source Dialect", ["Auto-Detect", "Oracle (PL/SQL)", "MySQL", "PostgreSQL", "SQL Server (T-SQL)", "BigQuery", "Redshift", "Spark SQL"])
        source_sql = st.text_area("Source SQL", height=300,
            placeholder="-- Paste your Oracle/MySQL/Postgres/etc SQL here\nSELECT NVL(col1, 'default'),\n       SYSDATE\nFROM schema.table\nWHERE ROWNUM <= 100")
        migrate = st.form_submit_button("🔄 Convert to Snowflake", type="primary")

    if migrate and source_sql:
        if not coco_ready: st.error("Cortex AI not available."); st.stop()
        dialect_map = {"Auto-Detect":"auto","Oracle (PL/SQL)":"oracle","MySQL":"mysql",
                       "PostgreSQL":"postgresql","SQL Server (T-SQL)":"tsql",
                       "BigQuery":"bigquery","Redshift":"redshift","Spark SQL":"spark"}
        with st.spinner("🤖 Converting..."):
            result = coco.migrate_sql(source_sql, dialect_map.get(dialect, "auto"))
            if result: st.markdown("#### Snowflake SQL"); st.markdown(result)
            else: st.error("Migration failed.")

    st.markdown("---")
    st.markdown("### 📖 Common Migration Patterns")
    patterns = {
        "Oracle → Snowflake": "`NVL` → `COALESCE`, `SYSDATE` → `CURRENT_TIMESTAMP()`, `DECODE` → `CASE`, `ROWNUM` → `LIMIT`",
        "MySQL → Snowflake": "`IFNULL` → `COALESCE`, `NOW()` → `CURRENT_TIMESTAMP()`, `LIMIT x,y` → `LIMIT y OFFSET x`",
        "PostgreSQL → Snowflake": "`::` casting works! `SERIAL` → `AUTOINCREMENT`, `ON CONFLICT` → `MERGE`",
        "SQL Server → Snowflake": "`GETDATE()` → `CURRENT_TIMESTAMP()`, `TOP N` → `LIMIT N`, `ISNULL` → `COALESCE`",
    }
    for title, content in patterns.items():
        with st.expander(title): st.markdown(content)

# ════════════════════════════════════════════════════════════════
# TAB 5: Stored Procedure Builder
# ════════════════════════════════════════════════════════════════
with tab5:
    st.markdown("### 🔧 Stored Procedure Builder")
    st.caption("Generate production-grade stored procedures with error handling, logging, and transactions.")

    with st.form("sp_form"):
        sp_desc = st.text_area("Describe the procedure", height=120,
            placeholder="Create a stored procedure that:\n1. Reads new rows from staging table\n2. Validates data quality\n3. Merges into target dimension table\n4. Logs results to an audit table\n5. Returns count of processed rows")
        sp1, sp2 = st.columns(2)
        sp_lang = sp1.selectbox("Language", ["SQL (Snowflake Scripting)", "Python (Snowpark)"])
        sp_name = sp2.text_input("Procedure Name", placeholder="sp_load_dim_customers")
        sp3, sp4 = st.columns(2)
        sp_target = sp3.text_input("Target Objects", placeholder="DB.SCHEMA.DIM_CUSTOMERS")
        sp_type = sp4.selectbox("Execution", ["CALLER", "OWNER"])
        sp_gen = st.form_submit_button("🤖 Generate Procedure", type="primary")

    if sp_gen and sp_desc:
        if not coco_ready: st.error("Cortex AI not available."); st.stop()
        lang = "snowflake_scripting" if "SQL" in sp_lang else "snowpark_python"
        prompt = f"""Generate a Snowflake stored procedure:
Name: {sp_name or 'my_procedure'}
Language: {lang}
Execute as: {sp_type}
Target: {sp_target or 'unspecified'}
Requirements: {sp_desc}

Include: error handling (TRY/CATCH), transaction management, audit logging, return value.
Follow security best practices: no ACCOUNTADMIN, use least-privilege roles."""
        with st.spinner("🤖 Generating procedure..."):
            result = coco.generate_stored_procedure(prompt) if hasattr(coco, 'generate_stored_procedure') else coco.write_script(prompt, "stored_procedure")
            if result:
                st.session_state.gen_proc = result
            else:
                st.error("Generation failed.")

    if st.session_state.get('gen_proc'):
        edited = st.text_area("Edit Procedure", value=st.session_state.gen_proc, height=400)
        pc1, pc2 = st.columns(2)
        if pc1.button("▶️ Create Procedure", type="primary"):
            try:
                client.execute_query(edited)
                st.success("✅ Procedure created!")
                st.session_state.gen_proc = None
            except Exception as e:
                st.error(f"❌ {e}")
        if pc2.button("🗑️ Clear", key="clear_proc"):
            st.session_state.gen_proc = None; st.rerun()

# ════════════════════════════════════════════════════════════════
# TAB 6: DMF Builder
# ════════════════════════════════════════════════════════════════
with tab6:
    st.markdown("### 📊 Data Metric Function (DMF) Builder")
    st.caption("Create native Snowflake DMFs for automated data quality monitoring.")

    dc1, dc2 = st.columns(2)
    with dc1:
        st.markdown("#### 🤖 AI-Generated DMF")
        with st.form("dmf_ai"):
            dmf_desc = st.text_area("Describe the quality check", height=100,
                placeholder="Check that the email column in customers table has valid email format (contains @ and .)")
            dmf_table = st.text_input("Target Table", placeholder="DB.SCHEMA.CUSTOMERS")
            dmf_col = st.text_input("Target Column", placeholder="EMAIL")
            if st.form_submit_button("🤖 Generate DMF", type="primary"):
                if coco_ready and dmf_desc:
                    with st.spinner("Generating DMF..."):
                        prompt = f"Generate a Snowflake Data Metric Function (DMF) for: {dmf_desc}\nTable: {dmf_table}\nColumn: {dmf_col}"
                        result = coco.generate_dmf(prompt) if hasattr(coco, 'generate_dmf') else coco.write_script(prompt, "dmf")
                        if result: st.session_state.gen_dmf = result

        if st.session_state.get('gen_dmf'):
            edited = st.text_area("Edit DMF", value=st.session_state.gen_dmf, height=250)
            if st.button("▶️ Create DMF", type="primary"):
                try:
                    client.execute_query(edited)
                    st.success("✅ DMF created!")
                    st.session_state.gen_dmf = None
                except Exception as e:
                    st.error(f"❌ {e}")

    with dc2:
        st.markdown("#### 📝 DMF Templates")
        dmf_templates = {
            "Null Count": """CREATE OR REPLACE DATA METRIC FUNCTION null_count_check(
    ARG_T TABLE(ARG_C VARCHAR))
RETURNS NUMBER AS 'SELECT COUNT_IF(ARG_C IS NULL) FROM ARG_T'""",
            "Duplicate Count": """CREATE OR REPLACE DATA METRIC FUNCTION duplicate_check(
    ARG_T TABLE(ARG_C VARCHAR))
RETURNS NUMBER AS 'SELECT COUNT(*) - COUNT(DISTINCT ARG_C) FROM ARG_T'""",
            "Value Range": """CREATE OR REPLACE DATA METRIC FUNCTION range_check(
    ARG_T TABLE(ARG_C NUMBER))
RETURNS NUMBER AS 'SELECT COUNT_IF(ARG_C < 0 OR ARG_C > 1000000) FROM ARG_T'""",
            "Freshness": """CREATE OR REPLACE DATA METRIC FUNCTION freshness_check(
    ARG_T TABLE(ARG_C TIMESTAMP_NTZ))
RETURNS NUMBER AS 'SELECT DATEDIFF(HOUR, MAX(ARG_C), CURRENT_TIMESTAMP()) FROM ARG_T'""",
        }
        for tname, tsql in dmf_templates.items():
            with st.expander(f"📋 {tname}"):
                st.code(tsql, language='sql')
                if st.button(f"▶️ Create {tname}", key=f"dmf_t_{tname}"):
                    try:
                        client.execute_query(tsql)
                        st.success(f"✅ {tname} DMF created!")
                    except Exception as e:
                        st.error(f"❌ {e}")
