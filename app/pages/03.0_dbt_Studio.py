"""
dbt Studio — In-Snowflake dbt Project Manager
Build, test, document, and deploy dbt-style transformation models
powered by Cortex AI (CoCo) for intelligent code generation.
"""
import streamlit as st
import pandas as pd
import json, time

# ── Page Config ──
st.set_page_config(page_title="dbt Studio", page_icon="🔧", layout="wide")

def init_client():
    if 'snowflake_client' not in st.session_state:
        st.error("⚠️ Not connected. Return to the main dashboard.")
        st.stop()
    return st.session_state.snowflake_client

def get_engines(client):
    from utils.dbt_engine import DbtEngine
    from utils.coco_client import CocoClient
    if 'dbt_engine' not in st.session_state:
        e = DbtEngine(client)
        e.ensure_tables()
        st.session_state.dbt_engine = e
    coco = None
    try:
        coco = CocoClient(client.session)
    except: pass
    return st.session_state.dbt_engine, coco

# ── Header ──
st.markdown("""
<style>
.dbt-header { background: linear-gradient(135deg, #FF694A 0%, #FF4500 100%); padding: 1.5rem 2rem; border-radius: 12px; margin-bottom: 1.5rem; }
.dbt-header h1 { color: white; margin: 0; font-size: 1.8rem; }
.dbt-header p { color: rgba(255,255,255,0.85); margin: 0.3rem 0 0; }
.layer-badge { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: 600; }
.layer-staging { background: #29B5E8; color: white; }
.layer-intermediate { background: #FFB020; color: #1a1a2e; }
.layer-marts { background: #00D4AA; color: #1a1a2e; }
.model-card { background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 1rem; margin: 0.5rem 0; }
.status-pass { color: #00D4AA; font-weight: bold; }
.status-fail { color: #FF4444; font-weight: bold; }
</style>
<div class="dbt-header">
    <h1>🔧 dbt Studio</h1>
    <p>Build, test & deploy transformation models — powered by Cortex AI</p>
</div>
""", unsafe_allow_html=True)

client = init_client()
dbt, coco = get_engines(client)

# ── Sidebar: Project Selector ──
with st.sidebar:
    st.markdown("### 📁 dbt Projects")
    projects = dbt.list_projects()

    if st.button("➕ New Project", use_container_width=True, type="primary"):
        st.session_state.show_new_project = True

    if st.session_state.get('show_new_project'):
        with st.form("new_project_form"):
            pname = st.text_input("Project Name", placeholder="analytics_warehouse")
            pdb = st.text_input("Target Database", placeholder="ANALYTICS")
            pschema = st.text_input("Target Schema", value="PUBLIC")
            pdesc = st.text_area("Description", height=60)
            if st.form_submit_button("Create Project"):
                if pname and pdb:
                    pid = dbt.create_project(pname, pdb, pschema, pdesc)
                    st.success(f"✅ Created project: {pname}")
                    st.session_state.active_project = pid
                    st.session_state.show_new_project = False
                    st.rerun()

    if not projects.empty:
        project_map = {f"{r['PROJECT_NAME']} ({r['TARGET_DATABASE']})": r['PROJECT_ID'] for _, r in projects.iterrows()}
        selected = st.selectbox("Select Project", list(project_map.keys()))
        st.session_state.active_project = project_map.get(selected)
    else:
        st.info("No projects yet. Create one above!")

# ── Main Content ──
pid = st.session_state.get('active_project')
if not pid:
    st.info("👈 Create or select a project from the sidebar to get started.")
    st.stop()

project = dbt.get_project(pid)
if not project:
    st.error("Project not found."); st.stop()

# ── Tabs ──
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["📊 Models", "🤖 AI Builder", "🧪 Testing", "📖 Docs", "🚀 Deploy", "📦 Versions"])

