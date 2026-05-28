import streamlit as st
import pandas as pd
import json
import uuid
import time
import sys
import os
import io

# Set up path
try:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
except (NameError, TypeError):
    pass

from utils.snowflake_client import SnowflakeClient
from utils.styles import apply_global_styles, render_sidebar
from utils.visualizations import render_bi_chart, BIEncoder

st.set_page_config(page_title="AI/BI Builder", page_icon="✨", layout="wide")
apply_global_styles()

def get_db_schema_context(client):
    try:
        if 'db_context_cache' not in st.session_state:
            dbs = client.execute_query("SHOW DATABASES")
            if not dbs.empty:
                st.session_state.db_context_cache = [db for db in dbs['NAME'].tolist() if db not in ['SNOWFLAKE', 'SNOWFLAKE_SAMPLE_DATA']]
            else:
                st.session_state.db_context_cache = []
        return st.session_state.db_context_cache
    except Exception as e:
        st.sidebar.error(f"Context Error: {e}")
        return []


def get_tables_context(client, database, schema):
    """Get tables and views in a given database.schema."""
    try:
        tables = client.execute_query(f"SHOW TABLES IN SCHEMA {database}.{schema}")
        views = client.execute_query(f"SHOW VIEWS IN SCHEMA {database}.{schema}")
        t_list = tables['NAME'].tolist() if not tables.empty else []
        v_list = views['NAME'].tolist() if not views.empty else []
        return sorted(t_list + v_list)
    except:
        return []


def get_table_metadata(client, database, schema, tables):
    """Get column metadata for selected tables."""
    metadata = {}
    for t in tables:
        try:
            desc = client.execute_query(f"DESC TABLE {database}.{schema}.{t}")
            if not desc.empty:
                metadata[t] = [f"{r['NAME']} ({r['TYPE']})" for _, r in desc.iterrows()]
        except:
            continue
    return metadata

def save_dashboard(client, name, desc, layout):
    try:
        dash_id = layout.get("dashboard_id", str(uuid.uuid4()))
        layout["dashboard_id"] = dash_id # Ensure it's in the layout
        layout_json = json.dumps(layout, cls=BIEncoder).replace("'", "''") 
        
        query = f"""
        MERGE INTO APP_CONTEXT.SAVED_DASHBOARDS target
        USING (SELECT '{name}' as NAME) source
        ON target.NAME = source.NAME
        WHEN MATCHED THEN
            UPDATE SET LAYOUT_JSON = PARSE_JSON('{layout_json}'), DESCRIPTION = '{desc}', UPDATED_AT = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN
            INSERT (DASHBOARD_ID, NAME, DESCRIPTION, LAYOUT_JSON, CREATED_BY)
            VALUES ('{dash_id}', '{name}', '{desc}', PARSE_JSON('{layout_json}'), CURRENT_USER())
        """
        client.execute_query(query)
        st.success(f"Dashboard '{name}' saved successfully! Share Link: `/?dashboard_id={dash_id}`")
        time.sleep(2)
        st.rerun()
    except Exception as e:
        st.error(f"Save failed: {e}")

def load_dashboards(client):
    try:
        return client.execute_query("SELECT DASHBOARD_ID, NAME, DESCRIPTION, LAYOUT_JSON FROM APP_CONTEXT.SAVED_DASHBOARDS ORDER BY UPDATED_AT DESC")
    except:
        return pd.DataFrame()

def load_dashboard_by_id(client, dash_id):
    try:
        df = client.execute_query(f"SELECT NAME, DESCRIPTION, LAYOUT_JSON FROM APP_CONTEXT.SAVED_DASHBOARDS WHERE DASHBOARD_ID = '{dash_id}'")
        if not df.empty:
            return df.iloc[0]
    except:
        pass
    return None

