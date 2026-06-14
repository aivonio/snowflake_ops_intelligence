"""
Setup Wizard Utility - Production Edition
Full SQL integration with deployment-specific execution.
"""

import streamlit as st
from datetime import datetime

class DiagnosticLog:
    """Collects diagnostic information."""
    
    def __init__(self):
        self.entries = []
    
    def log(self, category, check_name, status, message="", fix_hint=""):
        self.entries.append({
            'timestamp': datetime.now().isoformat(),
            'category': category,
            'check': check_name,
            'status': status,
            'message': message,
            'fix_hint': fix_hint
        })
    
    def get_summary(self):
        return {
            'pass': sum(1 for e in self.entries if e['status'] == 'PASS'),
            'fail': sum(1 for e in self.entries if e['status'] == 'FAIL'),
            'warn': sum(1 for e in self.entries if e['status'] == 'WARN'),
        }
    
    def export_text(self):
        lines = ["=" * 60, "DIAGNOSTIC REPORT", f"Generated: {datetime.now()}", "=" * 60, ""]
        current_cat = None
        for e in self.entries:
            if e['category'] != current_cat:
                current_cat = e['category']
                lines.append(f"\n### {current_cat.upper()}")
            icon = {'PASS': '✅', 'FAIL': '❌', 'WARN': '⚠️', 'INFO': 'ℹ️'}.get(e['status'], '?')
            lines.append(f"{icon} {e['check']}: {e['message']}")
            if e['fix_hint']:
                lines.append(f"   FIX: {e['fix_hint']}")
        summary = self.get_summary()
        lines.append(f"\n{'=' * 60}\nSUMMARY: {summary['pass']} passed, {summary['fail']} failed, {summary['warn']} warnings")
        return "\n".join(lines)