# ════════════════════════════════════════════════════════════════════
# TAB 1: Model Explorer
# ════════════════════════════════════════════════════════════════════
with tab1:
    models = dbt.list_models(pid)
    sources = dbt.list_sources(pid)

    col1, col2, col3, col4 = st.columns(4)
    model_count = len(models) if not models.empty else 0
    source_count = len(sources) if not sources.empty else 0
    success = len(models[models['LAST_RUN_STATUS'] == 'SUCCESS']) if not models.empty and 'LAST_RUN_STATUS' in models.columns else 0
    failed = len(models[models['LAST_RUN_STATUS'] == 'FAILED']) if not models.empty and 'LAST_RUN_STATUS' in models.columns else 0
    col1.metric("Models", model_count)
    col2.metric("Sources", source_count)
    col3.metric("✅ Success", success)
    col4.metric("❌ Failed", failed)

    st.markdown("---")

    c1, c2 = st.columns([1, 2])
    with c1:
        st.markdown("### 📂 Model Tree")
        for layer in ['staging', 'intermediate', 'marts']:
            layer_models = models[models['LAYER'].str.lower() == layer] if not models.empty else pd.DataFrame()
            badge = f'<span class="layer-badge layer-{layer}">{layer.upper()}</span>'
            st.markdown(f"{badge} ({len(layer_models)})", unsafe_allow_html=True)
            for _, m in layer_models.iterrows():
                icon = {"SUCCESS": "✅", "FAILED": "❌"}.get(m.get('LAST_RUN_STATUS', ''), "⬜")
                mat = f"({m['MATERIALIZATION']})" if m.get('MATERIALIZATION') else ""
                if st.button(f"{icon} {m['MODEL_NAME']} {mat}", key=f"sel_{m['MODEL_ID']}",
                            use_container_width=True):
                    st.session_state.selected_model = m['MODEL_ID']

        st.markdown("---")
        st.markdown("### 📥 Sources")
        if not sources.empty:
            for _, s in sources.iterrows():
                st.markdown(f"🔗 `{s['DATABASE_NAME']}.{s['SCHEMA_NAME']}.{s['TABLE_NAME']}`")
        else:
            st.caption("No sources defined")

    with c2:
        mid = st.session_state.get('selected_model')
        if mid:
            model = dbt.get_model(mid)
            if model:
                st.markdown(f"### {model['MODEL_NAME']}")
                st.caption(model.get('DESCRIPTION', ''))

                mc1, mc2, mc3, mc4 = st.columns(4)
                mc1.metric("Layer", model.get('LAYER', '?'))
                mc2.metric("Materialization", model.get('MATERIALIZATION', '?'))
                mc4.metric("Version", model.get('VERSION', 1))

                # Name linting
                lint_issues = dbt.lint_model_name(model['MODEL_NAME'], model.get('LAYER','staging'))
                if lint_issues:
                    for li in lint_issues: st.warning(f"⚠️ {li}")
                status = model.get('LAST_RUN_STATUS', 'Never')
                mc3.metric("Last Run", status)

                st.markdown("#### SQL")
                edited_sql = st.code(model.get('SQL_BODY', ''), language='sql')

                bc1, bc2, bc3, bc4 = st.columns(4)
                if bc1.button("▶️ Run", key="run_single", type="primary"):
                    with st.spinner("Executing model..."):
                        r = dbt.run_model(mid)
                        if r['status'] == 'SUCCESS':
                            st.success(f"✅ {r.get('rows', 0)} rows in {r.get('duration_ms', 0)}ms")
                        else:
                            st.error(f"❌ {r.get('error', 'Unknown error')}")
                            if coco and coco.is_available:
                                with st.expander("🤖 AI Diagnosis"):
                                    fix = coco.explain_error(r.get('error', ''), model.get('SQL_BODY', ''))
                                    if fix: st.markdown(fix)

                if bc2.button("🧪 Test", key="test_single"):
                    results = dbt.test_model(mid)
                    for t in results:
                        icon = "✅" if t['status'] == 'PASS' else "❌"
                        st.markdown(f"{icon} {t['test']}: {t['status']} ({t.get('failures', 0)} failures)")

                if bc3.button("🗑️ Delete", key="del_model"):
                    dbt.delete_model(mid)
                    st.session_state.selected_model = None
                    st.rerun()
        else:
            # DAG Visualization
            st.markdown("### 🔀 Model DAG")
            dag = dbt.get_dag(pid)
            if dag['nodes']:
                # Render as mermaid-like text DAG
                st.markdown("```")
                for node in dag['nodes']:
                    st.text(f"  [{node['layer'].upper()}] {node['label']}")
                for edge in dag['edges']:
                    src = next((n['label'] for n in dag['nodes'] if n['id'] == edge['from']), '?')
                    tgt = next((n['label'] for n in dag['nodes'] if n['id'] == edge['to']), '?')
                    st.text(f"    {src} ──▶ {tgt}")
                st.markdown("```")
            else:
                st.info("Select a model from the tree, or use AI Builder to create one.")

