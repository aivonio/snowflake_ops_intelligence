"""
Comprehensive Resource Explorer
Access and monitor ALL Snowflake resources with ACCOUNTADMIN privileges
Warehouses, Databases, Schemas, Tables, Roles, Users, Stages, Pipes, Tasks, Streams, etc.
"""

import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.snowflake_client import get_snowflake_client
from utils.formatters import format_bytes, format_credits, dataframe_to_excel_bytes
from utils.styles import apply_global_styles, COLORS

st.set_page_config(
    page_title="Resource Explorer | Snowflake Ops",
    page_icon="🔍",
    layout="wide"
)

# Apply unified Snowflake design system
apply_global_styles()
from utils.styles import render_sidebar
render_sidebar()

st.title("🔍 Comprehensive Resource Explorer")
st.markdown("*Full visibility into all Snowflake resources with ACCOUNTADMIN access*")


client = get_snowflake_client()

if not client.session:
    st.error("⚠️ Could not connect to Snowflake")
    st.stop()

# Verify ACCOUNTADMIN
current_role = client.execute_query("SELECT CURRENT_ROLE()").iloc[0, 0]
st.info(f"🔐 Running as: **{current_role}**")

# Main tabs
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "🏭 Warehouses",
    "🗄️ Databases & Schemas",
    "📊 Tables & Views",
    "👥 Users & Roles",
    "📦 Stages & Pipes",
    "⚙️ Tasks & Streams",
    "🔧 Functions & Procedures",
    "📈 Resource Usage"
])

