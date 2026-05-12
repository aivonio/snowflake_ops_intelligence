"""
Pipeline Builder — Visual Pipeline Designer, Monitor & Debugger
Create, deploy, monitor, and debug Snowflake data pipelines
(Tasks, Dynamic Tables, Streams, Snowpipe) with AI assistance.
"""
import streamlit as st
import pandas as pd
import json

st.set_page_config(page_title="Pipeline Builder", page_icon="🔄", layout="wide")

def init():
    if 'snowflake_client' not in st.session_state:
        st.error("⚠️ Not connected."); st.stop()
    return st.session_state.snowflake_client

def get_engines(client):
    from app.utils.pipeline_engine import PipelineEngine
    from app.utils.coco_client import CocoClient
    if 'pipeline_engine' not in st.session_state:
        e = PipelineEngine(client)
        e.ensure_tables()
        st.session_state.pipeline_engine = e
    coco = None
    try: coco = CocoClient(client.session)
    except: pass
    return st.session_state.pipeline_engine, coco

# ── Header ──
st.markdown("""
<style>
.pipe-header { background: linear-gradient(135deg, #6366F1 0%, #8B5CF6 50%, #A855F7 100%); padding: 1.5rem 2rem; border-radius: 12px; margin-bottom: 1.5rem; }
.pipe-header h1 { color: white; margin: 0; font-size: 1.8rem; }
.pipe-header p { color: rgba(255,255,255,0.85); margin: 0.3rem 0 0; }
.step-card { background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 1rem; margin: 0.5rem 0; }
.status-healthy { color: #00D4AA; } .status-failed { color: #FF4444; } .status-suspended { color: #FFB020; }
</style>
<div class="pipe-header">
    <h1>🔄 Pipeline Builder</h1>
    <p>Design, deploy, monitor & debug Snowflake data pipelines</p>
</div>
""", unsafe_allow_html=True)

client = init()
engine, coco = get_engines(client)

tab1, tab2, tab3, tab4 = st.tabs(["🏗️ Build Pipeline", "📋 Registry", "🐛 Debugger", "📊 Monitor"])