# ════════════════════════════════════════════════════════════════════
# TAB 2: AI Builder
# ════════════════════════════════════════════════════════════════════
with tab2:
    st.markdown("### 🤖 AI-Powered Model Builder")
    if not coco or not coco.is_available:
        st.warning("⚠️ Cortex AI not available. You can still create models manually below.")

    with st.form("ai_model_form"):
        description = st.text_area("Describe the model", placeholder="Create a staging model that cleans customer data from RAW.PUBLIC.CUSTOMERS — rename columns to snake_case, cast dates, filter out test accounts")
        ac1, ac2 = st.columns(2)
        layer = ac1.selectbox("Layer", ["staging", "intermediate", "marts"])
        materialization = ac2.selectbox("Materialization", ["view", "table", "dynamic_table", "incremental"])
        if materialization == 'incremental':
            unique_key = st.text_input("Unique Key (for MERGE)", placeholder="ID")
        else:
            unique_key = None

        st.markdown("**Source Tables** (one per line)")
        src_text = st.text_area("Sources", placeholder="RAW.PUBLIC.CUSTOMERS\nRAW.PUBLIC.ORDERS", height=80)
        generate = st.form_submit_button("🤖 Generate Model", type="primary")

    if generate and description:
        src_tables = [s.strip() for s in src_text.strip().split('\n') if s.strip()]
        if coco and coco.is_available:
            with st.spinner("🤖 CoCo is generating your model..."):
                result = coco.generate_dbt_model(description, src_tables, layer, materialization)
                if result and isinstance(result, dict):
                    st.session_state.ai_generated = result
                else:
                    st.error("AI generation failed. Please try again or write manually.")
        else:
            st.info("Cortex AI not available — use the manual model form below.")

    if st.session_state.get('ai_generated'):
        gen = st.session_state.ai_generated
        st.success(f"✅ Generated: **{gen.get('model_name', 'model')}**")
        st.markdown(f"*{gen.get('description', '')}*")
        sql = gen.get('sql', '')
        edited = st.text_area("Edit SQL", value=sql, height=300)
        name = st.text_input("Model Name", value=gen.get('model_name', ''))

        if st.button("💾 Save Model", type="primary"):
            mid = dbt.create_model(
                project_id=pid, name=name, sql=edited, layer=layer,
                materialization=materialization, description=gen.get('description', ''),
                dependencies=gen.get('dependencies'), tests=gen.get('tests'),
                columns_meta=gen.get('columns'),
                unique_key=unique_key if materialization == 'incremental' else None)
            st.success(f"✅ Model saved: {name}")
            st.session_state.ai_generated = None
            st.session_state.selected_model = mid
            st.rerun()

    st.markdown("---")
    st.markdown("### ✍️ Manual Model Builder")
    with st.form("manual_model"):
        mm_name = st.text_input("Model Name", placeholder="stg_raw__customers")
        mm_layer = st.selectbox("Layer", ["staging", "intermediate", "marts"], key="mm_layer")
        mm_mat = st.selectbox("Materialization", ["view", "table", "dynamic_table"], key="mm_mat")
        mm_sql = st.text_area("SQL", height=200, placeholder="SELECT\n    customer_id,\n    LOWER(email) AS email\nFROM {{ source('raw', 'customers') }}")
        mm_desc = st.text_input("Description")
        if st.form_submit_button("💾 Save"):
            if mm_name and mm_sql:
                mid = dbt.create_model(pid, mm_name, mm_sql, mm_layer, mm_mat, mm_desc)
                st.success(f"✅ Model created: {mm_name}")
                st.rerun()