with tab1:
    st.markdown("### All Warehouses")
    
    warehouses = client.get_all_warehouses()
    
    if not warehouses.empty:
        # Standardize column names
        warehouses.columns = [c.upper() for c in warehouses.columns]
        
        st.metric("Total Warehouses", len(warehouses))
        
        # Display with filters
        col1, col2 = st.columns([1, 3])
        with col1:
            state_filter = st.multiselect(
                "Filter by State",
                options=warehouses['STATE'].unique() if 'STATE' in warehouses.columns else [],
                default=None
            )
        
        filtered_wh = warehouses
        if state_filter:
            filtered_wh = warehouses[warehouses['STATE'].isin(state_filter)]
        
        st.dataframe(filtered_wh, use_container_width=True, hide_index=True)
        
        # Export
        excel_data = dataframe_to_excel_bytes(warehouses, "Warehouses")
        st.download_button(
            "📥 Export to Excel",
            data=excel_data,
            file_name=f"warehouses_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.info("No warehouses found")

with tab2:
    st.markdown("### Databases & Schemas")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### Databases")
        databases = client.get_all_databases()
        
        if not databases.empty:
            databases.columns = [c.upper() for c in databases.columns]
            st.metric("Total Databases", len(databases))
            st.dataframe(databases, use_container_width=True, hide_index=True)
        else:
            st.info("No databases found")
    
    with col2:
        st.markdown("#### Schemas")
        
        # Select database
        if not databases.empty:
            selected_db = st.selectbox(
                "Select Database",
                options=databases['NAME'].tolist() if 'NAME' in databases.columns else []
            )
            
            if selected_db:
                schemas = client.get_all_schemas(selected_db)
                
                if not schemas.empty:
                    schemas.columns = [c.upper() for c in schemas.columns]
                    st.metric(f"Schemas in {selected_db}", len(schemas))
                    st.dataframe(schemas, use_container_width=True, hide_index=True)
                else:
                    st.info(f"No schemas in {selected_db}")

with tab3:
    st.markdown("### Tables & Views")
    
    # Database and schema selector
    databases = client.get_all_databases()
    
    if not databases.empty:
        databases.columns = [c.upper() for c in databases.columns]
        
        col1, col2 = st.columns(2)
        with col1:
            db_names = []
            if 'NAME' in databases.columns:
                db_names = databases['NAME'].tolist()
            elif 'name' in databases.columns:
                db_names = databases['name'].tolist()
            
            if db_names:
                selected_db = st.selectbox(
                    "Database",
                    options=db_names,
                    key="table_db"
                )
            else:
                st.warning(f"No database names found in columns: {databases.columns.tolist()}")
                selected_db = None
        
        with col2:
            selected_schema = None
            if selected_db:
                schemas = client.get_all_schemas(selected_db)
                if not schemas.empty:
                    schemas.columns = [c.upper() for c in schemas.columns]
                    schema_names = schemas['NAME'].tolist() if 'NAME' in schemas.columns else []
                    if schema_names:
                        selected_schema = st.selectbox(
                            "Schema",
                            options=schema_names
                        )
                    else:
                        st.info(f"No schemas in {selected_db}")
                else:
                    st.info(f"No schemas in {selected_db}")
        
        if selected_db and selected_schema:
            with st.spinner(f"Loading tables from {selected_db}.{selected_schema}..."):
                tables = client.get_all_tables(selected_db, selected_schema)
                
                if not tables.empty:
                    tables.columns = [c.upper() for c in tables.columns]
                    
                    # Summary metrics
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Total Tables", len(tables))
                    with col2:
                        if 'BYTES' in tables.columns:
                            total_bytes = tables['BYTES'].fillna(0).sum()
                            st.metric("Total Size", format_bytes(total_bytes))
                        else:
                            st.metric("Total Size", "N/A")
                    with col3:
                        if 'ROWS' in tables.columns:
                            total_rows = tables['ROWS'].fillna(0).sum()
                            st.metric("Total Rows", f"{int(total_rows):,}")
                        else:
                            st.metric("Total Rows", "N/A")
                    
                    # Display tables
                    st.dataframe(tables, use_container_width=True, hide_index=True)
                    
                    # Export
                    excel_data = dataframe_to_excel_bytes(tables, "Tables")
                    st.download_button(
                        "📥 Export to Excel",
                        data=excel_data,
                        file_name=f"tables_{selected_db}_{selected_schema}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                else:
                    st.info(f"No tables in {selected_db}.{selected_schema}")
        elif selected_db:
            st.info("Please select a schema to view tables")
    else:
        st.warning("No databases found")

with tab4:
    st.markdown("### Users & Roles")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### Users")
        with st.spinner("Loading users..."):
            users = client.get_all_users()
        
        if not users.empty:
            users.columns = [c.upper() for c in users.columns]
            st.metric("Total Users", len(users))
            
            # Display key columns
            display_cols = []
            for col in ['NAME', 'LOGIN_NAME', 'DISPLAY_NAME', 'EMAIL', 'DISABLED', 'DEFAULT_ROLE', 'DEFAULT_WAREHOUSE']:
                if col in users.columns:
                    display_cols.append(col)
            
            if display_cols:
                st.dataframe(users[display_cols], use_container_width=True, hide_index=True)
            else:
                st.dataframe(users, use_container_width=True, hide_index=True)
        else:
            st.info("No users found")
    
    with col2:
        st.markdown("#### Roles")
        with st.spinner("Loading roles..."):
            roles = client.get_all_roles()
        
        if not roles.empty:
            roles.columns = [c.upper() for c in roles.columns]
            st.metric("Total Roles", len(roles))
            
            # Display key columns
            display_cols = []
            for col in ['NAME', 'COMMENT', 'CREATED_ON', 'OWNER']:
                if col in roles.columns:
                    display_cols.append(col)
            
            if display_cols:
                st.dataframe(roles[display_cols], use_container_width=True, hide_index=True)
            else:
                st.dataframe(roles, use_container_width=True, hide_index=True)
            
            # Role grants explorer
            st.markdown("##### Explore Role Grants")
            role_names = roles['NAME'].tolist() if 'NAME' in roles.columns else []
            if role_names:
                selected_role = st.selectbox(
                    "Select Role",
                    options=role_names
                )
                
                if selected_role:
                    with st.spinner(f"Loading grants for {selected_role}..."):
                        grants = client.get_all_grants_to_role(selected_role)
                    if not grants.empty:
                        grants.columns = [c.upper() for c in grants.columns]
                        st.dataframe(grants, use_container_width=True, hide_index=True)
                    else:
                        st.info(f"No grants for {selected_role}")
        else:
            st.info("No roles found")

with tab5:
    st.markdown("### Stages & Pipes")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### Stages")
        stages = client.get_all_stages()
        
        if not stages.empty:
            stages.columns = [c.upper() for c in stages.columns]
            st.metric("Total Stages", len(stages))
            st.dataframe(stages, use_container_width=True, hide_index=True)
        else:
            st.info("No stages found")
    
    with col2:
        st.markdown("#### Pipes")
        pipes = client.get_all_pipes()
        
        if not pipes.empty:
            pipes.columns = [c.upper() for c in pipes.columns]
            st.metric("Total Pipes", len(pipes))
            st.dataframe(pipes, use_container_width=True, hide_index=True)
        else:
            st.info("No pipes found")

with tab6:
    st.markdown("### Tasks & Streams")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### Tasks")
        tasks = client.get_all_tasks()
        
        if not tasks.empty:
            tasks.columns = [c.upper() for c in tasks.columns]
            st.metric("Total Tasks", len(tasks))
            
            # Filter by state
            if 'STATE' in tasks.columns:
                state_filter = st.multiselect(
                    "Filter by State",
                    options=tasks['STATE'].unique(),
                    key="task_state"
                )
                if state_filter:
                    tasks = tasks[tasks['STATE'].isin(state_filter)]
            
            st.dataframe(tasks, use_container_width=True, hide_index=True)
        else:
            st.info("No tasks found")
    
    with col2:
        st.markdown("#### Streams")
        streams = client.get_all_streams()
        
        if not streams.empty:
            streams.columns = [c.upper() for c in streams.columns]
            st.metric("Total Streams", len(streams))
            
            # Check for stale streams
            if 'STALE' in streams.columns:
                stale_count = len(streams[streams['STALE'] == 'true'])
                if stale_count > 0:
                    st.warning(f"⚠️ {stale_count} stale stream(s) detected")
            
            st.dataframe(streams, use_container_width=True, hide_index=True)
        else:
            st.info("No streams found")

with tab7:
    st.markdown("### Functions & Procedures")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### User-Defined Functions")
        functions = client.get_all_functions()
        
        if not functions.empty:
            functions.columns = [c.upper() for c in functions.columns]
            st.metric("Total Functions", len(functions))
            st.dataframe(functions, use_container_width=True, hide_index=True)
        else:
            st.info("No user-defined functions found")
    
    with col2:
        st.markdown("#### Stored Procedures")
        procedures = client.get_all_procedures()
        
        if not procedures.empty:
            procedures.columns = [c.upper() for c in procedures.columns]
            st.metric("Total Procedures", len(procedures))
            st.dataframe(procedures, use_container_width=True, hide_index=True)
        else:
            st.info("No stored procedures found")

with tab8:
    st.markdown("### Resource Usage Summary")
    
    with st.spinner("Loading resource counts..."):
        # Aggregate resource counts with error handling
        resource_counts = {}
        
        try:
            wh = client.get_all_warehouses()
            resource_counts['Warehouses'] = len(wh) if not wh.empty else 0
        except:
            resource_counts['Warehouses'] = 0
        
        try:
            db = client.get_all_databases()
            resource_counts['Databases'] = len(db) if not db.empty else 0
        except:
            resource_counts['Databases'] = 0
        
        try:
            users = client.get_all_users()
            resource_counts['Users'] = len(users) if not users.empty else 0
        except:
            resource_counts['Users'] = 0
        
        try:
            roles = client.get_all_roles()
            resource_counts['Roles'] = len(roles) if not roles.empty else 0
        except:
            resource_counts['Roles'] = 0
        
        try:
            stages = client.get_all_stages()
            resource_counts['Stages'] = len(stages) if not stages.empty else 0
        except:
            resource_counts['Stages'] = 0
        
        try:
            pipes = client.get_all_pipes()
            resource_counts['Pipes'] = len(pipes) if not pipes.empty else 0
        except:
            resource_counts['Pipes'] = 0
        
        try:
            tasks = client.get_all_tasks()
            resource_counts['Tasks'] = len(tasks) if not tasks.empty else 0
        except:
            resource_counts['Tasks'] = 0
        
        try:
            streams = client.get_all_streams()
            resource_counts['Streams'] = len(streams) if not streams.empty else 0
        except:
            resource_counts['Streams'] = 0
        
        try:
            functions = client.get_all_functions()
            resource_counts['Functions'] = len(functions) if not functions.empty else 0
        except:
            resource_counts['Functions'] = 0
        
        try:
            procedures = client.get_all_procedures()
            resource_counts['Procedures'] = len(procedures) if not procedures.empty else 0
        except:
            resource_counts['Procedures'] = 0
    
    # Display as metrics
    cols = st.columns(5)
    for idx, (resource, count) in enumerate(resource_counts.items()):
        with cols[idx % 5]:
            st.metric(resource, count)
    
    # Chart
    resource_df = pd.DataFrame(list(resource_counts.items()), columns=['Resource', 'Count'])
    
    chart = alt.Chart(resource_df).mark_bar(color='#29B5E8').encode(
        x=alt.X('Count:Q', title='Count'),
        y=alt.Y('Resource:N', title='', sort='-x'),
        tooltip=['Resource', 'Count']
    ).properties(height=400, title='Resource Distribution')
    
    st.altair_chart(chart, use_container_width=True)
    
    # Export all resources summary
    st.markdown("### Export All Resources")
    
    if st.button("📥 Generate Complete Resource Report"):
        with st.spinner("Generating comprehensive report..."):
            # Create Excel with multiple sheets
            import io
            
            buffer = io.BytesIO()
            
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                # Write each resource type to a sheet
                resource_data = [
                    ('Warehouses', client.get_all_warehouses),
                    ('Databases', client.get_all_databases),
                    ('Users', client.get_all_users),
                    ('Roles', client.get_all_roles),
                    ('Stages', client.get_all_stages),
                    ('Pipes', client.get_all_pipes),
                    ('Tasks', client.get_all_tasks),
                    ('Streams', client.get_all_streams),
                    ('Functions', client.get_all_functions),
                    ('Procedures', client.get_all_procedures)
                ]
                
                for resource_name, df_func in resource_data:
                    try:
                        df = df_func()
                        if not df.empty:
                            df.to_excel(writer, sheet_name=resource_name[:31], index=False)
                    except Exception as e:
                        # Create empty sheet with error message
                        error_df = pd.DataFrame({'Error': [f'Could not load {resource_name}: {str(e)}']})
                        error_df.to_excel(writer, sheet_name=resource_name[:31], index=False)
            
            st.download_button(
                "📥 Download Complete Report",
                data=buffer.getvalue(),
                file_name=f"snowflake_resources_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
            st.success("✅ Report generated successfully!")
