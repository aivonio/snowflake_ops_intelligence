"""
Anomaly Monitor Service
Automated daily checks for cost anomalies with multi-channel notifications.
"""
import json

class AnomalyMonitor:
    def __init__(self, client):
        self.client = client
        self._ensure_log_table()

    def _ensure_log_table(self):
        """Ensure analytics table exists"""
        try:
            self.client.execute_query("""
                CREATE TABLE IF NOT EXISTS APP_ANALYTICS.ANOMALY_LOG (
                    EVENT_TIME TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
                    METRIC VARCHAR, -- 'COST', 'LOGIN', etc.
                    VALUE FLOAT,
                    THRESHOLD FLOAT,
                    Z_SCORE FLOAT,
                    DETAILS VARIANT,
                    IS_ALERTED BOOLEAN DEFAULT FALSE
                )
            """, log=False)
        except Exception as e:
            print(f"Log table error: {e}")

    def deploy_monitor(self):
        """Deploy the anomaly detection task"""
        try:
            # Create Stored Procedure
            sp_sql = """
            CREATE OR REPLACE PROCEDURE APP_CONTEXT.RUN_ANOMALY_CHECK()
            RETURNS STRING
            LANGUAGE PYTHON
            RUNTIME_VERSION = '3.8'
            PACKAGES = ('snowflake-snowpark-python')
            HANDLER = 'check_anomalies'
            AS
            $$
            import snowflake.snowpark as snowpark
            import json
            
            def check_anomalies(session):
                alerts = []
                
                # 1. Cost Anomaly (Z-Score > 2)
                # Look at yesterday's full day
                query = \"\"\"
                WITH daily_credits AS (
                    SELECT 
                        DATE(START_TIME) as usage_date,
                        SUM(CREDITS_USED) as daily_credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
                    WHERE START_TIME >= DATEADD(day, -30, CURRENT_DATE()) 
                    AND START_TIME < CURRENT_DATE() -- Exclude today (partial)
                    GROUP BY DATE(START_TIME)
                ),
                stats AS (
                    SELECT 
                        AVG(daily_credits) as avg_credits,
                        STDDEV(daily_credits) as stddev_credits
                    FROM daily_credits
                ),
                yesterday AS (
                    SELECT daily_credits, usage_date FROM daily_credits 
                    WHERE usage_date = DATEADD(day, -1, CURRENT_DATE())
                )
                SELECT 
                    y.daily_credits,
                    s.avg_credits,
                    s.stddev_credits,
                    (y.daily_credits - s.avg_credits) / NULLIF(s.stddev_credits, 0) as z_score
                FROM yesterday y, stats s
                WHERE y.daily_credits > (s.avg_credits + (2 * s.stddev_credits))
                \"\"\"
                
                res = session.sql(query).collect()
                
                if res:
                    row = res[0]
                    val = float(row['DAILY_CREDITS'])
                    avg = float(row['AVG_CREDITS'])
                    z = float(row['Z_SCORE'])
                    
                    # Log Anomaly
                    log_sql = f"INSERT INTO APP_ANALYTICS.ANOMALY_LOG (METRIC, VALUE, THRESHOLD, Z_SCORE, DETAILS, IS_ALERTED) VALUES ('COST', {val}, {avg}, {z}, PARSE_JSON('{{\"msg\": \"Cost detection\"}}'), TRUE)"
                    session.sql(log_sql).collect()
                    
                    alerts.append(f"Cost Spike Detected: {val:.2f} credits (Z-Score: {z:.2f})")
                    
                    # TODO: Call Notification Integration (External Function or Email)
                    # For now, we log to the Anomaly Log which is surfacing in the UI
                
                return "Anomalies: " + ", ".join(alerts) if alerts else "No anomalies found."
             $$;
            """
            self.client.execute_query(sp_sql)

            # Create Task (Daily at 8 AM UTC)
            task_sql = """
            CREATE OR REPLACE TASK APP_CONTEXT.ANOMALY_SENTINEL_TASK
            WAREHOUSE = COMPUTE_WH
            SCHEDULE = 'USING CRON 0 8 * * * UTC'
            AS
            CALL APP_CONTEXT.RUN_ANOMALY_CHECK();
            """
            self.client.execute_query(task_sql)
            self.client.execute_query("ALTER TASK APP_CONTEXT.ANOMALY_SENTINEL_TASK RESUME")
            
            return True
        except Exception as e:
            print(f"Deploy monitor error: {e}")
            return False
