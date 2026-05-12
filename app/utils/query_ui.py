
import streamlit as st
import pandas as pd
from utils.formatters import format_duration_ms, format_bytes

def render_interactive_query_inspector(df, title="Queries", key_prefix="insp"):
    """
    Renders a unified 'Master-Detail' view for a list of queries.
    
    Args:
        df (pd.DataFrame): DataFrame containing query history. Must have 'QUERY_ID', 'QUERY_TEXT', 'USER_NAME'.
        title (str): Section title.
        key_prefix (str): Unique key prefix for widgets.
    """
    if df.empty:
        st.info(f"No {title.lower()} found.")
        return

    st.markdown(f"### {title}")
    
    # 1. Selector
    # Create a nice label
    # Handle missing columns gracefully
    
    labels = []
    for idx, row in df.iterrows():
        # Try to find relevant metrics for label
        metric = ""
        if 'TOTAL_ELAPSED_TIME' in row:
             metric = f"⏱️ {row['TOTAL_ELAPSED_TIME']/1000:.1f}s"
        elif 'EST_CREDITS' in row:
             metric = f"💰 {row['EST_CREDITS']:.2f} Cr"
        elif 'BYTES_SCANNED' in row:
             metric = f"💾 {row['BYTES_SCANNED']/1024**3:.2f} GB"
             
        # Truncate text
        q_text = str(row['QUERY_TEXT'])[:60].replace('\n', ' ')
        labels.append(f"{metric} | {q_text}... ({row.get('USER_NAME', 'Unknown')})")
    
    df['display_label'] = labels
    
    selected_label = st.selectbox(
        f"🔎 Select a query to inspect:",
        options=df['display_label'].tolist(),
        index=0 if len(df) == 1 else None,
        key=f"{key_prefix}_selector",
        placeholder="Choose a query from the list..."
    )
    
    st.divider()
    
    # 2. Detail View
    if selected_label:
        row = df[df['display_label'] == selected_label].iloc[0]
        
        # Container style
        with st.container():
            # Header
            c1, c2 = st.columns([3, 1])
            with c1:

                st.caption("Query ID (Copy)")
                st.code(row['QUERY_ID'], language="text")
                st.markdown(f"**User:** `{row.get('USER_NAME', 'N/A')}` | **Warehouse:** `{row.get('WAREHOUSE_NAME', 'N/A')}`")
            with c2:
                if 'EXECUTION_STATUS' in row:
                    status = row['EXECUTION_STATUS']
                    color = "green" if status == 'SUCCESS' else "red"
                    st.markdown(f"<span style='color:{color}; font-weight:bold; font-size:1.2em'>{status}</span>", unsafe_allow_html=True)

            # TABS for organized details
            d_tab1, d_tab2, d_tab3, d_tab4 = st.tabs(["📊 Overview", "📝 SQL", "📚 Metadata Context", "🤖 AI Analysis"])
            
            with d_tab1:
                # Metrics Grid
                m1, m2, m3, m4 = st.columns(4)
                
                with m1:
                    if 'TOTAL_ELAPSED_TIME' in row:
                        st.metric("Duration", f"{row['TOTAL_ELAPSED_TIME']/1000:.2f}s")
                    elif 'EXECUTION_TIME' in row:
                        st.metric("Duration", f"{row['EXECUTION_TIME']/1000:.2f}s")
                
                with m2:
                    if 'BYTES_SCANNED' in row:
                        st.metric("Bytes Scanned", format_bytes(row['BYTES_SCANNED']))
                
                with m3:
                     if 'PARTITIONS_SCANNED' in row and 'PARTITIONS_TOTAL' in row:
                         scanned = row['PARTITIONS_SCANNED']
                         total = row['PARTITIONS_TOTAL']
                         if total > 0:
                             ratio = scanned / total
                             st.metric("Partitions", f"{scanned}/{total}", help="Scanned / Total Partitions. Low ratio is better (Pruning).", delta=f"{ratio:.0%} Scanned", delta_color="inverse")
                         else:
                             st.metric("Partitions", f"{scanned}/{total}")
                
                with m4:
                    if 'EST_CREDITS' in row:
                        st.metric("Est. Cost", f"{row['EST_CREDITS']:.4f} Cr", help="Estimated cost based on warehouse size and duration.")
                    elif 'CREDITS_USED_CLOUD_SERVICES' in row:
                        st.metric("Cloud Credits", f"{row['CREDITS_USED_CLOUD_SERVICES']:.4f}", help="Credits used for cloud services (metadata, compilation).")

                # Row 2: Rows & Ratio
                m5, m6, m7, m8 = st.columns(4)
                with m5:
                    if 'ROWS_PRODUCED' in row:
                        st.metric("Rows Produced", f"{row['ROWS_PRODUCED']:,}", help="Total rows generated. High numbers may indicate exploding joins.")
                    elif 'rows_returned' in row:
                         st.metric("Rows Returned", f"{row['rows_returned']:,}")


            with d_tab2:
                st.code(row['QUERY_TEXT'], language='sql')

            with d_tab3:
                st.markdown("##### Possible Tables Involved")
                st.caption("Auto-detected from query text (Simulated parser)")
                # Simple heuristic to find words that look like tables (schema.table)
                # This is weak but better than nothing without sqlglot
                import re
                q_text = row['QUERY_TEXT'].upper()
                # Regex for SCHEMA.TABLE or DATABASE.SCHEMA.TABLE
                potential_tables = set(re.findall(r'([A-Z0-9_]+\.[A-Z0-9_]+(?:\.[A-Z0-9_]+)?)', q_text))
                
                if potential_tables:
                    st.write("Found references:", ", ".join(list(potential_tables)))
                    
                    if st.button("🔎 Fetch Table Stats", key=f"{key_prefix}_meta_{row['QUERY_ID']}"):
                        from utils.snowflake_client import get_snowflake_client
                        client = get_snowflake_client()
                        if client.session:
                            for t in potential_tables:
                                try:
                                    # Safe-ish DESC (might fail if not authorized or not a table)
                                    # Use basic quoting to prevent injection if regex failed validation
                                    safe_t = t.replace(";", "") 
                                    res = client.execute_query(f"SHOW TABLES LIKE '{safe_t.split('.')[-1]}' IN SCHEMA {'.'.join(safe_t.split('.')[:-1])}")
                                    if not res.empty:
                                        st.write(f"**{t}**")
                                        st.dataframe(res[['name', 'rows', 'bytes', 'owner', 'created_on']], use_container_width=True)
                                    else:
                                        st.warning(f"Could not find metadata for {t}")
                                except Exception as e:
                                    pass # Ignore errors in heuristics
                else:
                    st.info("No explicit schema.table references found in text.")

            with d_tab4:
                # AI Actions (Optimization / Explanation)
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✨ Explain Query", key=f"{key_prefix}_expl_{row['QUERY_ID']}"):
                        st.info("AI Explanation feature placeholder")
                with c2:
                    if st.button("⚡ Optimize Query", type="primary", key=f"{key_prefix}_opt_{row['QUERY_ID']}"):
                         st.warning("Optimization requires page-specific context (available in original tabs).")
            
    else:
        st.info("Select a query above to view full details.")
