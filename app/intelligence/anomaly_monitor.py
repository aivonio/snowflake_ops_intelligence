"""
Anomaly Monitor Service
Automated daily checks for cost anomalies with multi-dimensional detection
(account-level, per-warehouse, per-user) and multi-channel notifications.
"""
import json
import logging

logger = logging.getLogger(__name__)


class AnomalyMonitor:
    def __init__(self, client):
        self.client = client
        self._ensure_log_table()

    def _ensure_log_table(self):
        """Ensure analytics table exists with all required columns."""
        try:
            self.client.execute_query("""
                CREATE TABLE IF NOT EXISTS APP_ANALYTICS.ANOMALY_LOG (
                    EVENT_TIME TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
                    METRIC VARCHAR,
                    VALUE FLOAT,
                    THRESHOLD FLOAT,
                    Z_SCORE FLOAT,
                    DETAILS VARIANT,
                    IS_ALERTED BOOLEAN DEFAULT FALSE,
                    DIMENSION VARCHAR DEFAULT 'ACCOUNT',
                    DIMENSION_VALUE VARCHAR
                )
            """, log=False)
        except Exception as e:
            logger.debug(f"Log table error: {e}")

        for col, dtype in [('DIMENSION', "VARCHAR DEFAULT 'ACCOUNT'"),
                           ('DIMENSION_VALUE', 'VARCHAR')]:
            try:
                self.client.execute_query(
                    f"ALTER TABLE APP_ANALYTICS.ANOMALY_LOG ADD COLUMN IF NOT EXISTS {col} {dtype}",
                    log=False)
            except Exception:
                pass

    def deploy_monitor(self):
        """Deploy the multi-dimensional anomaly detection task."""
        try:
            sp_sql = """
            CREATE OR REPLACE PROCEDURE APP_CONTEXT.RUN_ANOMALY_CHECK()
            RETURNS STRING
            LANGUAGE PYTHON
            RUNTIME_VERSION = '3.11'
            PACKAGES = ('snowflake-snowpark-python')
            HANDLER = 'check_anomalies'
            AS
            $$
import snowflake.snowpark as snowpark
import json

def check_anomalies(session):
    alerts = []

    # ── Read configurable Z-score threshold ──
    try:
        t = session.sql(
            "SELECT SETTING_VALUE FROM APP_CONTEXT.PLATFORM_SETTINGS "
            "WHERE SETTING_KEY = 'ANOMALY_Z_THRESHOLD'"
        ).collect()
        z_threshold = float(t[0][0]) if t else 2.0
    except:
        z_threshold = 2.0

    # ── 1. Account-Level Cost Anomaly ──
    query = f\"\"\"
    WITH daily_credits AS (
        SELECT DATE(START_TIME) as usage_date,
               SUM(CREDITS_USED) as daily_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
        WHERE START_TIME >= DATEADD(day, -30, CURRENT_DATE())
          AND START_TIME < CURRENT_DATE()
        GROUP BY DATE(START_TIME)
    ),
    stats AS (
        SELECT AVG(daily_credits) as avg_credits,
               STDDEV(daily_credits) as stddev_credits
        FROM daily_credits
    ),
    yesterday AS (
        SELECT daily_credits, usage_date FROM daily_credits
        WHERE usage_date = DATEADD(day, -1, CURRENT_DATE())
    )
    SELECT y.daily_credits, s.avg_credits, s.stddev_credits,
           (y.daily_credits - s.avg_credits) / NULLIF(s.stddev_credits, 0) as z_score
    FROM yesterday y, stats s
    WHERE y.daily_credits > (s.avg_credits + ({z_threshold} * s.stddev_credits))
    \"\"\"
    try:
        res = session.sql(query).collect()
        if res:
            row = res[0]
            val = float(row['DAILY_CREDITS'])
            avg = float(row['AVG_CREDITS'])
            z = float(row['Z_SCORE'])
            session.sql(
                f"INSERT INTO APP_ANALYTICS.ANOMALY_LOG "
                f"(METRIC, VALUE, THRESHOLD, Z_SCORE, DETAILS, IS_ALERTED, DIMENSION, DIMENSION_VALUE) "
                f"VALUES ('COST', {val}, {avg}, {z}, "
                f"PARSE_JSON('{{\"msg\": \"Account cost spike\"}}'), TRUE, 'ACCOUNT', 'ACCOUNT')"
            ).collect()
            alerts.append(f"Account Cost Spike: {val:.2f} credits (Z={z:.2f})")
    except:
        pass

    # ── 2. Per-Warehouse Anomaly ──
    wh_query = f\"\"\"
    WITH daily_wh AS (
        SELECT WAREHOUSE_NAME, DATE(START_TIME) as usage_date,
               SUM(CREDITS_USED) as daily_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE START_TIME >= DATEADD(day, -30, CURRENT_DATE())
          AND START_TIME < CURRENT_DATE()
        GROUP BY 1, 2
    ),
    wh_stats AS (
        SELECT WAREHOUSE_NAME,
               AVG(daily_credits) as avg_credits,
               STDDEV(daily_credits) as stddev_credits
        FROM daily_wh GROUP BY 1
    ),
    wh_yesterday AS (
        SELECT WAREHOUSE_NAME, daily_credits FROM daily_wh
        WHERE usage_date = DATEADD(day, -1, CURRENT_DATE())
    )
    SELECT y.WAREHOUSE_NAME, y.daily_credits, s.avg_credits, s.stddev_credits,
           (y.daily_credits - s.avg_credits) / NULLIF(s.stddev_credits, 0) as z_score
    FROM wh_yesterday y JOIN wh_stats s ON y.WAREHOUSE_NAME = s.WAREHOUSE_NAME
    WHERE s.stddev_credits > 0
      AND y.daily_credits > (s.avg_credits + ({z_threshold} * s.stddev_credits))
    \"\"\"
    try:
        wh_res = session.sql(wh_query).collect()
        for row in wh_res:
            wh = row['WAREHOUSE_NAME']
            val = float(row['DAILY_CREDITS'])
            avg = float(row['AVG_CREDITS'])
            z = float(row['Z_SCORE'])
            session.sql(
                f"INSERT INTO APP_ANALYTICS.ANOMALY_LOG "
                f"(METRIC, VALUE, THRESHOLD, Z_SCORE, DETAILS, IS_ALERTED, DIMENSION, DIMENSION_VALUE) "
                f"VALUES ('COST', {val}, {avg}, {z}, "
                f"PARSE_JSON('{{\"warehouse\": \"{wh}\"}}'), TRUE, 'WAREHOUSE', '{wh}')"
            ).collect()
            alerts.append(f"Warehouse {wh}: {val:.2f} credits (Z={z:.2f})")
    except:
        pass

    # ── 3. Per-User Anomaly ──
    user_query = f\"\"\"
    WITH daily_user AS (
        SELECT USER_NAME, DATE(START_TIME) as usage_date,
               SUM(CREDITS_USED_CLOUD_SERVICES) as daily_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD(day, -30, CURRENT_DATE())
          AND START_TIME < CURRENT_DATE()
        GROUP BY 1, 2
        HAVING SUM(CREDITS_USED_CLOUD_SERVICES) > 0
    ),
    user_stats AS (
        SELECT USER_NAME, AVG(daily_credits) as avg_credits,
               STDDEV(daily_credits) as stddev_credits
        FROM daily_user GROUP BY 1
    ),
    user_yesterday AS (
        SELECT USER_NAME, daily_credits FROM daily_user
        WHERE usage_date = DATEADD(day, -1, CURRENT_DATE())
    )
    SELECT y.USER_NAME, y.daily_credits, s.avg_credits, s.stddev_credits,
           (y.daily_credits - s.avg_credits) / NULLIF(s.stddev_credits, 0) as z_score
    FROM user_yesterday y JOIN user_stats s ON y.USER_NAME = s.USER_NAME
    WHERE s.stddev_credits > 0
      AND y.daily_credits > (s.avg_credits + ({z_threshold} * s.stddev_credits))
    \"\"\"
    try:
        u_res = session.sql(user_query).collect()
        for row in u_res:
            uname = row['USER_NAME']
            val = float(row['DAILY_CREDITS'])
            avg = float(row['AVG_CREDITS'])
            z = float(row['Z_SCORE'])
            session.sql(
                f"INSERT INTO APP_ANALYTICS.ANOMALY_LOG "
                f"(METRIC, VALUE, THRESHOLD, Z_SCORE, DETAILS, IS_ALERTED, DIMENSION, DIMENSION_VALUE) "
                f"VALUES ('COST', {val}, {avg}, {z}, "
                f"PARSE_JSON('{{\"user\": \"{uname}\"}}'), TRUE, 'USER', '{uname}')"
            ).collect()
            alerts.append(f"User {uname}: {val:.4f} credits (Z={z:.2f})")
    except:
        pass

    # ── 4. Send Notifications via configured channels ──
    if alerts:
        alert_text = "; ".join(alerts).replace("'", "''")[:3000]
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
                            f"'SnowOps Anomaly Alert', '{alert_text}')"
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

    return "Anomalies: " + ", ".join(alerts) if alerts else "No anomalies found."
            $$;
            """
            self.client.execute_query(sp_sql)

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
            logger.error(f"Deploy monitor error: {e}")
            return False