def generate_dashboard_with_cortex(client, prompt, context_metadata, semantic_dict):
    schema_context = "\n".join([f"Table {t}: {', '.join(cols)}" for t, cols in context_metadata.items()])
    semantic_context = "\n".join([f"{k}: {v}" for k, v in semantic_dict.items()]) if semantic_dict else "None"
    
    system_prompt = f"""
    You are an expert AI BI Developer. Generate a JSON configuration for a Streamlit dashboard based on the user's request.
    
    AVAILABLE SCHEMA:
    {schema_context}
    
    SEMANTIC DICTIONARY (Apply these business rules/calculations):
    {semantic_context}
    
    OUTPUT FORMAT (JSON ONLY):
    {{
        "title": "Dashboard Title",
        "widgets": [
            {{
                "title": "Widget Title",
                "width": 1-12 (Streamlit column width),
                "sql": "Valid Snowflake SQL query. Use fully qualified names if needed or assume current schema.",
                "chart": {{
                    "type": "bar|line|area|scatter|pie|donut|funnel|sankey|pareto|parallel|bullet|heatmap|table",
                    "x": "column_name",
                    "y": ["col1", "col2"],
                    "title": "Chart Title",
                    "color": "col_name (optional)",
                    "x_label": "Label",
                    "y_label": "Label"
                }}
            }}
        ]
    }}
    
    RULES:
    1. Generate valid SQL compatible with Snowflake.
    2. Use aggregation for charts (GROUP BY).
    5. Return ONLY JSON. No markdown.
    6. For 'map', set x/y to null and use 'lat', 'lon' OR 'locations'.
    """
    safe_prompt = system_prompt.replace("'", "''")
    safe_user = prompt.replace("'", "''")
    cmd = f"SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large', '{safe_prompt} \\n\\n USER REQUEST: {safe_user}')"
    try:
        res = client.execute_query(cmd)
        if not res.empty:
            response_text = res.iloc[0, 0].replace("```json", "").replace("```", "").strip()
            return json.loads(response_text)
    except Exception as e:
        st.error(f"Generation Failed: {e}")
        return None

def modify_dashboard_with_cortex(client, prompt, current_layout):
    system_prompt = f"""
    You are an expert AI BI Developer. Modify the provided JSON layout based on the user request.
    Keep existing widgets intact unless the user explicitly wants to change, delete, or replace them.
    
    CURRENT LAYOUT:
    {json.dumps(current_layout)}
    
    RULES:
    1. Output ONLY the modified JSON structure.
    """
    safe_system = system_prompt.replace("'", "''")
    safe_user = prompt.replace("'", "''")
    cmd = f"SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large', '{safe_system} \\n\\n USER REQUEST: {safe_user}')"
    try:
        res = client.execute_query(cmd, log=False)
        if not res.empty:
            response_text = res.iloc[0, 0].replace("```json", "").replace("```", "").strip()
            return json.loads(response_text)
    except Exception as e:
        st.error(f"Modification Failed: {e}")
    return None

def inject_sql_modifiers(query, global_filters, calc_field):
    # Case insensitive replacements
    query_upper = query.upper()
    modified_query = query
    
    if calc_field:
        if "FROM" in query_upper:
            # simple inject before first FROM
            idx = query_upper.find("FROM")
            modified_query = modified_query[:idx] + f", {calc_field} \n" + modified_query[idx:]
            
    for col, val in global_filters.items():
        # Inject WHERE clause naively
        query_upper = modified_query.upper()
        if "WHERE " in query_upper:
            idx = query_upper.find("WHERE ") + 6
            modified_query = modified_query[:idx] + f"{col} = '{val}' AND " + modified_query[idx:]
        elif "GROUP BY" in query_upper:
            idx = query_upper.find("GROUP BY")
            modified_query = modified_query[:idx] + f"WHERE {col} = '{val}' \n" + modified_query[idx:]
        elif "ORDER BY" in query_upper:
            idx = query_upper.find("ORDER BY")
            modified_query = modified_query[:idx] + f"WHERE {col} = '{val}' \n" + modified_query[idx:]
        else:
            modified_query += f"\nWHERE {col} = '{val}'"
            
    return modified_query

