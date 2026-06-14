"""
Automation Engine — Snowflake-native background orchestration.

Key insight: Streamlit runs only when the user has the app open, but Snowflake
Tasks, Alerts, and Notification Integrations run SERVER-SIDE on Snowflake
compute — they execute on schedule even when the app is closed.

This engine lets users configure:
  1. Scheduled Tasks (cron-based SQL/SP execution)
  2. Native Snowflake Alerts (condition → action)
  3. Notification Integrations (Email, Slack, Teams, PagerDuty webhooks)
  4. Task-based agent scheduling (run AI agents on a cron)
  5. Quality gate watchdogs (scheduled quality checks with alerts)
  6. Cost watchdogs (credit budget enforcement)
"""
import streamlit as st
import pandas as pd
import json, uuid
from datetime import datetime
from typing import Optional, List, Dict


class AutomationEngine:
    """Control plane for Snowflake-native background automation."""

    def __init__(self, client):
        self.client = client
        self.session = client.session
        self._app_db = None

    @property
    def app_db(self):
        if not self._app_db:
            self._app_db = self.client.get_app_db() if hasattr(self.client, 'get_app_db') else 'SNOWFLAKE_OPS_INTELLIGENCE'
        return self._app_db

    def ensure_tables(self):
        ddls = [
            f"""CREATE TABLE IF NOT EXISTS {self.app_db}.APP_CONTEXT.AUTOMATION_JOBS (
                JOB_ID VARCHAR(50) PRIMARY KEY, JOB_NAME VARCHAR(255),
                JOB_TYPE VARCHAR(50), DESCRIPTION VARCHAR(2000),
                SCHEDULE VARCHAR(255), CONFIG VARIANT,
                SNOWFLAKE_OBJECT_NAME VARCHAR(500),
                STATUS VARCHAR(20) DEFAULT 'CREATED',
                LAST_RUN_AT TIMESTAMP_NTZ, LAST_STATUS VARCHAR(20),
                CREATED_BY VARCHAR(255), CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP())""",
            f"""CREATE TABLE IF NOT EXISTS {self.app_db}.APP_CONTEXT.NOTIFICATION_CONFIGS (
                CONFIG_ID VARCHAR(50) PRIMARY KEY, CHANNEL_TYPE VARCHAR(50),
                CHANNEL_NAME VARCHAR(255), CONFIG VARIANT,
                INTEGRATION_NAME VARCHAR(255),
                IS_ACTIVE BOOLEAN DEFAULT TRUE,
                CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP())""",
        ]
        for d in ddls:
            try: self.client.execute_query(d, log=False)
            except: pass

    # ════════════════════════════════════════════════════════════════
    # Notification Integrations
    # ════════════════════════════════════════════════════════════════
    def create_email_notification(self, name, allowed_recipients):
        """Create an email notification integration. Requires ACCOUNTADMIN."""
        recipients = ", ".join([f"'{r.strip()}'" for r in allowed_recipients])
        sql = f"""CREATE OR REPLACE NOTIFICATION INTEGRATION {name}
            TYPE=EMAIL ENABLED=TRUE
            ALLOWED_RECIPIENTS=({recipients})"""
        try:
            self.client.execute_query(sql)
            self._save_notification_config(name, "EMAIL", name, {"recipients": allowed_recipients})
            return {"status": "SUCCESS", "integration": name}
        except Exception as e:
            return {"status": "ERROR", "error": str(e)}

    def create_webhook_notification(self, name, webhook_url, webhook_type="SLACK"):
        """Create a webhook notification integration (Slack, Teams, PagerDuty)."""
        sql = f"""CREATE OR REPLACE NOTIFICATION INTEGRATION {name}
            TYPE=WEBHOOK ENABLED=TRUE
            WEBHOOK_URL='{webhook_url}'
            WEBHOOK_BODY_TEMPLATE='{{\"text\": \"SNOWFLAKE_WEBHOOK_MESSAGE\"}}'"""
        try:
            self.client.execute_query(sql)
            self._save_notification_config(name, webhook_type, name, {"url": webhook_url[:50]+"..."})
            return {"status": "SUCCESS", "integration": name}
        except Exception as e:
            return {"status": "ERROR", "error": str(e)}

    def send_test_email(self, integration_name, recipient, subject="SnowOps Test", body="This is a test notification from SnowOps Intelligence."):
        try:
            self.client.execute_query(f"CALL SYSTEM$SEND_EMAIL('{integration_name}', '{recipient}', '{subject}', '{body}')")
            return {"status": "SUCCESS"}
        except Exception as e:
            return {"status": "ERROR", "error": str(e)}

    def list_notification_integrations(self):
        try: return self.client.execute_query("SHOW NOTIFICATION INTEGRATIONS", log=False)
        except: return pd.DataFrame()

    def _save_notification_config(self, name, channel_type, integration_name, config):
        cid = str(uuid.uuid4())[:8]
        cfg = json.dumps(config, default=str).replace("'","''")
        try:
            self.client.execute_query(f"""INSERT INTO {self.app_db}.APP_CONTEXT.NOTIFICATION_CONFIGS
                (CONFIG_ID, CHANNEL_TYPE, CHANNEL_NAME, CONFIG, INTEGRATION_NAME)
                VALUES('{cid}','{channel_type}','{name}',PARSE_JSON('{cfg}'),'{integration_name}')""")
        except: pass

    # ════════════════════════════════════════════════════════════════
    # Snowflake Native Alerts
    # ════════════════════════════════════════════════════════════════
    def create_snowflake_alert(self, name, warehouse, schedule, condition_sql, action_sql, database=None, schema=None):
        """Create a native Snowflake ALERT object that runs server-side."""
        fn = f"{database}.{schema}.{name}" if database and schema else name
        sql = f"""CREATE OR REPLACE ALERT {fn}
            WAREHOUSE = {warehouse}
            SCHEDULE = '{schedule}'
            IF (EXISTS ({condition_sql}))
            THEN {action_sql}"""
        try:
            self.client.execute_query(sql)
            self.client.execute_query(f"ALTER ALERT {fn} RESUME")
            return {"status": "SUCCESS", "alert": fn}
        except Exception as e:
            return {"status": "ERROR", "error": str(e)}

    def create_cost_watchdog(self, name, warehouse, credit_limit, notification_integration, recipient_email, check_interval="60 MINUTE"):
        """Scheduled alert that monitors credit consumption and sends email when limit is exceeded."""
        condition = f"""SELECT 1 FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
            WHERE USAGE_DATE = CURRENT_DATE() AND CREDITS_USED > {credit_limit}"""
        action = f"""CALL SYSTEM$SEND_EMAIL('{notification_integration}', '{recipient_email}',
            'SnowOps Alert: Daily credit limit exceeded',
            'Credit usage has exceeded {credit_limit} credits today. Please review warehouse activity.')"""
        return self.create_snowflake_alert(name, warehouse, check_interval, condition, action)

    def create_quality_watchdog(self, name, warehouse, table_name, max_null_pct, notification_integration, recipient_email, check_interval="60 MINUTE"):
        """Scheduled alert that monitors data quality and sends notification on failure."""
        condition = f"""SELECT 1 FROM (
            SELECT COUNT_IF(c IS NULL) * 100.0 / NULLIF(COUNT(*),0) AS null_pct
            FROM {table_name}) WHERE null_pct > {max_null_pct}"""
        action = f"""CALL SYSTEM$SEND_EMAIL('{notification_integration}', '{recipient_email}',
            'SnowOps Alert: Data quality issue on {table_name}',
            'Null percentage on {table_name} exceeds {max_null_pct}%. Investigate immediately.')"""
        return self.create_snowflake_alert(name, warehouse, check_interval, condition, action)

    def create_failure_watchdog(self, name, warehouse, task_name, notification_integration, recipient_email, check_interval="15 MINUTE"):
        """Scheduled alert that monitors task failures and notifies."""
        condition = f"""SELECT 1 FROM TABLE(INFORMATION_SCHEMA.TASK_HISTORY(TASK_NAME=>'{task_name}'))
            WHERE STATE='FAILED' AND COMPLETED_TIME > DATEADD(MINUTE, -20, CURRENT_TIMESTAMP())"""
        action = f"""CALL SYSTEM$SEND_EMAIL('{notification_integration}', '{recipient_email}',
            'SnowOps Alert: Task {task_name} has FAILED',
            'Task {task_name} failed. Check the pipeline debugger for details.')"""
        return self.create_snowflake_alert(name, warehouse, check_interval, condition, action)

    def list_alerts(self):
        try: return self.client.execute_query("SHOW ALERTS", log=False)
        except: return pd.DataFrame()

    def suspend_alert(self, name):
        try: self.client.execute_query(f"ALTER ALERT {name} SUSPEND"); return {"status":"SUCCESS"}
        except Exception as e: return {"status":"ERROR","error":str(e)}

    def resume_alert(self, name):
        try: self.client.execute_query(f"ALTER ALERT {name} RESUME"); return {"status":"SUCCESS"}
        except Exception as e: return {"status":"ERROR","error":str(e)}

    def drop_alert(self, name):
        try: self.client.execute_query(f"DROP ALERT IF EXISTS {name}"); return {"status":"SUCCESS"}
        except Exception as e: return {"status":"ERROR","error":str(e)}

    # ════════════════════════════════════════════════════════════════
    # Scheduled Procedures (wrap complex logic as a Snowflake Task)
    # ════════════════════════════════════════════════════════════════
    def create_scheduled_procedure(self, proc_name, proc_body, schedule, warehouse, database=None, schema=None):
        """Create a stored procedure and a Task that calls it on schedule."""
        db = database or ""; sch = schema or "PUBLIC"
        fn = f"{db}.{sch}.{proc_name}" if db else proc_name
        task_name = f"TASK_SCHED_{proc_name.upper()}"
        task_fn = f"{db}.{sch}.{task_name}" if db else task_name
        results = []
        # Create the procedure
        try:
            self.client.execute_query(f"""CREATE OR REPLACE PROCEDURE {fn}()
                RETURNS VARCHAR LANGUAGE SQL EXECUTE AS CALLER AS
                BEGIN
                    {proc_body}
                    RETURN 'SUCCESS';
                END""")
            results.append({"step": "Create Procedure", "status": "SUCCESS"})
        except Exception as e:
            return {"status": "ERROR", "error": f"Procedure creation failed: {e}"}
        # Create the task
        try:
            self.client.execute_query(f"""CREATE OR REPLACE TASK {task_fn}
                WAREHOUSE = {warehouse} SCHEDULE = '{schedule}'
                AS CALL {fn}()""")
            self.client.execute_query(f"ALTER TASK {task_fn} RESUME")
            results.append({"step": "Create & Resume Task", "status": "SUCCESS"})
        except Exception as e:
            results.append({"step": "Create Task", "status": "ERROR", "error": str(e)})
        return {"status": "SUCCESS", "results": results}

    # ════════════════════════════════════════════════════════════════
    # Error/Success Integration on Task Graphs
    # ════════════════════════════════════════════════════════════════
    def attach_error_notification(self, task_name, notification_integration):
        """Attach a notification integration to a task's error handler."""
        try:
            self.client.execute_query(f"ALTER TASK {task_name} SET ERROR_INTEGRATION = {notification_integration}")
            return {"status": "SUCCESS"}
        except Exception as e:
            return {"status": "ERROR", "error": str(e)}

    def attach_success_notification(self, task_name, notification_integration):
        """Attach a notification integration to a task's success handler (root task only)."""
        try:
            self.client.execute_query(f"ALTER TASK {task_name} SET SUCCESS_INTEGRATION = {notification_integration}")
            return {"status": "SUCCESS"}
        except Exception as e:
            return {"status": "ERROR", "error": str(e)}

    # ════════════════════════════════════════════════════════════════
    # Resource Monitors
    # ════════════════════════════════════════════════════════════════
    def create_resource_monitor(self, name, credit_quota, warehouses=None,
                                 notify_75=True, suspend_90=True, suspend_100=True):
        """Create a resource monitor with tiered alerts."""
        triggers = []
        if notify_75: triggers.append("ON 75 PERCENT DO NOTIFY")
        if suspend_90: triggers.append("ON 90 PERCENT DO SUSPEND")
        if suspend_100: triggers.append("ON 100 PERCENT DO SUSPEND_IMMEDIATE")
        trigger_str = "\n    TRIGGERS ".join(triggers)
        sql = f"""CREATE OR REPLACE RESOURCE MONITOR {name}
            WITH CREDIT_QUOTA = {credit_quota}
            FREQUENCY = MONTHLY START_TIMESTAMP = IMMEDIATELY
            TRIGGERS {trigger_str}"""
        try:
            self.client.execute_query(sql)
            if warehouses:
                block_parts = ["BEGIN"]
                for wh in warehouses:
                    block_parts.append(f"    BEGIN ALTER WAREHOUSE {wh} SET RESOURCE_MONITOR = {name}; EXCEPTION WHEN OTHER THEN NULL; END;")
                block_parts.append("END;")

                block_sql = "\n".join(block_parts)
                try:
                    self.client.execute_query(block_sql)
                except Exception:
                    pass
            return {"status": "SUCCESS", "monitor": name}
        except Exception as e:
            return {"status": "ERROR", "error": str(e)}

    def list_resource_monitors(self):
        try: return self.client.execute_query("SHOW RESOURCE MONITORS", log=False)
        except: return pd.DataFrame()

    # ════════════════════════════════════════════════════════════════
    # Job Registry (saved in metadata)
    # ════════════════════════════════════════════════════════════════
    def register_job(self, name, job_type, schedule, config, sf_object_name="", description=""):
        jid = str(uuid.uuid4())[:8]
        cfg = json.dumps(config, default=str).replace("'","''")
        s = lambda x: x.replace("'","''") if x else ""
        self.client.execute_query(f"""INSERT INTO {self.app_db}.APP_CONTEXT.AUTOMATION_JOBS
            (JOB_ID,JOB_NAME,JOB_TYPE,DESCRIPTION,SCHEDULE,CONFIG,SNOWFLAKE_OBJECT_NAME,STATUS,CREATED_BY)
            VALUES('{jid}','{s(name)}','{s(job_type)}','{s(description)}','{s(schedule)}',
                   PARSE_JSON('{cfg}'),'{s(sf_object_name)}','ACTIVE',CURRENT_USER())""")
        return jid

    def list_jobs(self):
        try: return self.client.execute_query(f"SELECT * FROM {self.app_db}.APP_CONTEXT.AUTOMATION_JOBS ORDER BY CREATED_AT DESC", log=False)
        except: return pd.DataFrame()

    def delete_job(self, job_id):
        try:
            job = self.client.execute_query(f"SELECT SNOWFLAKE_OBJECT_NAME, JOB_TYPE FROM {self.app_db}.APP_CONTEXT.AUTOMATION_JOBS WHERE JOB_ID='{job_id}'", log=False)
            if not job.empty:
                obj = job.iloc[0].get('SNOWFLAKE_OBJECT_NAME','')
                jtype = job.iloc[0].get('JOB_TYPE','')
                if obj:
                    if jtype == 'ALERT': self.drop_alert(obj)
                    elif jtype == 'TASK':
                        try: self.client.execute_query(f"DROP TASK IF EXISTS {obj}")
                        except: pass
            self.client.execute_query(f"DELETE FROM {self.app_db}.APP_CONTEXT.AUTOMATION_JOBS WHERE JOB_ID='{job_id}'")
        except: pass


def get_automation_engine(client=None):
    if client is None and "snowflake_client" in st.session_state: client = st.session_state.snowflake_client
    if client is None: return None
    if 'automation_engine' not in st.session_state:
        engine = AutomationEngine(client); engine.ensure_tables(); st.session_state.automation_engine = engine
    return st.session_state.automation_engine
