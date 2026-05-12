"""
Autopilot Manager
Handles automated warehouse optimization logic.
"""
import pandas as pd
import json

class AutopilotManager:
    def __init__(self, client):
        self.client = client
        self._ensure_config_table()
        self._ensure_log_table()

    def _ensure_config_table(self):
        """Ensure configuration table exists"""
        try:
            self.client.execute_query("""
                CREATE TABLE IF NOT EXISTS APP_CONTEXT.APP_CONFIG (
                    CONFIG_KEY VARCHAR PRIMARY KEY,
                    CONFIG_VALUE VARIANT,
                    UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                )
            """, log=False)
        except Exception as e:
            print(f"Config table error: {e}")

    def _ensure_log_table(self):
        """Ensure log table exists"""
        try:
            self.client.execute_query("""
                CREATE TABLE IF NOT EXISTS APP_ANALYTICS.AUTOPILOT_LOG (
                    EVENT_TIME TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
                    ACTION VARCHAR,
                    REASON VARCHAR,
                    WAREHOUSE_NAME VARCHAR,
                    DETAILS VARIANT
                )
            """, log=False)
        except Exception as e:
            print(f"Log table error: {e}")

    def get_status(self):
        """Get current status (STARTED, SUSPENDED, NOT_CONFIGURED)"""
        try:
            res = self.client.execute_query("SELECT CONFIG_VALUE FROM APP_CONTEXT.APP_CONFIG WHERE CONFIG_KEY = 'AUTOPILOT_STATUS'")
            if not res.empty:
                return res.iloc[0, 0].replace('"', '')
            return "NOT_CONFIGURED"
        except:
            return "NOT_CONFIGURED"

    def deploy_autopilot(self, mode='CONSERVATIVE'):
        """Deploy the scheduled task for optimization"""
        try:
            # 1. Save Config
            self.client.execute_query(f"MERGE INTO APP_CONTEXT.APP_CONFIG t USING (SELECT 'AUTOPILOT_STATUS' k, 'STARTED' v) s ON t.CONFIG_KEY=s.k WHEN MATCHED THEN UPDATE SET CONFIG_VALUE=s.v WHEN NOT MATCHED THEN INSERT (CONFIG_KEY, CONFIG_VALUE) VALUES (s.k, s.v)")
            self.client.execute_query(f"MERGE INTO APP_CONTEXT.APP_CONFIG t USING (SELECT 'AUTOPILOT_MODE' k, '{mode}' v) s ON t.CONFIG_KEY=s.k WHEN MATCHED THEN UPDATE SET CONFIG_VALUE=s.v WHEN NOT MATCHED THEN INSERT (CONFIG_KEY, CONFIG_VALUE) VALUES (s.k, s.v)")

            # 2. Create Stored Procedure for Optimization Logic
            sp_sql = """
            CREATE OR REPLACE PROCEDURE APP_CONTEXT.AUTOPILOT_OPTIMIZE()
            RETURNS STRING
            LANGUAGE PYTHON
            RUNTIME_VERSION = '3.8'
            PACKAGES = ('snowflake-snowpark-python')
            HANDLER = 'run_optimization'
            AS
            $$
            import snowflake.snowpark as snowpark
            from snowflake.snowpark.functions import col, avg, count
            
            def run_optimization(session):
                actions = []
                
                # Get Mode
                mode_row = session.sql("SELECT CONFIG_VALUE FROM APP_CONTEXT.APP_CONFIG WHERE CONFIG_KEY = 'AUTOPILOT_MODE'").collect()
                mode = mode_row[0][0].replace('"', '') if mode_row else 'CONSERVATIVE'
                
                # Get Warehouses
                wh_df = session.sql("SHOW WAREHOUSES").collect()
                
                for row in wh_df:
                    wh_name = row['name']
                    auto_suspend = int(row['auto_suspend']) if row['auto_suspend'] else 0
                    
                    # Skip if not enabled or critical (simplified logic for now)
                    if auto_suspend == 0: continue 

                    # Analyze Load (Last 7 days)
                    load_query = f"SELECT AVG(AVG_RUNNING) as avg_run, AVG(AVG_QUEUED_LOAD) as avg_queue FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_LOAD_HISTORY WHERE WAREHOUSE_NAME = '{wh_name}' AND START_TIME >= DATEADD(day, -7, CURRENT_TIMESTAMP())"
                    load_res = session.sql(load_query).collect()[0]
                    avg_run = load_res['AVG_RUN'] or 0
                    
                    # Optimization Rule
                    new_suspend = None
                    reason = ""
                    
                    if avg_run < 0.1: # Very low utilization
                        if mode == 'AGGRESSIVE' and auto_suspend > 60:
                            new_suspend = 60
                            reason = "Aggressive idle trim (Utilization < 10%)"
                        elif mode == 'CONSERVATIVE' and auto_suspend > 300:
                            new_suspend = 300
                            reason = "Conservative idle trim (Utilization < 10%)"
                    
                    if new_suspend:
                        try:
                            session.sql(f"ALTER WAREHOUSE {wh_name} SET AUTO_SUSPEND = {new_suspend}").collect()
                            
                            # Log Action
                            log_msg = f"Reduced auto-suspend from {auto_suspend} to {new_suspend}"
                            sql_cmd = f'''INSERT INTO APP_ANALYTICS.AUTOPILOT_LOG (ACTION, REASON, WAREHOUSE_NAME, DETAILS) VALUES ('OPTIMIZE', '{reason}', '{wh_name}', PARSE_JSON('{{"old": {auto_suspend}, "new": {new_suspend}}}'))'''
                            session.sql(sql_cmd).collect()
                            actions.append(f"{wh_name}: {log_msg}")
                        except Exception as e:
                            actions.append(f"Failed {wh_name}: {str(e)}")
                            
                return "Executed: " + ", ".join(actions) if actions else "No optimizations needed."
            $$;
            """
            self.client.execute_query(sp_sql)

            # 3. Create Task (Hourly)
            task_sql = """
            CREATE OR REPLACE TASK APP_CONTEXT.AUTOPILOT_TASK
            WAREHOUSE = COMPUTE_WH
            SCHEDULE = 'USING CRON 0 * * * * UTC'
            AS
            CALL APP_CONTEXT.AUTOPILOT_OPTIMIZE();
            """
            self.client.execute_query(task_sql)
            self.client.execute_query("ALTER TASK APP_CONTEXT.AUTOPILOT_TASK RESUME")
            
            return True
        except Exception as e:
            print(f"Deploy error: {e}")
            return False

    def disable_autopilot(self):
        """Suspend the autopilot task"""
        try:
            self.client.execute_query("ALTER TASK IF EXISTS APP_CONTEXT.AUTOPILOT_TASK SUSPEND")
            self.client.execute_query("UPDATE APP_CONTEXT.APP_CONFIG SET CONFIG_VALUE = 'SUSPENDED' WHERE CONFIG_KEY = 'AUTOPILOT_STATUS'")
            return True
        except:
            return False

    def get_logs(self):
        """Get recent activity logs"""
        try:
            return self.client.execute_query("SELECT * FROM APP_ANALYTICS.AUTOPILOT_LOG ORDER BY EVENT_TIME DESC LIMIT 50")
        except:
            return pd.DataFrame()