def main():
    client = SnowflakeClient()
    qp = st.query_params
    is_read_only = "dashboard_id" in qp
    dash_id = qp.get("dashboard_id")

    if not client.session and not is_read_only:
        st.warning("Please log in from Home page.")
        return

    # --- STATE MANAGEMENT ---
    if 'ctx_database' not in st.session_state: st.session_state.ctx_database = None
    if 'ctx_schema' not in st.session_state: st.session_state.ctx_schema = None
    if 'dashboard_layout' not in st.session_state: st.session_state.dashboard_layout = None
    if 'refresh_trigger' not in st.session_state: st.session_state.refresh_trigger = 0
    if 'global_filters' not in st.session_state: st.session_state.global_filters = {}
    if 'semantic_dict' not in st.session_state: st.session_state.semantic_dict = {}

    if is_read_only and not st.session_state.dashboard_layout:
        row = load_dashboard_by_id(client, dash_id)
        if row is not None:
            layout = json.loads(row['LAYOUT_JSON']) if isinstance(row['LAYOUT_JSON'], str) else row['LAYOUT_JSON']
            st.session_state.dashboard_layout = layout
        else:
            st.error("Dashboard not found.")
            return

    if not is_read_only:
        render_sidebar()
        
    if not is_read_only:
        st.title("✨ AI/BI Builder")
        st.caption("Context-Aware, Persistent Dashboards generated by AI.")

    # --- SIDEBAR CONTROLS ---
    if not is_read_only:
        with st.sidebar:
            st.markdown("### 📂 Dashboard Manager")
            saved_df = load_dashboards(client)
            
            action = st.radio("Action", ["New Dashboard", "Load Dashboard"], label_visibility="collapsed")
            
            if action == "Load Dashboard" and not saved_df.empty:
                selected_dash = st.selectbox("Select Dashboard", saved_df['NAME'].tolist())
                if st.button("Load", use_container_width=True):
                    row = saved_df[saved_df['NAME'] == selected_dash].iloc[0]
                    try:
                        layout = json.loads(row['LAYOUT_JSON']) if isinstance(row['LAYOUT_JSON'], str) else row['LAYOUT_JSON']
                        layout["dashboard_id"] = row['DASHBOARD_ID']
                        st.session_state.dashboard_layout = layout
                        st.session_state.global_filters = {}
                        st.success(f"Loaded '{selected_dash}'")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Load Error: {e}")
            
            st.markdown("---")
            st.markdown("### 🧠 AI Context")
            dbs = get_db_schema_context(client)
            selected_tables = []
            if dbs:
                db = st.selectbox("Database", dbs)
                if db:
                    schemas_df = client.execute_query(f"SHOW SCHEMAS IN DATABASE {db}")
                    schemas = [s for s in schemas_df['NAME'].tolist() if s != 'INFORMATION_SCHEMA'] if not schemas_df.empty else []
                    schema = st.selectbox("Schema", schemas)
                    
                    if db and schema:
                        st.session_state.ctx_database = db
                        st.session_state.ctx_schema = schema
                        tables = get_tables_context(client, db, schema)
                        if tables:
                            selected_tables = st.multiselect("Active Tables (for AI)", tables)
                        else:
                            st.warning("No tables found in this schema.")
            
            with st.expander("📚 Semantic Dictionary", expanded=False):
                st.caption("Define logic for AI (e.g., 'Active = STATUS=\"A\"')")
                new_term = st.text_input("Term")
                new_def = st.text_input("Definition/SQL Logic")
                if st.button("Add Term"):
                    if new_term and new_def:
                        st.session_state.semantic_dict[new_term] = new_def
                if st.session_state.semantic_dict:
                    st.write(st.session_state.semantic_dict)
                    if st.button("Clear Dictionary"):
                        st.session_state.semantic_dict = {}
                        st.rerun()
                        
            with st.expander("🔗 Bring Your Own Data (CSV)", expanded=False):
                st.caption("Upload local data to blend with Snowflake models.")
                uploaded_file = st.file_uploader("Upload CSV", type=['csv'])
                if uploaded_file and st.session_state.ctx_database and st.session_state.ctx_schema:
                    if st.button("Stage Data to Snowflake"):
                        try:
                            # Read CSV and stage to Snowflake temporarily
                            temp_df = pd.read_csv(uploaded_file)
                            # Basic cleanup
                            temp_df.columns = [c.upper().replace(' ', '_') for c in temp_df.columns]
                            table_name = f"TEMP_UPLOAD_{str(uuid.uuid4()).split('-')[0].upper()}"
                            full_table = f"{st.session_state.ctx_database}.{st.session_state.ctx_schema}.{table_name}"
                            with st.spinner(f"Writing {table_name}..."):
                                client.session.write_pandas(temp_df, table_name, auto_create_table=True, overwrite=True)
                            st.success(f"Staged as {table_name}. Select it in Active Tables.")
                        except Exception as e:
                            st.error(f"Upload failed: {e}")
            
            if st.button("Clear Workspace", type="secondary"):
                st.session_state.dashboard_layout = None
                st.session_state.global_filters = {}
                st.rerun()

    # --- MAIN WORKSPACE ---
    
    if not st.session_state.dashboard_layout and not is_read_only:
        st.info("👋 Select Database & Schema in sidebar, then pick tables to start.")
        
        if st.session_state.ctx_schema and selected_tables:
            prompt = st.text_area("What do you want to analyze?", height=100, 
                                  placeholder="e.g. creating a sales dashboard showing revenue by region, top products pareto, and shipping delay heatmap.\nTip: Ask for complex joins if needed!")
            
            if st.button("✨ Generate Dashboard", type="primary"):
                with st.spinner("Analyzing Metadata & Designing Dashboard..."):
                    meta = get_table_metadata(client, st.session_state.ctx_database, st.session_state.ctx_schema, selected_tables)
                    layout = generate_dashboard_with_cortex(client, prompt, meta, st.session_state.semantic_dict)
                    
                    if layout:
                        st.session_state.dashboard_layout = layout
                        st.rerun()

    # 2. DASHBOARD RENDERING & EDITING
    elif st.session_state.dashboard_layout:
        layout = st.session_state.dashboard_layout
        
        # --- GLOBAL BAR ---
        gc1, gc2, gc_save = st.columns([5, 4, 3])
        with gc1: 
            st.header(layout.get("title", "Untitled Dashboard"))
            if st.session_state.global_filters:
                st.caption(f"Active Filters: {st.session_state.global_filters}")
                if st.button("Clear Filters", size="small", type="secondary"):
                    st.session_state.global_filters = {}
                    st.rerun()
        with gc2:
            st.markdown("<div style='padding-top: 15px;'></div>", unsafe_allow_html=True)
            auto_refresh = st.selectbox("Auto Refresh", ["Off", "1 Minute", "5 Minutes"], label_visibility="collapsed")
            if auto_refresh != "Off":
                secs = 60 if auto_refresh == "1 Minute" else 300
                st.write(f"⏳ Auto-refresh active ({secs}s)")
                time.sleep(secs)
                st.session_state.refresh_trigger += 1
                st.rerun()
                
        with gc_save:
            st.markdown("<div style='padding-top: 15px;'></div>", unsafe_allow_html=True)
            if not is_read_only:
                c_exp, c_save_btn = st.columns([1, 1])
                with c_exp:
                    export_data = {} # Used later
                with c_save_btn:
                    with st.popover("💾 Save Dashboard"):
                        save_name = st.text_input("Name", value=layout.get("title", ""))
                        save_desc = st.text_area("Description")
                        if st.button("Confirm Save", type="primary", use_container_width=True):
                            save_dashboard(client, save_name, save_desc, layout)
            else:
                export_data = {}

        st.markdown("---")
        
        # --- WIDGET GRID RENDERING ---
        widgets = layout.get("widgets", [])
        
        # Store data for Excel Export
        excel_dfs = {}
        
        row_width = 0
        current_cols = []
        rows = []
        for w in widgets:
            w_width = w.get("width", 6)
            if row_width + w_width > 12:
                rows.append(current_cols)
                current_cols = []
                row_width = 0
            current_cols.append(w)
            row_width += w_width
        if current_cols: rows.append(current_cols)

        for r_idx, row_widgets in enumerate(rows):
            col_specs = [max(1, w.get("width", 6)) for w in row_widgets]
            st_cols = st.columns(col_specs)
            
            for c_idx, w in enumerate(row_widgets):
                with st_cols[c_idx]:
                    with st.container(border=True):
                        # Header & Editing
                        wh1, wh2 = st.columns([8, 2])
                        with wh1: st.subheader(w.get("title", "Chart"))
                        if not is_read_only:
                            with wh2: 
                                with st.popover("⚙️"):
                                    st.write("**Chart Configuration**")
                                    w['width'] = st.slider(f"Width (Columns)", 1, 12, w.get("width", 6), key=f"w_{r_idx}_{c_idx}")
                                    w_h = w.get("chart", {}).get("height", 350)
                                    new_h = st.number_input("Height (px)", min_value=200, max_value=800, value=w_h, step=50, key=f"h_{r_idx}_{c_idx}")
                                    
                                    w['calc_field'] = st.text_input("Calculated Field (e.g. SUM(A)/SUM(B) AS C)", w.get("calc_field", ""), key=f"cf_{r_idx}_{c_idx}")
                                    
                                    w['sql'] = st.text_area(f"SQL", w['sql'], height=150, key=f"s_{r_idx}_{c_idx}")
                                    
                                    # Alering
                                    st.write("**Alerts**")
                                    w['alert_col'] = st.text_input("Alert Metric Column", w.get("alert_col", ""), key=f"ac_{r_idx}_{c_idx}")
                                    w['alert_thresh'] = st.number_input("Alert Threshold (<)", value=w.get("alert_thresh", 0.0), key=f"at_{r_idx}_{c_idx}")
                                    
                                    if w.get("chart"):
                                        ctypes = ["bar", "line", "area", "scatter", "pie", "donut", "heatmap", "pareto", "parallel", "sankey", "bullet", "funnel", "treemap", "sunburst", "map", "choropleth"]
                                        w['chart']['type'] = st.selectbox(f"Type", ctypes, index=ctypes.index(w['chart']['type']) if w['chart']['type'] in ctypes else 0, key=f"t_{r_idx}_{c_idx}")
                                        w['chart']['height'] = new_h
                                        
                                        if w['chart']['type'] in ['line', 'scatter']:
                                            w['chart']['forecast'] = st.checkbox("Show 3-Point Rolling Forecast", value=w['chart'].get("forecast", False), key=f"fx_{r_idx}_{c_idx}")
                                        
                                    if st.button(f"Apply Changes", key=f"a_{r_idx}_{c_idx}"): 
                                        st.rerun()

                        # Execution
                        try:
                            _ = st.session_state.refresh_trigger 
                            
                            # Inject Filters and Calculations
                            final_query = inject_sql_modifiers(w['sql'], st.session_state.global_filters, w.get('calc_field'))
                            
                            start_time = time.time()
                            df = client.execute_query(final_query, log=False)
                            exec_time = time.time() - start_time
                            
                            if not df.empty:
                                widget_title = w.get("title", f"Widget_{r_idx}_{c_idx}")
                                # clean for excel sheet name
                                clean_title = "".join(c for c in widget_title if c.isalnum() or c in [' ', '_']).strip()[:30]
                                excel_dfs[clean_title] = df
                                
                                # Process Alerts & Warnings
                                if exec_time > 5.0 and not is_read_only:
                                    st.warning(f"⚡ Slow Query ({exec_time:.1f}s). Consider Materializing:")
                                    st.code(f"CREATE MATERIALIZED VIEW MV_{clean_title.upper()} AS \n{final_query}", language="sql")
                                
                                # Process Alerts
                                if w.get("alert_col") and w.get("alert_thresh"):
                                    if w['alert_col'] in df.columns:
                                        min_val = df[w['alert_col']].min()
                                        if min_val < w['alert_thresh']:
                                            st.error(f"🚨 ALERT: {w['alert_col']} dropped below {w['alert_thresh']} (Min: {min_val})")
                                
                                if w.get("chart"):
                                    fig = render_bi_chart(df, w['chart'])
                                    if fig: 
                                        event = st.plotly_chart(fig, use_container_width=True, key=f"fig_{r_idx}_{c_idx}", on_select="rerun" if not is_read_only else "ignore")
                                        # Handle Cross-Filtering
                                        if event and hasattr(event, "selection") and getattr(event, "selection", None) and "points" in event.selection and event.selection["points"]:
                                            point = event.selection["points"][0]
                                            if "x" in point:
                                                x_col = w['chart'].get("x")
                                                if isinstance(x_col, list) and len(x_col) > 0: x_col = x_col[0]
                                                if x_col:
                                                    st.session_state.global_filters[x_col] = point["x"]
                                                    st.rerun()
                                    else: st.warning("Chart render failed. Check config.")
                                else:
                                    st.dataframe(df, height=w.get("chart", {}).get("height", 350))
                            else:
                                st.info("No data returned.")
                        except Exception as e:
                            st.error(f"Error: {e}")

        # Excel Export Button processing (outside loop to collect all DFs)
        if excel_dfs and not is_read_only:
            with gc_save:
                with c_exp:
                    output = io.BytesIO()
                    # Try writing without specific engine to let Pandas pick openpyxl, avoiding xlsxwriter native app issues
                    try:
                        with pd.ExcelWriter(output) as writer:
                            for sheet_name, d_df in excel_dfs.items():
                                d_df.to_excel(writer, sheet_name=sheet_name, index=False)
                        excel_data = output.getvalue()
                        st.download_button(
                            label="📥 Export",
                            data=excel_data,
                            file_name=f"{layout.get('title', 'Dashboard')}_Export.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True
                        )
                    except Exception as e:
                        st.warning(f"Export Unavailable: {e}")

        st.markdown("---")
        
        # --- AI COPILOT INTERFACE & MULTI-AGENT ANALYSIS ---
        if not is_read_only:
            with st.expander("🤖 Agentic Insights & Copilot", expanded=False):
                tab1, tab2 = st.tabs(["Layout Copilot", "Executive Analyst"])
                
                with tab1:
                    st.caption("Chat with Cortex to modify the dashboard naturally.")
                    mod_prompt = st.chat_input("e.g. 'Change the Top Products chart to a Donut Chart and add a new query showing failed tasks'")
                    if mod_prompt:
                        st.chat_message("user").write(mod_prompt)
                        with st.chat_message("assistant"):
                            with st.spinner("Applying changes..."):
                                new_layout = modify_dashboard_with_cortex(client, mod_prompt, layout)
                                if new_layout:
                                    st.session_state.dashboard_layout = new_layout
                                    st.rerun()
                                    
                with tab2:
                    st.caption("Let the AI analyze all requested DataFrames across the entire dashboard to find correlations.")
                    if st.button("Generate Executive Summary...", type="primary", use_container_width=True):
                        with st.spinner("Analyzing Global Dashboard Context..."):
                            if excel_dfs:
                                # Serialize first 5 rows of every DF to give the model context
                                context_string = ""
                                for name, df in excel_dfs.items():
                                    context_string += f"\\n--- WIDGET: {name} ---\\n{df.head(5).to_markdown()}\\n"
                                
                                prompt = f"You are an elite data scientist reviewing a LIVE dashboard. Write an executive summary highlighting the actual data values seen below. Point out trends, anomalies, and overall performance.\\n\\nCurrent Dashboard Data Snapshot:\\n{context_string}"
                                prompt = prompt.replace("'", "''") # Escape single quotes for SQL
                                query = f"SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large', '{prompt}')"
                                
                                try:
                                    res = client.execute_query(query, log=False)
                                    if not res.empty:
                                        summary = res.iloc[0, 0]
                                        st.markdown(summary)
                                except Exception as e:
                                    st.error(f"Analysis failed: {e}")
                            else:
                                st.warning("No data on dashboard to analyze.")

if __name__ == "__main__":
    main()