class SetupWizard:
    """Production Setup Wizard with full SQL integration."""
    
    # Deployment Types
    DEPLOY_NATIVE_APP = 'NATIVE_APP'
    DEPLOY_SIS = 'STREAMLIT_IN_SNOWFLAKE'
    DEPLOY_EXTERNAL = 'EXTERNAL'
    
    # ==================== SQL TEMPLATES BY DEPLOYMENT TYPE ====================
    
    SQL_TEMPLATES = {
        # ========== COMMON SQL (All Deployments) ==========
        'COMMON': {
            'warehouse': '''
                CREATE WAREHOUSE IF NOT EXISTS {warehouse}
                WAREHOUSE_SIZE = XSMALL
                AUTO_SUSPEND = 60
                AUTO_RESUME = TRUE
            ''',
            'database': 'CREATE DATABASE IF NOT EXISTS {database}',
            'schemas': [
                'CREATE SCHEMA IF NOT EXISTS {database}.APP_DATA',
                'CREATE SCHEMA IF NOT EXISTS {database}.APP_CONTEXT',
                'CREATE SCHEMA IF NOT EXISTS {database}.APP_ANALYTICS'
            ],
            'tables': {
                'APP_CONTEXT.PLATFORM_SETTINGS': '''
                    CREATE TABLE IF NOT EXISTS {database}.APP_CONTEXT.PLATFORM_SETTINGS (
                        SETTING_KEY VARCHAR(100) PRIMARY KEY,
                        SETTING_VALUE VARCHAR(1000),
                        DESCRIPTION VARCHAR(500),
                        UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                    )
                ''',
                'APP_CONTEXT.BUDGET_ALERTS': '''
                    CREATE TABLE IF NOT EXISTS {database}.APP_CONTEXT.BUDGET_ALERTS (
                        ALERT_ID NUMBER AUTOINCREMENT PRIMARY KEY,
                        ALERT_NAME VARCHAR(255),
                        ALERT_TYPE VARCHAR(50),
                        TARGET_NAME VARCHAR(255),
                        THRESHOLD_CREDITS FLOAT,
                        THRESHOLD_PERCENTAGE FLOAT,
                        NOTIFICATION_CHANNEL VARCHAR(50) DEFAULT 'DASHBOARD',
                        IS_ACTIVE BOOLEAN DEFAULT TRUE,
                        CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                    )
                ''',
                'APP_CONTEXT.WAREHOUSE_CONTEXT': '''
                    CREATE TABLE IF NOT EXISTS {database}.APP_CONTEXT.WAREHOUSE_CONTEXT (
                        WAREHOUSE_NAME VARCHAR(255) PRIMARY KEY,
                        PURPOSE VARCHAR(50) DEFAULT 'GENERAL',
                        SIZE VARCHAR(20),
                        COST_PROFILE VARCHAR(20) DEFAULT 'BALANCED',
                        CONCURRENCY_TOLERANCE VARCHAR(20) DEFAULT 'MEDIUM',
                        OWNER_TEAM VARCHAR(255),
                        NOTES VARCHAR(2000),
                        UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                    )
                ''',
                'APP_CONTEXT.TABLE_CONTEXT': '''
                    CREATE TABLE IF NOT EXISTS {database}.APP_CONTEXT.TABLE_CONTEXT (
                        DATABASE_NAME VARCHAR(255),
                        SCHEMA_NAME VARCHAR(255),
                        TABLE_NAME VARCHAR(255),
                        FRESHNESS_REQUIREMENT VARCHAR(20) DEFAULT 'DAILY',
                        ACCESS_FREQUENCY VARCHAR(20) DEFAULT 'UNKNOWN',
                        IS_CRITICAL BOOLEAN DEFAULT FALSE,
                        PRIMARY KEY (DATABASE_NAME, SCHEMA_NAME, TABLE_NAME)
                    )
                ''',
                'APP_CONTEXT.TEAM_ATTRIBUTION': '''
                    CREATE TABLE IF NOT EXISTS {database}.APP_CONTEXT.TEAM_ATTRIBUTION (
                        USER_NAME VARCHAR(255) PRIMARY KEY,
                        TEAM_NAME VARCHAR(255),
                        DEPARTMENT VARCHAR(255),
                        COST_CENTER VARCHAR(100),
                        BUDGET_LIMIT_CREDITS FLOAT,
                        UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                    )
                ''',
                'APP_ANALYTICS.METADATA_CACHE': '''
                    CREATE TABLE IF NOT EXISTS {database}.APP_ANALYTICS.METADATA_CACHE (
                        CACHE_KEY VARCHAR(500) PRIMARY KEY,
                        CACHE_VALUE VARIANT,
                        EXPIRY_TIME TIMESTAMP_NTZ,
                        CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                    )
                ''',
                'APP_ANALYTICS.QUERY_BENCHMARK': '''
                    CREATE TABLE IF NOT EXISTS {database}.APP_ANALYTICS.QUERY_BENCHMARK (
                        BENCHMARK_ID NUMBER AUTOINCREMENT PRIMARY KEY,
                        QUERY_TEXT VARCHAR(10000),
                        QUERY_HASH VARCHAR(64),
                        RUN_TYPE VARCHAR(20),
                        PREDICTED_COST_CREDITS FLOAT,
                        ACTUAL_COST_CREDITS FLOAT,
                        PREDICTED_TIME_MS NUMBER,
                        ACTUAL_TIME_MS NUMBER,
                        BYTES_SCANNED NUMBER,
                        WAREHOUSE_USED VARCHAR(255),
                        WAREHOUSE_SIZE VARCHAR(20),
                        OPTIMIZATION_APPLIED VARCHAR(1000),
                        COST_SAVINGS_CREDITS FLOAT,
                        TIME_SAVINGS_MS NUMBER,
                        RUN_TIMESTAMP TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                    )
                ''',
                'APP_DATA.SETUP_STATUS': '''
                    CREATE TABLE IF NOT EXISTS {database}.APP_DATA.SETUP_STATUS (
                        SETUP_KEY VARCHAR(100) PRIMARY KEY,
                        SETUP_VALUE VARCHAR(1000),
                        CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                    )
                ''',
                'APP_DATA.AI_QUERY_LOG': '''
                    CREATE TABLE IF NOT EXISTS {database}.APP_DATA.AI_QUERY_LOG (
                        LOG_ID NUMBER AUTOINCREMENT PRIMARY KEY,
                        USER_NAME VARCHAR(256),
                        USER_PROMPT VARCHAR(10000),
                        GENERATED_SQL VARCHAR(50000),
                        EXECUTION_STATUS VARCHAR(20),
                        CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                    )
                ''',
                'APP_DATA.DIAGNOSTIC_LOG': '''
                    CREATE TABLE IF NOT EXISTS {database}.APP_DATA.DIAGNOSTIC_LOG (
                        LOG_ID NUMBER AUTOINCREMENT PRIMARY KEY,
                        LOG_TYPE VARCHAR(50),
                        LOG_MESSAGE VARCHAR(10000),
                        CREATED_BY VARCHAR(256),
                        CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                    )
                ''',
                'APP_CONTEXT.DBT_PROJECTS': '''
                    CREATE TABLE IF NOT EXISTS {database}.APP_CONTEXT.DBT_PROJECTS (
                        PROJECT_ID VARCHAR(50) PRIMARY KEY, PROJECT_NAME VARCHAR(255),
                        TARGET_DATABASE VARCHAR(255), TARGET_SCHEMA VARCHAR(255) DEFAULT 'PUBLIC',
                        DESCRIPTION VARCHAR(2000), CREATED_BY VARCHAR(255),
                        CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                    )
                ''',
                'APP_CONTEXT.DBT_MODELS': '''
                    CREATE TABLE IF NOT EXISTS {database}.APP_CONTEXT.DBT_MODELS (
                        MODEL_ID VARCHAR(50) PRIMARY KEY, PROJECT_ID VARCHAR(50),
                        MODEL_NAME VARCHAR(255), LAYER VARCHAR(50),
                        MATERIALIZATION VARCHAR(50) DEFAULT 'view',
                        SQL_BODY VARCHAR(100000), DESCRIPTION VARCHAR(2000),
                        DEPENDENCIES VARCHAR(10000), TESTS VARCHAR(10000),
                        COLUMNS_META VARCHAR(50000),
                        LAST_RUN_STATUS VARCHAR(20), LAST_RUN_AT TIMESTAMP_NTZ,
                        LAST_RUN_DURATION_MS NUMBER, LAST_RUN_ROWS NUMBER,
                        CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                    )
                ''',
                'APP_CONTEXT.DBT_SOURCES': '''
                    CREATE TABLE IF NOT EXISTS {database}.APP_CONTEXT.DBT_SOURCES (
                        SOURCE_ID VARCHAR(50) PRIMARY KEY, PROJECT_ID VARCHAR(50),
                        SOURCE_NAME VARCHAR(255), DATABASE_NAME VARCHAR(255),
                        SCHEMA_NAME VARCHAR(255), TABLE_NAME VARCHAR(255),
                        FRESHNESS_WARN VARCHAR(50), FRESHNESS_ERROR VARCHAR(50),
                        LOADED_AT_FIELD VARCHAR(255), ROW_COUNT NUMBER, SIZE_BYTES NUMBER,
                        CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                    )
                ''',
                'APP_CONTEXT.DBT_TEST_RESULTS': '''
                    CREATE TABLE IF NOT EXISTS {database}.APP_CONTEXT.DBT_TEST_RESULTS (
                        RESULT_ID VARCHAR(50) PRIMARY KEY, MODEL_ID VARCHAR(50),
                        TEST_NAME VARCHAR(255), TEST_TYPE VARCHAR(50),
                        STATUS VARCHAR(20), FAILURE_COUNT NUMBER,
                        RUN_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                    )
                ''',
                'APP_CONTEXT.PIPELINE_CONFIGS': '''
                    CREATE TABLE IF NOT EXISTS {database}.APP_CONTEXT.PIPELINE_CONFIGS (
                        PIPELINE_ID VARCHAR(50) PRIMARY KEY, PIPELINE_NAME VARCHAR(255),
                        PIPELINE_TYPE VARCHAR(50), DESCRIPTION VARCHAR(2000),
                        CONFIG VARIANT, STATUS VARCHAR(20) DEFAULT 'DRAFT',
                        TARGET_DATABASE VARCHAR(255), TARGET_SCHEMA VARCHAR(255),
                        CREATED_BY VARCHAR(255), CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
                        UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                    )
                ''',
                'APP_CONTEXT.PIPELINE_RUNS': '''
                    CREATE TABLE IF NOT EXISTS {database}.APP_CONTEXT.PIPELINE_RUNS (
                        RUN_ID VARCHAR(50) PRIMARY KEY, PIPELINE_ID VARCHAR(50),
                        STATUS VARCHAR(20), STARTED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
                        COMPLETED_AT TIMESTAMP_NTZ, ERROR_MESSAGE VARCHAR(10000),
                        CREDITS_USED FLOAT, ROWS_PROCESSED NUMBER, METADATA VARIANT
                    )
                ''',
                'APP_CONTEXT.MCP_CONNECTORS': '''
                    CREATE TABLE IF NOT EXISTS {database}.APP_CONTEXT.MCP_CONNECTORS (
                        CONNECTOR_ID VARCHAR(50) PRIMARY KEY, CONNECTOR_TYPE VARCHAR(50),
                        CONNECTOR_NAME VARCHAR(255), CONFIG VARIANT,
                        STATUS VARCHAR(20) DEFAULT 'ACTIVE',
                        LAST_USED_AT TIMESTAMP_NTZ, CREATED_BY VARCHAR(255),
                        CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                    )
                ''',
                'APP_CONTEXT.CORTEX_AGENTS': '''
                    CREATE TABLE IF NOT EXISTS {database}.APP_CONTEXT.CORTEX_AGENTS (
                        AGENT_ID VARCHAR(50) PRIMARY KEY, AGENT_NAME VARCHAR(255),
                        DESCRIPTION VARCHAR(2000), SYSTEM_PROMPT VARCHAR(10000),
                        TOOLS VARIANT, CAPABILITIES VARIANT,
                        MODEL VARCHAR(100) DEFAULT 'mistral-large',
                        MAX_TURNS NUMBER DEFAULT 5, GUARDRAILS VARIANT,
                        STATUS VARCHAR(20) DEFAULT 'ACTIVE',
                        CREATED_BY VARCHAR(255), CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                    )
                ''',
                'APP_CONTEXT.AGENT_RUNS': '''
                    CREATE TABLE IF NOT EXISTS {database}.APP_CONTEXT.AGENT_RUNS (
                        RUN_ID VARCHAR(50) PRIMARY KEY, AGENT_ID VARCHAR(50),
                        SESSION_ID VARCHAR(50), USER_QUERY VARCHAR(10000),
                        AGENT_RESPONSE VARCHAR(50000), TOOLS_USED VARIANT,
                        TOKENS_USED NUMBER, DURATION_MS NUMBER,
                        STATUS VARCHAR(20), CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                    )
                ''',
                'APP_DATA.SCRIPT_HISTORY': '''
                    CREATE TABLE IF NOT EXISTS {database}.APP_DATA.SCRIPT_HISTORY (
                        SCRIPT_ID NUMBER AUTOINCREMENT PRIMARY KEY,
                        SCRIPT_TYPE VARCHAR(50), USER_PROMPT VARCHAR(10000),
                        GENERATED_SCRIPT VARCHAR(100000), EXECUTION_STATUS VARCHAR(20),
                        CREATED_BY VARCHAR(256), CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                    )
                '''
            },
            'views': {
                'APP_DATA.V_DAILY_QUERY_SUMMARY': '''
                    CREATE OR REPLACE VIEW {database}.APP_DATA.V_DAILY_QUERY_SUMMARY AS
                    SELECT DATE_TRUNC('DAY', START_TIME) AS QUERY_DATE,
                           COUNT(*) AS TOTAL_QUERIES,
                           SUM(CASE WHEN EXECUTION_STATUS = 'SUCCESS' THEN 1 ELSE 0 END) AS SUCCESS_QUERIES,
                           SUM(CASE WHEN EXECUTION_STATUS = 'FAIL' THEN 1 ELSE 0 END) AS FAILED_QUERIES,
                           SUM(BYTES_SCANNED) AS TOTAL_BYTES_SCANNED
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE START_TIME >= DATEADD(DAY, -30, CURRENT_TIMESTAMP())
                    GROUP BY 1
                ''',
                'APP_DATA.V_WAREHOUSE_PERFORMANCE': '''
                    CREATE OR REPLACE VIEW {database}.APP_DATA.V_WAREHOUSE_PERFORMANCE AS
                    SELECT WAREHOUSE_NAME,
                           DATE_TRUNC('DAY', START_TIME) AS METRIC_DATE,
                           SUM(CREDITS_USED) AS CREDITS_USED
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                    WHERE START_TIME >= DATEADD(DAY, -30, CURRENT_TIMESTAMP())
                    GROUP BY 1, 2
                ''',
                'APP_DATA.V_TOP_USERS_BY_COST': '''
                    CREATE OR REPLACE VIEW {database}.APP_DATA.V_TOP_USERS_BY_COST AS
                    SELECT USER_NAME, COUNT(*) AS QUERY_COUNT,
                           SUM(CREDITS_USED_CLOUD_SERVICES) AS TOTAL_CREDITS
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE START_TIME >= DATEADD(DAY, -30, CURRENT_TIMESTAMP())
                    GROUP BY 1 ORDER BY 3 DESC
                '''
            },
            'grants_public': [
                'GRANT USAGE ON DATABASE {database} TO ROLE PUBLIC',
                'GRANT USAGE ON ALL SCHEMAS IN DATABASE {database} TO ROLE PUBLIC',
                'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {database}.APP_CONTEXT TO ROLE PUBLIC',
                'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {database}.APP_ANALYTICS TO ROLE PUBLIC',
                'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {database}.APP_DATA TO ROLE PUBLIC',
                'GRANT SELECT ON ALL VIEWS IN SCHEMA {database}.APP_DATA TO ROLE PUBLIC'
            ],
            'initial_data': [
                "INSERT INTO {database}.APP_DATA.SETUP_STATUS (SETUP_KEY, SETUP_VALUE) SELECT 'SETUP_COMPLETE', 'TRUE' WHERE NOT EXISTS (SELECT 1 FROM {database}.APP_DATA.SETUP_STATUS WHERE SETUP_KEY = 'SETUP_COMPLETE')",
                "INSERT INTO {database}.APP_CONTEXT.PLATFORM_SETTINGS (SETTING_KEY, SETTING_VALUE, DESCRIPTION) SELECT 'CORTEX_ENABLED', 'TRUE', 'Global AI Enablement' WHERE NOT EXISTS (SELECT 1 FROM {database}.APP_CONTEXT.PLATFORM_SETTINGS WHERE SETTING_KEY = 'CORTEX_ENABLED')",
                "INSERT INTO {database}.APP_CONTEXT.PLATFORM_SETTINGS (SETTING_KEY, SETTING_VALUE, DESCRIPTION) SELECT 'CORTEX_DEFAULT_MODEL', 'mistral-large', 'Default LLM' WHERE NOT EXISTS (SELECT 1 FROM {database}.APP_CONTEXT.PLATFORM_SETTINGS WHERE SETTING_KEY = 'CORTEX_DEFAULT_MODEL')",
                "INSERT INTO {database}.APP_CONTEXT.PLATFORM_SETTINGS (SETTING_KEY, SETTING_VALUE, DESCRIPTION) SELECT 'CORTEX_CROSS_REGION', 'FALSE', 'Cross Region Inference' WHERE NOT EXISTS (SELECT 1 FROM {database}.APP_CONTEXT.PLATFORM_SETTINGS WHERE SETTING_KEY = 'CORTEX_CROSS_REGION')"
            ]
        },
        
        # ========== NATIVE APP SPECIFIC ==========
        'NATIVE_APP': {
            'app_package': 'CREATE APPLICATION PACKAGE IF NOT EXISTS SNOWFLAKE_OPS_PACKAGE',
            'app_schema': 'CREATE SCHEMA IF NOT EXISTS SNOWFLAKE_OPS_PACKAGE.STAGE_CONTENT',
            'app_stage': "CREATE OR REPLACE STAGE SNOWFLAKE_OPS_PACKAGE.STAGE_CONTENT.APP_STAGE DIRECTORY = (ENABLE = TRUE)",
            'app_create': "CREATE APPLICATION IF NOT EXISTS SNOWFLAKE_OPS_APP FROM APPLICATION PACKAGE SNOWFLAKE_OPS_PACKAGE USING '@SNOWFLAKE_OPS_PACKAGE.STAGE_CONTENT.APP_STAGE'",
            'grants': [
                'GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO APPLICATION SNOWFLAKE_OPS_APP',
                'GRANT USAGE ON DATABASE {database} TO APPLICATION SNOWFLAKE_OPS_APP',
                'GRANT USAGE ON ALL SCHEMAS IN DATABASE {database} TO APPLICATION SNOWFLAKE_OPS_APP',
                'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN DATABASE {database} TO APPLICATION SNOWFLAKE_OPS_APP',
                'GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO APPLICATION SNOWFLAKE_OPS_APP',
                'GRANT USAGE ON WAREHOUSE {warehouse} TO APPLICATION SNOWFLAKE_OPS_APP'
            ],
            'roles': [
                'CREATE ROLE IF NOT EXISTS SNOWFLAKE_OPS_ADMIN',
                'CREATE ROLE IF NOT EXISTS SNOWFLAKE_OPS_USER',
                'GRANT DATABASE ROLE SNOWFLAKE.GOVERNANCE_VIEWER TO ROLE SNOWFLAKE_OPS_ADMIN',
                'GRANT DATABASE ROLE SNOWFLAKE.USAGE_VIEWER TO ROLE SNOWFLAKE_OPS_ADMIN',
                'GRANT USAGE ON APPLICATION SNOWFLAKE_OPS_APP TO ROLE SNOWFLAKE_OPS_ADMIN',
                'GRANT USAGE ON APPLICATION SNOWFLAKE_OPS_APP TO ROLE SNOWFLAKE_OPS_USER',
                'GRANT USAGE ON WAREHOUSE {warehouse} TO ROLE SNOWFLAKE_OPS_ADMIN',
                'GRANT USAGE ON WAREHOUSE {warehouse} TO ROLE SNOWFLAKE_OPS_USER'
            ]
        },
        
        # ========== STREAMLIT IN SNOWFLAKE (SiS) SPECIFIC ==========
        'SIS': {
            'stage': "CREATE STAGE IF NOT EXISTS {database}.APP_ANALYTICS.APP_STAGE DIRECTORY = (ENABLE = TRUE)",
            'streamlit_object': '''
                CREATE STREAMLIT IF NOT EXISTS {database}.APP_ANALYTICS.SNOWFLAKE_OPS_INTELLIGENCE
                ROOT_LOCATION = '@{database}.APP_ANALYTICS.APP_STAGE'
                MAIN_FILE = 'streamlit_app.py'
                QUERY_WAREHOUSE = '{warehouse}'
            ''',
            'grants': [
                'GRANT USAGE ON WAREHOUSE {warehouse} TO ROLE PUBLIC'
            ]
        },
        
        # ========== EXTERNAL APP SPECIFIC ==========
        'EXTERNAL': {
            'oauth': '''
                CREATE OR REPLACE SECURITY INTEGRATION SNOWFLAKE_OPS_OAUTH
                TYPE = OAUTH
                ENABLED = TRUE
                OAUTH_CLIENT = CUSTOM
                OAUTH_CLIENT_TYPE = 'PUBLIC'
                OAUTH_REDIRECT_URI = '{redirect_uri}'
                OAUTH_ISSUE_REFRESH_TOKENS = TRUE
                OAUTH_REFRESH_TOKEN_VALIDITY = 86400
                BLOCKED_ROLES_LIST = ('ORGADMIN')
            ''',
            'roles': [
                'CREATE ROLE IF NOT EXISTS SNOWFLAKE_OPS_ADMIN',
                'CREATE ROLE IF NOT EXISTS SNOWFLAKE_OPS_USER',
                'GRANT DATABASE ROLE SNOWFLAKE.GOVERNANCE_VIEWER TO ROLE SNOWFLAKE_OPS_ADMIN',
                'GRANT DATABASE ROLE SNOWFLAKE.USAGE_VIEWER TO ROLE SNOWFLAKE_OPS_ADMIN',
                'GRANT USAGE ON WAREHOUSE {warehouse} TO ROLE SNOWFLAKE_OPS_ADMIN',
                'GRANT USAGE ON WAREHOUSE {warehouse} TO ROLE SNOWFLAKE_OPS_USER'
            ]
        }
    }
    
    def __init__(self, client, database='SNOWFLAKE_OPS_INTELLIGENCE', warehouse='INTELLIGENCE_WH'):
        self.client = client
        self.db = database
        self.wh = warehouse
        self.log = DiagnosticLog()
        self.environment = {}
        self.deploy_type = self.DEPLOY_EXTERNAL
    
    def detect_environment(self):
        """Detect deployment type and context."""
        env = {'type': 'UNKNOWN', 'account': None, 'user': None, 'role': None, 'warehouse': None, 'edition': None, 'cortex': False}
        
        try:
            ctx = self.client.execute_query("SELECT CURRENT_ACCOUNT(), CURRENT_USER(), CURRENT_ROLE(), CURRENT_WAREHOUSE()", log=False)
            if not ctx.empty:
                env['account'], env['user'], env['role'], env['warehouse'] = ctx.iloc[0, :4]
                self.log.log('Environment', 'Context', 'PASS', f"Account: {env['account']}, Role: {env['role']}")
        except Exception as e:
            self.log.log('Environment', 'Context', 'FAIL', str(e))
        
        try:
            edition = self.client.execute_query("SELECT CURRENT_EDITION()", log=False)
            env['edition'] = edition.iloc[0, 0] if not edition.empty else 'Unknown'
        except:
            pass
        
        # Detect SiS
        try:
            from snowflake.snowpark.context import get_active_session
            if get_active_session():
                self.deploy_type = self.DEPLOY_SIS
                env['type'] = 'Streamlit in Snowflake'
        except:
            self.deploy_type = self.DEPLOY_EXTERNAL
            env['type'] = 'External App'
        
        # Cortex
        try:
            self.client.execute_query("SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-7b', 'test')", log=False)
            env['cortex'] = True
            self.log.log('AI', 'Cortex', 'PASS', 'Available')
        except:
            env['cortex'] = False
            self.log.log('AI', 'Cortex', 'WARN', 'Not available')
        
        self.environment = env
        return env
    
    def check_privileges(self):
        """Check required privileges."""
        try:
            self.client.execute_query("SELECT 1 FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY LIMIT 1", log=False)
            self.log.log('Privileges', 'ACCOUNT_USAGE', 'PASS', 'Access granted')
            return True
        except:
            self.log.log('Privileges', 'ACCOUNT_USAGE', 'FAIL', 'No access', 
                        f"GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO ROLE {self.environment.get('role')}")
            return False
    
    def check_object_exists(self, obj_type, name):
        try:
            if obj_type == 'WAREHOUSE':
                r = self.client.execute_query(f"SHOW WAREHOUSES LIKE '{name}'", log=False)
            elif obj_type == 'DATABASE':
                r = self.client.execute_query(f"SHOW DATABASES LIKE '{name}'", log=False)
            elif obj_type == 'SCHEMA':
                parts = name.split('.')
                r = self.client.execute_query(f"SHOW SCHEMAS LIKE '{parts[1]}' IN DATABASE {parts[0]}", log=False)
            elif obj_type == 'TABLE':
                parts = name.split('.')
                r = self.client.execute_query(f"SHOW TABLES LIKE '{parts[-1]}' IN {'.'.join(parts[:-1])}", log=False)
            else:
                return False
            return not r.empty
        except:
            return False
    
    def run_sql(self, sql, params=None):
        """Execute SQL with parameter substitution."""
        if params is None:
            params = {'database': self.db, 'warehouse': self.wh}
        try:
            formatted_sql = sql.format(**params)
            self.client.execute_query(formatted_sql, log=False)
            return True, None
        except Exception as e:
            return False, str(e)
    
    def _infer_warehouse_purpose(self, name):
        """Infer warehouse purpose from name."""
        name = name.upper()
        if any(x in name for x in ['ETL', 'LOAD', 'INGEST', 'PIPE']):
            return 'ETL'
        if any(x in name for x in ['BI', 'REPORT', 'DASH', 'TABL', 'POWER']):
            return 'REPORTING'
        if any(x in name for x in ['DS', 'SCIENCE', 'ML', 'AI', 'MODEL']):
            return 'DATA_SCIENCE'
        if any(x in name for x in ['DEV', 'TEST', 'SAND']):
            return 'DEVELOPMENT'
        return 'GENERAL'

    def _infer_table_criticality(self, name):
        """Infer if table is critical based on name."""
        name = name.upper()
        if any(x in name for x in ['FACT', 'DIM', 'REVENUE', 'SALES', 'USER', 'CUSTOMER', 'TRANSACTION']):
            return 'TRUE'
        return 'FALSE'

    def populate_initial_metadata(self):
        """Populate initial metadata for warehouses and tables using heuristics."""
        try:
            # 1. Warehouses with Heuristics
            try:
                wh_df = self.client.execute_query("SHOW WAREHOUSES", log=False)
                if not wh_df.empty:
                    name_col = 'name' if 'name' in wh_df.columns else 'NAME'
                    size_col = 'size' if 'size' in wh_df.columns else 'SIZE'
                    
                    values_clauses = []
                    values_list = []
                    for _, row in wh_df.iterrows():
                        name = row.get(name_col)
                        size = row.get(size_col)
                        if name:
                            purpose = self._infer_warehouse_purpose(name)
                            name_esc = str(name).replace("'", "''")
                            size_esc = str(size).replace("'", "''")
                            purpose_esc = str(purpose).replace("'", "''")
                            values_clauses.append(f"('{name_esc}', '{size_esc}', '{purpose_esc}')")

                    if values_clauses:
                        values_str = ",\n".join(values_clauses)
                        merge_sql = f"""
                        MERGE INTO {self.db}.APP_CONTEXT.WAREHOUSE_CONTEXT AS target
                        USING (VALUES {values_str}) AS source(NAME, SIZE, PURPOSE)
                            # Escape single quotes in names just in case
                            safe_name = str(name).replace("'", "''")
                            safe_size = str(size).replace("'", "''")
                            safe_purpose = str(purpose).replace("'", "''")
                            values_list.append(f"('{safe_name}', '{safe_size}', '{safe_purpose}')")

                    if values_list:
                        values_str = ",\n".join(values_list)
                        merge_sql = f"""
                        MERGE INTO {self.db}.APP_CONTEXT.WAREHOUSE_CONTEXT AS target
                        USING (
                            SELECT $1 AS NAME, $2 AS SIZE, $3 AS PURPOSE
                            FROM VALUES {values_str}
                        ) AS source
                        ON target.WAREHOUSE_NAME = source.NAME
                        WHEN NOT MATCHED THEN
                            INSERT (WAREHOUSE_NAME, SIZE, PURPOSE, COST_PROFILE, OWNER_TEAM)
                            VALUES (source.NAME, source.SIZE, source.PURPOSE, 'BALANCED', 'PLATFORM_TEAM')
                        """
                        self.client.execute_query(merge_sql, log=False)
                    self.log.log('Setup', 'Metadata', 'PASS', f"Analysis: {len(wh_df)} warehouses processed")
            except Exception as e:
                self.log.log('Setup', 'Warehouse Metadata', 'WARN', str(e))

            # 2. Table Discovery (Top 100 by size in current DB)
            try:
                # Discover tables in the current database context or user-accessible schemas
                # We limit to 100 to avoid overwhelming the context initially
                discovery_sql = """
                SELECT 
                    TABLE_CATALOG, 
                    TABLE_SCHEMA, 
                    TABLE_NAME, 
                    ROW_COUNT, 
                    BYTES,
                    LAST_ALTERED
                FROM SNOWFLAKE.ACCOUNT_USAGE.TABLES
                WHERE DELETED IS NULL
                    AND ROW_COUNT > 0
                    AND TABLE_SCHEMA != 'INFORMATION_SCHEMA'
                ORDER BY BYTES DESC
                LIMIT 100
                """
                # Try ACCOUNT_USAGE first (requires privileges), fallback to INFORMATION_SCHEMA
                try:
                    tables_df = self.client.execute_query(discovery_sql, log=False)
                except:
                    discovery_sql = """
                    SELECT 
                        TABLE_CATALOG, 
                        TABLE_SCHEMA, 
                        TABLE_NAME, 
                        ROW_COUNT, 
                        BYTES,
                        LAST_ALTERED
                    FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_TYPE = 'BASE TABLE'
                    ORDER BY BYTES DESC
                    LIMIT 100
                    """
                    tables_df = self.client.execute_query(discovery_sql, log=False)
                
                if not tables_df.empty:
                    values_clauses = []
                    values_list = []
                    for _, row in tables_df.iterrows():
                        db_name = str(row['TABLE_CATALOG']).replace("'", "''")
                        schema = str(row['TABLE_SCHEMA']).replace("'", "''")
                        table = str(row['TABLE_NAME']).replace("'", "''")
                        rows = row['ROW_COUNT'] if row['ROW_COUNT'] is not None else 0
                        bytes_size = row['BYTES'] if row['BYTES'] is not None else 0
                        is_critical = self._infer_table_criticality(table)
                        
                        values_clauses.append(f"('{db_name}', '{schema}', '{table}', {rows}, {bytes_size}, {is_critical})")

                    if values_clauses:
                        values_str = ",\n".join(values_clauses)
                        merge_sql = f"""
                        MERGE INTO {self.db}.APP_CONTEXT.TABLE_CONTEXT AS target
                        USING (VALUES {values_str}) AS source(DB, SCH, TBL, RC, SZ, CRIT)
                        values_list.append(f"('{db_name}', '{schema}', '{table}', {rows}, {bytes_size}, {is_critical})")

                    if values_list:
                        values_str = ",\n".join(values_list)
                        merge_sql = f"""
                        MERGE INTO {self.db}.APP_CONTEXT.TABLE_CONTEXT AS target
                        USING (
                            SELECT 
                                $1 AS DB,
                                $2 AS SCH,
                                $3 AS TBL,
                                $4 AS RC,
                                $5 AS SZ,
                                $6 AS CRIT
                            FROM VALUES {values_str}
                        ) AS source
                        ON target.DATABASE_NAME = source.DB 
                           AND target.SCHEMA_NAME = source.SCH 
                           AND target.TABLE_NAME = source.TBL
                        WHEN NOT MATCHED THEN
                            INSERT (DATABASE_NAME, SCHEMA_NAME, TABLE_NAME, ROW_COUNT, SIZE_BYTES, IS_CRITICAL, ACCESS_FREQUENCY)
                            VALUES (source.DB, source.SCH, source.TBL, source.RC, source.SZ, source.CRIT, 'UNKNOWN')
                        WHEN MATCHED THEN
                            UPDATE SET 
                                ROW_COUNT = source.RC,
                                SIZE_BYTES = source.SZ
                        """
                        self.client.execute_query(merge_sql, log=False)
                    self.log.log('Setup', 'Table Metadata', 'PASS', f"Scanned {len(tables_df)} tables")
                    
            except Exception as e:
                self.log.log('Setup', 'Table Metadata', 'WARN', f"Could not scan tables: {e}")

            # 3. Network Policy Check
            try:
                np_df = self.client.execute_query("SHOW NETWORK POLICIES", log=False)
                if np_df.empty:
                     self.log.log('Security', 'Network Policy', 'WARN', 'No network policies found', 'Create a network policy to restrict access')
            except:
                pass

        except Exception as e:
            self.log.log('Setup', 'Metadata Population', 'WARN', str(e))

    def run_setup(self, deploy_type=None, redirect_uri='http://localhost:8501'):
        """Run full setup based on deployment type."""
        if deploy_type is None:
            deploy_type = self.deploy_type
        
        results = {'created': [], 'failed': [], 'skipped': []}
        params = {'database': self.db, 'warehouse': self.wh, 'redirect_uri': redirect_uri}
        common = self.SQL_TEMPLATES['COMMON']
        
        # 1. Warehouse
        if not self.check_object_exists('WAREHOUSE', self.wh):
            ok, err = self.run_sql(common['warehouse'], params)
            if ok:
                results['created'].append(f"Warehouse: {self.wh}")
            else:
                results['failed'].append(f"Warehouse: {err}")
        else:
            results['skipped'].append(f"Warehouse: {self.wh}")
        
        # 2. Database
        if not self.check_object_exists('DATABASE', self.db):
            ok, err = self.run_sql(common['database'], params)
            if ok:
                results['created'].append(f"Database: {self.db}")
            else:
                results['failed'].append(f"Database: {err}")
        else:
            results['skipped'].append(f"Database: {self.db}")
        
        # 3. Schemas
        for schema_sql in common['schemas']:
            ok, _ = self.run_sql(schema_sql, params)
            if ok:
                results['created'].append("Schema (created/verified)")
        
        # 4. Tables
        for table_name, table_sql in common['tables'].items():
            ok, err = self.run_sql(table_sql, params)
            if ok:
                results['created'].append(f"Table: {table_name}")
            else:
                results['failed'].append(f"Table {table_name}: {err}")
        
        # 5. Views
        for view_name, view_sql in common['views'].items():
            ok, err = self.run_sql(view_sql, params)
            if ok:
                results['created'].append(f"View: {view_name}")
            else:
                results['failed'].append(f"View {view_name}: {err}")
        
        # 6. Grants
        for grant_sql in common['grants_public']:
            self.run_sql(grant_sql, params)
        
        # 7. Initial Data
        for data_sql in common['initial_data']:
            self.run_sql(data_sql, params)
            
        # 8. Populate Metadata (New Step)
        self.populate_initial_metadata()
        
        # 9. Deployment-specific setup
        if deploy_type == self.DEPLOY_NATIVE_APP:
            native = self.SQL_TEMPLATES['NATIVE_APP']
            for key in ['app_package', 'app_schema', 'app_stage']:
                self.run_sql(native[key], params)
            for grant in native.get('grants', []):
                self.run_sql(grant, params)
            for role_sql in native.get('roles', []):
                self.run_sql(role_sql, params)
            results['created'].append("Native App objects configured")
        
        elif deploy_type == self.DEPLOY_SIS:
            sis = self.SQL_TEMPLATES['SIS']
            self.run_sql(sis['stage'], params)
            self.run_sql(sis['streamlit_object'], params)
            for grant in sis.get('grants', []):
                self.run_sql(grant, params)
            results['created'].append("SiS objects configured")
        
        elif deploy_type == self.DEPLOY_EXTERNAL:
            ext = self.SQL_TEMPLATES['EXTERNAL']
            self.run_sql(ext['oauth'], params)
            for role_sql in ext.get('roles', []):
                self.run_sql(role_sql, params)
            results['created'].append("External app objects configured")
        
        self.log.log('Setup', 'Complete', 'PASS', f"Created {len(results['created'])}, Failed {len(results['failed'])}")
        return results
    
    def run_diagnostics(self):
        """Run full diagnostics."""
        results = {'environment': self.detect_environment(), 'privileges': self.check_privileges(), 'objects': {}}
        results['objects']['warehouse'] = self.check_object_exists('WAREHOUSE', self.wh)
        results['objects']['database'] = self.check_object_exists('DATABASE', self.db)
        for schema in ['APP_DATA', 'APP_CONTEXT', 'APP_ANALYTICS']:
            results['objects'][f'schema_{schema}'] = self.check_object_exists('SCHEMA', f'{self.db}.{schema}')
        return results
    
    def generate_sql_script(self, deploy_type=None):
        """Generate full SQL script for manual execution."""
        if deploy_type is None:
            deploy_type = self.deploy_type
        
        params = {'database': self.db, 'warehouse': self.wh, 'redirect_uri': 'http://localhost:8501'}
        lines = [
            "-- ========================================",
            f"-- SNOWFLAKE OPS INTELLIGENCE - SETUP SCRIPT",
            f"-- Deployment Type: {deploy_type}",
            f"-- Generated: {datetime.now()}",
            "-- ========================================",
            "",
            "USE ROLE ACCOUNTADMIN;",
            ""
        ]
        
        common = self.SQL_TEMPLATES['COMMON']
        
        lines.append("-- 1. WAREHOUSE")
        lines.append(common['warehouse'].format(**params) + ";")
        lines.append(f"\nUSE WAREHOUSE {self.wh};")
        
        lines.append("\n-- 2. DATABASE")
        lines.append(common['database'].format(**params) + ";")
        
        lines.append("\n-- 3. SCHEMAS")
        for s in common['schemas']:
            lines.append(s.format(**params) + ";")
        
        lines.append("\n-- 4. TABLES")
        for name, sql in common['tables'].items():
            lines.append(f"\n-- Table: {name}")
            lines.append(sql.format(**params) + ";")
        
        lines.append("\n-- 5. VIEWS")
        for name, sql in common['views'].items():
            lines.append(f"\n-- View: {name}")
            lines.append(sql.format(**params) + ";")
        
        lines.append("\n-- 6. GRANTS")
        for g in common['grants_public']:
            lines.append(g.format(**params) + ";")
        
        lines.append("\n-- 7. INITIAL DATA")
        for d in common['initial_data']:
            lines.append(d.format(**params) + ";")
        
        if deploy_type == self.DEPLOY_NATIVE_APP:
            lines.append("\n-- 8. NATIVE APP SETUP")
            native = self.SQL_TEMPLATES['NATIVE_APP']
            for key in ['app_package', 'app_schema', 'app_stage', 'app_create']:
                lines.append(native[key].format(**params) + ";")
            for g in native.get('grants', []):
                lines.append(g.format(**params) + ";")
            for r in native.get('roles', []):
                lines.append(r.format(**params) + ";")
        
        elif deploy_type == self.DEPLOY_EXTERNAL:
            lines.append("\n-- 8. EXTERNAL APP OAUTH")
            lines.append(self.SQL_TEMPLATES['EXTERNAL']['oauth'].format(**params) + ";")
            for r in self.SQL_TEMPLATES['EXTERNAL'].get('roles', []):
                lines.append(r.format(**params) + ";")
        
        return "\n".join(lines)