# ════════════════════════════════════════════════════════════════════
# TAB 1: Pipeline Builder
# ════════════════════════════════════════════════════════════════════
with tab1:
    st.markdown("### 🏗️ Pipeline Designer")
    mode = st.radio("Build Mode", ["🤖 AI-Assisted", "📝 Template", "✍️ Manual"], horizontal=True)

    if mode == "🤖 AI-Assisted":
        st.markdown("Describe your pipeline in plain English — CoCo will design it.")
        with st.form("ai_pipeline"):
            desc = st.text_area("Pipeline Description", height=100,
                placeholder="Build a CDC pipeline that captures changes from RAW.SALES.ORDERS, merges into ANALYTICS.DW.FACT_ORDERS using ORDER_ID as key, runs every 5 minutes")
            ac1, ac2 = st.columns(2)
            src = ac1.text_input("Source Tables (comma-sep)", placeholder="RAW.SALES.ORDERS, RAW.SALES.CUSTOMERS")
            tgt = ac2.text_input("Target Table", placeholder="ANALYTICS.DW.FACT_ORDERS")
            generate = st.form_submit_button("🤖 Design Pipeline", type="primary")

        if generate and desc:
            if coco and coco.is_available:
                with st.spinner("🤖 CoCo is designing your pipeline..."):
                    src_list = [s.strip() for s in src.split(',') if s.strip()] if src else None
                    config = coco.generate_pipeline_config(desc, src_list, tgt or None)
                    if config:
                        st.session_state.ai_pipeline = config
                    else:
                        st.error("Pipeline generation failed.")
            else:
                st.warning("Cortex AI not available. Use Template or Manual mode.")

        if st.session_state.get('ai_pipeline'):
            pipe = st.session_state.ai_pipeline
            st.success(f"✅ Pipeline: **{pipe.get('pipeline_name', 'Unnamed')}** ({pipe.get('pipeline_type', '?')})")

            steps = pipe.get('steps', [])
            for i, step in enumerate(steps):
                with st.expander(f"Step {i+1}: {step.get('step_name', step.get('name', '?'))}", expanded=True):
                    st.markdown(f"**Type:** {step.get('step_type', step.get('type', '?'))}")
                    sql = step.get('sql', '')
                    st.code(sql, language='sql')
                    if step.get('config'):
                        st.json(step['config'])

            recs = pipe.get('recommendations', [])
            if recs:
                st.markdown("#### 💡 Recommendations")
                for r in recs:
                    st.markdown(f"- {r}")

            pc1, pc2 = st.columns(2)
            pname = pc1.text_input("Pipeline Name", value=pipe.get('pipeline_name', ''))
            pdesc = pc2.text_input("Description", value=f"AI-generated {pipe.get('pipeline_type', '')} pipeline")
            if st.button("💾 Save & Deploy", type="primary"):
                pid = engine.save_pipeline(pname, pipe.get('pipeline_type', 'custom'), pipe, pdesc)
                result = engine.deploy_pipeline(pid)
                if result['status'] == 'SUCCESS':
                    st.success("✅ Pipeline deployed!")
                    st.session_state.ai_pipeline = None
                    st.balloons()
                else:
                    st.error(f"Deployment failed: {result.get('results', [])}")

    elif mode == "📝 Template":
        st.markdown("Use pre-built pipeline templates.")
        template = st.selectbox("Template", [
            "CDC (Change Data Capture)", "Incremental Load", "Dynamic Table Chain",
            "SCD Type 2 (Slowly Changing)", "Event Streaming", "Task Graph (DAG)"
        ])

        if template == "CDC (Change Data Capture)":
            with st.form("cdc_form"):
                st.markdown("**CDC Pipeline** — Captures changes via Stream + MERGE Task")
                c1, c2 = st.columns(2)
                src = c1.text_input("Source Table", placeholder="RAW.PUBLIC.ORDERS")
                tgt = c2.text_input("Target Table", placeholder="ANALYTICS.PUBLIC.FACT_ORDERS")
                keys = st.text_input("Primary Keys (comma-sep)", placeholder="ORDER_ID")
                wh = st.text_input("Warehouse", value="COMPUTE_WH")
                if st.form_submit_button("Generate CDC Pipeline", type="primary"):
                    key_list = [k.strip() for k in keys.split(',')]
                    pipe = engine.create_cdc_pipeline(src, tgt, key_list, wh)
                    st.session_state.template_pipeline = pipe

        elif template == "Incremental Load":
            with st.form("incr_form"):
                st.markdown("**Incremental Load** — Loads only new/changed records")
                c1, c2 = st.columns(2)
                src = c1.text_input("Source Table", placeholder="RAW.PUBLIC.EVENTS")
                tgt = c2.text_input("Target Table", placeholder="ANALYTICS.PUBLIC.EVENTS")
                incr_key = st.text_input("Incremental Key", placeholder="CREATED_AT")
                wh = st.text_input("Warehouse", value="COMPUTE_WH")
                if st.form_submit_button("Generate Pipeline", type="primary"):
                    pipe = engine.create_incremental_pipeline(src, tgt, incr_key, wh)
                    st.session_state.template_pipeline = pipe

        elif template == "Dynamic Table Chain":
            with st.form("dt_form"):
                st.markdown("**Dynamic Table Chain** — Declarative SQL pipeline")
                src = st.text_input("Source Table", placeholder="RAW.PUBLIC.EVENTS")
                tgt = st.text_input("Target Table Name", placeholder="DIM_EVENTS")
                sql = st.text_area("Transformation SQL", height=150, placeholder="SELECT\n    EVENT_ID,\n    EVENT_TYPE,\n    CREATED_AT::DATE AS EVENT_DATE\nFROM RAW.PUBLIC.EVENTS")
                lag = st.selectbox("Target Lag", ["1 minute", "5 minutes", "15 minutes", "1 hour", "1 day"])
                wh = st.text_input("Warehouse", value="COMPUTE_WH")
                if st.form_submit_button("Create Dynamic Table", type="primary"):
                    r = engine.create_dynamic_table(tgt, sql, lag, wh)
                    if r['status'] == 'SUCCESS':
                        st.success(f"✅ Dynamic Table created: {r['object']}")
                    else:
                        st.error(f"❌ {r['error']}")

        elif template == "SCD Type 2 (Slowly Changing)":
            with st.form("scd2_form"):
                st.markdown("**SCD Type 2** — Track historical changes with validity windows")
                c1, c2 = st.columns(2)
                src = c1.text_input("Source Table", placeholder="RAW.PUBLIC.CUSTOMERS")
                tgt = c2.text_input("Target Table", placeholder="ANALYTICS.PUBLIC.DIM_CUSTOMERS")
                keys = st.text_input("Business Keys (comma-sep)", placeholder="CUSTOMER_ID")
                wh = st.text_input("Warehouse", value="COMPUTE_WH", key="scd2_wh")
                if st.form_submit_button("Generate SCD2 Pipeline", type="primary"):
                    key_list = [k.strip() for k in keys.split(',')]
                    pipe = engine.create_scd2_pipeline(src, tgt, key_list, wh)
                    st.session_state.template_pipeline = pipe

        elif template == "Event Streaming":
            with st.form("evt_form"):
                st.markdown("**Event Streaming** — Real-time append-only stream processing")
                c1, c2 = st.columns(2)
                src = c1.text_input("Source Table", placeholder="RAW.PUBLIC.EVENTS")
                tgt = c2.text_input("Target Table", placeholder="ANALYTICS.PUBLIC.EVENTS_PROCESSED")
                wh = st.text_input("Warehouse", value="COMPUTE_WH", key="evt_wh")
                if st.form_submit_button("Generate Event Pipeline", type="primary"):
                    pipe = engine.create_event_streaming_pipeline(src, tgt, wh)
                    st.session_state.template_pipeline = pipe

        elif template == "Task Graph (DAG)":
            st.markdown("**Task Graph** — Multi-step DAG with dependencies")
            with st.form("dag_form"):
                dag_name = st.text_input("DAG Name", placeholder="daily_etl")
                num_tasks = st.number_input("Number of tasks", 2, 10, 3)
                wh = st.text_input("Warehouse", value="COMPUTE_WH", key="dag_wh")
                c1, c2 = st.columns(2)
                db = c1.text_input("Database", placeholder="ANALYTICS")
                sch = c2.text_input("Schema", value="PUBLIC")
                tasks = []
                for i in range(int(num_tasks)):
                    st.markdown(f"**Task {i+1}**")
                    tc1, tc2 = st.columns(2)
                    tname = tc1.text_input(f"Name", key=f"dag_t{i}_name", placeholder=f"task_{i+1}")
                    tafter = tc2.text_input(f"After (dep)", key=f"dag_t{i}_after", placeholder="task_1" if i > 0 else "")
                    tsql = st.text_area(f"SQL", key=f"dag_t{i}_sql", height=80)
                    tsched = st.text_input(f"Schedule", key=f"dag_t{i}_sched", placeholder="USING CRON 0 6 * * * UTC" if i == 0 else "")
                    tasks.append({"name": tname, "sql": tsql, "schedule": tsched if tsched else None, "after": [tafter] if tafter else None})
                if st.form_submit_button("🚀 Create Task Graph", type="primary"):
                    valid_tasks = [t for t in tasks if t['name'] and t['sql']]
                    if valid_tasks:
                        r = engine.create_task_graph(dag_name, valid_tasks, wh, db, sch)
                        st.session_state.template_pipeline = None
                        successes = sum(1 for s in r['results'] if s.get('status') == 'SUCCESS')
                        st.success(f"✅ DAG '{dag_name}' created: {successes}/{len(valid_tasks)} tasks")
                        for s in r['results']:
                            icon = "✅" if s.get('status') == 'SUCCESS' else "❌"
                            st.markdown(f"{icon} {s.get('task_name','?')}")

        if st.session_state.get('template_pipeline'):
            pipe = st.session_state.template_pipeline
            st.markdown(f"### Generated: {pipe['pipeline_type']} Pipeline")
            for step in pipe['steps']:
                with st.expander(f"📝 {step['name']}", expanded=True):
                    st.code(step['sql'], language='sql')
            if st.button("🚀 Execute All Steps", type="primary"):
                for step in pipe['steps']:
                    try:
                        client.execute_query(step['sql'])
                        st.success(f"✅ {step['name']}")
                    except Exception as e:
                        st.error(f"❌ {step['name']}: {e}")
                        break

    elif mode == "✍️ Manual":
        st.markdown("Build a pipeline step by step.")
        obj_type = st.selectbox("Object Type", ["Task", "Dynamic Table", "Stream"])

        if obj_type == "Task":
            with st.form("task_form"):
                c1, c2 = st.columns(2)
                name = c1.text_input("Task Name")
                wh = c2.text_input("Warehouse", value="COMPUTE_WH")
                c3, c4 = st.columns(2)
                schedule = c3.text_input("Schedule", placeholder="USING CRON 0 * * * * UTC")
                after = c4.text_input("After Task (optional)", placeholder="PARENT_TASK")
                sql = st.text_area("SQL Statement", height=200)
                if st.form_submit_button("Create Task", type="primary"):
                    r = engine.create_task(name, sql, schedule, wh, after if after else None)
                    if r['status'] == 'SUCCESS': st.success(f"✅ Task created: {r['task']}")
                    else: st.error(f"❌ {r['error']}")

        elif obj_type == "Dynamic Table":
            with st.form("dt_manual"):
                c1, c2 = st.columns(2)
                name = c1.text_input("Table Name")
                lag = c2.selectbox("Target Lag", ["1 minute","5 minutes","1 hour","1 day"])
                wh = st.text_input("Warehouse", value="COMPUTE_WH")
                sql = st.text_area("Query", height=200)
                if st.form_submit_button("Create", type="primary"):
                    r = engine.create_dynamic_table(name, sql, lag, wh)
                    if r['status'] == 'SUCCESS': st.success(f"✅ {r['object']}")
                    else: st.error(f"❌ {r['error']}")

        elif obj_type == "Stream":
            with st.form("stream_form"):
                c1, c2 = st.columns(2)
                name = c1.text_input("Stream Name")
                source = c2.text_input("Source Table")
                mode = st.selectbox("Mode", ["DEFAULT", "APPEND_ONLY"])
                if st.form_submit_button("Create", type="primary"):
                    r = engine.create_stream(name, source, mode)
                    if r['status'] == 'SUCCESS': st.success(f"✅ {r['stream']}")
                    else: st.error(f"❌ {r['error']}")

