import streamlit as st
import pandas as pd
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.snowflake_client import get_snowflake_client
from utils.styles import apply_global_styles, render_sidebar

st.set_page_config(page_title="SQL Workbench | Snowflake Ops", page_icon="💻", layout="wide")

apply_global_styles()
render_sidebar()

def main():
    st.title("💻 SQL Workbench & Optimizer")
    st.caption("Ad-hoc Query Execution & AI Performance Tuning")

    client = get_snowflake_client()
    if not client.session:
        st.error("Please log in.")
        return

    tab1, tab2 = st.tabs(["📝 Query Editor", "🚀 AI Optimizer"])

    with tab1:
        query = st.text_area("SQL Query", height=200, placeholder="SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY LIMIT 10")
        
        c1, c2 = st.columns([1, 4])
        with c1:
            if st.button("Run Query", type="primary"):
                if query:
                    with st.spinner("Running..."):
                        try:
                            df = client.execute_query(query)
                            st.success("Query Executed Successfully")
                            st.dataframe(df)
                        except Exception as e:
                            st.error(f"Error: {e}")
                            
    with tab2:
        st.markdown("### 🚀 AI Query Optimizer")
        st.info("Optimize your complex queries before running them.")
        
        # Optimizer Inputs
        opt_query = st.text_area("Query to Optimize", height=150, placeholder="PASTE COMPLEX SQL HERE...")
        
        col1, col2 = st.columns(2)
        with col1:
             # Fetch warehouses for dropdown
            try:
                wh_df = client.execute_query("SHOW WAREHOUSES")
                wh_df.columns = [c.upper() for c in wh_df.columns]
                wh_options = wh_df['NAME'].tolist() if 'NAME' in wh_df.columns else ["COMPUTE_WH"]
            except:
                wh_options = ["COMPUTE_WH"]
                
            target_wh = st.selectbox("Target Warehouse", wh_options)
            
        with col2:
             optimization_goal = st.selectbox("Optimization Goal", ["Maximize Performance", "Minimize Cost", "Balanced"])

        if st.button("✨ Generate Optimization Plan"):
            if not opt_query:
                st.warning("Please provide a SQL query.")
            else:
                with st.spinner("AI Analyst is analyzing execution plan..."):
                    # Mock AI Analysis for Demo (Real impl would use Cortex/Explain Plan)
                    import time
                    time.sleep(2)
                    
                    st.markdown("#### 🔍 Analysis Result")
                    st.markdown(f"""
                    **Strategy**: `{optimization_goal}` on `{target_wh}`
                    
                    **Findings**:
                    - ⚠️ **High Pruning Risk**: Query scans full partitions.
                    - ⚠️ **Join Explosion**: Cross join detected on line 4.
                    
                    **Recommendations**:
                    1. Add `WHERE usage_date >= current_date() - 30` to limit partition scan.
                    2. Use a specific Cluster Key on the larger table.
                    """)
                    
                    st.code(f"""
                    -- Optimized Version
                    /* Added Partition Filter */
                    {opt_query} 
                    WHERE START_TIME >= DATEADD(day, -30, CURRENT_TIMESTAMP())
                    """, language='sql')

if __name__ == "__main__":
    main()
