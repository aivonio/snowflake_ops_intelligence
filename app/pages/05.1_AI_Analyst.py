import streamlit as st
import pandas as pd
import sys
import os
import re
import json
import numpy as np

# Add parent directory to path for imports
try:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
except (NameError, TypeError):
    pass

from utils import SnowflakeClient
from utils.styles import apply_global_styles, render_metric_card, COLORS
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

class WizardEncoder(json.JSONEncoder):
    """Custom JSON encoder to handle Snowflake/Numpy types like Timestamps, Decimals, etc."""
    def default(self, obj):
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        if hasattr(obj, 'tolist'):
            return obj.tolist()
        if isinstance(obj, (np.integer, np.floating)):
            return obj.item()
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        try:
            return str(obj)
        except:
            return super().default(obj)

def make_json_safe(obj):
    """Recursively convert objects to JSON-safe types. Pro-level handling for all Snowflake/Pandas types."""
    import datetime
    
    if isinstance(obj, dict):
        return {str(k): make_json_safe(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [make_json_safe(i) for i in obj]
    # Explicit pd.Timestamp check (before generic isoformat)
    elif isinstance(obj, pd.Timestamp):
        return str(obj)
    elif isinstance(obj, (datetime.datetime, datetime.date, datetime.time)):
        return str(obj)
    elif hasattr(obj, 'isoformat'):
        try:
            return str(obj)
        except:
            return str(obj)
    elif isinstance(obj, (np.integer, np.floating)):
        return obj.item()
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif pd.isna(obj) or obj is None:
        return None
    elif isinstance(obj, (str, int, float, bool)):
        return obj
    else:
        return str(obj)

def sanitize_dataframe(df):
    """
    DEFINITIVE FIX: Convert all datetime/timestamp columns to strings.
    This prevents ANY JSON serialization issues downstream.
    """
    if df is None or df.empty:
        return df
    
    df_copy = df.copy()
    for col in df_copy.columns:
        # Check if column is datetime-like
        if pd.api.types.is_datetime64_any_dtype(df_copy[col]):
            df_copy[col] = df_copy[col].astype(str)
        # Check for object columns that might contain Timestamps
        elif df_copy[col].dtype == 'object':
            try:
                # Try to convert any remaining problematic types
                df_copy[col] = df_copy[col].apply(lambda x: str(x) if hasattr(x, 'isoformat') else x)
            except:
                pass
    return df_copy

class VisualizationAgent:
    """
    The 'Wizard' Visualization Agent.
    Decides how to best represent data using multiple charts.
    Uses a two-pass system:
      - Pass 1 (suggest_visualizations): Basic schema + sample.
      - Pass 2 (suggest_visualizations_v2): Full metadata profile for deep reasoning.
    """
    def __init__(self, client):
        self.client = client
        self.default_colors = ['#00D4AA', '#29B5E8', '#FFD700', '#FF6B6B', '#9F7AEA', '#48BB78', '#F6AD55']

    def _build_data_profile(self, df):
        """Build a rich metadata profile of the DataFrame for AI consumption."""
        profile = {}
        for col in df.columns:
            col_info = {"dtype": str(df[col].dtype), "nulls": int(df[col].isna().sum()), "unique": int(df[col].nunique())}
            if pd.api.types.is_numeric_dtype(df[col]):
                col_info["min"] = float(df[col].min()) if not df[col].isna().all() else None
                col_info["max"] = float(df[col].max()) if not df[col].isna().all() else None
                col_info["mean"] = round(float(df[col].mean()), 2) if not df[col].isna().all() else None
                col_info["std"] = round(float(df[col].std()), 2) if not df[col].isna().all() else None
                col_info["is_percentage"] = bool(col_info["max"] is not None and col_info["max"] <= 1.0 and col_info["min"] is not None and col_info["min"] >= 0.0)
            elif pd.api.types.is_string_dtype(df[col]) or df[col].dtype == 'object':
                col_info["top_values"] = df[col].value_counts().head(5).to_dict()
                col_info["avg_length"] = round(df[col].astype(str).str.len().mean(), 1)
            profile[col] = col_info
        return profile

    def _parse_viz_response(self, raw_response):
        """Safely parse AI viz JSON response."""
        json_start = raw_response.find('{')
        json_end = raw_response.rfind('}') + 1
        if json_start != -1 and json_end != -1:
            clean_json = raw_response[json_start:json_end]
            clean_json = clean_json.replace('```json', '').replace('```', '')
            viz_plan = json.loads(clean_json)
            st.session_state.viz_assumptions = viz_plan.get("design_assumptions", "")
            return viz_plan.get("charts", [])
        return None

    def suggest_visualizations_v2(self, df, user_prompt, query_title=""):
        """Deep Reasoning V2: Uses full data profile (cardinality, distributions, types) for smarter chart picks."""
        if df.empty: return []
        cols = df.columns.tolist()
        
        try:
            profile = self._build_data_profile(df)
            safe_profile = make_json_safe(profile)
            sample_data = df.head(3).astype(str).to_dict(orient='records')
            safe_sample = make_json_safe(sample_data)
        except:
            return self.suggest_visualizations(df, user_prompt)

        prompt_v2 = f"""
        You are a world-class Data Visualization Expert. You have access to FULL statistical metadata about the dataset.
        Use this to make the BEST possible chart selections.

        USER INTENT: "{user_prompt}"
        QUERY TITLE: "{query_title}"
        ROW COUNT: {len(df)}
        COLUMN COUNT: {len(cols)}

        FULL DATA PROFILE (per column — dtype, nulls, cardinality, min/max/mean/std, top values):
        {json.dumps(safe_profile, cls=WizardEncoder, indent=2)}

        SAMPLE DATA (first 3 rows):
        {json.dumps(safe_sample, cls=WizardEncoder, indent=2)}

        DECISION RULES (you MUST follow these):
        1. If a column has cardinality <= 6 and there's a numeric value column -> PIE or DONUT
        2. If a column has cardinality > 20 and is categorical -> TREEMAP or BAR with top-N filter
        3. If there are 2+ numeric columns -> consider SCATTER, BUBBLE, or PARALLEL COORDINATES
        4. If there's a datetime/time column -> LINE or AREA chart
        5. If data has hierarchical columns (e.g. ROLE + USER, or WAREHOUSE + QUERY_TYPE) -> SUNBURST
        6. If columns named source/target/value exist -> SANKEY
        7. If a column looks like percentages (max<=1, min>=0) -> format as percentage in labels
        8. If asking about "top N" or rankings -> horizontal BAR with sorted values
        9. If column names suggest categories (STATUS, TYPE, ROLE) -> use as color dimension
        10. If there's a single KPI row -> GAUGE or METRIC CARD (type: "gauge")
        11. For anomaly detection or outliers -> BOX or VIOLIN
        12. For distributions -> HISTOGRAM
        13. For comparing metrics across entities -> RADAR

        CHART STYLING RULES:
        - ALWAYS set "x_label" and "y_label" with human-readable names (replace underscores with spaces, title case)
        - For time-based x-axis: set "x_label" to the time granularity (e.g. "Hour", "Day", "Week")
        - For PIE charts: set "textinfo": "percent+label" so percentages are always visible
        - For BAR charts with long labels: set "orientation": "h" (horizontal) so labels are readable
        - If values are very large (>1M): set "value_format": "compact" (we will format as 1.2M, 3.4K)
        - Suggest 2-4 charts that together tell a complete analytical story
        - Each chart MUST have a descriptive, insight-driven title (not just column names)

        AVAILABLE CHART TYPES: bar, line, area, scatter, pie, treemap, heatmap, pareto, histogram, box, violin, funnel, waterfall, sunburst, radar, parallel, bubble, bullet, gauge, sankey

        OUTPUT FORMAT (JSON ONLY, no markdown):
        {{
            "design_assumptions": "One-line explanation of chart strategy",
            "charts": [
                {{
                    "type": "chart_type",
                    "x": "column_name",
                    "y": ["metric_col"] or "single_col",
                    "x_label": "Human Readable X Label",
                    "y_label": "Human Readable Y Label",
                    "color": "category_col_or_hex",
                    "title": "Insight-Driven Chart Title",
                    "barmode": "group|stack",
                    "orientation": "v|h",
                    "secondary_y": ["col"],
                    "size": "size_col",
                    "textinfo": "percent+label",
                    "value_format": "compact|percentage|default",
                    "path": ["hierarchy_cols"]
                }}
            ]
        }}
        """

        try:
            prompt_escaped = prompt_v2.replace("'", "''")
            query = f"SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large', '{prompt_escaped}')"
            result = self.client.execute_query(query, log=False)
            if not result.empty:
                charts = self._parse_viz_response(result.iloc[0, 0])
                if charts: return charts
        except:
            pass
        # Fallback to v1
        return self.suggest_visualizations(df, user_prompt)

    def suggest_visualizations(self, df, user_prompt):
        """Original V1 visualization suggestion (schema + sample only)."""
        if df.empty: return []
        cols = df.columns.tolist()
        
        try:
            sample_data = df.head(3).astype(str).to_dict(orient='records')
        except:
            sample_data = [{c: 'sample' for c in cols}]
        data_types = df.dtypes.apply(lambda x: x.name).to_dict()
        prompt_template = """
        You are a Pro-Level Data Visualization Wizard. Analyze the following data and user intent to design stunning, professional dashboard visualizations.
        
        USER INTENT: "{intent}"
        
        DATA SCHEMA:
        - Columns: {cols}
        - Types: {types}
        - Sample: {sample}
        
        GOAL:
        - Suggest 1 to 4 distinct charts that together tell a complete, compelling story.
        - Pick the BEST chart type for each insight. Be creative!
        - Assign specific colors from this palette: {palette}
        
        AVAILABLE CHART TYPES:
        | Type       | Best For                                      |
        |------------|-----------------------------------------------|
        | bar        | Comparisons, rankings, categories             |
        | line       | Trends over time, continuous data             |
        | area       | Cumulative trends, volume over time           |
        | scatter    | Correlations, distributions, outliers         |
        | pie        | Part-to-whole (< 6 categories)                |
        | treemap    | Hierarchical part-to-whole (Complex)          |
        | heatmap    | Density, correlation matrices, cohorts        |
        | pareto     | 80/20 Analysis (Impact vs Frequency)          |
        | histogram  | Frequency distributions                       |
        | box        | Statistical distributions, outliers           |
        | violin     | Distribution shape with density               |
        | funnel     | Conversion flows, pipeline stages             |
        | waterfall  | Sequential gains/losses, P&L breakdown        |
        | sunburst   | Deep Hierarchical data (3+ levels)            |
        | radar      | Multi-dimensional comparisons (Skills/Scores) |
        | parallel   | Multi-variable Analysis (Pattern Discovery)   |
        | bubble     | 3-variable scatter (x, y, size)               |
        | bullet     | Progress vs Target (Budgeting)                |
        | gauge      | Single KPI vs target                          |
        | sankey     | Flows, Data Lineage, Source -> Target         |
        
        OUTPUT FORMAT (JSON ONLY):
        {{
            "design_assumptions": "Short explanation of why these charts were chosen",
            "charts": [
                {{
                    "type": "bar|line|...",
                    "x": "column_name",
                    "y": ["metric_cols"] or "single_metric",
                    "x_label": "Custom X Axis Label",
                    "y_label": "Custom Y Axis Label",
                    "color": "category_col_or_hex_code",
                    "title": "Clear Chart Title",
                    "barmode": "group|stack",
                    "orientation": "v|h",
                    "secondary_y": ["metric_cols"],
                    "size": "size_col_for_bubble_or_treemap",
                    "textinfo": "percent+label",
                    "path": ["hierarchy_col_1", "hierarchy_col_2"]
                }}
            ]
        }}
        
        PRO TIPS:
        - Use 'secondary_y' if metrics have vastly different scales.
        - MUST suggest 2+ charts if user asks for multiple things.
        - For Hierarchies: Use SUNBURST or TREEMAP.
        - For Flows: Use SANKEY.
        - For Anomalies: Use SCATTER or BOX.
        - For Budget/Targets: Use BULLET.
        - For rankings with long labels: Use horizontal BAR (orientation: h).
        - ALWAYS set x_label and y_label with human-readable names.
        - ALWAYS set textinfo for pie charts.
        """
        
        try:
            safe_sample = make_json_safe(sample_data)
            
            prompt = prompt_template.format(
                intent=user_prompt,
                cols=cols,
                types=data_types,
                sample=json.dumps(safe_sample, cls=WizardEncoder),
                palette=self.default_colors
            )
            
            prompt_escaped = prompt.replace("'", "''")
            query = f"SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large', '{prompt_escaped}')"
            result = self.client.execute_query(query, log=False)
            if not result.empty:
                charts = self._parse_viz_response(result.iloc[0, 0])
                if charts: return charts
        except:
            pass
        return [{"type": "bar", "x": cols[0], "y": cols[-1], "title": "Auto-Analysis"}]

    def get_color_sequence(self, num_colors):
        return (self.default_colors * (num_colors // len(self.default_colors) + 1))[:num_colors]

def package_report(results, insights):
    """Package analysis results into a multi-sheet Excel file."""
    import io
    try:
        import xlsxwriter
    except ImportError:
        return None
        
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        # 1. Summary Sheet
        summary_data = []
        for i, res in enumerate(results):
            summary_data.append({
                "Step": i + 1,
                "Analysis": res['title'],
                "SQL Query": res['sql'],
                "Rows Returned": len(res['data'])
            })
        if insights:
            summary_data.append({"Step": "Global", "Analysis": "AI Insights", "SQL Query": "N/A", "Rows Returned": str(insights)})
            
        pd.DataFrame(summary_data).to_excel(writer, sheet_name="Summary", index=False)
        
        # 2. Data Sheets
        for i, res in enumerate(results):
            df = res['data']
            if not df.empty:
                # Clean timestamps for Excel
                df_clean = df.copy()
                for c in df_clean.columns:
                    if pd.api.types.is_datetime64_any_dtype(df_clean[c]):
                        df_clean[c] = df_clean[c].astype(str)
                
                sheet_name = f"Step_{i+1}"[:31] # Excel limit
                df_clean.to_excel(writer, sheet_name=sheet_name, index=False)
                
    return buffer.getvalue()
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(page_title="Wizard AI Data Analyst", page_icon="💬", layout="wide")

# Apply unified Snowflake design system
apply_global_styles()
from utils.styles import render_sidebar
render_sidebar()

# Additional Wizard-specific styles
st.markdown("""
<style>
    /* Minimalist Pro Chat Styles */
    .stChatMessage {
        background-color: transparent !important;
        border: none !important;
    }
    .stChatInput {
        border-color: #2e3b4e !important;
    }
    .insight-box {
        background: rgba(41, 181, 232, 0.05);
        border: 1px solid rgba(41, 181, 232, 0.2);
        border-left: 4px solid #00D4AA;
        padding: 1rem;
        border-radius: 8px;
        margin-top: 12px;
    }
    .code-container {
        position: relative;
        background: #1a1e22;
        border-radius: 8px;
        border: 1px solid #2e3b4e;
        margin: 12px 0;
    }
    .copy-button {
        position: absolute;
        top: 8px;
        right: 8px;
        background: rgba(41, 181, 232, 0.1);
        border: 1px solid rgba(41, 181, 232, 0.3);
        color: #29B5E8;
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 0.7rem;
        cursor: pointer;
        z-index: 10;
        transition: all 0.2s;
    }
    .copy-button:hover {
        background: rgba(41, 181, 232, 0.2);
    }
    .trace-item {
        font-size: 0.75rem;
        color: #9499A1;
        display: flex;
        align-items: center;
        gap: 6px;
        margin-bottom: 4px;
    }
    .trace-dot {
        width: 6px;
        height: 6px;
        background: #00D4AA;
        border-radius: 50%;
    }
</style>
""", unsafe_allow_html=True)

def get_client():
    if 'snowflake_client' not in st.session_state:
        st.session_state.snowflake_client = SnowflakeClient()
    return st.session_state.snowflake_client

def get_viz_agent():
    if 'viz_agent' not in st.session_state:
        st.session_state.viz_agent = VisualizationAgent(get_client())
    return st.session_state.viz_agent

# =====================================================
# UTILITIES & FORMATTERS
# =====================================================

def render_code_with_copy(code, language="sql"):
    """Render a code block with a simulated copy button and pro container."""
    escaped_code = code.replace('`', '\\`').replace('\n', '\\n')
    st.markdown(f"""
    <div class="code-container">
        <div class="copy-button" onclick="navigator.clipboard.writeText(`{escaped_code}`)">Copy</div>
    </div>
    """, unsafe_allow_html=True)
    st.code(code, language=language)

def render_tools_trace(context_config):
    """Render which tools/context the agent 'referenced' (tracing)."""
    with st.expander("🔍 **Context Trace** (Active Intelligence)", expanded=False):
        used = []
        if context_config.get('warehouses'): used.append(f"Warehouses: {len(context_config['warehouses'])}")
        if context_config.get('tables'): used.append(f"Pinned Tables: {len(context_config['tables'])}")
        if context_config.get('files'): used.append(f"File Scripts: {len(context_config['files'])}")
        
        if not used:
            st.caption("No specific items pinned. Using general Snowflake metadata.")
        else:
            for item in used:
                st.markdown(f'<div class="trace-item"><div class="trace-dot"></div>{item}</div>', unsafe_allow_html=True)

def get_dynamic_context(client, config):
    """Generate a text summary of the pinned context for the AI."""
    context = []
    if config.get('warehouses'):
        context.append(f"PINNED WAREHOUSES: {', '.join(config['warehouses'])}")
    
    if config.get('tables'):
        context.append(f"PINNED TABLES (Fully Qualified): {', '.join(config['tables'])}")
        # Optionally add column metadata for pinned tables here in the future
    
    if config.get('files'):
        context.append("ATTACHED SCRIPTS/DOCS:")
        for f_path in config['files']:
            try:
                # Expecting format @STAGE/PATH
                parts = f_path.lstrip('@').split('/', 1)
                if len(parts) == 2:
                    content = client.read_stage_file(parts[0], parts[1])
                    context.append(f"--- FILE: {f_path} ---\n{content[:2000]}") # Truncate large files
            except: pass
            
    # System Context Injection
    if config.get('system_usage'):
        context.append("SYSTEM CONTEXT: You have access to SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY and WAREHOUSE_METERING_HISTORY.")
    if config.get('system_pipelines'):
        context.append("SYSTEM CONTEXT: You have access to SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY and TASK_HISTORY.")
            
    return "\n".join(context)


def get_conversation_context():
    """Extract context from the last few messages."""
    if not st.session_state.get('messages'): return ""
    history = []
    for msg in st.session_state.messages[-3:]: # Last 3 messages for context
        history.append(f"{msg['role'].upper()}: {msg['content']}")
    return "\nCONVERSATION HISTORY:\n" + "\n".join(history)

def extract_multiple_queries(text):
    """
    Extract multiple SQL blocks from AI response.
    Each block can be prefixed with a title like ### [Title]
    Returns list of dicts: [{'title': '...', 'sql': '...'}]
    """
    if not text: return []
    
    queries = []
    # Pattern to find ### [Title] followed by a code block
    # Or just a code block
    segments = re.finditer(r"(?:###\s+\[(.*?)\]\s+)?```sql\s+(.*?)\s+```", text, re.DOTALL | re.IGNORECASE)
    
    for match in segments:
        title = match.group(1) or "Analysis Step"
        sql = match.group(2).strip()
        if sql:
            queries.append({"title": title, "sql": sql})
            
    # Fallback: if no code blocks but text looks like SQL
    if not queries:
        clean_text = text.strip()
        if clean_text.upper().startswith("SELECT") or clean_text.upper().startswith("WITH"):
            # Split by semicolon if multiple
            raw_queries = [q.strip() for q in clean_text.split(';') if q.strip()]
            for i, q in enumerate(raw_queries):
                queries.append({"title": f"Query {i+1}", "sql": q})
                
    return queries

# =====================================================
# CORE LOGIC
# =====================================================

def discover_all_tables(client):
    if 'discovered_tables' in st.session_state and st.session_state.discovered_tables:
        return st.session_state.discovered_tables
    
    tables_info = {}
    try:
        db_query = "SHOW DATABASES"
        db_df = client.execute_query(db_query, log=False)
        if not db_df.empty:
            db_col = 'name' if 'name' in db_df.columns else 'NAME'
            databases = db_df[db_col].tolist()[:10]
            
            for db in databases:
                if db.startswith('SNOWFLAKE'): continue
                try:
                    schema_query = f"SHOW SCHEMAS IN DATABASE {db}"
                    s_df = client.execute_query(schema_query, log=False)
                    if s_df.empty: continue
                    s_col = 'name' if 'name' in s_df.columns else 'NAME'
                    schemas = s_df[s_col].tolist()[:5]
                    
                    for sch in schemas:
                        if sch == 'INFORMATION_SCHEMA': continue
                        try:
                            t_query = f"SHOW TABLES IN {db}.{sch}"
                            t_df = client.execute_query(t_query, log=False)
                            if not t_df.empty:
                                t_col = 'name' if 'name' in t_df.columns else 'NAME'
                                for _, row in t_df.iterrows():
                                    full = f"{db}.{sch}.{row[t_col]}"
                                    tables_info[full] = {'database': db, 'schema': sch}
                        except: pass
                except: pass
    except: pass
    
    st.session_state.discovered_tables = tables_info
    return tables_info

def generate_insights_wizard(client, df, charts):
    """Wizard-style insights based on the chosen charts."""
    if df.empty: return None
    
    try:
        safe_charts = make_json_safe(charts)
        prompt = f"""
        Analyze this data and the suggested visualizations to provide 3 deep business insights.
        
        DATA SIZE: {len(df)} rows
        COLUMNS: {df.columns.tolist()}
        VISUALS: {json.dumps(safe_charts, cls=WizardEncoder)}
        
        Return 3 bullet points with emojis. Be concise but insightful (pro-level).
        """
        prompt_escaped = prompt.replace("'", "''")
        query = f"SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large', '{prompt_escaped}')"
        res = client.execute_query(query, log=False)
        if not res.empty:
            return res.iloc[0, 0]
    except: return None
    return "Insights unavailable."

def generate_followup_questions(client, prompt, df):
    """Generate smart follow-up questions based on the analysis."""
    try:
        cols = df.columns.tolist() if not df.empty else []
        p = f"""
        Based on the user's initial question: "{prompt}" and the data columns: {cols},
        suggest 3 short, relevant follow-up questions they might want to ask next.
        Return ONLY the questions, one per line.
        """
        p_esc = p.replace("'", "''")
        res = client.execute_query(f"SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large', '{p_esc}')", log=False)
        if not res.empty:
            return [x.strip() for x in res.iloc[0,0].split('\n') if x.strip() and '?' in x][:3]
    except: pass
    return []

def fix_sql_query(client, failed_sql, error_msg):
    """Attempt to fix broken SQL using Cortex."""
    try:
        p = f"""
        Fix this Snowflake SQL query which failed with error: "{error_msg}"
        
        BROKEN SQL:
        {failed_sql}
        
        Return ONLY the fixed SQL code block without explanation.
        """
        p_esc = p.replace("'", "''")
        res = client.execute_query(f"SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large', '{p_esc}')", log=False)
        if not res.empty:
            # Extract SQL logic
            clean = res.iloc[0,0].replace("```sql", "").replace("```", "").strip()
            return clean
    except: pass
    return None



def diagnose_query(client, query_id):
    """
    Diagnose a specific query performance using Cortex.
    """
    try:
        # 1. Fetch Query Stats
        q_sql = f"""
        SELECT 
            QUERY_TEXT,
            TOTAL_ELAPSED_TIME,
            BYTES_SCANNED,
            ROWS_PRODUCED,
            PARTITIONS_SCANNED,
            PARTITIONS_TOTAL,
            COMPILATION_TIME,
            EXECUTION_TIME,
            WAREHOUSE_NAME,
            WAREHOUSE_SIZE
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE QUERY_ID = '{query_id}'
        """
        res = client.execute_query(q_sql, log=False)
        
        if res.empty:
            return f"Query ID {query_id} not found in history."
            
        stats = res.iloc[0].to_dict()
        
        # 2. Analyze Pruning
        pruning_ratio = 0
        if stats['PARTITIONS_TOTAL'] > 0:
            pruning_ratio = stats['PARTITIONS_SCANNED'] / stats['PARTITIONS_TOTAL']
            
        # 3. Ask Cortex for Diagnosis
        prompt = f"""
        You are a Snowflake Performance Expert. Diagnose this query.
        
        QUERY: "{stats['QUERY_TEXT']}"
        
        METRICS:
        - Duration: {stats['TOTAL_ELAPSED_TIME']/1000:.2f}s (Compile: {stats['COMPILATION_TIME']/1000:.2f}s, Exec: {stats['EXECUTION_TIME']/1000:.2f}s)
        - Data: {stats['BYTES_SCANNED']/1024/1024:.2f} MB scanned
        - Rows: {stats['ROWS_PRODUCED']} returned
        - Pruning: Scanned {stats['PARTITIONS_SCANNED']} / {stats['PARTITIONS_TOTAL']} partitions (Ratio: {pruning_ratio:.2%})
        - Warehouse: {stats['WAREHOUSE_NAME']} ({stats['WAREHOUSE_SIZE']})
        
        IDENTIFY:
        1. Bottlenecks (e.g. Spill to disk, bad pruning, exploding joins)
        2. Recommendations (e.g. Cluster keys, larger WH, rewrite)
        
        Keep it professional and concise.
        """
        
        prompt_esc = prompt.replace("'", "''")
        cortex_res = client.execute_query(f"SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large', '{prompt_esc}')", log=False)
        
        if not cortex_res.empty:
            analysis = cortex_res.iloc[0, 0]
            return f"### 🩺 Query Diagnosis ({query_id})\n\n{analysis}"
            
    except Exception as e:
        return f"Diagnosis failed: {e}"
    return "Could not diagnose."


def discover_error_patterns(client):
    """
    Analyze failing queries to find recurring patterns using Cortex.
    """
    try:
        # 1. Get Top Errors
        q = """
        SELECT 
            ERROR_MESSAGE,
            COUNT(*) as FAIL_COUNT,
            listagg(DISTINCT LEFT(QUERY_TEXT, 100), ' || ') as EXAMPLES
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE EXECUTION_STATUS = 'FAIL' 
          AND START_TIME >= DATEADD(day, -7, CURRENT_TIMESTAMP())
          AND ERROR_MESSAGE IS NOT NULL
        GROUP BY 1
        ORDER BY 2 DESC
        LIMIT 5
        """
        df = client.execute_query(q, log=False)
        
        if df.empty:
            return "✅ No significant query failures found in the last 7 days."
            
        # 2. Format for Cortex
        error_context = []
        for _, row in df.iterrows():
            error_context.append(f"- Count: {row['FAIL_COUNT']} | Error: {row['ERROR_MESSAGE']} | Examples: {str(row['EXAMPLES'])[:200]}...")
            
        context_str = "\n".join(error_context)
        
        # 3. Cortex Analysis
        prompt = f"""
        You are a Snowflake Reliability Engineer. Analyze these top error patterns from the last 7 days.
        
        ERROR LOGS:
        {context_str}
        
        TASK:
        1. Summarize the recurring issues.
        2. Provide actionable fixes for the top 2 issues.
        3. Rate the overall system stability (High/Medium/Low Risk).
        
        Format as a professional markdown report with emojis.
        """
        
        prompt_esc = prompt.replace("'", "''")
        res = client.execute_query(f"SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large', '{prompt_esc}')", log=False)
        
        if not res.empty:
            return f"### 🚨 System Stability Report\n\n{res.iloc[0, 0]}"
            
    except Exception as e:
        return f"Pattern analysis failed: {e}"
    return "Analysis incomplete."


def forecast_costs(client):
    """
    Generate a natural language cost forecast using historical data and Cortex.
    """
    try:
        # 1. Get Daily History (60 days)
        q = """
        SELECT DATE(START_TIME) as DATE, SUM(CREDITS_USED) as CREDITS 
        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY 
        WHERE START_TIME >= DATEADD(day, -60, CURRENT_TIMESTAMP())
        GROUP BY 1 ORDER BY 1
        """
        df = client.execute_query(q, log=False)
        
        if df.empty or len(df) < 5:
            return "ℹ️ Not enough historical data to generate a forecast."
            
        # 2. Simple Linear Projection (Python)
        import numpy as np
        df['days_idx'] = np.arange(len(df))
        z = np.polyfit(df['days_idx'], df['CREDITS'], 1) # Linear fit
        p = np.poly1d(z)
        
        # Project next 30 days
        future_idx = np.arange(len(df), len(df) + 30)
        future_credits = p(future_idx)
        predicted_total = sum(future_credits)
        current_daily_avg = df['CREDITS'].mean()
        trend = "Increasing" if z[0] > 0 else "Decreasing"
        
        # 3. Cortex Narrative
        data_summary = f"""
        - Historical Daily Avg: {current_daily_avg:.2f} credits
        - Trend Direction: {trend} (Slope: {z[0]:.4f})
        - Last 30 Days Total: {df['CREDITS'].tail(30).sum():.2f} credits
        - Predicted Next 30 Days Total: {predicted_total:.2f} credits
        """
        
        prompt = f"""
        You are a CFO providing a cost forecast briefing.
        
        DATA ANALYSIS:
        {data_summary}
        
        TASK:
        1. Project the spending for the next month based on the trend.
        2. Warn if the trend is increasing aggressively.
        3. Provide a 'Budget Recommendation' based on the prediction.
        
        Keep it concise, professional, and use emojis.
        """
        
        prompt_esc = prompt.replace("'", "''")
        res = client.execute_query(f"SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large', '{prompt_esc}')", log=False)
        
        if not res.empty:
            return f"### 🔮 Cost Forecast (Next 30 Days)\n\n{res.iloc[0, 0]}"
            
    except Exception as e:
        return f"Forecast failed: {e}"
    return "Forecast unavailable."


def render_chart_wizard(df, config=None, chart_key="default"):
    if df.empty or not config: return
    
    # --- CROSS FILTERING APPLICATION ---
    filtered_df = df.copy()
    if 'wizard_filters' in st.session_state and st.session_state.wizard_filters:
        for fcol, fval in st.session_state.wizard_filters.items():
            if fcol in filtered_df.columns:
                try:
                    filtered_df = filtered_df[filtered_df[fcol].astype(str) == str(fval)]
                except: continue
                
    if filtered_df.empty:
        st.caption("No data matches current filters.")
        return
    df = filtered_df

    try:
        chart_type = config.get("type", "bar")
        title = config.get("title", "")
        # Ensure we don't accidentally get lists where strings are needed
        x = config.get("x")
        y = config.get("y")
        
        # --- AXIS MAPPING ENHANCEMENT ---
        x_label = config.get("x_label", "").strip() or x if isinstance(x, str) else "X Axis"
        y_label = config.get("y_label", "").strip()
        if not y_label and isinstance(y, list): y_label = ", ".join(y)
        elif not y_label and isinstance(y, str): y_label = y
        
        color = config.get("color")
        barmode = config.get("barmode", "group")
        
        # --- ROBUST TYPE HANDLING ---
        def flatten_if_list(val):
            if isinstance(val, list):
                return val[0] if len(val) == 1 else val
            return val

        # Resolve List vs String ambiguities for simple charts
        if chart_type not in ["sunburst", "treemap", "sankey"]:
             x = flatten_if_list(x)
             color = flatten_if_list(color)
        
        # Resolve Y (can be list for multi-metric)
        y = y if isinstance(y, list) else [y]
        secondary_y = config.get("secondary_y")
        secondary_y = secondary_y if isinstance(secondary_y, list) else ([secondary_y] if secondary_y else [])
        
        # Validate Columns exist
        if isinstance(x, str) and x not in df.columns: x = df.columns[0]
        primary_y = [c for c in y if c in df.columns]
        if not primary_y and len(df.columns) > 1: primary_y = [df.columns[1]]
        elif not primary_y: primary_y = [df.columns[0]]
            
        sec_y_cols = [c for c in secondary_y if c in df.columns]
            
        fig = None
        base_color_seq = ['#00D4AA', '#29B5E8', '#FFD700', '#FF6B6B', '#9F7AEA', '#48BB78', '#F6AD55']
        current_seq = base_color_seq

        # Color Override
        viz_color = None
        if color:
            if isinstance(color, str) and color in df.columns: viz_color = color
            elif isinstance(color, str) and color.startswith('#'): current_seq = [color] + base_color_seq

        # --- DUAL AXIS HANDLER ---
        if sec_y_cols:
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            
            for i, col_name in enumerate(primary_y):
                c = current_seq[i % len(current_seq)]
                if chart_type == "line":
                    fig.add_trace(go.Scatter(x=df[x], y=df[col_name], name=col_name, line=dict(color=c), mode='lines+markers'), secondary_y=False)
                else:
                    fig.add_trace(go.Bar(x=df[x], y=df[col_name], name=col_name, marker_color=c), secondary_y=False)
            
            for i, col_name in enumerate(sec_y_cols):
                c = current_seq[(i + len(primary_y)) % len(current_seq)]
                if chart_type == "line":
                    fig.add_trace(go.Scatter(x=df[x], y=df[col_name], name=col_name, line=dict(color=c, dash='dot'), mode='lines+markers'), secondary_y=True)
                else:
                    fig.add_trace(go.Scatter(x=df[x], y=df[col_name], name=col_name, line=dict(color=c), mode='lines+markers'), secondary_y=True)
            
            fig.update_yaxes(title_text=", ".join(primary_y), secondary_y=False)
            fig.update_yaxes(title_text=", ".join(sec_y_cols), secondary_y=True)
            fig.update_layout(title_text=title)
            
        # --- STANDARD HANDLER ---
        else:
            if chart_type == "bar":
                fig = px.bar(df, x=x, y=primary_y, color=viz_color, title=title, barmode=barmode, 
                             color_discrete_sequence=current_seq, orientation=config.get("orientation", "v"))
            elif chart_type == "line":
                fig = px.line(df, x=x, y=primary_y, color=viz_color, title=title, markers=True, color_discrete_sequence=current_seq)
            elif chart_type == "scatter":
                fig = px.scatter(df, x=x, y=primary_y, color=viz_color, title=title, color_discrete_sequence=current_seq)
            elif chart_type == "pie":
                textinfo = config.get("textinfo", "percent+label")
                fig = px.pie(df, names=x, values=primary_y[0], title=title, color_discrete_sequence=current_seq)
                fig.update_traces(textinfo=textinfo, textfont_size=13, textposition='inside', insidetextorientation='radial')
                fig.update_layout(showlegend=True)
            elif chart_type == "area":
                fig = px.area(df, x=x, y=primary_y, color=viz_color, title=title, color_discrete_sequence=current_seq)
            elif chart_type == "heatmap":
                # ... (Heatmap logic unchanged) ...
                try:
                    z_col = viz_color if isinstance(viz_color, str) else None
                    fig = px.density_heatmap(df, x=x, y=primary_y[0], z=z_col, title=title, color_continuous_scale='Viridis', text_auto=True)
                except:
                    fig = px.scatter(df, x=x, y=primary_y, title=title)
            
            elif chart_type in ["treemap", "sunburst"]:
                path_cols = config.get("path", [x])
                if isinstance(path_cols, str): path_cols = [path_cols]
                
                # 1. Ensure columns exist
                valid_path = [c for c in path_cols if c in df.columns]
                if not valid_path: valid_path = [x] if x in df.columns else [df.columns[0]]
                
                # 2. FILL NA/EMPTY to prevent "Non-leaves" error
                df_clean = df.copy()
                for c in valid_path:
                    df_clean[c] = df_clean[c].fillna("Unknown").astype(str).replace('', "Unknown")
                
                # 3. Check for value column (must be numeric)
                val_col = primary_y[0] if primary_y else None
                if val_col:
                     df_clean[val_col] = pd.to_numeric(df_clean[val_col], errors='coerce').fillna(0)
                
                if chart_type == "treemap":
                    fig = px.treemap(df_clean, path=valid_path, values=val_col, title=title, color_discrete_sequence=current_seq)
                else:
                    fig = px.sunburst(df_clean, path=valid_path, values=val_col, title=title, color_discrete_sequence=current_seq)

            elif chart_type == "radar":
                try:
                    categories = df[x].tolist() if isinstance(x, str) else df[x[0]].tolist()
                    values = df[primary_y[0]].tolist() if primary_y else df.iloc[:, 1].tolist()
                    fig = go.Figure(data=go.Scatterpolar(r=values, theta=categories, fill='toself', line_color=current_seq[0]))
                    fig.update_layout(polar=dict(radialaxis=dict(visible=True)), title=title)
                except:
                    fig = px.bar(df, x=x, y=primary_y, title=title, color_discrete_sequence=current_seq)

            elif chart_type == "pareto":
                try:
                    # Sort desc
                    val_col = primary_y[0] if primary_y else df.columns[1]
                    df_sorted = df.sort_values(by=val_col, ascending=False)
                    df_sorted['cumulative_prop'] = df_sorted[val_col].cumsum() / df_sorted[val_col].sum()
                    
                    fig = make_subplots(specs=[[{"secondary_y": True}]])
                    fig.add_trace(go.Bar(x=df_sorted[x], y=df_sorted[val_col], name=str(val_col), marker_color=current_seq[0]), secondary_y=False)
                    fig.add_trace(go.Scatter(x=df_sorted[x], y=df_sorted['cumulative_prop'], name='Cumulative %', mode='lines+markers', line=dict(color='red', width=2)), secondary_y=True)
                    fig.update_layout(title_text=title)
                    fig.update_yaxes(title_text="Cumulative %", tickformat=".0%", secondary_y=True)
                    fig.update_yaxes(title_text=str(val_col), secondary_y=False)
                except:
                     fig = px.bar(df, x=x, y=primary_y, title=title, color_discrete_sequence=current_seq)

            elif chart_type == "parallel":
                try:
                    # Parallel Coordinates
                    dims = [x] + primary_y + (sec_y_cols if sec_y_cols else [])
                    numeric_dims = [d for d in dims if pd.api.types.is_numeric_dtype(df[d])]
                    if len(numeric_dims) < 2: numeric_dims = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])][:5]
                    
                    fig = px.parallel_coordinates(df, dimensions=numeric_dims, color=numeric_dims[0], title=title, color_continuous_scale=px.colors.diverging.Tealrose)
                except:
                     fig = px.bar(df, x=x, y=primary_y, title=title, color_discrete_sequence=current_seq)

            elif chart_type == "bullet":
                try:
                    # Bullet Chart
                     val_col = primary_y[0] if primary_y else df.columns[1]
                     val = df[val_col].iloc[0]
                     target = df[secondary_y[0]].iloc[0] if secondary_y else val * 1.2
                     
                     fig = go.Figure(go.Indicator(
                        mode = "number+gauge+delta", value = val,
                        delta = {'reference': target},
                        gauge = {'shape': "bullet", 'axis': {'range': [None, target * 1.5]}, 'threshold': {'line': {'color': "red", 'width': 2}, 'thickness': 0.75, 'value': target}, 'bar': {'color': current_seq[0]}},
                        title = {'text': title}
                     ))
                     fig.update_layout(height=250)
                except:
                     fig = px.bar(df, x=x, y=primary_y, title=title, color_discrete_sequence=current_seq)

            elif chart_type == "sankey":
                # --- FIX: ROBUST SANKEY HANDLING ---
                try:
                    source_col = x if isinstance(x, str) else (x[0] if isinstance(x, list) else df.columns[0])
                    # Intelligent guess for target if not explicit
                    target_col = df.columns[1] if len(df.columns) > 1 else source_col
                    # If target is same as source, pick next available
                    if target_col == source_col and len(df.columns) > 2: target_col = df.columns[2]
                        
                    value_col = primary_y[0] if primary_y else (df.columns[2] if len(df.columns) > 2 else None)
                    
                    if source_col and target_col:
                        df_clean = df.copy()

                        # Clean source and target
                        df_clean[source_col] = df_clean[source_col].fillna("Unknown").astype(str).replace('', "Unknown")
                        df_clean[target_col] = df_clean[target_col].fillna("Unknown").astype(str).replace('', "Unknown")

                        # Clean or create value column
                        if value_col and value_col in df_clean.columns:
                            df_clean[value_col] = pd.to_numeric(df_clean[value_col], errors='coerce').fillna(1)
                        else:
                            value_col = "_Sankey_Count"
                            df_clean[value_col] = 1

                        # Filter valid links (no self loops, positive values)
                        df_clean = df_clean[(df_clean[value_col] > 0) & (df_clean[source_col] != df_clean[target_col])]

                        # Aggregate
                        df_agg = df_clean.groupby([source_col, target_col], as_index=False)[value_col].sum()

                        if df_agg.empty:
                            raise ValueError("No valid links for Sankey after cleaning")

                        # Create unique index mapping
                        labels = list(pd.concat([df_agg[source_col], df_agg[target_col]]).unique())
                        source_idx = [labels.index(s) for s in df_agg[source_col]]
                        target_idx = [labels.index(t) for t in df_agg[target_col]]
                        values = df_agg[value_col].tolist()
                        
                        fig = go.Figure(data=[go.Sankey(
                            node=dict(label=labels, pad=15, thickness=20, line=dict(color="black", width=0.5), color=current_seq[:len(labels)]),
                            link=dict(source=source_idx, target=target_idx, value=values)
                        )])
                        fig.update_layout(title_text=title)
                    else:
                        raise ValueError("Not enough columns for Sankey")
                except Exception as e:
                    fig = px.bar(df, x=x, y=primary_y, title=title + " (Sankey Fallback)", color_discrete_sequence=current_seq)

            elif chart_type == "histogram":
                try:
                    hist_col = primary_y[0] if primary_y else x
                    fig = px.histogram(df, x=hist_col, color=viz_color, title=title, color_discrete_sequence=current_seq, nbins=config.get("nbins", 30))
                    fig.update_layout(bargap=0.05)
                except:
                    fig = px.bar(df, x=x, y=primary_y, title=title, color_discrete_sequence=current_seq)

            elif chart_type == "box":
                try:
                    fig = px.box(df, x=x if viz_color else None, y=primary_y[0], color=viz_color, title=title, color_discrete_sequence=current_seq, points="outliers")
                except:
                    fig = px.bar(df, x=x, y=primary_y, title=title, color_discrete_sequence=current_seq)

            elif chart_type == "violin":
                try:
                    fig = px.violin(df, x=x if viz_color else None, y=primary_y[0], color=viz_color, title=title, color_discrete_sequence=current_seq, box=True, points="all")
                except:
                    fig = px.bar(df, x=x, y=primary_y, title=title, color_discrete_sequence=current_seq)

            elif chart_type == "bubble":
                try:
                    size_col = config.get("size")
                    if size_col and size_col in df.columns:
                        fig = px.scatter(df, x=x, y=primary_y[0], size=size_col, color=viz_color, title=title, color_discrete_sequence=current_seq, size_max=60)
                    else:
                        fig = px.scatter(df, x=x, y=primary_y[0], color=viz_color, title=title, color_discrete_sequence=current_seq)
                except:
                    fig = px.scatter(df, x=x, y=primary_y, title=title, color_discrete_sequence=current_seq)

            elif chart_type == "waterfall":
                try:
                    fig = go.Figure(go.Waterfall(
                        orientation="v",
                        x=df[x].tolist() if isinstance(x, str) else df.iloc[:, 0].tolist(),
                        y=df[primary_y[0]].tolist(),
                        connector={"line": {"color": "#29B5E8"}},
                        increasing={"marker": {"color": "#00D4AA"}},
                        decreasing={"marker": {"color": "#FF6B6B"}},
                        totals={"marker": {"color": "#FFD700"}}
                    ))
                    fig.update_layout(title=title)
                except:
                    fig = px.bar(df, x=x, y=primary_y, title=title, color_discrete_sequence=current_seq)

            elif chart_type == "funnel":
                try:
                    fig = px.funnel(df, x=primary_y[0], y=x, title=title, color_discrete_sequence=current_seq)
                except:
                    fig = px.bar(df, x=x, y=primary_y, title=title, color_discrete_sequence=current_seq)

            elif chart_type == "gauge":
                try:
                    val_col = primary_y[0] if primary_y else df.columns[1]
                    val = float(df[val_col].iloc[0])
                    max_val = float(df[val_col].max()) * 1.2 if len(df) > 1 else val * 1.5
                    fig = go.Figure(go.Indicator(
                        mode="gauge+number+delta",
                        value=val,
                        title={'text': title, 'font': {'size': 16, 'color': '#00D4AA'}},
                        gauge={
                            'axis': {'range': [0, max_val], 'tickcolor': 'white'},
                            'bar': {'color': '#00D4AA'},
                            'steps': [
                                {'range': [0, max_val * 0.5], 'color': 'rgba(0, 212, 170, 0.1)'},
                                {'range': [max_val * 0.5, max_val * 0.8], 'color': 'rgba(255, 215, 0, 0.1)'},
                                {'range': [max_val * 0.8, max_val], 'color': 'rgba(255, 107, 107, 0.1)'}
                            ]
                        }
                    ))
                    fig.update_layout(height=300)
                except:
                    fig = px.bar(df, x=x, y=primary_y, title=title, color_discrete_sequence=current_seq)

            else:
                # Catch-all
                fig = px.bar(df, x=x, y=primary_y, color=viz_color, title=title, color_discrete_sequence=current_seq)
            
        if fig:
            # --- VALUE FORMAT HANDLER ---
            value_format = config.get("value_format", "default")
            
            # Apply Custom Axis Labels if compatible
            try:
                if chart_type not in ['pie', 'treemap', 'sunburst', 'sankey', 'radar', 'gauge', 'bullet']:
                    fig.update_layout(
                        xaxis_title=x_label,
                        yaxis_title=y_label
                    )
                    # Auto rotate long x-axis labels
                    if isinstance(x, str) and x in df.columns:
                        avg_label_len = df[x].astype(str).str.len().mean()
                        if avg_label_len > 12:
                            fig.update_layout(xaxis_tickangle=-45)
                    # Compact number formatting for large values
                    if value_format == "compact":
                        fig.update_layout(yaxis_tickformat='.3s')  # 1.2M, 3.4K format
                    elif value_format == "percentage":
                        fig.update_layout(yaxis_tickformat='.1%')
            except: pass

            fig.update_layout(
                plot_bgcolor='rgba(0,0,0,0)',
                paper_bgcolor='rgba(0,0,0,0)',
                font=dict(color='white', size=13),
                title=dict(font=dict(size=16, color='#00D4AA')),
                margin=dict(l=60, r=20, t=50, b=80),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=12)),
                hoverlabel=dict(bgcolor='#1a1e22', font_size=13, font_color='white'),
                height=config.get("height", 420)
            )
            
            # Interactive Play
            event = st.plotly_chart(fig, use_container_width=True, on_select="rerun", key=chart_key)
            if event and hasattr(event, "selection") and getattr(event, "selection", None) and "points" in event.selection and event.selection["points"]:
                pt = event.selection["points"][0]
                filter_val = None
                filter_col = None
                
                if chart_type in ["pie", "treemap", "sunburst"]:
                    if "label" in pt:
                        filter_val = pt["label"]
                        # Robust hierarchical column fallback
                        filter_col = x if isinstance(x, str) else config.get("path", [x])[0]
                elif "x" in pt:
                    filter_val = pt["x"]
                    filter_col = x if isinstance(x, str) else (x[0] if isinstance(x, list) else df.columns[0])
                elif "y" in pt and config.get("orientation") == "h":
                    filter_val = pt["y"]
                    filter_col = x if isinstance(x, str) else (x[0] if isinstance(x, list) else df.columns[0])
                    
                if filter_val is not None and filter_col and filter_col in df.columns:
                    if 'wizard_filters' not in st.session_state: st.session_state.wizard_filters = {}
                    st.session_state.wizard_filters[filter_col] = filter_val
                    st.rerun()
            
    except Exception as e:
        st.error(f"Viz Error ({config.get('type')}): {e}")

