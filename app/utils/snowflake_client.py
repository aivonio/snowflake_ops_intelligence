"""
Snowflake Client Utility - Native App Optimized
Designed for Streamlit in Snowflake with ACCOUNTADMIN privileges
Provides comprehensive access to all Snowflake resources
"""

import streamlit as st
import pandas as pd
from typing import Optional, Dict, Any, List
import hashlib
import json
from datetime import datetime

# Snowpark for native app
try:
    from snowflake.snowpark import Session
    from snowflake.snowpark.context import get_active_session
    from snowflake.snowpark.functions import col, lit
    HAS_SNOWPARK = True
except ImportError:
    HAS_SNOWPARK = False
    st.error("Snowpark not available - this app requires Streamlit in Snowflake")


class SnowflakeClient:
    """
    Enhanced Snowflake client for native app with full ACCOUNTADMIN access
    Provides comprehensive monitoring and optimization capabilities
    """
    
    def __init__(self, token: str = None):
        self._session = None
        self._token = token
        self._metadata_cache = {}
        self._query_log = []
        self._app_db = None
        
    @property
    def session(self) -> Optional[Session]:
        """Get active Snowpark session"""
        if self._session is None:
            try:
                # 1. Try Native Environment (Streamlit in Snowflake)
                self._session = get_active_session()
            except:
                # 2. Try SaaS / Remote Environment (OAuth)
                if self._token:
                    try:
                        from snowflake.snowpark import Session
                        connection_params = {
                            "account": st.secrets["snowflake"]["account"],
                            "authenticator": "oauth",
                            "token": self._token,
                            "warehouse": st.secrets["snowflake"]["warehouse"],
                            "role": st.secrets["snowflake"].get("role", "ACCOUNTADMIN"), # Default role
                        }
                        self._session = Session.builder.configs(connection_params).create()
                    except Exception as e:
                        st.error(f"Failed to create session with token: {e}")
                        return None
                else:
                    # 3. Fallback to Username/Password (Local Dev)
                    try:
                        from snowflake.snowpark import Session
                        if "snowflake" in st.secrets:
                            self._session = Session.builder.configs(st.secrets["snowflake"]).create()
                    except Exception as e:
                        st.error(f"Failed to create session (Local): {e}")
                        return None

        return self._session

    def get_app_db(self) -> str:
        """
        Dynamically detect the storage database for the app.
        Checks for:
        1. SNOWFLAKE_OPS_APP_DATA (Preferred for Native App)
        2. SNOWFLAKE_OPS_INTELLIGENCE (Fallback for SAE/Manual)
        """
        if self._app_db:
            return self._app_db
            
        if self.session is None:
            return "SNOWFLAKE_OPS_INTELLIGENCE" # Default string
            
        # Try to detect which one exists
        try:
            # Check for Native App storage first
            dbs = self.session.sql("SHOW DATABASES LIKE 'SNOWFLAKE_OPS_APP_DATA'").collect()
            if not dbs:
                # Fallback to general storage
                dbs = self.session.sql("SHOW DATABASES LIKE 'SNOWFLAKE_OPS_INTELLIGENCE'").collect()
                
            if dbs:
                self._app_db = dbs[0]['name']
            else:
                self._app_db = "SNOWFLAKE_OPS_INTELLIGENCE" # Future default
        except:
            self._app_db = "SNOWFLAKE_OPS_INTELLIGENCE"
            
        return self._app_db

    def get_schema_path(self, schema_name: str) -> str:
        """Get fully qualified path for a schema (e.g. MY_DB.APP_CONTEXT)"""
        db = self.get_app_db()
        return f"{db}.{schema_name}"

    def detect_capabilities(self) -> Dict[str, bool]:
        """
        Dynamically detect what the current session can actually do.
        Tests for: Account Usage, Cortex AI, Warehouse Management
        """
        capabilities = {
            "account_usage": False,
            "cortex_ai": False,
            "warehouse_manage": False,
            "org_usage": False
        }
        
        if self.session is None:
            return capabilities
            
        # 0. Test access to Storage DB
        try:
            db_path = self.get_app_db()
            self.session.sql(f"USE DATABASE {db_path}").collect()
            capabilities["can_save_settings"] = True
        except:
            capabilities["can_save_settings"] = False

        # 1. Test Account Usage (Cost/Query History)
        try:
            self.session.sql("SELECT 1 FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY LIMIT 1").collect()
            capabilities["account_usage"] = True
        except:
            pass
            
        # 2. Test Cortex AI (AI Analyst)
        try:
            # Simple COMPLETE check to see if we have access
            self.session.sql("SELECT SNOWFLAKE.CORTEX.COMPLETE('snowflake-arctic', 'Hello')").collect()
            capabilities["cortex_ai"] = True
        except:
            pass
            
        # 3. Test Warehouse Management (SHOW WAREHOUSES)
        try:
            self.session.sql("SHOW WAREHOUSES").collect()
            capabilities["warehouse_manage"] = True
        except:
            pass
            
        return capabilities

    def get_current_user_context(self) -> Dict[str, Any]:
        """Get current user, role, and capabilities"""
        if self.session is None:
            return {}
        
        ctx = {"user": "UNKNOWN", "role": "PUBLIC", "roles": [], "capabilities": {}}
        
        try:
            query = "SELECT CURRENT_USER() as USER, CURRENT_ROLE() as ROLE, CURRENT_AVAILABLE_ROLES() as ROLES"
            df = self.execute_query(query, log=False)
            if not df.empty:
                ctx["user"] = df.iloc[0]['USER']
                ctx["role"] = df.iloc[0]['ROLE']
                roles_raw = df.iloc[0]['ROLES']
                ctx["roles"] = json.loads(roles_raw) if isinstance(roles_raw, str) else roles_raw
                
            # Perform Deep Discovery
            ctx["capabilities"] = self.detect_capabilities()
            
        except Exception as e:
            st.warning(f"Could not fetch user context: {e}")
        
        return ctx
    
    def execute_query(self, query: str, log: bool = True) -> pd.DataFrame:
        """
        Execute query and return DataFrame
        Logs all queries for analysis and optimization
        """
        if self.session is None:
            return pd.DataFrame()
        
        start_time = datetime.now()
        
        try:
            result = self.session.sql(query).to_pandas()
            
            # Normalize columns to uppercase and remove quotes for consistency
            if not result.empty:
                result.columns = [c.upper().replace('"', '').replace("'", "") for c in result.columns]
            
            # Log query execution
            if log:
                execution_time = (datetime.now() - start_time).total_seconds() * 1000
                self._log_query(query, execution_time, len(result), success=True)
            
            return result
            
        except Exception as e:
            if log:
                execution_time = (datetime.now() - start_time).total_seconds() * 1000
                self._log_query(query, execution_time, 0, success=False, error=str(e))
            
            st.warning(f"Query error: {e}")
            return pd.DataFrame()
    
    def execute_write(self, query: str) -> bool:
        """Execute write query (INSERT, UPDATE, DELETE, etc.)"""
        if self.session is None:
            return False
        
        try:
            self.session.sql(query).collect()
            return True
        except Exception as e:
            st.error(f"Write error: {e}")
            return False
    
    def _log_query(self, query: str, execution_time_ms: float, rows: int, 
                   success: bool = True, error: str = None):
        """Log query execution for analysis"""
        log_entry = {
            'timestamp': datetime.now(),
            'query_hash': hashlib.md5(query.encode()).hexdigest(),
            'query_text': query[:500],  # Truncate for storage
            'execution_time_ms': execution_time_ms,
            'rows_returned': rows,
            'success': success,
            'error': error
        }
        self._query_log.append(log_entry)
        
        # Keep only last 1000 queries in memory
        if len(self._query_log) > 1000:
            self._query_log = self._query_log[-1000:]
    
    def get_query_log(self) -> List[Dict]:
        """Get logged queries for analysis"""
        return self._query_log
    
    # ========================================================================
    # COMPREHENSIVE RESOURCE ACCESS - ACCOUNTADMIN PRIVILEGES
    # ========================================================================
    
    def get_all_warehouses(self) -> pd.DataFrame:
        """Get all warehouses with full details"""
        query = "SHOW WAREHOUSES"
        return self.execute_query(query)
    
    def get_all_databases(self) -> pd.DataFrame:
        """Get all databases"""
        query = "SHOW DATABASES"
        return self.execute_query(query)
    
    def get_all_schemas(self, database: str = None) -> pd.DataFrame:
        """Get all schemas, optionally filtered by database"""
        if database:
            query = f"SHOW SCHEMAS IN DATABASE {database}"
        else:
            query = "SHOW SCHEMAS IN ACCOUNT"
        return self.execute_query(query)
    
    def get_all_tables(self, database: str = None, schema: str = None) -> pd.DataFrame:
        """Get all tables with metadata"""
        if database and schema:
            query = f"SHOW TABLES IN SCHEMA {database}.{schema}"
        elif database:
            query = f"SHOW TABLES IN DATABASE {database}"
        else:
            query = "SHOW TABLES IN ACCOUNT"
        return self.execute_query(query)
    
    def get_all_roles(self) -> pd.DataFrame:
        """Get all roles - use ACCOUNT_USAGE for SiS compatibility"""
        # SHOW ROLES not supported in SiS, use ACCOUNT_USAGE instead
        query = """
        SELECT 
            NAME,
            COMMENT,
            CREATED_ON,
            DELETED_ON,
            OWNER
        FROM SNOWFLAKE.ACCOUNT_USAGE.ROLES
        WHERE DELETED_ON IS NULL
        ORDER BY NAME
        """
        return self.execute_query(query)
    
    def get_all_users(self) -> pd.DataFrame:
        """Get all users - use ACCOUNT_USAGE for SiS compatibility"""
        # SHOW USERS not supported in SiS, use ACCOUNT_USAGE instead
        query = """
        SELECT 
            NAME,
            LOGIN_NAME,
            DISPLAY_NAME,
            EMAIL,
            DISABLED,
            DEFAULT_ROLE,
            DEFAULT_WAREHOUSE,
            CREATED_ON,
            LAST_SUCCESS_LOGIN
        FROM SNOWFLAKE.ACCOUNT_USAGE.USERS
        WHERE DELETED_ON IS NULL
        ORDER BY NAME
        """
        return self.execute_query(query)
    
    def get_all_grants_to_role(self, role: str) -> pd.DataFrame:
        """Get all grants for a specific role"""
        query = f"SHOW GRANTS TO ROLE {role}"
        return self.execute_query(query)
    
    def get_all_stages(self) -> pd.DataFrame:
        """Get all stages"""
        query = "SHOW STAGES IN ACCOUNT"
        return self.execute_query(query)
    
    def get_all_pipes(self) -> pd.DataFrame:
        """Get all pipes"""
        query = "SHOW PIPES IN ACCOUNT"
        return self.execute_query(query)
    
    def get_all_tasks(self) -> pd.DataFrame:
        """Get all tasks"""
        query = "SHOW TASKS IN ACCOUNT"
        return self.execute_query(query)
    
    def get_all_streams(self) -> pd.DataFrame:
        """Get all streams"""
        query = "SHOW STREAMS IN ACCOUNT"
        return self.execute_query(query)
    
    def get_all_functions(self) -> pd.DataFrame:
        """Get all user-defined functions"""
        query = "SHOW USER FUNCTIONS IN ACCOUNT"
        return self.execute_query(query)
    
    def get_all_procedures(self) -> pd.DataFrame:
        """Get all stored procedures"""
        query = "SHOW PROCEDURES IN ACCOUNT"
        return self.execute_query(query)
    
    # ========================================================================
    # QUERY OPTIMIZATION & ANALYSIS
    # ========================================================================
    
    def explain_query(self, query: str) -> Dict[str, Any]:
        """
        Get query execution plan using EXPLAIN
        Returns detailed execution plan for optimization
        """
        try:
            explain_query = f"EXPLAIN {query}"
            result = self.execute_query(explain_query, log=False)
            
            if not result.empty:
                return {
                    'plan': result.to_dict('records'),
                    'has_plan': True
                }
        except Exception as e:
            return {
                'plan': [],
                'has_plan': False,
                'error': str(e)
            }
        
        return {'plan': [], 'has_plan': False}
    
    def get_query_profile(self, query_id: str) -> Dict[str, Any]:
        """
        Get detailed query profile for a specific query
        Includes execution stats, partitions scanned, cache usage
        """
        query = f"""
        SELECT 
            QUERY_ID,
            QUERY_TEXT,
            QUERY_TYPE,
            WAREHOUSE_NAME,
            WAREHOUSE_SIZE,
            EXECUTION_STATUS,
            TOTAL_ELAPSED_TIME,
            BYTES_SCANNED,
            BYTES_WRITTEN,
            BYTES_SPILLED_TO_LOCAL_STORAGE,
            BYTES_SPILLED_TO_REMOTE_STORAGE,
            ROWS_PRODUCED,
            ROWS_INSERTED,
            ROWS_UPDATED,
            ROWS_DELETED,
            COMPILATION_TIME,
            EXECUTION_TIME,
            QUEUED_PROVISIONING_TIME,
            QUEUED_OVERLOAD_TIME,
            QUEUED_REPAIR_TIME,
            TRANSACTION_BLOCKED_TIME,
            PARTITIONS_SCANNED,
            PARTITIONS_TOTAL,
            PERCENTAGE_SCANNED_FROM_CACHE,
            CREDITS_USED_CLOUD_SERVICES,
            QUERY_LOAD_PERCENT
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE QUERY_ID = '{query_id}'
        """
        
        result = self.execute_query(query, log=False)
        
        if not result.empty:
            return result.iloc[0].to_dict()
        return {}
    
    def get_similar_queries(self, query_hash: str, limit: int = 10) -> pd.DataFrame:
        """
        Find similar queries based on parameterized hash
        Useful for identifying optimization opportunities
        """
        query = f"""
        SELECT 
            QUERY_ID,
            QUERY_TEXT,
            START_TIME,
            TOTAL_ELAPSED_TIME,
            BYTES_SCANNED,
            WAREHOUSE_NAME,
            WAREHOUSE_SIZE,
            PERCENTAGE_SCANNED_FROM_CACHE,
            CREDITS_USED_CLOUD_SERVICES
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE QUERY_PARAMETERIZED_HASH = '{query_hash}'
            AND START_TIME >= DATEADD(day, -30, CURRENT_TIMESTAMP())
        ORDER BY START_TIME DESC
        LIMIT {limit}
        """
        
        return self.execute_query(query, log=False)
    
    def get_table_metadata(self, database: str, schema: str, table: str) -> Dict[str, Any]:
        """
        Get comprehensive table metadata including:
        - Size, row count
        - Clustering information
        - Last modified time
        - Partitions
        """
        query = f"""
        SELECT 
            TABLE_CATALOG,
            TABLE_SCHEMA,
            TABLE_NAME,
            TABLE_TYPE,
            ROW_COUNT,
            BYTES,
            CLUSTERING_KEY,
            AUTO_CLUSTERING_ON,
            CREATED,
            LAST_ALTERED,
            COMMENT
        FROM {database}.INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = '{schema}'
            AND TABLE_NAME = '{table}'
        """
        
        result = self.execute_query(query, log=False)
        
        if not result.empty:
            return result.iloc[0].to_dict()
        return {}
    
    def get_clustering_info(self, database: str, schema: str, table: str) -> pd.DataFrame:
        """Get clustering information for a table"""
        query = f"""
        SELECT SYSTEM$CLUSTERING_INFORMATION('{table}', '({database}.{schema})')
        """
        return self.execute_query(query, log=False)
    
    def check_result_cache(self, query: str) -> Dict[str, Any]:
        """
        Check if query result is in cache
        Returns cache status and potential savings
        """
        # Execute query and check if it was served from cache
        query_hash = hashlib.md5(query.encode()).hexdigest()
        
        # Check recent executions of same query
        check_query = f"""
        SELECT 
            QUERY_ID,
            PERCENTAGE_SCANNED_FROM_CACHE,
            TOTAL_ELAPSED_TIME,
            BYTES_SCANNED
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE QUERY_HASH = '{query_hash}'
            AND START_TIME >= DATEADD(hour, -24, CURRENT_TIMESTAMP())
        ORDER BY START_TIME DESC
        LIMIT 1
        """
        
        result = self.execute_query(check_query, log=False)
        
        if not result.empty:
            cache_pct = result.iloc[0]['PERCENTAGE_SCANNED_FROM_CACHE']
            return {
                'in_cache': cache_pct > 90,
                'cache_percentage': cache_pct,
                'last_execution': result.iloc[0].to_dict()
            }
        
        return {'in_cache': False, 'cache_percentage': 0}
    
    # ========================================================================
    # COST ANALYSIS & OPTIMIZATION
    # ========================================================================
    
    def estimate_query_cost(self, query: str, warehouse_size: str) -> Dict[str, Any]:
        """
        Estimate query cost before execution
        Uses historical data and query analysis
        """
        # Get query plan
        plan = self.explain_query(query)
        
        # Warehouse credits per hour
        warehouse_credits = {
            'X-SMALL': 1, 'SMALL': 2, 'MEDIUM': 4, 'LARGE': 8,
            'X-LARGE': 16, '2X-LARGE': 32, '3X-LARGE': 64, '4X-LARGE': 128
        }
        
        credits_per_hour = warehouse_credits.get(warehouse_size.upper(), 4)
        
        # Estimate based on similar queries
        query_hash = hashlib.md5(query.encode()).hexdigest()
        similar = self.get_similar_queries(query_hash, limit=5)
        
        if not similar.empty:
            avg_time_ms = similar['TOTAL_ELAPSED_TIME'].mean()
            avg_bytes = similar['BYTES_SCANNED'].mean()
            avg_cache = similar['PERCENTAGE_SCANNED_FROM_CACHE'].mean()
            
            # Adjust for cache
            effective_time_ms = avg_time_ms * (1 - avg_cache / 100)
            
            estimated_credits = (effective_time_ms / 3600000) * credits_per_hour
            
            return {
                'estimated_credits': estimated_credits,
                'estimated_cost_usd': estimated_credits * 3.0,
                'estimated_time_ms': effective_time_ms,
                'based_on_history': True,
                'similar_executions': len(similar),
                'avg_cache_hit': avg_cache,
                'warehouse_size': warehouse_size,
                'credits_per_hour': credits_per_hour
            }
        
        # No history - rough estimate
        return {
            'estimated_credits': 0.001,  # Minimum estimate
            'estimated_time_ms': 1000,
            'based_on_history': False,
            'similar_executions': 0,
            'warehouse_size': warehouse_size,
            'credits_per_hour': credits_per_hour,
            'note': 'No historical data - run query to get accurate estimates'
        }
    
    def get_optimization_suggestions(self, query: str) -> List[Dict[str, Any]]:
        """
        Analyze query and provide optimization suggestions
        Returns list of actionable recommendations
        """
        suggestions = []
        
        query_upper = query.upper()
        
        # Check for SELECT *
        if 'SELECT *' in query_upper:
            suggestions.append({
                'type': 'COLUMN_SELECTION',
                'severity': 'MEDIUM',
                'issue': 'Using SELECT * retrieves all columns',
                'suggestion': 'Specify only needed columns to reduce data transfer',
                'potential_savings': '20-50% reduction in bytes scanned'
            })
        
        # Check for missing WHERE
        if 'WHERE' not in query_upper and 'LIMIT' not in query_upper:
            suggestions.append({
                'type': 'FILTERING',
                'severity': 'HIGH',
                'issue': 'No WHERE clause or LIMIT - full table scan',
                'suggestion': 'Add filter conditions to reduce data scanned',
                'potential_savings': '50-90% reduction in bytes scanned'
            })
        
        # Check for result cache opportunity
        cache_info = self.check_result_cache(query)
        if cache_info['in_cache']:
            suggestions.append({
                'type': 'CACHING',
                'severity': 'INFO',
                'issue': 'Query result is in cache',
                'suggestion': 'Re-running this query will be nearly instant and free',
                'potential_savings': '100% cost savings on re-execution'
            })
        
        # Check for clustering opportunities
        # (Would need table analysis - placeholder)
        
        return suggestions
    
    def get_warehouse_utilization_stats(self, days: int = 7) -> pd.DataFrame:
        """
        Get detailed warehouse utilization stats for AI analysis
        Metrix: Load, Queue, Spill, Credits
        """
        query = f"""
        WITH load_metrics AS (
            SELECT 
                WAREHOUSE_NAME,
                AVG(AVG_RUNNING) as AVG_RUNNING,
                MAX(AVG_RUNNING) as MAX_RUNNING,
                AVG(AVG_QUEUED_LOAD) as AVG_QUEUED,
                MAX(AVG_QUEUED_LOAD) as MAX_QUEUED
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_LOAD_HISTORY
            WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            GROUP BY 1
        ),
        cost_metrics AS (
            SELECT 
                WAREHOUSE_NAME,
                SUM(CREDITS_USED) as TOTAL_CREDITS
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
            WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            GROUP BY 1
        )
        SELECT 
            w.NAME as WAREHOUSE_NAME,
            w.SIZE,
            w.AUTO_SUSPEND,
            w.MIN_CLUSTER_COUNT,
            w.MAX_CLUSTER_COUNT,
            w.SCALING_POLICY,
            l.AVG_RUNNING,
            l.MAX_RUNNING,
            l.AVG_QUEUED,
            l.MAX_QUEUED,
            c.TOTAL_CREDITS
        FROM (SHOW WAREHOUSES) w
        LEFT JOIN load_metrics l ON w.NAME = l.WAREHOUSE_NAME
        LEFT JOIN cost_metrics c ON w.NAME = c.WAREHOUSE_NAME
        WHERE w.STATE = 'STARTED' OR c.TOTAL_CREDITS > 0
        """
        # Note: SHOW WAREHOUSES result can be queried using result scan or similar, 
        # but Snowpark/Python connector might not support selecting from SHOW directly in a subquery easily in all contexts.
        # However, for simplicity and robustness in this app context, let's do a join in Python 
        # because 'SHOW WAREHOUSES' outputs to a session variable differently.
        
        # Better approach for this specific method: 
        # 1. Get Warehouses
    def get_warehouse_utilization_stats(self, days: int = 7) -> pd.DataFrame:
        """
        Get detailed warehouse utilization stats for AI analysis
        Metrix: Load, Queue, Spill, Credits
        """
        # 1. Get Warehouses Config
        wh_df = self.get_all_warehouses()
        
        if wh_df.empty:
            return pd.DataFrame()
            
        # 2. Get Metrics using CTEs and Joins
        metrics_query = f"""
        WITH load AS (
            SELECT 
                WAREHOUSE_NAME,
                AVG(AVG_RUNNING) as AVG_RUNNING,
                MAX(AVG_RUNNING) as MAX_RUNNING,
                AVG(AVG_QUEUED_LOAD) as AVG_QUEUED,
                MAX(AVG_QUEUED_LOAD) as MAX_QUEUED
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_LOAD_HISTORY 
            WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            GROUP BY 1
        ),
        cost AS (
            SELECT 
                WAREHOUSE_NAME,
                SUM(CREDITS_USED) as TOTAL_CREDITS
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY 
            WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            GROUP BY 1
        ),
        spill AS (
            SELECT 
                WAREHOUSE_NAME,
                SUM(BYTES_SPILLED_TO_LOCAL_STORAGE) + SUM(BYTES_SPILLED_TO_REMOTE_STORAGE) as TOTAL_SPILL_BYTES
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            GROUP BY 1
        )
        SELECT 
            COALESCE(l.WAREHOUSE_NAME, c.WAREHOUSE_NAME, s.WAREHOUSE_NAME) as WAREHOUSE_NAME,
            l.AVG_RUNNING,
            l.MAX_RUNNING,
            l.AVG_QUEUED,
            l.MAX_QUEUED,
            c.TOTAL_CREDITS,
            s.TOTAL_SPILL_BYTES
        FROM load l
        FULL OUTER JOIN cost c ON l.WAREHOUSE_NAME = c.WAREHOUSE_NAME
        FULL OUTER JOIN spill s ON COALESCE(l.WAREHOUSE_NAME, c.WAREHOUSE_NAME) = s.WAREHOUSE_NAME
        """
        
        metrics = self.execute_query(metrics_query, log=False)
        
        # Standardize columns for merge
        # wh_df handles 'NAME' logic in get_all_warehouses usually, but ensure consistency
        if 'NAME' in wh_df.columns:
            wh_df = wh_df.rename(columns={'NAME': 'WAREHOUSE_NAME'})
            
        if metrics.empty:
            # Return warehouses with empty metrics
            result = wh_df.copy()
            # Ensure required columns exist
            cols = ['AVG_RUNNING', 'MAX_RUNNING', 'AVG_QUEUED', 'MAX_QUEUED', 'TOTAL_CREDITS', 'TOTAL_SPILL_BYTES']
            for c in cols:
                result[c] = 0
            return result
        
        # Merge stats onto the warehouse list
        # We use LEFT JOIN so we preserve all active warehouses from SHOW WAREHOUSES
        final_df = pd.merge(wh_df, metrics, on='WAREHOUSE_NAME', how='left')
        
        # Fill missing values for warehouses that had no usage/metrics
        final_df = final_df.fillna(0)
        
        return final_df



    def get_daily_credit_usage(self, days: int = 90) -> pd.DataFrame:
        """
        Get daily credit usage for forecasting and anomaly detection
        Returns DataFrame with USAGE_DATE and CREDITS_USED
        """
        query = f"""
        SELECT 
            DATE(START_TIME) as USAGE_DATE,
            SUM(CREDITS_USED) as CREDITS_USED
        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
        WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        GROUP BY DATE(START_TIME)
        ORDER BY USAGE_DATE
        """
        return self.execute_query(query)  # Default safe fallback

    # ========================================================================
    # STAGE & FILE ACCESS (Added for AI Analyst Phase 2)
    # ========================================================================
    
    def list_stage_files(self, stage_name: str) -> pd.DataFrame:
        """List files in a specific stage"""
        try:
            # Stage names often need @ prefix if not internal table stage
            if not stage_name.startswith('@') and not stage_name.startswith('scno'): 
                # Basic heuristic, user might provide '@stage' or just 'stage'
                # If just 'stage', try adding @
                stage_ref = f"@{stage_name}"
            else:
                stage_ref = stage_name
                
            query = f"LIST {stage_ref}"
            return self.execute_query(query, log=False)
        except Exception:
            return pd.DataFrame()

    def read_stage_file(self, stage_name: str, relative_path: str) -> str:
        """
        Read content of a file from stage.
        Uses SELECT $1 FROM @stage/file
        """
        try:
            # Construct full path
            # Remove leading slash from relative_path if present
            path = relative_path.lstrip('/')
            
            # Ensure stage has @
            if not stage_name.startswith('@'):
                stage_ref = f"@{stage_name}"
            else:
                stage_ref = stage_name

            full_path = f"{stage_ref}/{path}"
            
            # Use query to read file content (assuming text/script)
            # GET is for downloading to local client, inside Snowflake we use SELECT on file
            # For SQL/Python scripts, we treat them as unstructured text
            query = f"SELECT $1::STRING as CONTENT FROM {full_path}"
            
            # Note: This works for single-file reading if file format is compatible or default
            # For robustness, we might need a file format, but let's try default first
            result = self.execute_query(query, log=False)
            
            if not result.empty:
                # Combine all lines
                return "\\n".join(result['CONTENT'].dropna().tolist())
            return ""
        except Exception as e:
            return f"Error reading file: {str(e)}"


# Global client instance
_client = None

def get_snowflake_client() -> SnowflakeClient:
    """Get or create the global Snowflake client"""
    global _client
    if _client is None:
        _client = SnowflakeClient()
    return _client
