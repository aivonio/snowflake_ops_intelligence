"""
Observability Engine — Four Golden Signals + SLO/SLI tracking.
Monitors latency, traffic, errors, saturation from ACCOUNT_USAGE views.
Includes alert rules, trend analysis, and AI root cause analysis.
"""
import streamlit as st
import pandas as pd
import json, uuid
from datetime import datetime
from typing import Optional, Dict, List


class ObservabilityEngine:
    """Unified observability: Four Golden Signals, SLOs, alerts."""

    def __init__(self, client):
        self.client = client
        self._app_db = None

    @property
    def app_db(self):
        if not self._app_db:
            self._app_db = self.client.get_app_db() if hasattr(self.client, 'get_app_db') else 'SNOWFLAKE_OPS_INTELLIGENCE'
        return self._app_db

    def ensure_tables(self):
        ddls = [
            f"""CREATE TABLE IF NOT EXISTS {self.app_db}.APP_CONTEXT.OBSERVABILITY_METRICS (
                METRIC_ID VARCHAR(50) PRIMARY KEY, METRIC_NAME VARCHAR(255),
                METRIC_TYPE VARCHAR(50), METRIC_VALUE FLOAT,
                DIMENSIONS VARIANT, COLLECTED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP())""",
            f"""CREATE TABLE IF NOT EXISTS {self.app_db}.APP_CONTEXT.ALERT_RULES (
                ALERT_ID VARCHAR(50) PRIMARY KEY, ALERT_NAME VARCHAR(255),
                METRIC_QUERY VARCHAR(5000), THRESHOLD FLOAT,
                COMPARISON VARCHAR(10) DEFAULT 'gt', SEVERITY VARCHAR(20) DEFAULT 'WARNING',
                IS_ACTIVE BOOLEAN DEFAULT TRUE, COOLDOWN_MINUTES NUMBER DEFAULT 60,
                LAST_TRIGGERED_AT TIMESTAMP_NTZ,
                CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP())""",
            f"""CREATE TABLE IF NOT EXISTS {self.app_db}.APP_CONTEXT.ALERT_HISTORY (
                HISTORY_ID VARCHAR(50) PRIMARY KEY, ALERT_ID VARCHAR(50),
                ALERT_NAME VARCHAR(255), METRIC_VALUE FLOAT,
                SEVERITY VARCHAR(20), MESSAGE VARCHAR(2000),
                ACKNOWLEDGED BOOLEAN DEFAULT FALSE,
                TRIGGERED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP())""",
        ]
        for d in ddls:
            try: self.client.execute_query(d, log=False)
            except: pass

    # ── Four Golden Signals ──
    def get_latency(self, hours=24):
        try: return self.client.execute_query(f"""
            SELECT WAREHOUSE_NAME,
                APPROX_PERCENTILE(TOTAL_ELAPSED_TIME,0.5)/1000 AS p50_s,
                APPROX_PERCENTILE(TOTAL_ELAPSED_TIME,0.95)/1000 AS p95_s,
                APPROX_PERCENTILE(TOTAL_ELAPSED_TIME,0.99)/1000 AS p99_s,
                COUNT(*) AS query_count
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE START_TIME>=DATEADD(HOUR,-{hours},CURRENT_TIMESTAMP()) AND TOTAL_ELAPSED_TIME>0
            GROUP BY 1 ORDER BY p95_s DESC""", log=False)
        except: return pd.DataFrame()

    def get_traffic(self, hours=24):
        try: return self.client.execute_query(f"""
            SELECT DATE_TRUNC('HOUR',START_TIME) AS hour,
                COUNT(*) AS queries, COUNT(DISTINCT USER_NAME) AS users,
                COUNT(DISTINCT WAREHOUSE_NAME) AS warehouses
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE START_TIME>=DATEADD(HOUR,-{hours},CURRENT_TIMESTAMP())
            GROUP BY 1 ORDER BY 1""", log=False)
        except: return pd.DataFrame()

    def get_errors(self, hours=24):
        try: return self.client.execute_query(f"""
            SELECT ERROR_CODE, ERROR_MESSAGE, WAREHOUSE_NAME, USER_NAME, COUNT(*) AS count
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE START_TIME>=DATEADD(HOUR,-{hours},CURRENT_TIMESTAMP()) AND EXECUTION_STATUS='FAIL'
            GROUP BY 1,2,3,4 ORDER BY count DESC LIMIT 50""", log=False)
        except: return pd.DataFrame()

    def get_saturation(self, days=7):
        try: return self.client.execute_query(f"""
            SELECT WAREHOUSE_NAME,
                SUM(CREDITS_USED) AS total_credits,
                AVG(CREDITS_USED) AS avg_daily_credits,
                MAX(CREDITS_USED) AS peak_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
            WHERE START_TIME>=DATEADD(DAY,-{days},CURRENT_TIMESTAMP())
            GROUP BY 1 ORDER BY total_credits DESC""", log=False)
        except: return pd.DataFrame()

    def get_error_rate(self, hours=24):
        try:
            df = self.client.execute_query(f"""
                SELECT COUNT(*) AS total,
                    SUM(CASE WHEN EXECUTION_STATUS='FAIL' THEN 1 ELSE 0 END) AS failed
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE START_TIME>=DATEADD(HOUR,-{hours},CURRENT_TIMESTAMP())""", log=False)
            if df.empty: return 0
            total = df.iloc[0]['TOTAL'] or 1
            return round((df.iloc[0]['FAILED'] or 0) / total * 100, 2)
        except: return 0

    # ── Dashboard Summary ──
    def get_health_summary(self, hours=24):
        return {
            "error_rate": self.get_error_rate(hours),
            "latency": self.get_latency(hours),
            "traffic": self.get_traffic(hours),
            "saturation": self.get_saturation(7),
            "errors": self.get_errors(hours),
        }

    # ── Alert Rules ──
    def create_alert(self, name, metric_query, threshold, comparison='gt', severity='WARNING', cooldown=60):
        aid = str(uuid.uuid4())[:8]
        s = lambda x: x.replace("'","''") if x else ""
        self.client.execute_query(f"""INSERT INTO {self.app_db}.APP_CONTEXT.ALERT_RULES
            (ALERT_ID,ALERT_NAME,METRIC_QUERY,THRESHOLD,COMPARISON,SEVERITY,COOLDOWN_MINUTES)
            VALUES('{aid}','{s(name)}','{s(metric_query)}',{threshold},'{comparison}','{severity}',{cooldown})""")
        return aid

    def list_alerts(self):
        return self.client.execute_query(f"SELECT * FROM {self.app_db}.APP_CONTEXT.ALERT_RULES ORDER BY CREATED_AT DESC")

    def check_alerts(self):
        alerts = self.list_alerts()
        if alerts.empty: return []
        triggered = []
        for _, alert in alerts.iterrows():
            if not alert.get('IS_ACTIVE', True): continue
            try:
                r = self.client.execute_query(alert['METRIC_QUERY'], log=False)
                if r.empty: continue
                val = float(r.iloc[0, 0])
                threshold = float(alert['THRESHOLD'])
                comp = alert.get('COMPARISON', 'gt')
                fire = (comp == 'gt' and val > threshold) or (comp == 'lt' and val < threshold) or (comp == 'eq' and val == threshold)
                if fire:
                    hid = str(uuid.uuid4())[:8]
                    msg = f"{alert['ALERT_NAME']}: value={val}, threshold={threshold}"
                    self.client.execute_query(f"""INSERT INTO {self.app_db}.APP_CONTEXT.ALERT_HISTORY
                        (HISTORY_ID,ALERT_ID,ALERT_NAME,METRIC_VALUE,SEVERITY,MESSAGE)
                        VALUES('{hid}','{alert['ALERT_ID']}','{alert['ALERT_NAME']}',{val},'{alert['SEVERITY']}','{msg[:500]}')""", log=False)
                    triggered.append({"alert": alert['ALERT_NAME'], "value": val, "severity": alert['SEVERITY']})
            except: pass
        return triggered

    def get_alert_history(self, limit=50):
        return self.client.execute_query(f"SELECT * FROM {self.app_db}.APP_CONTEXT.ALERT_HISTORY ORDER BY TRIGGERED_AT DESC LIMIT {limit}")

    # ── Trend Analysis ──
    def get_credit_trend(self, days=30):
        try: return self.client.execute_query(f"""
            SELECT DATE_TRUNC('DAY',START_TIME) AS day, SUM(CREDITS_USED) AS credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
            WHERE START_TIME>=DATEADD(DAY,-{days},CURRENT_TIMESTAMP())
            GROUP BY 1 ORDER BY 1""", log=False)
        except: return pd.DataFrame()

    def get_query_volume_trend(self, days=30):
        try: return self.client.execute_query(f"""
            SELECT DATE_TRUNC('DAY',START_TIME) AS day, COUNT(*) AS queries,
                AVG(TOTAL_ELAPSED_TIME)/1000 AS avg_duration_s
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE START_TIME>=DATEADD(DAY,-{days},CURRENT_TIMESTAMP())
            GROUP BY 1 ORDER BY 1""", log=False)
        except: return pd.DataFrame()


def get_observability_engine(client=None):
    if client is None and "snowflake_client" in st.session_state: client = st.session_state.snowflake_client
    if client is None: return None
    if 'obs_engine' not in st.session_state:
        engine = ObservabilityEngine(client); engine.ensure_tables(); st.session_state.obs_engine = engine
    return st.session_state.obs_engine
