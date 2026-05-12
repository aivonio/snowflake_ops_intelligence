
import streamlit as st
import pandas as pd

def init_database(client):
    """
    Initialize the application database schema and tables.
    Performs 'Self-Healing' by creating missing tables and adding missing columns.
    """
    if not client.session:
        return

    # 1. Ensure Schema
    try:
        client.execute_query("CREATE SCHEMA IF NOT EXISTS APP_CONTEXT", log=False)
    except Exception as e:
        print(f"Schema Init Error: {e}")
        return

    # 2. Define Tables and their expected columns
    tables = {
        "WAREHOUSE_CONTEXT": {
            "ddl": """
                CREATE TABLE IF NOT EXISTS APP_CONTEXT.WAREHOUSE_CONTEXT (
                    WAREHOUSE_NAME VARCHAR(255) PRIMARY KEY,
                    PURPOSE VARCHAR(100),
                    COST_PROFILE VARCHAR(50),
                    OWNER_TEAM VARCHAR(100),
                    CONCURRENCY_TOLERANCE VARCHAR(50),
                    NOTES VARCHAR(500),
                    LAST_UPDATED TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                )
            """,
            "columns": ["WAREHOUSE_NAME", "PURPOSE", "COST_PROFILE", "OWNER_TEAM", "CONCURRENCY_TOLERANCE", "NOTES", "LAST_UPDATED"]
        },
        "TEAM_ATTRIBUTION": {
            "ddl": """
                CREATE TABLE IF NOT EXISTS APP_CONTEXT.TEAM_ATTRIBUTION (
                    USER_NAME VARCHAR(255) PRIMARY KEY,
                    TEAM_NAME VARCHAR(100),
                    COST_CENTER VARCHAR(50),
                    BUDGET_LIMIT_CREDITS FLOAT,
                    ALERT_THRESHOLD_PERCENT INTEGER,
                    LAST_UPDATED TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                )
            """,
            "columns": ["USER_NAME", "TEAM_NAME", "COST_CENTER", "BUDGET_LIMIT_CREDITS", "ALERT_THRESHOLD_PERCENT", "LAST_UPDATED"]
        },
        "BUDGET_ALERTS": {
            "ddl": """
                CREATE TABLE IF NOT EXISTS APP_CONTEXT.BUDGET_ALERTS (
                    ALERT_ID NUMBER AUTOINCREMENT PRIMARY KEY,
                    ALERT_NAME VARCHAR(255),
                    ALERT_TYPE VARCHAR(50),
                    TARGET_NAME VARCHAR(255),
                    THRESHOLD_VALUE FLOAT,
                    CONDITION_OP VARCHAR(50),
                    NOTIFICATION_CHANNEL VARCHAR(50) DEFAULT 'DASHBOARD',
                    IS_ACTIVE BOOLEAN DEFAULT TRUE,
                    CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                )
            """,
            "columns": ["ALERT_ID", "ALERT_NAME", "ALERT_TYPE", "TARGET_NAME", "THRESHOLD_VALUE", "CONDITION_OP", "NOTIFICATION_CHANNEL", "IS_ACTIVE", "CREATED_AT"]
        },
        "NOTIFICATIONS_LOG": {
            "ddl": """
                CREATE TABLE IF NOT EXISTS APP_CONTEXT.NOTIFICATIONS_LOG (
                    EVENT_TIME TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
                    LEVEL VARCHAR(20),
                    MESSAGE VARCHAR(500),
                    CHANNEL VARCHAR(50) DEFAULT 'ALL'
                )
            """,
            "columns": ["EVENT_TIME", "LEVEL", "MESSAGE", "CHANNEL"]
        },
        "ENFORCEMENT_LOG": {
            "ddl": """
                CREATE TABLE IF NOT EXISTS APP_CONTEXT.ENFORCEMENT_LOG (
                    EVENT_TIME TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
                    ACTION VARCHAR(50),
                    TARGET_ID VARCHAR(255),
                    TEAM_NAME VARCHAR(100),
                    REASON VARCHAR(500)
                )
            """,
            "columns": ["EVENT_TIME", "ACTION", "TARGET_ID", "TEAM_NAME", "REASON"]
        },
        "APP_CONFIG": {
             "ddl": """
                CREATE TABLE IF NOT EXISTS APP_CONTEXT.APP_CONFIG (
                    CONFIG_KEY VARCHAR(100) PRIMARY KEY,
                    CONFIG_VALUE VARCHAR(5000),
                    CATEGORY VARCHAR(50),
                    DESCRIPTION VARCHAR(255),
                    UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                )
             """,
             "columns": ["CONFIG_KEY", "CONFIG_VALUE", "CATEGORY", "DESCRIPTION", "UPDATED_AT"]
        },
        "SAVED_DASHBOARDS": {
            "ddl": """
                CREATE TABLE IF NOT EXISTS APP_CONTEXT.SAVED_DASHBOARDS (
                    DASHBOARD_ID VARCHAR(36) PRIMARY KEY,
                    NAME VARCHAR(255),
                    DESCRIPTION VARCHAR(500),
                    LAYOUT_JSON VARIANT,
                    CREATED_BY VARCHAR(255),
                    UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                )
            """,
            "columns": ["DASHBOARD_ID", "NAME", "DESCRIPTION", "LAYOUT_JSON", "CREATED_BY", "UPDATED_AT"]
        }
    }

    # 3. Heal Tables
    for table_name, spec in tables.items():
        try:
            # A. Create if not exists
            client.execute_query(spec['ddl'], log=False)
            
            # B. Check for missing columns (Self-Healing)
            # This is a bit "heavy" to run every time, but specific to user request.
            # We can cache "healed" state in session state to run only once per session.
            if f"healed_{table_name}" not in st.session_state:
                current_cols_df = client.execute_query(f"DESC TABLE APP_CONTEXT.{table_name}", log=False)
                if not current_cols_df.empty:
                    current_cols = [c.upper() for c in current_cols_df['name'].tolist()] # DESC TABLE returns 'name'
                    
                    for req_col in spec['columns']:
                        if req_col not in current_cols:
                            # Add missing column
                            print(f"Healing: Adding {req_col} to {table_name}")
                            default_val = "NULL"
                            if "TIMESTAMP" in spec['ddl'] and req_col == "LAST_UPDATED": default_val = "CURRENT_TIMESTAMP()"
                            
                            alter_sql = f"ALTER TABLE APP_CONTEXT.{table_name} ADD COLUMN {req_col} VARCHAR(255)" # Default to VARCHAR for safety
                            # Refine types if needed, but generic healing is safer with VARCHAR or specific mapping
                            if "FLOAT" in spec['ddl'] and req_col in ["BUDGET_LIMIT_CREDITS", "THRESHOLD_VALUE"]:
                                alter_sql = f"ALTER TABLE APP_CONTEXT.{table_name} ADD COLUMN {req_col} FLOAT"
                            elif "BOOLEAN" in spec['ddl'] and req_col in ["IS_ACTIVE"]:
                                alter_sql = f"ALTER TABLE APP_CONTEXT.{table_name} ADD COLUMN {req_col} BOOLEAN DEFAULT TRUE"
                            elif "TIMESTAMP" in spec['ddl'] and req_col in ["CREATED_AT", "EVENT_TIME", "UPDATED_AT", "LAST_UPDATED"]:
                                alter_sql = f"ALTER TABLE APP_CONTEXT.{table_name} ADD COLUMN {req_col} TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()"
                            
                            client.execute_query(alter_sql, log=False)
                
                st.session_state[f"healed_{table_name}"] = True
                
        except Exception as e:
            print(f"Error healing {table_name}: {e}")
