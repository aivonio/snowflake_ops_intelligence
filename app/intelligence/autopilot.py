"""
Autopilot Manager
Handles automated warehouse optimization: auto-suspend tuning
and warehouse rightsizing (AGGRESSIVE mode).
"""
import pandas as pd
import json

WAREHOUSE_SIZES = ['X-Small', 'Small', 'Medium', 'Large', 'X-Large', '2X-Large', '3X-Large', '4X-Large']


class AutopilotManager:
    def __init__(self, client):
        self.client = client
        self._ensure_config_table()
        self._ensure_log_table()

    def _ensure_config_table(self):
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
        try:
            res = self.client.execute_query("SELECT CONFIG_VALUE FROM APP_CONTEXT.APP_CONFIG WHERE CONFIG_KEY = 'AUTOPILOT_STATUS'")
            if not res.empty:
                return res.iloc[0, 0].replace('"', '')
            return "NOT_CONFIGURED"
        except:
            return "NOT_CONFIGURED"

    def deploy_autopilot(self, mode='CONSERVATIVE'):
        try:
            self.client.execute_query(f"MERGE INTO APP_CONTEXT.APP_CONFIG t USING (SELECT 'AUTOPILOT_STATUS' k, 'STARTED' v) s ON t.CONFIG_KEY=s.k WHEN MATCHED THEN UPDATE SET CONFIG_VALUE=s.v WHEN NOT MATCHED THEN INSERT (CONFIG_KEY, CONFIG_VALUE) VALUES (s.k, s.v)")
            self.client.execute_query(f"MERGE INTO APP_CONTEXT.APP_CONFIG t USING (SELECT 'AUTOPILOT_MODE' k, '{mode}' v) s ON t.CONFIG_KEY=s.k WHEN MATCHED THEN UPDATE SET CONFIG_VALUE=s.v WHEN NOT MATCHED THEN INSERT (CONFIG_KEY, CONFIG_VALUE) VALUES (s.k, s.v)")

            sp_sql = """
            CREATE OR REPLACE PROCEDURE APP_CONTEXT.AUTOPILOT_OPTIMIZE()
            RETURNS STRING
            LANGUAGE PYTHON
            RUNTIME_VERSION = '3.11'
            PACKAGES = ('snowflake-snowpark-python')
            HANDLER = 'run_optimization'
            AS
            $$
import snowflake.snowpark as snowpark
from snowflake.snowpark.functions import col, avg, count
import json

WAREHOUSE_SIZES = ['X-Small', 'Small', 'Medium', 'Large', 'X-Large', '2X-Large', '3X-Large', '4X-Large']

def run_optimization(session):
    actions = []

    mode_row = session.sql("SELECT CONFIG_VALUE FROM APP_CONTEXT.APP_CONFIG WHERE CONFIG_KEY = 'AUTOPILOT_MODE'").collect()
    mode = mode_row[0][0].replace('"', '') if mode_row else 'CONSERVATIVE'

    wh_df = session.sql("SHOW WAREHOUSES").collect()

    for row in wh_df:
        wh_name = row['name']
        auto_suspend = int(row['auto_suspend']) if row['auto_suspend'] else 0
        current_size = row['size'] if 'size' in row.as_dict() else ''

        if auto_suspend == 0:
            continue

        # ── Auto-suspend optimization ──
        load_query = (
            f"SELECT AVG(AVG_RUNNING) as avg_run, AVG(AVG_QUEUED_LOAD) as avg_queue, COUNT(*) as data_points "
            f"FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_LOAD_HISTORY "
            f"WHERE WAREHOUSE_NAME = '{wh_name}' AND START_TIME >= DATEADD(day, -7, CURRENT_TIMESTAMP())"
        )
        try:
            load_res = session.sql(load_query).collect()[0]
        except:
            continue

        avg_run = float(load_res['AVG_RUN'] or 0)
        avg_queue = float(load_res['AVG_QUEUE'] or 0)
        data_points = int(load_res['DATA_POINTS'] or 0)

        new_suspend = None
        reason = ""

        if avg_run < 0.1:
            if mode == 'AGGRESSIVE' and auto_suspend > 60:
                new_suspend = 60
                reason = "Aggressive idle trim (Utilization < 10%)"
            elif mode == 'CONSERVATIVE' and auto_suspend > 300:
                new_suspend = 300
                reason = "Conservative idle trim (Utilization < 10%)"

        if new_suspend:
            try:
                session.sql(f"ALTER WAREHOUSE {wh_name} SET AUTO_SUSPEND = {new_suspend}").collect()
                log_msg = f"Reduced auto-suspend from {auto_suspend} to {new_suspend}"
                sql_cmd = f"INSERT INTO APP_ANALYTICS.AUTOPILOT_LOG (ACTION, REASON, WAREHOUSE_NAME, DETAILS) VALUES ('OPTIMIZE', '{reason}', '{wh_name}', PARSE_JSON('{{\"old\": {auto_suspend}, \"new\": {new_suspend}}}'))"
                session.sql(sql_cmd).collect()
                actions.append(f"{wh_name}: {log_msg}")
            except Exception as e:
                actions.append(f"Failed {wh_name}: {str(e)}")

        # ── Automated Savings (Warehouse rightsizing) ──
        # Expanded to perform rightsizing in both CONSERVATIVE and AGGRESSIVE modes
        # Data points requirement relaxed slightly if heavily used
        if data_points < 24:
            continue

        if not current_size or current_size not in WAREHOUSE_SIZES:
            continue

        idx = WAREHOUSE_SIZES.index(current_size)

        # Get P95 query time for this warehouse
        perf_query = (
            f"SELECT APPROX_PERCENTILE(TOTAL_ELAPSED_TIME, 0.95) / 1000 as p95_sec, "
            f"AVG(TOTAL_ELAPSED_TIME) / 1000 as avg_sec, COUNT(*) as query_count "
            f"FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY "
            f"WHERE WAREHOUSE_NAME = '{wh_name}' "
            f"AND START_TIME >= DATEADD(day, -7, CURRENT_TIMESTAMP()) "
            f"AND EXECUTION_STATUS = 'SUCCESS'"
        )
        try:
            perf_res = session.sql(perf_query).collect()[0]
        except:
            continue

        p95_sec = float(perf_res['P95_SEC'] or 0)
        query_count = int(perf_res['QUERY_COUNT'] or 0)

        if query_count < 10:
            continue

        new_size = None
        resize_reason = ""

        # Downsize: P95 query time < 5s AND avg queue < 1s AND not already smallest
        if p95_sec < 5.0 and avg_queue < 1.0 and idx > 0:
            new_size = WAREHOUSE_SIZES[idx - 1]
            resize_reason = f"Automated Savings: Downsize P95={p95_sec:.1f}s, queue={avg_queue:.1f}s (both low)"

        # Upsize: avg queue > 10s AND not already largest (Only allowed in AGGRESSIVE)
        elif mode == 'AGGRESSIVE' and avg_queue > 10.0 and idx < len(WAREHOUSE_SIZES) - 1:
            new_size = WAREHOUSE_SIZES[idx + 1]
            resize_reason = f"Automated Savings: Upsize avg queue={avg_queue:.1f}s (high contention)"

        if new_size:
            try:
                sf_size = new_size.upper().replace('-', '')
                session.sql(f"ALTER WAREHOUSE {wh_name} SET WAREHOUSE_SIZE = '{sf_size}'").collect()
                details = json.dumps({"old_size": current_size, "new_size": new_size, "p95_sec": p95_sec, "avg_queue": avg_queue})
                session.sql(
                    f"INSERT INTO APP_ANALYTICS.AUTOPILOT_LOG (ACTION, REASON, WAREHOUSE_NAME, DETAILS) "
                    f"VALUES ('RESIZE', '{resize_reason}', '{wh_name}', PARSE_JSON('{details}'))"
                ).collect()
                actions.append(f"{wh_name}: Resized {current_size} -> {new_size}")
            except Exception as e:
                actions.append(f"Resize failed {wh_name}: {str(e)}")

    return "Executed: " + ", ".join(actions) if actions else "No optimizations needed."
            $$;
            """
            self.client.execute_query(sp_sql)

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
        try:
            self.client.execute_query("ALTER TASK IF EXISTS APP_CONTEXT.AUTOPILOT_TASK SUSPEND")
            self.client.execute_query("UPDATE APP_CONTEXT.APP_CONFIG SET CONFIG_VALUE = 'SUSPENDED' WHERE CONFIG_KEY = 'AUTOPILOT_STATUS'")
            return True
        except:
            return False

    def get_logs(self):
        try:
            return self.client.execute_query("SELECT * FROM APP_ANALYTICS.AUTOPILOT_LOG ORDER BY EVENT_TIME DESC LIMIT 50")
        except:
            return pd.DataFrame()