# ════════════════════════════════════════════════════════════════════
# TAB 3: Testing
# ════════════════════════════════════════════════════════════════════
with tab3:
    st.markdown("### 🧪 Data Quality Testing")
    models = dbt.list_models(pid)

    if models.empty:
        st.info("Create models first to run tests.")
    else:
        tc1, tc2 = st.columns([1, 2])
        with tc1:
            model_names = {r['MODEL_NAME']: r['MODEL_ID'] for _, r in models.iterrows()}
            sel_model = st.selectbox("Select Model", list(model_names.keys()))
            sel_mid = model_names.get(sel_model)

            if st.button("▶️ Run All Tests", type="primary"):
                with st.spinner("Running tests..."):
                    results = dbt.test_model(sel_mid)
                    st.session_state.test_results = results

            # Add test form
            st.markdown("#### ➕ Add Test")
            with st.form("add_test"):
                model = dbt.get_model(sel_mid) if sel_mid else None
                test_col = st.text_input("Column Name")
                test_type = st.selectbox("Test Type", ["not_null", "unique", "accepted_values", "recency", "relationships"])
                if st.form_submit_button("Add Test"):
                    if model:
                        current_tests = model.get('TESTS', []) or []
                        current_tests.append({"column": test_col, "test": test_type, "config": {}})
                        dbt.update_model(sel_mid, tests=current_tests)
                        st.success(f"Added {test_type} test on {test_col}")
                        st.rerun()

        with tc2:
            if 'test_results' in st.session_state:
                results = st.session_state.test_results
                passed = sum(1 for r in results if r['status'] == 'PASS')
                failed = sum(1 for r in results if r['status'] == 'FAIL')
                st.metric("Results", f"{passed} passed, {failed} failed")
                for r in results:
                    icon = {"PASS": "✅", "FAIL": "❌", "ERROR": "⚠️"}.get(r['status'], "?")
                    st.markdown(f"{icon} **{r['test']}** — {r['status']} ({r.get('failures', 0)} failures)")

            if coco and coco.is_available:
                st.markdown("---")
                if st.button("🤖 AI Suggest Tests"):
                    model = dbt.get_model(sel_mid)
                    if model:
                        with st.spinner("Analyzing model..."):
                            suggestions = coco.suggest_dbt_tests(model.get('SQL_BODY', ''), ['*'])
                            if suggestions:
                                for s in suggestions:
                                    st.markdown(f"💡 `{s.get('test', '?')}` on `{s.get('column', '?')}`")

# ════════════════════════════════════════════════════════════════════
# TAB 4: Documentation
# ════════════════════════════════════════════════════════════════════
with tab4:
    st.markdown("### 📖 Model Documentation")
    models = dbt.list_models(pid)
    if models.empty:
        st.info("No models to document yet.")
    else:
        for _, m in models.iterrows():
            with st.expander(f"📄 {m['MODEL_NAME']} ({m['LAYER']})"):
                st.markdown(f"**Description:** {m.get('DESCRIPTION', 'No description')}")
                st.markdown(f"**Materialization:** `{m.get('MATERIALIZATION', '?')}`")
                st.markdown(f"**Last Run:** {m.get('LAST_RUN_STATUS', 'Never')} at {m.get('LAST_RUN_AT', 'N/A')}")
                cols = m.get('COLUMNS_META')
                if cols:
                    if isinstance(cols, str):
                        try: cols = json.loads(cols)
                        except: cols = []
                    if cols:
                        st.markdown("**Columns:**")
                        col_df = pd.DataFrame(cols)
                        st.dataframe(col_df, use_container_width=True)

                if coco and coco.is_available:
                    if st.button(f"🤖 Auto-Document", key=f"doc_{m['MODEL_ID']}"):
                        with st.spinner("Generating documentation..."):
                            docs = coco.generate_dbt_docs(m.get('SQL_BODY', ''), m['MODEL_NAME'])
                            if docs:
                                dbt.update_model(m['MODEL_ID'],
                                    description=docs.get('description', ''),
                                    columns_meta=docs.get('columns', []))
                                st.success("✅ Documentation generated!")
                                st.rerun()