# ════════════════════════════════════════════════════════════════════
# TAB 2: Pipeline Registry
# ════════════════════════════════════════════════════════════════════
with tab2:
    st.markdown("### 📋 Pipeline Objects Registry")

    reg_tab = st.radio("Object Type", ["Saved Pipelines", "Tasks", "Dynamic Tables", "Streams", "Pipes"], horizontal=True)

    if reg_tab == "Saved Pipelines":
        pipes = engine.list_pipelines()
        if pipes.empty:
            st.info("No saved pipelines. Build one in the Build tab!")
        else:
            for _, p in pipes.iterrows():
                status_color = {"DEPLOYED":"status-healthy","FAILED":"status-failed","DRAFT":"status-suspended"}.get(p.get('STATUS',''),"")
                st.markdown(f"""<div class="step-card">
                    <strong>{p['PIPELINE_NAME']}</strong> <span class="{status_color}">● {p.get('STATUS','?')}</span><br>
                    <small>Type: {p.get('PIPELINE_TYPE','?')} | Created: {p.get('CREATED_AT','?')}</small>
                </div>""", unsafe_allow_html=True)

    elif reg_tab == "Tasks":
        tasks = engine.list_tasks()
        if tasks.empty: st.info("No tasks found.")
        else:
            name_col = 'name' if 'name' in tasks.columns else 'NAME'
            state_col = 'state' if 'state' in tasks.columns else 'STATE'
            for _, t in tasks.iterrows():
                state = t.get(state_col, '?')
                color = "status-healthy" if state == "started" else "status-suspended"
                st.markdown(f"<span class='{color}'>●</span> **{t.get(name_col, '?')}** — {state}", unsafe_allow_html=True)
                c1, c2 = st.columns([1,4])
                if state == "started":
                    if c1.button("⏸️ Suspend", key=f"sus_{t.get(name_col,'')}"): engine.suspend_task(t[name_col])
                else:
                    if c1.button("▶️ Resume", key=f"res_{t.get(name_col,'')}"): engine.resume_task(t[name_col])

    elif reg_tab == "Dynamic Tables":
        dts = engine.list_dynamic_tables()
        if dts.empty: st.info("No dynamic tables found.")
        else: st.dataframe(dts, use_container_width=True)

    elif reg_tab == "Streams":
        streams = engine.list_streams()
        if streams.empty: st.info("No streams found.")
        else: st.dataframe(streams, use_container_width=True)

    elif reg_tab == "Pipes":
        pipes_obj = engine.list_pipes()
        if pipes_obj.empty: st.info("No pipes found.")
        else: st.dataframe(pipes_obj, use_container_width=True)

