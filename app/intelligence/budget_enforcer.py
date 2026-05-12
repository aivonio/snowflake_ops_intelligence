import snowflake.connector
import pandas as pd
import json

class BudgetEnforcer:
    def __init__(self, client):
        self.client = client
        self.db = "SNOWFLAKE_OPS" # Assuming standard DB
        self.schema = "APP_CONTEXT"
    
    def get_status(self):
        """Check if the Sentinel Task is running"""
        try:
            res = self.client.execute_query(
                "SHOW TASKS LIKE 'BUDGET_SENTINEL_TASK' IN SCHEMA APP_CONTEXT"
            )
            if not res.empty:
                return res.iloc[0]['state']
            return "NOT_CONFIGURED"
        except:
            return "ERROR"

    def deploy_sentinel(self):
        """Deploy the Stored Procedure and scheduled Task"""
        
        # 1. The Python Stored Procedure
        sp_sql = """
        CREATE OR REPLACE PROCEDURE APP_CONTEXT.RUN_BUDGET_CHECK()
        RETURNS STRING
        LANGUAGE PYTHON
        RUNTIME_VERSION = '3.8'
        PACKAGES = ('snowflake-snowpark-python', 'pandas')
        HANDLER = 'run_check'
        AS
        $$
import snowflake.snowpark as snowpark
from snowflake.snowpark.functions import col, sum as sum_, current_timestamp
import pandas as pd
import json

def run_check(session):
    # 1. Fetch Active Alerts
    alerts_df = session.table("APP_CONTEXT.BUDGET_ALERTS").filter(col("IS_ACTIVE") == True).to_pandas()
    
    actions_taken = []
    
    for _, row in alerts_df.iterrows():
        try:
            alert_id = row['ALERT_ID']
            name = row['ALERT_NAME']
            target = row['TARGET_NAME']
            threshold = row['THRESHOLD_VALUE']
            op = row['CONDITION_OP']
            metric_type = row['ALERT_TYPE']
            
            # 2. Evaluate Metric
            current_value = 0.0
            
            if metric_type == 'COST':
                # Check Last 24 Hours Cost
                if target.upper() == 'ACCOUNT':
                    # Account-level check
                    q = "SELECT SUM(CREDITS_USED) FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY WHERE START_TIME >= DATEADD(hour, -24, CURRENT_TIMESTAMP())"
                else:
                    # Warehouse-level check
                    q = f"SELECT SUM(CREDITS_USED) FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY WHERE WAREHOUSE_NAME = '{target}' AND START_TIME >= DATEADD(hour, -24, CURRENT_TIMESTAMP())"
                
                res = session.sql(q).collect()
                current_value = float(res[0][0]) if res[0][0] is not None else 0.0
                
            elif metric_type == 'PERFORMANCE': # Failed Queries
                 if target.upper() == 'ACCOUNT':
                     q = "SELECT COUNT(*) FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY WHERE EXECUTION_STATUS = 'FAIL' AND START_TIME >= DATEADD(hour, -24, CURRENT_TIMESTAMP())"
                 else:
                     q = f"SELECT COUNT(*) FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY WHERE WAREHOUSE_NAME = '{target}' AND EXECUTION_STATUS = 'FAIL' AND START_TIME >= DATEADD(hour, -24, CURRENT_TIMESTAMP())"
                 res = session.sql(q).collect()
                 current_value = float(res[0][0])
            
            elif metric_type == 'ANOMALY': # Z-Score based cost anomaly
                # Fetch last 30 days history
                q = "SELECT DATE(START_TIME) as D, SUM(CREDITS_USED) as C FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY WHERE START_TIME >= DATEADD(day, -30, CURRENT_TIMESTAMP()) GROUP BY 1"
                hist_df = session.sql(q).to_pandas()
                
                if not hist_df.empty:
                    avg_cost = hist_df['C'].mean()
                    std_cost = hist_df['C'].std()
                    
                    # Today (approx last 24h sum) - simpler approx
                    q_today = "SELECT SUM(CREDITS_USED) FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY WHERE START_TIME >= DATEADD(hour, -24, CURRENT_TIMESTAMP())"
                    res_today = session.sql(q_today).collect()
                    current_cost = float(res_today[0][0]) if res_today[0][0] else 0.0
                    
                    if std_cost > 0:
                        z_score = (current_cost - avg_cost) / std_cost
                        current_value = z_score # Value to check against Threshold (which is z-score limit like 2.0)
                    else:
                        current_value = 0.0 # No variance
            
            # 3. Check Condition

            violation = False
            if op == '>' and current_value > threshold: violation = True
            elif op == '>=' and current_value >= threshold: violation = True
            # ... support other ops if needed
            
            if violation:
                msg = f"Alert '{name}' triggered! {target} value {current_value:.2f} {op} {threshold}"
                
                # LOG NOTIFICATION
                session.sql(f"INSERT INTO APP_CONTEXT.NOTIFICATIONS_LOG (LEVEL, MESSAGE, CHANNEL) VALUES ('WARNING', '{msg}', '{row['NOTIFICATION_CHANNEL']}')").collect()
                
                # ENFORCE ACTION (Mockup for strict enforcement)
                # If name contains 'Hard Limit', actually suspend
                if 'HARD LIMIT' in name.upper() and target.upper() != 'ACCOUNT':
                     try:
                         session.sql(f"ALTER WAREHOUSE {target} SUSPEND").collect()
                         log_msg = f"Auto-suspended warehouse {target} due to limit violation."
                         session.sql(f"INSERT INTO APP_CONTEXT.ENFORCEMENT_LOG (ACTION, TARGET_ID, REASON) VALUES ('SUSPEND', '{target}', '{msg}')").collect()
                         actions_taken.append(log_msg)
                     except Exception as e:
                         session.sql(f"INSERT INTO APP_CONTEXT.NOTIFICATIONS_LOG (LEVEL, MESSAGE) VALUES ('ERROR', 'Failed to suspend {target}: {str(e)}')").collect()
                else:
                     actions_taken.append(msg)

        except Exception as e:
            session.sql(f"INSERT INTO APP_CONTEXT.NOTIFICATIONS_LOG (LEVEL, MESSAGE) VALUES ('ERROR', 'Sentinel Error: {str(e)}')").collect()
            
    return json.dumps(actions_taken)
        $$;
        """
        self.client.execute_query(sp_sql)
        
        # 2. Create the Task
        task_sql = """
        CREATE OR REPLACE TASK APP_CONTEXT.BUDGET_SENTINEL_TASK
        WAREHOUSE = COMPUTING_WH
        SCHEDULE = '60 MINUTE'
        AS
        CALL APP_CONTEXT.RUN_BUDGET_CHECK();
        """
        # Note: Using COMPUTING_WH (or whatever is available). 
        # Ideally should use the user's configured warehouse, but hardcoding for MVP safety if client doesn't expose it easily.
        # Replacing COMPUTING_WH with a safer default if needed.
        
        self.client.execute_query(task_sql)
        self.client.execute_query("ALTER TASK APP_CONTEXT.BUDGET_SENTINEL_TASK RESUME")
        
        return "Budget Sentinel Deployed & Started"

    def stop_sentinel(self):
        try:
            self.client.execute_query("ALTER TASK APP_CONTEXT.BUDGET_SENTINEL_TASK SUSPEND")
            return "Sentinel Suspended"
        except:
            return "Sentinel was not running"