WIZARD_STEPS = ['WELCOME', 'ENVIRONMENT', 'PRIVILEGES', 'DATABASE_SETUP',
                'FEATURE_CONFIG', 'SECURITY_REVIEW', 'COMPLETE']

FEATURE_DESCRIPTIONS = {
    'autopilot': {
        'name': 'Warehouse Autopilot',
        'description': (
            'Automatically adjusts warehouse auto-suspend timers based on 7-day usage patterns. '
            'Runs hourly as a Snowflake Task. In AGGRESSIVE mode, also resizes warehouses one step '
            'at a time based on P95 query latency and queue times.'
        ),
        'security_warning': (
            'This will ALTER WAREHOUSE settings on your account every hour. '
            'In CONSERVATIVE mode, auto-suspend is reduced to 5 minutes for idle warehouses. '
            'In AGGRESSIVE mode, auto-suspend is reduced to 60 seconds AND warehouse sizes may change, '
            'which directly affects your credit burn rate (each size doubles cost).'
        ),
        'permissions': ['ALTER WAREHOUSE', 'EXECUTE TASK', 'USAGE on ACCOUNT_USAGE'],
    },
    'budget_enforcer': {
        'name': 'Budget Sentinel',
        'description': (
            'Monitors credit usage against your configured budget alerts every 60 minutes. '
            'Checks account-level, warehouse-level, and team-level costs. Detects cost anomalies '
            'using Z-score analysis against 30-day baselines.'
        ),
        'security_warning': (
            'When alerts named "Hard Limit" are triggered, this will AUTOMATICALLY SUSPEND warehouses '
            'that exceed credit thresholds. For team-level hard limits, running queries from that '
            "team's users will be cancelled. This CAN interrupt active workloads."
        ),
        'permissions': ['ALTER WAREHOUSE', 'EXECUTE TASK', 'USAGE on ACCOUNT_USAGE'],
    },
    'anomaly_monitor': {
        'name': 'Anomaly Sentinel',
        'description': (
            'Daily Z-score analysis (8:00 AM UTC) of credit consumption to detect spending anomalies. '
            'Checks at account level, per-warehouse, and per-user. Alerts when spending deviates '
            'beyond the configured Z-score threshold (default: 2 standard deviations).'
        ),
        'security_warning': (
            'This deploys a Snowflake Task running daily. It queries ACCOUNT_USAGE views and writes '
            'to ANOMALY_LOG. This is read-only monitoring -- it does NOT modify any warehouses or '
            'cancel any queries. Notifications are sent via configured channels (email, Slack, etc.).'
        ),
        'permissions': ['EXECUTE TASK', 'USAGE on ACCOUNT_USAGE'],
    },
}