# ════════════════════════════════════════════════════════════════════
# TAB 3: Pipeline Debugger
# ════════════════════════════════════════════════════════════════════
with tab3:
    st.markdown("### 🐛 Pipeline Debugger")
    st.markdown("Analyze failed pipelines and get AI-powered fix suggestions.")

    dc1, dc2 = st.columns(2)
    hours = dc1.slider("Look back (hours)", 1, 168, 24)
    auto_fix = dc2.checkbox("Show AI fix suggestions", value=True)

    failed = engine.get_failed_tasks(hours)
    if failed.empty:
        st.success(f"✅ No failed tasks in the last {hours} hours!")
    else:
        st.warning(f"⚠️ {len(failed)} failed task runs found")

        for _, f_row in failed.iterrows():
            task_name = f_row.get('NAME', '?')
            error_msg = f_row.get('ERROR_MESSAGE', 'No message')
            error_code = str(f_row.get('ERROR_CODE', '?'))
            query_text = f_row.get('QUERY_TEXT', '')
            scheduled = f_row.get('SCHEDULED_TIME', '?')

            with st.expander(f"❌ {task_name} — {str(scheduled)[:19]}", expanded=False):
                st.markdown(f"**Error Code:** `{error_code}`")
                st.markdown(f"**Error:** {error_msg}")
                if query_text:
                    st.code(str(query_text)[:1000], language='sql')

                # Compare with last success
                if st.button(f"📊 Compare Runs", key=f"cmp_{task_name}_{scheduled}"):
                    comp = engine.compare_runs(task_name)
                    if comp.get('last_success'):
                        st.markdown("**Last Successful Run:**")
                        st.json({k: str(v)[:200] for k, v in comp['last_success'].items() if k in ['COMPLETED_TIME','QUERY_START_TIME']})

                if auto_fix and coco and coco.is_available:
                    if st.button(f"🤖 AI Diagnose", key=f"fix_{task_name}_{scheduled}"):
                        with st.spinner("Analyzing failure..."):
                            diagnosis = coco.debug_task_failure(task_name, error_code, str(error_msg), str(query_text))
                            if diagnosis:
                                st.markdown(diagnosis)

