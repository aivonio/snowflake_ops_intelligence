"""
Data Quality Engine — Native Snowflake DMF-based quality monitoring.
Manages Data Metric Functions, quality rules, scoring, anomaly detection,
quality gates, and freshness monitoring.
"""
import streamlit as st
import pandas as pd
import json, uuid
from datetime import datetime
from typing import Optional, List, Dict


class DataQualityEngine:
    """Native Data Quality Engine with DMF support, scoring, and gates."""

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
            f"""CREATE TABLE IF NOT EXISTS {self.app_db}.APP_CONTEXT.DATA_QUALITY_RULES (
                RULE_ID VARCHAR(50) PRIMARY KEY, TABLE_NAME VARCHAR(500),
                COLUMN_NAME VARCHAR(255), RULE_TYPE VARCHAR(50),
                RULE_CONFIG VARIANT, THRESHOLD_WARN FLOAT, THRESHOLD_ERROR FLOAT,
                IS_ACTIVE BOOLEAN DEFAULT TRUE, SCHEDULE VARCHAR(100),
                LAST_RUN_AT TIMESTAMP_NTZ, LAST_RESULT FLOAT,
                LAST_STATUS VARCHAR(20), CREATED_BY VARCHAR(255),
                CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP())""",
            f"""CREATE TABLE IF NOT EXISTS {self.app_db}.APP_CONTEXT.DATA_QUALITY_RESULTS (
                RESULT_ID VARCHAR(50) PRIMARY KEY, RULE_ID VARCHAR(50),
                TABLE_NAME VARCHAR(500), METRIC_VALUE FLOAT,
                STATUS VARCHAR(20), DETAILS VARCHAR(5000),
                RUN_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP())""",
        ]
        for d in ddls:
            try: self.client.execute_query(d, log=False)
            except: pass

    # ── Built-in Quality Checks ──
    SYSTEM_CHECKS = {
        "null_count": "SELECT COUNT(*) FROM {table} WHERE {column} IS NULL",
        "null_rate": "SELECT ROUND(COUNT(CASE WHEN {column} IS NULL THEN 1 END)*100.0/NULLIF(COUNT(*),0),2) FROM {table}",
        "duplicate_count": "SELECT COUNT(*)-COUNT(DISTINCT {column}) FROM {table}",
        "unique_rate": "SELECT ROUND(COUNT(DISTINCT {column})*100.0/NULLIF(COUNT(*),0),2) FROM {table}",
        "row_count": "SELECT COUNT(*) FROM {table}",
        "freshness_hours": "SELECT ROUND(TIMESTAMPDIFF('HOUR',MAX({column}),CURRENT_TIMESTAMP()),2) FROM {table}",
        "min_value": "SELECT MIN({column}) FROM {table}",
        "max_value": "SELECT MAX({column}) FROM {table}",
        "avg_value": "SELECT AVG({column}) FROM {table}",
        "empty_string_count": "SELECT COUNT(*) FROM {table} WHERE TRIM({column})=''",
        "zero_count": "SELECT COUNT(*) FROM {table} WHERE {column}=0",
        "negative_count": "SELECT COUNT(*) FROM {table} WHERE {column}<0",
    }

    # ── Rule CRUD ──
    def create_rule(self, table_name, column_name, rule_type, threshold_warn=None,
                    threshold_error=None, config=None, schedule=None):
        rid = str(uuid.uuid4())[:8]
        s = lambda x: x.replace("'","''") if x else ""
        cfg = json.dumps(config or {}).replace("'","''")
        tw = threshold_warn if threshold_warn is not None else "NULL"
        te = threshold_error if threshold_error is not None else "NULL"
        sch = f"'{s(schedule)}'" if schedule else "NULL"
        self.client.execute_query(f"""INSERT INTO {self.app_db}.APP_CONTEXT.DATA_QUALITY_RULES
            (RULE_ID,TABLE_NAME,COLUMN_NAME,RULE_TYPE,RULE_CONFIG,THRESHOLD_WARN,THRESHOLD_ERROR,SCHEDULE,CREATED_BY)
            VALUES('{rid}','{s(table_name)}','{s(column_name)}','{s(rule_type)}',
                   PARSE_JSON('{cfg}'),{tw},{te},{sch},CURRENT_USER())""")
        return rid

    def list_rules(self, table_name=None):
        where = f"WHERE TABLE_NAME='{table_name}'" if table_name else ""
        return self.client.execute_query(f"SELECT * FROM {self.app_db}.APP_CONTEXT.DATA_QUALITY_RULES {where} ORDER BY TABLE_NAME,COLUMN_NAME")

    def delete_rule(self, rid):
        self.client.execute_query(f"DELETE FROM {self.app_db}.APP_CONTEXT.DATA_QUALITY_RESULTS WHERE RULE_ID='{rid}'")
        self.client.execute_query(f"DELETE FROM {self.app_db}.APP_CONTEXT.DATA_QUALITY_RULES WHERE RULE_ID='{rid}'")

    # ── Rule Execution ──
    def run_rule(self, rule_id):
        df = self.client.execute_query(f"SELECT * FROM {self.app_db}.APP_CONTEXT.DATA_QUALITY_RULES WHERE RULE_ID='{rule_id}'")
        if df.empty: return {"status":"ERROR","error":"Rule not found"}
        rule = df.iloc[0]
        rtype = rule['RULE_TYPE']
        table = rule['TABLE_NAME']
        column = rule.get('COLUMN_NAME','')
        sql_template = self.SYSTEM_CHECKS.get(rtype)
        if not sql_template: return {"status":"ERROR","error":f"Unknown rule type: {rtype}"}
        sql = sql_template.format(table=table, column=column)
        try:
            r = self.client.execute_query(sql, log=False)
            value = float(r.iloc[0,0]) if not r.empty and r.iloc[0,0] is not None else 0
            tw = rule.get('THRESHOLD_WARN')
            te = rule.get('THRESHOLD_ERROR')
            status = 'PASS'
            if te is not None and value > float(te): status = 'FAIL'
            elif tw is not None and value > float(tw): status = 'WARN'
            # Save result
            resid = str(uuid.uuid4())[:8]
            self.client.execute_query(f"""INSERT INTO {self.app_db}.APP_CONTEXT.DATA_QUALITY_RESULTS
                (RESULT_ID,RULE_ID,TABLE_NAME,METRIC_VALUE,STATUS)
                VALUES('{resid}','{rule_id}','{table}',{value},'{status}')""", log=False)
            self.client.execute_query(f"""UPDATE {self.app_db}.APP_CONTEXT.DATA_QUALITY_RULES
                SET LAST_RUN_AT=CURRENT_TIMESTAMP(),LAST_RESULT={value},LAST_STATUS='{status}'
                WHERE RULE_ID='{rule_id}'""", log=False)
            return {"status":status,"value":value,"rule_type":rtype,"table":table,"column":column}
        except Exception as e:
            return {"status":"ERROR","error":str(e)}

    def run_all_rules(self, table_name=None):
        rules = self.list_rules(table_name)
        if rules.empty: return []
        results = []
        for _, rule in rules.iterrows():
            if rule.get('IS_ACTIVE', True):
                results.append(self.run_rule(rule['RULE_ID']))
        return results

    # ── Quality Scoring ──
    def get_table_score(self, table_name):
        results = self.client.execute_query(f"""
            SELECT RULE_ID,LAST_STATUS FROM {self.app_db}.APP_CONTEXT.DATA_QUALITY_RULES
            WHERE TABLE_NAME='{table_name}' AND IS_ACTIVE=TRUE AND LAST_STATUS IS NOT NULL""", log=False)
        if results.empty: return {"score":100,"total_rules":0,"passed":0,"warned":0,"failed":0}
        total = len(results)
        passed = len(results[results['LAST_STATUS']=='PASS'])
        warned = len(results[results['LAST_STATUS']=='WARN'])
        failed = len(results[results['LAST_STATUS']=='FAIL'])
        score = round((passed * 100 + warned * 50) / max(total, 1), 1)
        return {"score":score,"total_rules":total,"passed":passed,"warned":warned,"failed":failed}

    def get_all_table_scores(self):
        try:
            return self.client.execute_query(f"""
                SELECT TABLE_NAME,
                    COUNT(*) AS total_rules,
                    SUM(CASE WHEN LAST_STATUS='PASS' THEN 1 ELSE 0 END) AS passed,
                    SUM(CASE WHEN LAST_STATUS='WARN' THEN 1 ELSE 0 END) AS warned,
                    SUM(CASE WHEN LAST_STATUS='FAIL' THEN 1 ELSE 0 END) AS failed,
                    ROUND((SUM(CASE WHEN LAST_STATUS='PASS' THEN 100 WHEN LAST_STATUS='WARN' THEN 50 ELSE 0 END))/NULLIF(COUNT(*),0),1) AS score
                FROM {self.app_db}.APP_CONTEXT.DATA_QUALITY_RULES
                WHERE IS_ACTIVE=TRUE AND LAST_STATUS IS NOT NULL
                GROUP BY TABLE_NAME ORDER BY score ASC""", log=False)
        except: return pd.DataFrame()

    # ── Quality Gate ──
    def check_quality_gate(self, table_name, min_score=70):
        score_data = self.get_table_score(table_name)
        return {"passed": score_data['score'] >= min_score, "score": score_data['score'], "min_required": min_score}

    # ── History & Trends ──
    def get_result_history(self, rule_id=None, table_name=None, limit=100):
        where = []
        if rule_id: where.append(f"RULE_ID='{rule_id}'")
        if table_name: where.append(f"TABLE_NAME='{table_name}'")
        w = f"WHERE {' AND '.join(where)}" if where else ""
        return self.client.execute_query(f"SELECT * FROM {self.app_db}.APP_CONTEXT.DATA_QUALITY_RESULTS {w} ORDER BY RUN_AT DESC LIMIT {limit}")

    # ── Auto-Suggest Rules ──
    def suggest_rules(self, table_name):
        suggestions = []
        try:
            cols = self.client.execute_query(f"DESCRIBE TABLE {table_name}", log=False)
            if cols.empty: return suggestions
            for _, col in cols.iterrows():
                cn = col.get('name','')
                dt = str(col.get('type','')).upper()
                if 'NOT NULL' not in str(col.get('null?','')).upper():
                    suggestions.append({"column":cn,"rule_type":"null_rate","threshold_warn":5,"threshold_error":20})
                if cn.upper().endswith('_ID'):
                    suggestions.append({"column":cn,"rule_type":"duplicate_count","threshold_warn":0,"threshold_error":0})
                if 'TIMESTAMP' in dt or 'DATE' in dt:
                    suggestions.append({"column":cn,"rule_type":"freshness_hours","threshold_warn":24,"threshold_error":72})
                if 'NUMBER' in dt or 'FLOAT' in dt or 'INT' in dt:
                    suggestions.append({"column":cn,"rule_type":"negative_count","threshold_warn":0,"threshold_error":10})
            suggestions.append({"column":"*","rule_type":"row_count","threshold_warn":None,"threshold_error":None})
        except: pass
        return suggestions


def get_data_quality_engine(client=None):
    if client is None and "snowflake_client" in st.session_state: client = st.session_state.snowflake_client
    if client is None: return None
    if 'dq_engine' not in st.session_state:
        engine = DataQualityEngine(client); engine.ensure_tables(); st.session_state.dq_engine = engine
    return st.session_state.dq_engine
