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
                    
                    for _, row in wh_df.iterrows():
                        name = row.get(name_col)
                        size = row.get(size_col)
                        if name:
                            purpose = self._infer_warehouse_purpose(name)
                            merge_sql = f"""
                            MERGE INTO {self.db}.APP_CONTEXT.WAREHOUSE_CONTEXT AS target
                            USING (SELECT '{name}' AS NAME, '{size}' AS SIZE, '{purpose}' AS PURPOSE) AS source
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
                    for _, row in tables_df.iterrows():
                        db_name = row['TABLE_CATALOG']
                        schema = row['TABLE_SCHEMA']
                        table = row['TABLE_NAME']
                        rows = row['ROW_COUNT'] if row['ROW_COUNT'] is not None else 0
                        bytes_size = row['BYTES'] if row['BYTES'] is not None else 0
                        is_critical = self._infer_table_criticality(table)
                        
                        merge_sql = f"""
                        MERGE INTO {self.db}.APP_CONTEXT.TABLE_CONTEXT AS target
                        USING (
                            SELECT 
                                '{db_name}' AS DB, 
                                '{schema}' AS SCH, 
                                '{table}' AS TBL,
                                {rows} AS RC,
                                {bytes_size} AS SZ,
                                {is_critical} AS CRIT
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


def render_setup_wizard(client):
    """Render the production setup wizard UI."""
    st.markdown("## 🧙‍♂️ Setup Wizard")
    
    wizard = SetupWizard(client)
    diag = wizard.run_diagnostics()
    env = diag['environment']
    
    # Environment Display
    col1, col2, col3 = st.columns(3)
    col1.metric("Deployment", env.get('type', 'Unknown'))
    col2.metric("Role", env.get('role', 'Unknown'))
    col3.metric("Edition", env.get('edition', 'Unknown'))
    
    # Status
    st.markdown("### 📊 Status")
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f"{'✅' if diag['privileges'] else '❌'} Privileges")
    c2.markdown(f"{'✅' if env.get('cortex') else '⚠️'} Cortex AI")
    c3.markdown(f"{'✅' if diag['objects'].get('warehouse') else '⚠️'} Warehouse")
    c4.markdown(f"{'✅' if diag['objects'].get('database') else '⚠️'} Database")
    
    if not diag['privileges']:
        st.error("Missing ACCOUNT_USAGE access")
        st.code(f"GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO ROLE {env.get('role')};")
    
    st.markdown("---")
    
    # Setup Options
    st.markdown("### 🚀 Setup Options")
    
    deploy_options = {
        'External App (Local/Cloud Hosted)': SetupWizard.DEPLOY_EXTERNAL,
        'Streamlit in Snowflake (SiS)': SetupWizard.DEPLOY_SIS,
        'Native App': SetupWizard.DEPLOY_NATIVE_APP
    }
    selected_deploy = st.selectbox("Deployment Type", list(deploy_options.keys()))
    deploy_type = deploy_options[selected_deploy]
    
    c1, c2 = st.columns(2)
    
    with c1:
        if st.button("🔧 Run Automatic Setup", type="primary", use_container_width=True):
            with st.spinner("Creating objects..."):
                results = wizard.run_setup(deploy_type=deploy_type)
                st.success(f"✅ Created {len(results['created'])} objects")
                if results['failed']:
                    st.error(f"❌ {len(results['failed'])} failed")
                    for f in results['failed']:
                        st.markdown(f"- {f}")
                else:
                    st.session_state.setup_complete = True
                    st.balloons()
    
    with c2:
        if st.button("📜 Generate SQL Script", use_container_width=True):
            script = wizard.generate_sql_script(deploy_type=deploy_type)
            st.code(script, language='sql')
            st.download_button("⬇️ Download SQL", script, "setup_snowflake_ops.sql", "text/sql")
    
    # Diagnostic Log
    with st.expander("📋 Diagnostic Log"):
        st.code(wizard.log.export_text())
    
    return diag['privileges'] and diag['objects'].get('database')
