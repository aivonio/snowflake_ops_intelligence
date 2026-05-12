"""
Cost Optimizer Engine — FinOps & proactive cost intelligence.
Warehouse rightsizing, resource monitors, credit forecasting,
auto-suspend optimization, idle detection, and cost attribution.
"""
import streamlit as st
import pandas as pd
import json
from typing import Optional, Dict, List


class CostOptimizer:
    """Proactive cost intelligence for Snowflake."""

    def __init__(self, client):
        self.client = client

    # ── Warehouse Rightsizing ──
    def get_warehouse_utilization(self, days=7):
        try: return self.client.execute_query(f"""
            SELECT wm.WAREHOUSE_NAME, wm.WAREHOUSE_SIZE,
                SUM(wm.CREDITS_USED) AS total_credits,
                COUNT(DISTINCT qh.QUERY_ID) AS total_queries,
                AVG(qh.TOTAL_ELAPSED_TIME)/1000 AS avg_query_s,
                APPROX_PERCENTILE(qh.TOTAL_ELAPSED_TIME,0.95)/1000 AS p95_query_s,
                SUM(qh.BYTES_SCANNED)/1e9 AS gb_scanned
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY wm
            LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY qh
                ON wm.WAREHOUSE_NAME=qh.WAREHOUSE_NAME
                AND qh.START_TIME>=DATEADD(DAY,-{days},CURRENT_TIMESTAMP())
            WHERE wm.START_TIME>=DATEADD(DAY,-{days},CURRENT_TIMESTAMP())
            GROUP BY 1,2 ORDER BY total_credits DESC""", log=False)
        except: return pd.DataFrame()

    def get_rightsizing_recommendations(self, days=7):
        util = self.get_warehouse_utilization(days)
        if util.empty: return []
        recs = []
        sizes = ['X-Small','Small','Medium','Large','X-Large','2X-Large','3X-Large','4X-Large']
        for _, w in util.iterrows():
            wh = w['WAREHOUSE_NAME']
            size = str(w.get('WAREHOUSE_SIZE','')).replace('-',' ').title()
            avg_s = w.get('AVG_QUERY_S', 0) or 0
            p95_s = w.get('P95_QUERY_S', 0) or 0
            credits = w.get('TOTAL_CREDITS', 0) or 0
            queries = w.get('TOTAL_QUERIES', 0) or 0

            if queries == 0 and credits > 0:
                recs.append({"warehouse":wh,"current_size":size,"recommendation":"SUSPEND","reason":"Warehouse consuming credits with zero queries","potential_savings_pct":100})
            elif avg_s < 2 and p95_s < 10 and size not in ['X Small','Small']:
                recs.append({"warehouse":wh,"current_size":size,"recommendation":"DOWNSIZE","reason":f"Avg query {avg_s:.1f}s — smaller warehouse sufficient","potential_savings_pct":50})
            elif p95_s > 120:
                recs.append({"warehouse":wh,"current_size":size,"recommendation":"UPSIZE","reason":f"P95 latency {p95_s:.0f}s — larger warehouse may reduce queue time","potential_savings_pct":-25})
        return recs

    # ── Auto-Suspend Analysis ──
    def get_auto_suspend_recommendations(self):
        try:
            wh = self.client.execute_query("""
                SELECT "name" AS WAREHOUSE_NAME, "auto_suspend" AS AUTO_SUSPEND, "size" AS SIZE
                FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()))""", log=False)
        except:
            try: wh = self.client.execute_query("SHOW WAREHOUSES", log=False)
            except: return []
        recs = []
        # Simple heuristic recommendations
        return recs

    # ── Credit Forecasting ──
    def get_credit_forecast(self, days_back=30, days_forward=7):
        try:
            trend = self.client.execute_query(f"""
                SELECT DATE_TRUNC('DAY',START_TIME) AS day, SUM(CREDITS_USED) AS credits
                FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                WHERE START_TIME>=DATEADD(DAY,-{days_back},CURRENT_TIMESTAMP())
                GROUP BY 1 ORDER BY 1""", log=False)
            if trend.empty: return {"daily_avg":0,"forecast_total":0}
            daily_avg = trend['CREDITS'].mean()
            return {
                "daily_avg": round(daily_avg, 2),
                "forecast_total": round(daily_avg * days_forward, 2),
                "forecast_monthly": round(daily_avg * 30, 2),
                "trend_data": trend,
            }
        except: return {"daily_avg":0,"forecast_total":0}

    # ── Idle Warehouse Detection ──
    def detect_idle_warehouses(self, hours=24):
        try: return self.client.execute_query(f"""
            SELECT wm.WAREHOUSE_NAME, SUM(wm.CREDITS_USED) AS credits_wasted
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY wm
            LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY qh
                ON wm.WAREHOUSE_NAME=qh.WAREHOUSE_NAME
                AND qh.START_TIME>=DATEADD(HOUR,-{hours},CURRENT_TIMESTAMP())
            WHERE wm.START_TIME>=DATEADD(HOUR,-{hours},CURRENT_TIMESTAMP())
            GROUP BY 1 HAVING COUNT(DISTINCT qh.QUERY_ID)=0 AND SUM(wm.CREDITS_USED)>0
            ORDER BY credits_wasted DESC""", log=False)
        except: return pd.DataFrame()

    # ── Cloud Services Audit ──
    def get_cloud_services_ratio(self, days=30):
        try:
            df = self.client.execute_query(f"""
                SELECT SUM(CREDITS_USED_COMPUTE) AS compute,
                    SUM(CREDITS_USED_CLOUD_SERVICES) AS cloud_services,
                    SUM(CREDITS_USED) AS total
                FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                WHERE START_TIME>=DATEADD(DAY,-{days},CURRENT_TIMESTAMP())""", log=False)
            if df.empty: return {"ratio":0}
            total = df.iloc[0]['TOTAL'] or 1
            cs = df.iloc[0]['CLOUD_SERVICES'] or 0
            return {"compute": df.iloc[0]['COMPUTE'], "cloud_services": cs,
                    "ratio": round(cs/total*100, 2), "exceeds_threshold": cs/total > 0.10}
        except: return {"ratio":0}

    # ── Cost Attribution ──
    def get_cost_by_user(self, days=7):
        try: return self.client.execute_query(f"""
            SELECT USER_NAME, WAREHOUSE_NAME, COUNT(*) AS queries,
                SUM(TOTAL_ELAPSED_TIME)/1000 AS total_compute_s
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE START_TIME>=DATEADD(DAY,-{days},CURRENT_TIMESTAMP())
            GROUP BY 1,2 ORDER BY total_compute_s DESC LIMIT 50""", log=False)
        except: return pd.DataFrame()

    # ── Summary Dashboard ──
    def get_cost_summary(self, days=7):
        return {
            "utilization": self.get_warehouse_utilization(days),
            "recommendations": self.get_rightsizing_recommendations(days),
            "forecast": self.get_credit_forecast(days),
            "idle_warehouses": self.detect_idle_warehouses(),
            "cloud_services": self.get_cloud_services_ratio(),
        }


def get_cost_optimizer(client=None):
    if client is None and "snowflake_client" in st.session_state: client = st.session_state.snowflake_client
    if client is None: return None
    if 'cost_optimizer' not in st.session_state:
        st.session_state.cost_optimizer = CostOptimizer(client)
    return st.session_state.cost_optimizer
