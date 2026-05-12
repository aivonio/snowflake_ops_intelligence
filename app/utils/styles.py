
import streamlit as st

# Color Palette (Snowflake Brand + Modern Dark Theme)
COLORS = {
    "primary": "#29B5E8",       # Snowflake Blue
    "secondary": "#11567f",     # Darker Blue
    "background": "#0f1116",    # Dark Background
    "surface": "#1a1c24",       # Card Surface
    "text": "#ffffff",
    "muted": "#9499A1",
    "success": "#00D4AA",
    "warning": "#FFB020",
    "error": "#FF4B4B"
}

def apply_global_styles():
    """Apply global CSS styles for a premium Snowflake look."""
    st.markdown("""
        <style>
        /* Modern Dark Theme Base */
        .stApp {
            background-color: #0f1116;
            font-family: 'Inter', sans-serif;
        }
        
        /* Sidebar Styling */
        [data-testid="stSidebar"] {
            background-color: #1a1c24;
            border-right: 1px solid #2e3b4e;
        }

        /* Expander Styling */
        .streamlit-expanderHeader {
            background-color: #1a1c24 !important;
            border: 1px solid #2e3b4e !important;
            border-radius: 4px;
        }

        /* Metric Cards */
        div[data-testid="metric-container"] {
            background-color: #1a1c24;
            padding: 15px;
            border-radius: 8px;
            border: 1px solid #2e3b4e;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }

        /* Custom Navigation Headers */
        .nav-header {
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: #9499A1;
            margin-top: 20px;
            margin-bottom: 10px;
            padding-left: 5px;
            font-weight: 600;
        }
        
        /* HIDE DEFAULT STREAMLIT NAV */
        [data-testid="stSidebarNav"] {
            display: none !important;
        }
        </style>
    """, unsafe_allow_html=True)

def render_page_header(title, icon=None, description=None):
    """Render a consistent page header."""
    if icon:
        st.markdown(f"# {icon} {title}")
    else:
        st.title(title)
        
    if description:
        st.caption(description)
    st.divider()

def render_metric_card(label, value, delta=None, help_text=None, sub_label=None):
    """Render a styled metric card."""
    st.metric(label=label, value=value, delta=delta, help=help_text)
    if sub_label:
        st.caption(sub_label)

def render_sidebar():
    """
    Render the custom 'Mega Menu' sidebar with grouped navigation.
    Replaces the default Streamlit sidebar.
    """
    with st.sidebar:
        st.logo("https://upload.wikimedia.org/wikipedia/commons/f/ff/Snowflake_Logo.svg", icon_image="https://upload.wikimedia.org/wikipedia/commons/f/ff/Snowflake_Logo.svg")
        st.markdown("### ❄️ SnowOps Intel")
        
        # --- INTELLIGENCE HUB ---
        st.markdown('<div class="nav-header">Intelligence Hub</div>', unsafe_allow_html=True)
        st.page_link("pages/1_Cost.py", label="Cost Intelligence", icon="💰")
        st.page_link("pages/2_Queries.py", label="Query Performance", icon="⚡")
        st.page_link("pages/6_Cluster_Benchmark.py", label="Cluster Benchmarking", icon="⚖️")
        st.page_link("pages/14_Monitoring.py", label="Alerts & Monitoring", icon="🔔")

        # --- AI POWER SUITE ---
        st.markdown('<div class="nav-header">AI Power Suite</div>', unsafe_allow_html=True)
        st.page_link("pages/10_AI_Analyst.py", label="Cortex Analyst", icon="🧠")
        st.page_link("pages/8_AI_Query_Optimizer.py", label="Query Optimizer", icon="🚀")
        st.page_link("pages/13_Agent_Builder.py", label="Agent Builder", icon="🤖")
        st.page_link("pages/15_AI_BI_Builder.py", label="AI/BI Dashboarder", icon="📊")
        st.page_link("pages/12_Workbench.py", label="SQL Workbench", icon="💻")

        # --- OPERATIONS ---
        st.markdown('<div class="nav-header">Operations</div>', unsafe_allow_html=True)
        st.page_link("pages/4_Waste_Manager.py", label="Waste Manager", icon="🗑️")
        st.page_link("pages/3_Data_Observability_Hub.py", label="Data Observability", icon="🔭")
        st.page_link("pages/3_Warehouses.py", label="Warehouse Ops", icon="🏭")
        st.page_link("pages/4_Pipelines.py", label="Data Pipelines", icon="🔄")
        st.page_link("pages/7_Resource_Explorer.py", label="Resource Explorer", icon="🔎")
        st.page_link("pages/11_Data_Quality.py", label="Data Quality", icon="✅")
        st.page_link("pages/16_Governance.py", label="Security & Gov", icon="🛡️")

        # --- ADMIN ---
        st.markdown('<div class="nav-header">Admin</div>', unsafe_allow_html=True)
        st.page_link("pages/5_Settings.py", label="Settings & Config", icon="⚙️")
        st.page_link("streamlit_app.py", label="Home / Setup", icon="🏠")

        # Context Info
        if 'user_context' in st.session_state:
            st.divider()
            role = st.session_state.user_context.get('role', 'Unknown')
            st.caption(f"Logged in as: **{role}**")
            
        # --- SOCIAL LINKS ---
        st.divider()
        st.markdown('<div class="nav-header">Connect</div>', unsafe_allow_html=True)
        
        # Using columns for layout
        col_gh, col_li = st.columns(2)
        with col_gh:
            # REPLACE WITH YOUR GITHUB LINK
            st.markdown(
                """<a href="https://github.com/devbysatyam" target="_blank" style="text-decoration: none; color: #ffffff; display: flex; align-items: center; justify-content: center; background-color: #333; padding: 10px; border-radius: 5px;">
                    <img src="https://simpleicons.org/icons/github.svg" width="20" height="20" style="filter: invert(1);">
                </a>""", 
                unsafe_allow_html=True
            )
        with col_li:
             # REPLACE WITH YOUR LINKEDIN LINK
             st.markdown(
                """<a href="https://www.linkedin.com/in/devbysatyam/" target="_blank" style="text-decoration: none; color: #ffffff; display: flex; align-items: center; justify-content: center; background-color: #0077b5; padding: 10px; border-radius: 5px;">
                    <img src="https://simpleicons.org/icons/linkedin.svg" width="20" height="20" style="filter: invert(1);">
                </a>""", 
                unsafe_allow_html=True
            )
            
        st.markdown(
            """
            <div style="text-align: center; margin-top: 10px; font-size: 0.8em; color: #666;">
                DevBySatyam X Anktechsol
            </div>
            """,
            unsafe_allow_html=True
        )

def render_status_bar(user, role, warehouse):
    """Render a fixed bottom status bar."""
    st.markdown(f"""
        <style>
        .footer {{
            position: fixed;
            left: 0;
            bottom: 0;
            width: 100%;
            background-color: #1a1c24;
            color: #9499A1;
            text-align: center;
            padding: 5px;
            font-size: 0.8rem;
            border-top: 1px solid #2e3b4e;
            z-index: 1000;
        }}
        </style>
        <div class="footer">
            <span>👤 {user}</span> &nbsp;|&nbsp; 
            <span>🛡️ {role}</span> &nbsp;|&nbsp; 
            <span>🏭 {warehouse}</span>
        </div>
    """, unsafe_allow_html=True)