# =====================================================
# WIZARD UI: CONTEXT HUB V2
# =====================================================

def render_context_hub_wizard(client):
    if "context_config" not in st.session_state:
        st.session_state.context_config = {'warehouses': [], 'databases': [], 'tables': [], 'files': []}
        
    with st.expander("🛡️ **Wizard Context Hub** (Deep Analysis Control)", expanded=False):
        st.caption("Enable multi-warehouse view, pin specific tables, or attach custom script logic.")
        
        tab_compute, tab_data, tab_files = st.tabs(["⚡ Compute & Warehouses", "📊 Data Tables", "📄 Script Files"])
        
        # 1. Compute
        with tab_compute:
            try:
                wh_df = client.get_all_warehouses()
                all_whs = wh_df['NAME'].tolist() if not wh_df.empty else []
                
                c1, c2 = st.columns([1, 1])
                with c1:
                    if st.button("Select All Warehouses", use_container_width=True):
                        st.session_state.context_config['warehouses'] = all_whs
                    if st.button("Clear Selection", key="clr_wh", use_container_width=True):
                        st.session_state.context_config['warehouses'] = []
                
                with c2:
                    st.session_state.context_config['warehouses'] = st.multiselect(
                        "Search & Select:", all_whs, default=st.session_state.context_config['warehouses']
                    )
                
                manual_wh = st.text_input("Paste Specific (comma-sep):", placeholder="DEV_WH, PROD_WH...")
                if manual_wh:
                    st.session_state.context_config['warehouses'] = list(set(st.session_state.context_config['warehouses'] + [x.strip() for x in manual_wh.split(',') if x.strip()]))
            except: st.warning("Snowflake access restricted.")

        # 2. Data Tables
        with tab_data:
            tables = discover_all_tables(client)
            all_tbls = list(tables.keys())
            
            c1, c2 = st.columns([2, 1])
            with c1:
                st.session_state.context_config['tables'] = st.multiselect(
                    "Search Pinned Tables:", all_tbls, default=st.session_state.context_config['tables']
                )
            with c2:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("Index Discovery", type="secondary"):
                    st.session_state.discovered_tables = None
                    st.rerun()
            
            manual_tbl = st.text_area("Paste Fully Qualified Names:", height=68, placeholder="DB.SCHEMA.TABLE_ONE, DB.SCHEMA.TABLE_TWO")
            if manual_tbl:
                st.session_state.context_config['tables'] = list(set(st.session_state.context_config['tables'] + [x.strip() for x in manual_tbl.split(',') if x.strip()]))

        # 3. Files
        with tab_files:
            try:
                stages = client.get_all_stages()
                s_list = stages['name'].tolist() if not stages.empty else []
                if '~' not in s_list: s_list.insert(0, '~')
                
                col_s, col_f = st.columns([1, 2])
                selected_stage = col_s.selectbox("Stage", s_list)
                
                try:
                    files_df = client.list_stage_files(selected_stage)
                    all_files = [f"@{selected_stage}/{f}" for f in files_df['name'].tolist()] if not files_df.empty else []
                    st.session_state.context_config['files'] = st.multiselect("Select Script Files:", all_files)
                except: st.caption("No files discovered.")
            except: pass

        # 4. Systems (New Phase 8)
        with st.tabs(["⚙️ System Views"])[0]:
            st.caption("Auto-include high-level Snowflake telemetry.")
            c1, c2 = st.columns(2)
            with c1:
                if st.checkbox("Include Account Usage", value=False, help="Adds QUERY_HISTORY, WAREHOUSE_METERING to context."):
                    st.session_state.context_config['system_usage'] = True
                else:
                    st.session_state.context_config['system_usage'] = False
            with c2:
                if st.checkbox("Include Pipes & Tasks", value=False, help="Adds COPY_HISTORY, TASK_HISTORY to context."):
                    st.session_state.context_config['system_pipelines'] = True
                else:
                    st.session_state.context_config['system_pipelines'] = False

        # 5. Settings
        st.divider()
        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            st.session_state.viz_enabled = st.toggle("🎨 **Visualization Mode**", value=True, help="Enable autonomous multi-graph plotting.")
        with c2:
            st.session_state.safe_mode = st.toggle("🛡️ **Safe Mode**", value=True, help="Require approval for write operations.")
        with c3:
            st.session_state.chart_layout = st.selectbox(
                "📊 Chart Layout",
                ["Vertical (Stacked)", "Horizontal (Side-by-Side)"],
                index=0,
                help="Choose how charts are arranged"
            )
        
        cc1, cc2 = st.columns([1, 1])
        with cc1:
            st.session_state.deep_reasoning = st.toggle(
                "🧠 **Deep Reasoning Mode**", value=True,
                help="When enabled, the Wizard feeds actual data statistics (cardinality, distributions, min/max) back to the AI for smarter chart selection. Uses 2 AI calls per query block instead of 1."
            )
        with cc2:
            if st.button("🗑️ Clear Chat", use_container_width=True):
                st.session_state.messages = []
                st.session_state.wizard_filters = {}
                st.rerun()

    return st.session_state.context_config