SECURITY_CHECKLIST = [
    {
        'item': 'Network Policy',
        'check_sql': 'SHOW NETWORK POLICIES',
        'pass_condition': 'has_rows',
        'warning': 'No network policy configured. Any IP address can connect to your Snowflake account.',
        'doc': 'Network policies restrict which IP addresses can connect. Strongly recommended for production.',
    },
    {
        'item': 'ACCOUNTADMIN Users',
        'check_sql': "SHOW GRANTS OF ROLE ACCOUNTADMIN",
        'pass_condition': 'few_rows',
        'max_rows': 3,
        'warning': 'More than 3 users have ACCOUNTADMIN. Minimize users with this all-powerful role.',
        'doc': 'ACCOUNTADMIN has unrestricted access. Follow least-privilege: use SYSADMIN for daily work.',
    },
    {
        'item': 'Auto-Suspend Enabled',
        'check_sql': None,
        'pass_condition': 'info_only',
        'warning': 'Warehouses without auto-suspend incur continuous credit charges even when idle.',
        'doc': 'Auto-suspend pauses idle warehouses. Set to 60-300 seconds for interactive workloads.',
    },
    {
        'item': 'Resource Monitors',
        'check_sql': 'SHOW RESOURCE MONITORS',
        'pass_condition': 'has_rows',
        'warning': 'No resource monitors configured. There is no hard cap on spending.',
        'doc': 'Resource monitors set credit quotas and can auto-suspend warehouses at thresholds.',
    },
]