# ════════════════════════════════════════════════════════════════════
# TAB 5: Deploy
# ════════════════════════════════════════════════════════════════════
with tab5:
    st.markdown("### 🚀 Deploy Project")
    st.markdown(f"**Target:** `{project['TARGET_DATABASE']}.{project.get('TARGET_SCHEMA', 'PUBLIC')}`")

    dc1, dc2 = st.columns(2)
    env = dc1.selectbox("Environment", ["DEV", "STAGING", "PROD"])
    target_schema = dc2.text_input("Target Schema Override", value=f"{env}_{project.get('TARGET_SCHEMA', 'PUBLIC')}")

    models = dbt.list_models(pid)
    if models.empty:
        st.info("No models to deploy.")
    else:
        st.markdown(f"**{len(models)} models** will be deployed:")
        for layer in ['staging', 'intermediate', 'marts']:
            lm = models[models['LAYER'].str.lower() == layer] if not models.empty else pd.DataFrame()
            if not lm.empty:
                st.markdown(f"- **{layer.upper()}**: {', '.join(lm['MODEL_NAME'].tolist())}")

        cc1, cc2 = st.columns(2)
        if cc1.button("🔍 Dry Run (Preview)", use_container_width=True):
            st.info(f"Would create {len(models)} objects in `{project['TARGET_DATABASE']}.{target_schema}`")
            for _, m in models.iterrows():
                mat = m['MATERIALIZATION'].upper()
                st.code(f"-- {mat}: {project['TARGET_DATABASE']}.{target_schema}.{m['MODEL_NAME']}")

        slim_ci = st.checkbox("🏎️ Slim CI (modified models only)", value=False)

        if cc2.button("🚀 Deploy Now", use_container_width=True, type="primary"):
            progress = st.progress(0)
            status = st.empty()
            status.markdown("⏳ Computing topological order...")
            results = dbt.run_project(pid, target_schema, modified_only=slim_ci)
            for i, r in enumerate(results):
                progress.progress((i + 1) / max(len(results), 1))

            success = sum(1 for r in results if r['status'] == 'SUCCESS')
            failed = sum(1 for r in results if r['status'] != 'SUCCESS')
            if failed == 0:
                st.success(f"✅ All {success} models deployed successfully!")
                st.balloons()
            else:
                st.warning(f"⚠️ {success} succeeded, {failed} failed")
                for r in results:
                    icon = "✅" if r['status'] == 'SUCCESS' else "❌"
                    msg = f"{icon} **{r['model_name']}**"
                    if r.get('error'): msg += f" — {r['error'][:100]}"
                    elif r.get('rows') is not None: msg += f" — {r['rows']} rows, {r['duration_ms']}ms"
                    st.markdown(msg)

# ════════════════════════════════════════════════════════════════════
# TAB 6: Versions & Freshness
# ════════════════════════════════════════════════════════════════════
with tab6:
    st.markdown("### 📦 Model Versions & Source Freshness")

    vc1, vc2 = st.columns(2)
    with vc1:
        st.markdown("#### 📜 Model Version History")
        models = dbt.list_models(pid)
        if not models.empty:
            model_names = {r['MODEL_NAME']: r['MODEL_ID'] for _, r in models.iterrows()}
            sel = st.selectbox("Select Model", list(model_names.keys()), key="ver_model")
            sel_mid = model_names.get(sel)
            if sel_mid:
                versions = dbt.get_model_versions(sel_mid)
                if not versions.empty:
                    for _, v in versions.iterrows():
                        with st.expander(f"v{v.get('VERSION', '?')} — {v.get('CREATED_AT', '')}"):
                            st.caption(f"By: {v.get('CHANGED_BY', '?')} | {v.get('CHANGE_SUMMARY', '')}")
                            st.code(v.get('SQL_BODY', '')[:2000], language='sql')
                else:
                    st.info("No version history for this model.")

    with vc2:
        st.markdown("#### 🕐 Source Freshness")
        if st.button("🔄 Check Freshness"):
            with st.spinner("Checking source freshness..."):
                freshness = dbt.check_source_freshness(pid)
                if freshness:
                    for f in freshness:
                        icon = {"FRESH": "🟢", "WARN": "🟡", "ERROR": "🔴"}.get(f.get('status', ''), "⚪")
                        st.markdown(f"{icon} **{f.get('source','')}**.{f.get('table','')} — Latest: {f.get('latest','?')}")
                else:
                    st.info("No sources with `loaded_at_field` configured.")

# ── Add Source Dialog ──
with st.sidebar:
    st.markdown("---")
    st.markdown("### ➕ Add Source")
    with st.form("add_source"):
        src_name = st.text_input("Source Name", placeholder="raw")
        src_db = st.text_input("Database", placeholder="RAW_DATA")
        src_sch = st.text_input("Schema", placeholder="PUBLIC")
        src_tbl = st.text_input("Table", placeholder="CUSTOMERS")
        if st.form_submit_button("Add Source"):
            if src_name and src_db and src_tbl:
                dbt.add_source(pid, src_name, src_db, src_sch or "PUBLIC", src_tbl)
                st.success(f"✅ Added source: {src_db}.{src_sch}.{src_tbl}")
                st.rerun()

    # Quick discover
    if st.button("🔍 Discover Tables"):
        disc = dbt.discover_tables(limit=20)
        if not disc.empty:
            for _, r in disc.iterrows():
                st.caption(f"`{r['TABLE_CATALOG']}.{r['TABLE_SCHEMA']}.{r['TABLE_NAME']}`")