# ════════════════════════════════════════════════════════════════════
# TAB 4: Pipeline Monitor
# ════════════════════════════════════════════════════════════════════
with tab4:
    st.markdown("### 📊 Pipeline Health Monitor")

    # Task execution history
    st.markdown("#### Recent Task Executions")
    history = engine.get_task_history(limit=100)
    if not history.empty:
        state_col = 'STATE' if 'STATE' in history.columns else 'state'
        if state_col in history.columns:
            succeeded = len(history[history[state_col] == 'SUCCEEDED'])
            failed_count = len(history[history[state_col] == 'FAILED'])
            skipped = len(history[history[state_col] == 'SKIPPED'])

            mc1, mc2, mc3, mc4 = st.columns(4)
            mc1.metric("Total Runs", len(history))
            mc2.metric("Succeeded", succeeded)
            mc3.metric("Failed", failed_count)
            mc4.metric("Success Rate", f"{succeeded/max(len(history),1)*100:.1f}%")

        st.dataframe(history.head(50), use_container_width=True, height=400)
    else:
        st.info("No task execution history available.")

    # Dynamic table refresh status
    st.markdown("#### Dynamic Table Refresh Status")
    dts = engine.list_dynamic_tables()
    if not dts.empty:
        name_col = 'name' if 'name' in dts.columns else 'NAME'
        for _, dt in dts.head(10).iterrows():
            dt_name = dt.get(name_col, '?')
            with st.expander(f"🔄 {dt_name}"):
                rh = engine.get_dynamic_table_refresh_history(dt_name)
                if not rh.empty:
                    st.dataframe(rh.head(10), use_container_width=True)
                else:
                    st.caption("No refresh history available")
    else:
        st.info("No dynamic tables found.")