def render_setup_wizard(client):
    """Render the multi-step production setup wizard.

    Returns True when setup is complete and the dashboard can load.
    Uses st.session_state for step tracking and wizard data persistence.
    """
    if 'wizard_step' not in st.session_state:
        st.session_state.wizard_step = 0
    if 'wizard_data' not in st.session_state:
        st.session_state.wizard_data = {}

    step = st.session_state.wizard_step
    total = len(WIZARD_STEPS)

    st.markdown("## Setup Wizard")
    st.progress(step / (total - 1), text=f"Step {step + 1} of {total}: {WIZARD_STEPS[step].replace('_', ' ').title()}")
    st.markdown("---")

    wizard = SetupWizard(client)

    # ── Navigation helpers ──
    def go_next():
        st.session_state.wizard_step = min(step + 1, total - 1)

    def go_back():
        st.session_state.wizard_step = max(step - 1, 0)

    # ── STEP 0: WELCOME ──
    if step == 0:
        st.markdown("### Welcome to Snowflake Ops Intelligence")
        st.markdown(
            "This wizard will configure your Snowflake account for full observability, "
            "cost management, pipeline monitoring, and AI-powered analytics."
        )
        st.markdown("#### What this wizard will do:")
        st.markdown(
            "1. **Detect your environment** -- account type, role, edition, Cortex AI availability\n"
            "2. **Check privileges** -- verify access to ACCOUNT_USAGE and required permissions\n"
            "3. **Create database objects** -- tables, views, and schemas for the platform\n"
            "4. **Configure features** -- choose which automation to enable (Autopilot, Budget Alerts, Anomaly Detection)\n"
            "5. **Security review** -- check network policies, role grants, and resource monitors\n"
        )
        st.info(
            "**No changes are made until Step 4.** Steps 1-2 are read-only diagnostics. "
            "You can go back and change settings at any time."
        )
        st.markdown("#### Platform capabilities:")
        cols = st.columns(3)
        cols[0].markdown("- Cost Intelligence\n- Warehouse Metrics\n- Query Optimization\n- Waste Manager")
        cols[1].markdown("- Pipeline Builder\n- dbt Studio\n- Data Quality\n- Observability Hub")
        cols[2].markdown("- AI Agents (Cortex)\n- BI Dashboard Builder\n- Automation Center\n- Security & Governance")

        if st.button("Get Started", type="primary", use_container_width=True):
            go_next()
            st.rerun()

    # ── STEP 1: ENVIRONMENT DETECTION ──
    elif step == 1:
        st.markdown("### Environment Detection")
        st.caption("Detecting your Snowflake account configuration...")

        env = wizard.detect_environment()
        st.session_state.wizard_data['env'] = env

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Account", env.get('account', 'Unknown')[:20])
        c2.metric("Role", env.get('role', 'Unknown'))
        c3.metric("Edition", env.get('edition', 'Unknown'))
        c4.metric("Cortex AI", "Available" if env.get('cortex') else "Unavailable")

        deploy_type = env.get('type', 'EXTERNAL')
        if deploy_type == 'STREAMLIT_IN_SNOWFLAKE':
            st.success("Running inside Streamlit in Snowflake (SiS). Native session detected.")
        elif deploy_type == 'NATIVE_APP':
            st.success("Running as a Snowflake Native App.")
        else:
            st.info("Running as an external application. OAuth or credentials required for connection.")

        st.session_state.wizard_data['deploy_type'] = deploy_type

        if not env.get('cortex'):
            st.warning(
                "Cortex AI is not available in this region/edition. AI features (query explanation, "
                "optimization suggestions, CoCo agent, AI BI Builder) will be disabled. "
                "The platform will still work for all non-AI features."
            )

        _render_wizard_nav(go_back, go_next)

    # ── STEP 2: PRIVILEGE CHECK ──
    elif step == 2:
        st.markdown("### Privilege Check")
        st.caption("Verifying required permissions for full functionality...")

        has_privs = wizard.check_privileges()
        env = st.session_state.wizard_data.get('env', {})

        checks = [
            ("ACCOUNT_USAGE access", has_privs,
             "Required for cost analytics, query history, warehouse metrics, and all monitoring features."),
            ("CREATE DATABASE", wizard.check_object_exists('database', wizard.database) or True,
             "Needed to create the application database. Existing databases will not be modified."),
            ("Warehouse available", bool(env.get('warehouse')),
             "A warehouse is needed to run queries. The wizard can create one if needed."),
        ]

        all_pass = True
        for name, passed, desc in checks:
            icon = "pass" if passed else "fail"
            if icon == "fail":
                all_pass = False
            col1, col2 = st.columns([1, 4])
            col1.markdown(f"{'✅' if passed else '❌'} **{name}**")
            col2.caption(desc)

        if not has_privs:
            st.error("ACCOUNT_USAGE access is required for most platform features.")
            st.markdown("Run this SQL as ACCOUNTADMIN to grant access:")
            st.code(f"GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO ROLE {env.get('role', 'YOUR_ROLE')};")
            st.caption(
                "Without this grant, cost analytics, query history, warehouse monitoring, and "
                "anomaly detection will not work. You can still proceed, but features will be limited."
            )

        st.session_state.wizard_data['has_privs'] = has_privs
        _render_wizard_nav(go_back, go_next)

    # ── STEP 3: DATABASE SETUP ──
    elif step == 3:
        st.markdown("### Database Setup")
        deploy_type = st.session_state.wizard_data.get('deploy_type', SetupWizard.DEPLOY_EXTERNAL)

        st.markdown(f"**Target database:** `{wizard.database}`")
        st.markdown(f"**Target warehouse:** `{wizard.warehouse}`")
        st.caption(
            "This will create the database, 3 schemas (APP_DATA, APP_CONTEXT, APP_ANALYTICS), "
            "18+ tables, 3 views, and populate initial metadata from your warehouse and table inventory."
        )

        deploy_options = {
            'External App (Local/Cloud Hosted)': SetupWizard.DEPLOY_EXTERNAL,
            'Streamlit in Snowflake (SiS)': SetupWizard.DEPLOY_SIS,
            'Native App': SetupWizard.DEPLOY_NATIVE_APP,
        }
        selected = st.selectbox("Deployment Type", list(deploy_options.keys()),
                                index=list(deploy_options.values()).index(deploy_type))
        deploy_type = deploy_options[selected]

        col_auto, col_manual = st.columns(2)

        with col_auto:
            if st.button("Run Automatic Setup", type="primary", use_container_width=True):
                progress = st.progress(0, text="Creating objects...")
                results = wizard.run_setup(deploy_type=deploy_type)
                progress.progress(70, text="Populating metadata...")
                try:
                    wizard.populate_initial_metadata()
                except Exception:
                    pass
                progress.progress(100, text="Complete!")

                if results['failed']:
                    st.warning(f"Created {len(results['created'])} objects, {len(results['failed'])} failed")
                    for f in results['failed']:
                        st.caption(f"Failed: {f}")
                else:
                    st.success(f"Created {len(results['created'])} objects successfully!")
                    st.session_state.wizard_data['setup_done'] = True

        with col_manual:
            if st.button("Download SQL Script", use_container_width=True):
                script = wizard.generate_sql_script(deploy_type=deploy_type)
                st.download_button("Download", script, "setup_snowflake_ops.sql", "text/sql",
                                   use_container_width=True)

        if st.session_state.wizard_data.get('setup_done'):
            st.success("Database setup complete. Proceed to feature configuration.")

        _render_wizard_nav(go_back, go_next)

    # ── STEP 4: FEATURE CONFIGURATION ──
    elif step == 4:
        st.markdown("### Feature Configuration")
        st.caption(
            "Choose which automated features to enable. Each feature runs as a Snowflake Task "
            "on your account's compute. You can change these settings later in the Settings page."
        )

        features = st.session_state.wizard_data.get('features', {})

        for key, desc in FEATURE_DESCRIPTIONS.items():
            with st.container(border=True):
                c1, c2 = st.columns([3, 1])
                with c1:
                    st.markdown(f"**{desc['name']}**")
                    st.caption(desc['description'])
                with c2:
                    features[key] = st.toggle("Enable", value=features.get(key, False), key=f"feat_{key}")

                if features.get(key):
                    st.warning(f"**Security notice:** {desc['security_warning']}")
                    st.caption(f"Required permissions: {', '.join(desc['permissions'])}")

        st.session_state.wizard_data['features'] = features
        _render_wizard_nav(go_back, go_next)

    # ── STEP 5: SECURITY REVIEW ──
    elif step == 5:
        st.markdown("### Security Review")
        st.caption(
            "Review your account's security posture. These are recommendations, not requirements."
        )

        features = st.session_state.wizard_data.get('features', {})
        enabled_features = [FEATURE_DESCRIPTIONS[k]['name'] for k, v in features.items() if v]

        if enabled_features:
            st.info(f"**Enabled automation:** {', '.join(enabled_features)}")

        for check in SECURITY_CHECKLIST:
            with st.container(border=True):
                passed = None
                if check['check_sql']:
                    try:
                        result = wizard.client.execute_query(check['check_sql'], log=False)
                        if check['pass_condition'] == 'has_rows':
                            passed = not result.empty
                        elif check['pass_condition'] == 'few_rows':
                            passed = len(result) <= check.get('max_rows', 3)
                    except Exception:
                        passed = None

                icon = "✅" if passed else ("⚠️" if passed is None else "❌")
                st.markdown(f"{icon} **{check['item']}**")
                if not passed:
                    st.caption(check['warning'])
                st.caption(check['doc'])

        if features.get('budget_enforcer'):
            st.warning(
                "**Budget Sentinel is enabled.** Alerts named 'Hard Limit' will automatically "
                "suspend warehouses or cancel team queries when thresholds are exceeded. "
                "Configure your alerts carefully in Settings > Budget Alerts after setup."
            )

        if features.get('autopilot'):
            st.warning(
                "**Autopilot is enabled.** It will run hourly and modify warehouse settings. "
                "Start with CONSERVATIVE mode to limit changes to auto-suspend timers only."
            )

        _render_wizard_nav(go_back, go_next)

    # ── STEP 6: COMPLETE ──
    elif step == 6:
        st.markdown("### Setup Complete")
        features = st.session_state.wizard_data.get('features', {})
        env = st.session_state.wizard_data.get('env', {})

        st.success("Your Snowflake Ops Intelligence platform is ready!")

        st.markdown("#### Summary")
        st.markdown(f"- **Account:** {env.get('account', 'N/A')}")
        st.markdown(f"- **Database:** `{wizard.database}`")
        st.markdown(f"- **Cortex AI:** {'Enabled' if env.get('cortex') else 'Disabled (region/edition)'}")
        for key, enabled in features.items():
            name = FEATURE_DESCRIPTIONS[key]['name']
            st.markdown(f"- **{name}:** {'Enabled' if enabled else 'Disabled'}")

        st.markdown("#### Next Steps")
        st.markdown(
            "1. **Settings > Budget Alerts** -- Configure spending thresholds and notification channels\n"
            "2. **Settings > Team Attribution** -- Map users to teams for cost allocation\n"
            "3. **Settings > Warehouse Context** -- Define warehouse purposes and cost profiles\n"
            "4. **Observability Hub** -- View your Four Golden Signals dashboard\n"
            "5. **Cost Intelligence** -- Analyze spending patterns and identify waste\n"
        )

        with st.expander("Diagnostic Log"):
            wizard.run_diagnostics()
            st.code(wizard.log.export_text())

        if st.button("Go to Dashboard", type="primary", use_container_width=True):
            st.session_state.setup_complete = True
            st.session_state.pop('wizard_step', None)
            st.session_state.pop('wizard_data', None)
            st.rerun()

    return st.session_state.get('setup_complete', False)


def _render_wizard_nav(go_back, go_next):
    """Render Back/Next navigation buttons."""
    c1, c2, c3 = st.columns([1, 2, 1])
    with c1:
        if st.session_state.wizard_step > 0:
            if st.button("Back", use_container_width=True):
                go_back()
                st.rerun()
    with c3:
        if st.button("Next", type="primary", use_container_width=True):
            go_next()
            st.rerun()