# =====================================================
# MAIN WINDOW
# =====================================================

def main():
    st.markdown("<h1 style='text-align: center; color: #00D4AA; margin-bottom: 0px;'>✨ Wizard AI Data Analyst</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #8899A6; margin-top: 4px;'>Multi-Graph Visualization & Autonomous Reasoning Agent.</p>", unsafe_allow_html=True)
    
    client = get_client()
    viz_wizard = get_viz_agent()
    
    if 'messages' not in st.session_state: st.session_state.messages = []
    if 'wizard_filters' not in st.session_state: st.session_state.wizard_filters = {}
    
    render_context_hub_wizard(client)
    
    # Render Active Cross Filters
    if st.session_state.wizard_filters:
        f_cols = st.columns([8, 1])
        with f_cols[0]:
            st.info(f"🔍 **Active Cross-Filters:** {st.session_state.wizard_filters}")
        with f_cols[1]:
            if st.button("Clear", key="clr_wiz_flt", type="primary"):
                st.session_state.wizard_filters = {}
                st.rerun()
    
    # Render History
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            
            # Phase 5: Handle multiple result blocks
            if "results" in msg:
                msg_idx = list(st.session_state.messages).index(msg)
                for r_idx, res in enumerate(msg["results"]):
                    st.markdown(f"#### 🔍 {res.get('title', 'Result')}")
                    if "sql" in res:
                        render_code_with_copy(res["sql"])
                    
                    if "charts" in res and res.get("data") is not None:
                        df = res["data"]
                        num_charts = len(res["charts"])
                        is_horizontal = st.session_state.get('chart_layout', 'Vertical (Stacked)') == 'Horizontal (Side-by-Side)'
                        
                        if num_charts == 1:
                            with st.expander(res["charts"][0].get('title', 'Chart'), expanded=True):
                                render_chart_wizard(df, res["charts"][0], chart_key=f"ch_{msg_idx}_{r_idx}_0")
                        elif is_horizontal:
                            chart_cols = st.columns(2)
                            for j, cfg in enumerate(res["charts"]):
                                with chart_cols[j % 2]:
                                    with st.expander(cfg.get('title', f'Chart {j+1}'), expanded=True):
                                        render_chart_wizard(df, cfg, chart_key=f"ch_{msg_idx}_{r_idx}_{j}")
                        else:
                            # Default: Vertical stacking
                            for j, cfg in enumerate(res["charts"]):
                                with st.expander(cfg.get('title', f'Chart {j+1}'), expanded=True):
                                    render_chart_wizard(df, cfg, chart_key=f"ch_{msg_idx}_{r_idx}_{j}")

                    
                    if "data" in res and res.get("data") is not None:
                        with st.expander(f"📋 RAW DATA: {res.get('title', '')}"):
                            st.dataframe(res["data"], use_container_width=True)
            
            # Legacy support for single-result messages
            else:
                msg_idx = list(st.session_state.messages).index(msg)
                if "sql" in msg:
                     render_code_with_copy(msg["sql"])
                if "charts" in msg and msg.get("data") is not None:
                    df = msg["data"]
                    num_charts = len(msg["charts"])
                    if num_charts == 1:
                        render_chart_wizard(df, msg["charts"][0], chart_key=f"leg_{msg_idx}_0")
                    else:
                        cols = st.columns(2)
                        for j, cfg in enumerate(msg["charts"]):
                            with cols[j % 2]:
                                render_chart_wizard(df, cfg, chart_key=f"leg_{msg_idx}_{j}")
                if "data" in msg and msg.get("data") is not None:
                    with st.expander("📋 RAW DATA RESULTS"):
                        st.dataframe(msg["data"], use_container_width=True)

            if "insights" in msg and msg["insights"]:
                 st.markdown(f'<div class="insight-box">{msg["insights"]}</div>', unsafe_allow_html=True)
                 
            if "followups" in msg and msg["followups"]:
                st.caption("Suggested Follow-ups:")
                c1, c2, c3 = st.columns(3)
                for i, fq in enumerate(msg["followups"]):
                    if i < 3:
                        if st.button(fq, key=f"fq_{len(st.session_state.messages)}_{i}"):
                             # Logic to populate chat input would go here, but Streamlit limitaion
                             # Instead we can potentially rerun with this prompt?
                             pass    


    # Input Area
    if prompt := st.chat_input("Ask your Analytics Wizard..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)
        
        # 0. Check for Query Diagnosis Intent (Regex for UUID-like query ID)
        query_id_match = re.search(r'[a-z0-9]{8}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{12}', prompt)
        # 3. Check for "Forecast" Intent
        if "forecast" in prompt.lower() and ("cost" in prompt.lower() or "spend" in prompt.lower() or "budget" in prompt.lower()):
             with st.chat_message("assistant"):
                with st.spinner("🔮 Generating cost forecast (Linear Projection)..."):
                     forecast = forecast_costs(client)
                     st.markdown(forecast)
                     st.session_state.messages.append({"role": "assistant", "content": forecast})
             return
        if query_id_match and ("diagnose" in prompt.lower() or "why" in prompt.lower() or "slow" in prompt.lower()):
            q_id = query_id_match.group(0)
            with st.chat_message("assistant"):
                with st.spinner(f"Diagnosing query {q_id}..."):
                    diagnosis = diagnose_query(client, q_id)
                    st.markdown(diagnosis)
                    st.session_state.messages.append({"role": "assistant", "content": diagnosis})
            return # Stop processing

        # 2. Check for "Pattern Discovery" Intent
        if re.search(r'(common|top|recurring).*(errors|failures|patterns)', prompt.lower()):
            with st.chat_message("assistant"):
                with st.spinner("Analyzing failure patterns across the account..."):
                     report = discover_error_patterns(client)
                     st.markdown(report)
                     st.session_state.messages.append({"role": "assistant", "content": report})
            return

        with st.chat_message("assistant"):
            status = st.status("Wizard is orchestrating...", expanded=True)
            
            try:
                # 1. SQL
                status.write("🧠 Reasoning & SQL Synthesis...")
                
                # Fetch full dynamic context
                dynamic_context = get_dynamic_context(client, st.session_state.context_config)
                conversation_context = get_conversation_context()
                
                prompt_sql = f"""
                You are a Snowflake SQL Expert & Data Scientist. 
                Analyze the user's request and provide SQL queries to answer it with DEPTH and COMPLEXITY.
                
                CRITICAL FORMATTING RULES:
                - Use CTEs (Common Table Expressions) to break down complex logic.
                - DO NOT create separate queries for scalar values. JOIN tables to create a "Master Dataset".
                - If user asks for "trends", usage DATE_TRUNC and Window Functions (AVG OVER PARTITION).
                - Prefix EACH code block with: ### [Descriptive Title]
                - You MUST wrap your SQL queries inside ```sql ... ``` code blocks.
                - Return ONLY SQL blocks with headings. NO markdown text outside the headings/blocks.
                
                ADVANCED ANALYSIS INSTRUCTIONS:
                1. **Complex Joins**: Always try to enrich data. (e.g., Join Query History with Warehouse Metering on truncated timestamps).
                2. **Edge Cases**: Filter out noise (e.g., `WHERE BYTES_SCANNED > 0`, `EXECUTION_TIME > 100`).
                3. **Hierarchies**: For "Breakdowns", utilize `GROUP BY ROLLUP` or grouping sets if helpful, or just flat complex groupings.
                4. **Flows**: If user asks for "Lineage" or "Flow", generate `SOURCE`, `TARGET`, `VALUE` columns for Sankey charts.
                5. **System Noise Mapping**: ALWAYS filter out Snowflake background tasks in your queries: `WHERE QUERY_TEXT NOT ILIKE '%streamlit%' AND QUERY_TEXT NOT ILIKE '%ATU%'`.
                
                BAD EXAMPLE (DO NOT DO THIS):
                ### [Total Queries]
                ```sql
                SELECT COUNT(*) FROM ...
                ```
                
                GOOD EXAMPLE (DO THIS INSTEAD):
                ### [Comprehensive Query Performance & Cost Landscape]
                ```sql
                WITH hourly_stats AS (
                    SELECT 
                        DATE_TRUNC('hour', start_time) as hour_bucket,
                        warehouse_name,
                        COUNT(*) as query_count,
                        AVG(total_elapsed_time)/1000 as avg_duration_s,
                        SUM(case when execution_status = 'FAIL' then 1 else 0 end) as failures
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time > DATEADD(day, -7, CURRENT_TIMESTAMP())
                    GROUP BY 1, 2
                )
                SELECT 
                    h.hour_bucket,
                    h.warehouse_name,
                    h.query_count,
                    h.avg_duration_s,
                    h.failures,
                    m.credits_used
                FROM hourly_stats h
                LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY m 
                  ON h.warehouse_name = m.warehouse_name 
                  AND h.hour_bucket = m.start_time
                ORDER BY 1 DESC, 2
                ```
                
                USER PROMPT: "{prompt}"
                
                AVAILABLE CONTEXT:
                {dynamic_context}
                {conversation_context}
                
                CORE TABLES:
                - SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY (BYTES_SCANNED, TOTAL_ELAPSED_TIME, USER_NAME, ROLE_NAME, WAREHOUSE_NAME, EXECUTION_STATUS, START_TIME, CREDITS_USED_CLOUD_SERVICES, ERROR_MESSAGE, QUERY_TEXT)
                - SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY (WAREHOUSE_NAME, CREDITS_USED, START_TIME)
                - SNOWFLAKE.ACCOUNT_USAGE.USERS (NAME, LOGIN_NAME, DISABLED, LAST_SUCCESS_LOGIN)
                - SNOWFLAKE.ACCOUNT_USAGE.TABLES (TABLE_NAME, TABLE_SCHEMA, ROW_COUNT, BYTES)
                
                STRICT RULES:
                1. Use BYTES_SCANNED, not TOTAL_BYTE_SCANNED.
                2. For trends, ALWAYS GROUP BY truncated time (DATE_TRUNC).
                3. Return data with MULTIPLE rows suitable for charts.
                4. For Queue Time analysis, use (QUEUED_PROVISIONING_TIME + QUEUED_OVERLOAD_TIME + QUEUED_REPAIR_TIME).
                """
                
                prompt_sql_escaped = prompt_sql.replace("'", "''")
                full_raw_resp = client.execute_query(f"SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large', '{prompt_sql_escaped}')", log=False)
                raw_text = full_raw_resp.iloc[0,0] if not full_raw_resp.empty else ""
                
                query_blocks = extract_multiple_queries(raw_text)
                
                if not query_blocks:
                     status.update(label="Reasoning Error", state="error")
                     st.error("Wizard could not synthesize any valid queries.")
                else:
                     results_to_persist = []
                     
                     # PHASE 1: COLLECT ALL DATA FIRST (no rendering yet)
                     status.write("📊 Fetching all data...")
                     for i, q_meta in enumerate(query_blocks):
                         q_title = q_meta['title']
                         q_sql = q_meta['sql']
                         
                         # Check for destructive/write operations
                         is_destructive = bool(re.search(r"\b(DROP|ALTER|DELETE|UPDATE|INSERT|CREATE|GRANT|REVOKE|COPY|TRUNCATE)\b", q_sql.upper()))
                         is_safe_mode = st.session_state.get('safe_mode', True)
                         
                         if is_destructive and is_safe_mode:
                             status.write(f"🛡️ **Blocked Critical Action**: {q_title}")
                             results_to_persist.append({
                                 "title": f"⚠️ {q_title} (APPROVAL REQUIRED)",
                                 "sql": q_sql,
                                 "data": pd.DataFrame(),
                                 "blocked": True,
                                 "charts": []
                             })
                             continue

                         status.write(f"🚀 Executing Step {i+1}/{len(query_blocks)}: **{q_title}**...")
                         try:
                             df = client.execute_query(q_sql)
                             df = sanitize_dataframe(df)
                         except Exception as e:
                             # SELF HEALING ATTEMPT
                             status.write(f"⚠️ Query failed. Attempting self-healing...")
                             fixed_sql = fix_sql_query(client, q_sql, str(e))
                             if fixed_sql:
                                 status.write(f"🚑 Fix proposed. Retrying...")
                                 try:
                                     df = client.execute_query(fixed_sql)
                                     df = sanitize_dataframe(df)
                                     q_sql = fixed_sql # Update logic
                                     status.write("✅ Fix successful!")
                                 except Exception as e2:
                                    df = pd.DataFrame()
                                    st.warning(f"Self-healing failed: {e2}")
                             else:
                                 df = pd.DataFrame()
                                 st.warning(f"Query error for '{q_title}': {e}")
                         
                         # Store result without rendering
                         results_to_persist.append({
                             "title": q_title,
                             "sql": q_sql,
                             "data": df,
                             "blocked": False,
                             "charts": []  # Will be populated in phase 2
                         })
                     
                     # PHASE 2: DESIGN VISUALIZATIONS (after all data is ready)
                     status.write("🎨 Designing visualizations...")
                     use_deep = st.session_state.get('deep_reasoning', True)
                     for res_block in results_to_persist:
                         df = res_block['data']
                         q_title = res_block['title']
                         
                         should_visualize = not df.empty and len(df) > 1 and st.session_state.get('viz_enabled', True)
                         if should_visualize:
                             if use_deep:
                                 status.write(f"🧠 Deep Reasoning for **{q_title}**...")
                                 res_block['charts'] = viz_wizard.suggest_visualizations_v2(df, f"{prompt} - {q_title}", query_title=q_title)
                             else:
                                 status.write(f"🎨 Designing Visuals for **{q_title}**...")
                                 res_block['charts'] = viz_wizard.suggest_visualizations(df, f"{prompt} - {q_title}")
                     
                     # PHASE 3: RENDER ALL CHARTS (after all design is complete)
                     status.write("📈 Rendering visualizations...")
                     for res_block in results_to_persist:
                         df = res_block['data']
                         q_title = res_block['title']
                         charts = res_block['charts']
                         should_visualize = not df.empty and len(df) > 1 and st.session_state.get('viz_enabled', True)
                         
                         st.markdown(f"#### 🔍 {q_title}")
                         
                         if res_block.get('blocked'):
                             st.warning("🛑 This action was blocked by Safe Mode.")
                             st.caption("Review the SQL above. To execute, disable Safe Mode in settings or copy the query.")
                             if st.button(f"🚨 Execute: {q_title}", key=f"exec_{i}"):
                                 try:
                                     client.execute_query(res_block['sql'])
                                     st.success("Executed!")
                                     st.rerun()
                                 except Exception as ex:
                                     st.error(f"Execution failed: {ex}")
                                     
                         elif df.empty:
                             st.info(f"No data returned for '{q_title}'")
                         elif len(df) == 1:
                             # Display single row as metric cards
                             metric_cols = st.columns(min(len(df.columns), 4))
                             for idx, col in enumerate(df.columns[:4]):
                                 with metric_cols[idx]:
                                     val = df[col].iloc[0]
                                     st.metric(label=col.replace('_', ' ').title(), value=val)
                         elif should_visualize and charts:
                             is_horizontal = st.session_state.get('chart_layout', 'Vertical (Stacked)') == 'Horizontal (Side-by-Side)'
                             msg_idx_active = len(st.session_state.messages) # Active message being formed
                             
                             if len(charts) == 1:
                                 with st.expander(charts[0].get('title', 'Chart'), expanded=True):
                                     render_chart_wizard(df, charts[0], chart_key=f"dyn_{msg_idx_active}_{i}_0")
                             elif is_horizontal:
                                 chart_cols = st.columns(2)
                                 for j, cfg in enumerate(charts):
                                     with chart_cols[j % 2]:
                                         with st.expander(cfg.get('title', f'Chart {j+1}'), expanded=True):
                                             render_chart_wizard(df, cfg, chart_key=f"dyn_{msg_idx_active}_{i}_{j}")
                             else:
                                 # Default: Vertical stacking (one below another)
                                 for j, cfg in enumerate(charts):
                                     with st.expander(cfg.get('title', f'Chart {j+1}'), expanded=True):
                                         render_chart_wizard(df, cfg, chart_key=f"dyn_{msg_idx_active}_{i}_{j}")

                         else:
                             st.dataframe(df, use_container_width=True)

                     # Final Insights
                     status.write("💡 Extracting Global Insights...")
                     concat_df = pd.concat([r['data'] for r in results_to_persist if not r['data'].empty]) if any(not r['data'].empty for r in results_to_persist) else pd.DataFrame()
                     insights = generate_insights_wizard(client, concat_df, [c for r in results_to_persist for c in r['charts']])
                     
                     status.write("🤔 Generating Follow-ups...")
                     followups = generate_followup_questions(client, prompt, concat_df)
                     
                     status.update(label="Wizardry Complete!", state="complete", expanded=False)
                     
                     if insights:
                         st.markdown(f'<div class="insight-box">{insights}</div>', unsafe_allow_html=True)
                        
                     # EXPORT BUTTON
                     try:
                         report_bytes = package_report(results_to_persist, insights)
                         if report_bytes:
                             st.download_button(
                                 label="📥 Download Full Analysis Report",
                                 data=report_bytes,
                                 file_name=f"snow_ops_analysis_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                                 mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                             )
                     except Exception as e:
                         st.error(f"Report generation failed: {e}")
                          
                     # Persist
                     st.session_state.messages.append({
                         "role": "assistant",
                         "content": f"I've performed **{len(results_to_persist)}** analysis steps.",
                         "results": results_to_persist,
                         "insights": insights,
                         "followups": followups
                     })
                         
            except Exception as e:
                status.update(label="Wizard Stalled", state="error")
                st.error(f"Error: {e}")
                with st.expander("🛠️ Wizard Debug Console (Error Trace)"):
                     st.code(f"""
Type: {type(e).__name__}
Message: {str(e)}
File: 10_AI_Analyst.py
Context: Agent Execution Loop
                     """, language="text")

if __name__ == "__main__":
    main()
