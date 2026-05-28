"""
Budget Enforcer — Automated budget checking with multi-channel notifications
and team-level enforcement via TEAM_ATTRIBUTION.
"""
import pandas as pd
import json

class BudgetEnforcer:
    def __init__(self, client):
        self.client = client
        self.db = "SNOWFLAKE_OPS_INTELLIGENCE"
        self.schema = "APP_CONTEXT"
        self.warehouse = "COMPUTE_WH"

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

        sp_sql = """
        CREATE OR REPLACE PROCEDURE APP_CONTEXT.RUN_BUDGET_CHECK()
        RETURNS STRING
        LANGUAGE PYTHON
        RUNTIME_VERSION = '3.11'
        PACKAGES = ('snowflake-snowpark-python', 'pandas')
        HANDLER = 'run_check'
        AS
        $$
import snowflake.snowpark as snowpark
from snowflake.snowpark.functions import col, sum as sum_, current_timestamp
import pandas as pd
import json

def run_check(session):
    alerts_df = session.table("APP_CONTEXT.BUDGET_ALERTS").filter(col("IS_ACTIVE") == True).to_pandas()

    actions_taken = []

    for _, row in alerts_df.iterrows():
        try:
            alert_id = row.get('ALERT_ID', '')
            name = row.get('ALERT_NAME', '')
            target = row.get('TARGET_NAME', '')
            metric_type = row.get('ALERT_TYPE', 'COST')
            channel = row.get('NOTIFICATION_CHANNEL', 'DASHBOARD')
            recipients = row.get('RECIPIENTS', '')

            # Handle column naming: THRESHOLD_VALUE or THRESHOLD_CREDITS
            threshold = 0.0
            if 'THRESHOLD_VALUE' in row and row['THRESHOLD_VALUE'] is not None:
                threshold = float(row['THRESHOLD_VALUE'])
            elif 'THRESHOLD_CREDITS' in row and row['THRESHOLD_CREDITS'] is not None:
                threshold = float(row['THRESHOLD_CREDITS'])

            op = row.get('CONDITION_OP', '>')
            if not op:
                op = '>'

            current_value = 0.0

            if metric_type == 'COST':
                if not target or target.upper() == 'ACCOUNT':
                    q = "SELECT SUM(CREDITS_USED) FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY WHERE START_TIME >= DATEADD(hour, -24, CURRENT_TIMESTAMP())"
                else:
                    q = f"SELECT SUM(CREDITS_USED) FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY WHERE WAREHOUSE_NAME = '{target}' AND START_TIME >= DATEADD(hour, -24, CURRENT_TIMESTAMP())"
                res = session.sql(q).collect()
                current_value = float(res[0][0]) if res[0][0] is not None else 0.0

            elif metric_type == 'PERFORMANCE':
                if not target or target.upper() == 'ACCOUNT':
                    q = "SELECT COUNT(*) FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY WHERE EXECUTION_STATUS = 'FAIL' AND START_TIME >= DATEADD(hour, -24, CURRENT_TIMESTAMP())"
                else:
                    q = f"SELECT COUNT(*) FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY WHERE WAREHOUSE_NAME = '{target}' AND EXECUTION_STATUS = 'FAIL' AND START_TIME >= DATEADD(hour, -24, CURRENT_TIMESTAMP())"
                res = session.sql(q).collect()
                current_value = float(res[0][0])

            elif metric_type == 'ANOMALY':
                q = "SELECT DATE(START_TIME) as D, SUM(CREDITS_USED) as C FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY WHERE START_TIME >= DATEADD(day, -30, CURRENT_TIMESTAMP()) GROUP BY 1"
                hist_df = session.sql(q).to_pandas()
                if not hist_df.empty:
                    avg_cost = hist_df['C'].mean()
                    std_cost = hist_df['C'].std()
                    q_today = "SELECT SUM(CREDITS_USED) FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY WHERE START_TIME >= DATEADD(hour, -24, CURRENT_TIMESTAMP())"
                    res_today = session.sql(q_today).collect()
                    current_cost = float(res_today[0][0]) if res_today[0][0] else 0.0
                    if std_cost > 0:
                        current_value = (current_cost - avg_cost) / std_cost
                    else:
                        current_value = 0.0

            elif metric_type == 'TEAM':
                team_name = target
                if not team_name:
                    continue
                team_q = (
                    f"WITH team_users AS ("
                    f"  SELECT USER_NAME, BUDGET_LIMIT_CREDITS"
                    f"  FROM APP_CONTEXT.TEAM_ATTRIBUTION"
                    f"  WHERE TEAM_NAME = '{team_name}'"
                    f"), team_cost AS ("
                    f"  SELECT SUM(qh.CREDITS_USED_CLOUD_SERVICES) as total_credits"
                    f"  FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY qh"
                    f"  JOIN team_users tu ON qh.USER_NAME = tu.USER_NAME"
                    f"  WHERE qh.START_TIME >= DATEADD(hour, -24, CURRENT_TIMESTAMP())"
                    f") SELECT COALESCE(total_credits, 0) as TEAM_CREDITS FROM team_cost"
                )
                try:
                    team_res = session.sql(team_q).collect()
                    current_value = float(team_res[0]['TEAM_CREDITS']) if team_res else 0.0
                except:
                    current_value = 0.0

            # Check condition
            violation = False
            if op == '>' and current_value > threshold:
                violation = True
            elif op == '>=' and current_value >= threshold:
                violation = True
            elif op == '<' and current_value < threshold:
                violation = True

            if violation:
                safe_name = name.replace("'", "''")
                safe_target = (target or 'ACCOUNT').replace("'", "''")
                msg = f"Alert '{safe_name}' triggered! {safe_target} value {current_value:.2f} {op} {threshold}"

                session.sql(
                    f"INSERT INTO APP_CONTEXT.NOTIFICATIONS_LOG (LEVEL, MESSAGE, CHANNEL) "
                    f"VALUES ('WARNING', '{msg}', '{channel}')"
                ).collect()

                # ── Send notifications via configured channels ──
                alert_text = msg.replace("'", "''")[:3000]
                try:
                    channels = session.sql(
                        "SELECT CONFIG_ID, CHANNEL_TYPE, INTEGRATION_NAME "
                        "FROM APP_CONTEXT.NOTIFICATION_CONFIGS WHERE IS_ACTIVE = TRUE"
                    ).collect()
                    for ch in channels:
                        int_name = ch['INTEGRATION_NAME']
                        ch_type = ch['CHANNEL_TYPE']
                        if ch_type == 'EMAIL':
                            try:
                                session.sql(
                                    f"CALL SYSTEM$SEND_EMAIL('{int_name}', "
                                    f"'SnowOps Budget Alert', '{alert_text}')"
                                ).collect()
                            except:
                                pass
                        else:
                            try:
                                session.sql(
                                    f"SELECT SYSTEM$SEND_NOTIFICATION('{int_name}', '{alert_text}')"
                                ).collect()
                            except:
                                pass
                except:
                    pass

                # ── Enforcement actions ──
                if metric_type == 'TEAM' and 'HARD LIMIT' in name.upper():
                    # For team hard limits: cancel running queries for team users
                    try:
                        running = session.sql(
                            f"SELECT qh.QUERY_ID "
                            f"FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY_BY_USER()) qh "
                            f"JOIN APP_CONTEXT.TEAM_ATTRIBUTION ta ON qh.USER_NAME = ta.USER_NAME "
                            f"WHERE ta.TEAM_NAME = '{safe_target}' "
                            f"AND qh.EXECUTION_STATUS = 'RUNNING'"
                        ).collect()
                        cancelled = 0
                        for qrow in running:
                            try:
                                session.sql(f"SELECT SYSTEM$CANCEL_QUERY('{qrow['QUERY_ID']}')").collect()
                                cancelled += 1
                            except:
                                pass
                        if cancelled > 0:
                            log_msg = f"Cancelled {cancelled} queries for team {safe_target} (budget exceeded)"
                            session.sql(
                                f"INSERT INTO APP_CONTEXT.ENFORCEMENT_LOG (ACTION, TARGET_ID, TEAM_NAME, REASON) "
                                f"VALUES ('CANCEL_QUERIES', '{safe_target}', '{safe_target}', '{log_msg}')"
                            ).collect()
                            actions_taken.append(log_msg)
                    except:
                        pass

                elif 'HARD LIMIT' in name.upper() and target and target.upper() != 'ACCOUNT':
                    try:
                        session.sql(f"ALTER WAREHOUSE {target} SUSPEND").collect()
                        log_msg = f"Auto-suspended warehouse {target} due to limit violation."
                        session.sql(
                            f"INSERT INTO APP_CONTEXT.ENFORCEMENT_LOG (ACTION, TARGET_ID, REASON) "
                            f"VALUES ('SUSPEND', '{safe_target}', '{msg}')"
                        ).collect()
                        actions_taken.append(log_msg)
                    except Exception as e:
                        session.sql(
                            f"INSERT INTO APP_CONTEXT.NOTIFICATIONS_LOG (LEVEL, MESSAGE) "
                            f"VALUES ('ERROR', 'Failed to suspend {safe_target}: {str(e)[:200]}')"
                        ).collect()
                else:
                    actions_taken.append(msg)

        except Exception as e:
            err_msg = str(e)[:300].replace("'", "''")
            session.sql(
                f"INSERT INTO APP_CONTEXT.NOTIFICATIONS_LOG (LEVEL, MESSAGE) "
                f"VALUES ('ERROR', 'Sentinel Error: {err_msg}')"
            ).collect()

    return json.dumps(actions_taken)
        $$;
        """
        self.client.execute_query(sp_sql)

        task_sql = """
        CREATE OR REPLACE TASK APP_CONTEXT.BUDGET_SENTINEL_TASK
        WAREHOUSE = COMPUTE_WH
        SCHEDULE = '60 MINUTE'
        AS
        CALL APP_CONTEXT.RUN_BUDGET_CHECK();
        """
        self.client.execute_query(task_sql)
        self.client.execute_query("ALTER TASK APP_CONTEXT.BUDGET_SENTINEL_TASK RESUME")

        return "Budget Sentinel Deployed & Started"

    def stop_sentinel(self):
        try:
            self.client.execute_query("ALTER TASK APP_CONTEXT.BUDGET_SENTINEL_TASK SUSPEND")
            return "Sentinel Suspended"
        except:
            return "Sentinel was not running"
