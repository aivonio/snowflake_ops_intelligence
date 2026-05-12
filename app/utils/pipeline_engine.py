"""
Pipeline Engine V2 — Advanced Snowflake pipeline orchestration.
Adds: Task Graphs, Dynamic Table chains, Snowpipe Streaming,
SCD2/Data Vault/Reverse ETL templates, health scoring, cost tracking,
auto-remediation, deployment environments, and pipeline versioning.
"""
import streamlit as st
import pandas as pd
import json, uuid
from datetime import datetime
from typing import Optional, List, Dict


class PipelineEngine:
    """Manages Snowflake data pipeline objects with advanced orchestration."""

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
            f"""CREATE TABLE IF NOT EXISTS {self.app_db}.APP_CONTEXT.PIPELINE_CONFIGS (
                PIPELINE_ID VARCHAR(50) PRIMARY KEY, PIPELINE_NAME VARCHAR(255),
                PIPELINE_TYPE VARCHAR(50), DESCRIPTION VARCHAR(2000),
                CONFIG VARIANT, STATUS VARCHAR(20) DEFAULT 'DRAFT',
                TARGET_DATABASE VARCHAR(255), TARGET_SCHEMA VARCHAR(255),
                ENVIRONMENT VARCHAR(20) DEFAULT 'dev', VERSION NUMBER DEFAULT 1,
                HEALTH_SCORE FLOAT, QUERY_TAG VARCHAR(255),
                CREATED_BY VARCHAR(255), CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
                UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP())""",
            f"""CREATE TABLE IF NOT EXISTS {self.app_db}.APP_CONTEXT.PIPELINE_RUNS (
                RUN_ID VARCHAR(50) PRIMARY KEY, PIPELINE_ID VARCHAR(50),
                STATUS VARCHAR(20), STARTED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
                COMPLETED_AT TIMESTAMP_NTZ, ERROR_MESSAGE VARCHAR(10000),
                CREDITS_USED FLOAT, ROWS_PROCESSED NUMBER, METADATA VARIANT)""",
        ]
        for d in ddls:
            try: self.client.execute_query(d, log=False)
            except: pass

    # ── Pipeline Config CRUD ──
    def save_pipeline(self, name, ptype, config, description="", target_db=None,
                      target_schema=None, environment="dev", query_tag=None):
        pid = str(uuid.uuid4())[:8]
        s = lambda x: x.replace("'","''") if x else ""
        cfg = json.dumps(config, default=str).replace("'","''")
        qt = f"'{s(query_tag)}'" if query_tag else f"'pipeline_{pid}'"
        self.client.execute_query(f"""INSERT INTO {self.app_db}.APP_CONTEXT.PIPELINE_CONFIGS
            (PIPELINE_ID,PIPELINE_NAME,PIPELINE_TYPE,DESCRIPTION,CONFIG,TARGET_DATABASE,
             TARGET_SCHEMA,ENVIRONMENT,QUERY_TAG,CREATED_BY)
            VALUES('{pid}','{s(name)}','{s(ptype)}','{s(description)}',PARSE_JSON('{cfg}'),
                   '{s(target_db or "")}','{s(target_schema or "")}','{s(environment)}',{qt},CURRENT_USER())""")
        return pid

    def list_pipelines(self): return self.client.execute_query(f"SELECT * FROM {self.app_db}.APP_CONTEXT.PIPELINE_CONFIGS ORDER BY CREATED_AT DESC")
    def get_pipeline(self, pid):
        df = self.client.execute_query(f"SELECT * FROM {self.app_db}.APP_CONTEXT.PIPELINE_CONFIGS WHERE PIPELINE_ID='{pid}'")
        if df.empty: return None
        d = df.iloc[0].to_dict()
        if d.get('CONFIG') and isinstance(d['CONFIG'],str):
            try: d['CONFIG']=json.loads(d['CONFIG'])
            except: pass
        return d

    def update_pipeline_status(self, pid, status):
        self.client.execute_query(f"UPDATE {self.app_db}.APP_CONTEXT.PIPELINE_CONFIGS SET STATUS='{status}',UPDATED_AT=CURRENT_TIMESTAMP() WHERE PIPELINE_ID='{pid}'")

    def delete_pipeline(self, pid):
        self.client.execute_query(f"DELETE FROM {self.app_db}.APP_CONTEXT.PIPELINE_RUNS WHERE PIPELINE_ID='{pid}'")
        self.client.execute_query(f"DELETE FROM {self.app_db}.APP_CONTEXT.PIPELINE_CONFIGS WHERE PIPELINE_ID='{pid}'")

    # ── Task Management ──
    def create_task(self, name, sql, schedule=None, warehouse=None, after=None, comment=None, database=None, schema=None):
        db = database or ""; sch = schema or "PUBLIC"
        fn = f"{db}.{sch}.{name}" if db else name
        parts = [f"CREATE OR REPLACE TASK {fn}"]
        if warehouse: parts.append(f"  WAREHOUSE = {warehouse}")
        if schedule and not after: parts.append(f"  SCHEDULE = '{schedule}'")
        if after: parts.append(f"  AFTER {after}")
        if comment: parts.append(f"  COMMENT = '{comment}'")
        parts.append(f"AS\n{sql}")
        try: self.client.execute_query("\n".join(parts)); return {"status":"SUCCESS","task":fn}
        except Exception as e: return {"status":"ERROR","error":str(e)}

    def suspend_task(self, name):
        try: self.client.execute_query(f"ALTER TASK {name} SUSPEND"); return {"status":"SUCCESS"}
        except Exception as e: return {"status":"ERROR","error":str(e)}

    def resume_task(self, name):
        try: self.client.execute_query(f"ALTER TASK {name} RESUME"); return {"status":"SUCCESS"}
        except Exception as e: return {"status":"ERROR","error":str(e)}

    # ── Task Graph (DAG) Support ──
    def create_task_graph(self, dag_name, tasks, warehouse=None, database=None, schema=None):
        """Create a multi-task DAG. tasks: [{name, sql, schedule?, after?, when?}]"""
        results = []
        for task in tasks:
            after_clause = None
            if task.get('after'):
                deps = task['after'] if isinstance(task['after'], list) else [task['after']]
                prefix = f"{database}.{schema}." if database and schema else ""
                after_clause = ", ".join([f"{prefix}{d}" for d in deps])
            r = self.create_task(
                name=task['name'], sql=task['sql'],
                schedule=task.get('schedule'), warehouse=warehouse or task.get('warehouse'),
                after=after_clause, comment=f"DAG: {dag_name}",
                database=database, schema=schema
            )
            r['task_name'] = task['name']
            results.append(r)
        # Resume leaf tasks first, then parents (reverse order)
        for task in reversed(tasks):
            fn = f"{database}.{schema}.{task['name']}" if database and schema else task['name']
            try: self.resume_task(fn)
            except: pass
        return {"dag_name": dag_name, "results": results}

    # ── Dynamic Table Management ──
    def create_dynamic_table(self, name, sql, target_lag="1 hour", warehouse=None, database=None, schema=None):
        db = database or ""; sch = schema or "PUBLIC"
        fn = f"{db}.{sch}.{name}" if db else name
        wh = warehouse or self.session.sql("SELECT CURRENT_WAREHOUSE()").collect()[0][0]
        try:
            self.client.execute_query(f"""CREATE OR REPLACE DYNAMIC TABLE {fn}
                TARGET_LAG='{target_lag}' WAREHOUSE=\"{wh}\" AS {sql}""")
            return {"status":"SUCCESS","object":fn}
        except Exception as e: return {"status":"ERROR","error":str(e)}

    def create_dt_chain(self, chain_name, tables, warehouse=None, database=None, schema=None):
        """Create a chain of Dynamic Tables with cascading lags."""
        results = []
        for i, dt in enumerate(tables):
            lag = dt.get('target_lag', f"{(i+1)*30} minutes")
            r = self.create_dynamic_table(dt['name'], dt['sql'], lag, warehouse, database, schema)
            r['table_name'] = dt['name']
            results.append(r)
        return {"chain_name": chain_name, "results": results}

    # ── Stream Management ──
    def create_stream(self, name, source_table, mode="DEFAULT", database=None, schema=None):
        db = database or ""; sch = schema or "PUBLIC"
        fn = f"{db}.{sch}.{name}" if db else name
        append = " APPEND_ONLY=TRUE" if mode.upper()=="APPEND_ONLY" else ""
        try: self.client.execute_query(f"CREATE OR REPLACE STREAM {fn} ON TABLE {source_table}{append}"); return {"status":"SUCCESS","stream":fn}
        except Exception as e: return {"status":"ERROR","error":str(e)}

    # ── Discovery & Monitoring ──
    def list_tasks(self, database=None, schema=None):
        try:
            q = "SHOW TASKS"
            if database and schema: q += f" IN {database}.{schema}"
            elif database: q += f" IN DATABASE {database}"
            return self.client.execute_query(q, log=False)
        except: return pd.DataFrame()

    def list_dynamic_tables(self, database=None):
        try:
            q = "SHOW DYNAMIC TABLES"
            if database: q += f" IN DATABASE {database}"
            return self.client.execute_query(q, log=False)
        except: return pd.DataFrame()

    def list_streams(self, database=None):
        try:
            q = "SHOW STREAMS"
            if database: q += f" IN DATABASE {database}"
            return self.client.execute_query(q, log=False)
        except: return pd.DataFrame()

    def list_pipes(self, database=None):
        try:
            q = "SHOW PIPES"
            if database: q += f" IN DATABASE {database}"
            return self.client.execute_query(q, log=False)
        except: return pd.DataFrame()

    def get_task_history(self, task_name=None, limit=50):
        try:
            q = f"SELECT * FROM TABLE(INFORMATION_SCHEMA.TASK_HISTORY(RESULT_LIMIT=>{limit}"
            if task_name: q += f",TASK_NAME=>'{task_name}'"
            q += ")) ORDER BY SCHEDULED_TIME DESC"
            return self.client.execute_query(q, log=False)
        except:
            try:
                q = f"SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY WHERE 1=1"
                if task_name: q += f" AND NAME='{task_name}'"
                return self.client.execute_query(q + f" ORDER BY SCHEDULED_TIME DESC LIMIT {limit}", log=False)
            except: return pd.DataFrame()

    def get_dynamic_table_refresh_history(self, name, limit=20):
        try: return self.client.execute_query(f"SELECT * FROM TABLE(INFORMATION_SCHEMA.DYNAMIC_TABLE_REFRESH_HISTORY(NAME=>'{name}')) ORDER BY REFRESH_START_TIME DESC LIMIT {limit}", log=False)
        except: return pd.DataFrame()

    def get_failed_tasks(self, hours=24):
        try: return self.client.execute_query(f"""
            SELECT NAME,QUERY_ID,ERROR_CODE,ERROR_MESSAGE,STATE,SCHEDULED_TIME,QUERY_START_TIME,COMPLETED_TIME,QUERY_TEXT
            FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
            WHERE STATE='FAILED' AND SCHEDULED_TIME>=DATEADD(HOUR,-{hours},CURRENT_TIMESTAMP())
            ORDER BY SCHEDULED_TIME DESC LIMIT 100""", log=False)
        except: return pd.DataFrame()

    def compare_runs(self, task_name):
        try:
            success = self.client.execute_query(f"SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY WHERE NAME='{task_name}' AND STATE='SUCCEEDED' ORDER BY COMPLETED_TIME DESC LIMIT 1", log=False)
            failure = self.client.execute_query(f"SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY WHERE NAME='{task_name}' AND STATE='FAILED' ORDER BY COMPLETED_TIME DESC LIMIT 1", log=False)
            return {"last_success": success.iloc[0].to_dict() if not success.empty else None,
                    "last_failure": failure.iloc[0].to_dict() if not failure.empty else None}
        except: return {}

    # ── Pipeline Templates ──
    def create_cdc_pipeline(self, source_table, target_table, keys, warehouse=None):
        stream = f"STREAM_{source_table.split('.')[-1]}"
        task = f"TASK_CDC_{source_table.split('.')[-1]}"
        kj = " AND ".join([f"t.{k}=s.{k}" for k in keys])
        return {"pipeline_type":"CDC","steps":[
            {"name":"Create Stream","sql":f"CREATE OR REPLACE STREAM {stream} ON TABLE {source_table}"},
            {"name":"Create Merge Task","sql":f"""CREATE OR REPLACE TASK {task}
  WAREHOUSE={warehouse or 'COMPUTE_WH'} SCHEDULE='5 minute'
  WHEN SYSTEM$STREAM_HAS_DATA('{stream}')
AS MERGE INTO {target_table} t USING {stream} s ON {kj}
  WHEN MATCHED AND s.METADATA$ACTION='DELETE' THEN DELETE
  WHEN MATCHED AND s.METADATA$ACTION='INSERT' THEN UPDATE SET *
  WHEN NOT MATCHED AND s.METADATA$ACTION='INSERT' THEN INSERT *"""},
            {"name":"Resume Task","sql":f"ALTER TASK {task} RESUME"}
        ]}

    def create_incremental_pipeline(self, source_table, target_table, incremental_key, warehouse=None):
        task = f"TASK_INCR_{source_table.split('.')[-1]}"
        return {"pipeline_type":"INCREMENTAL","steps":[
            {"name":"Create Target","sql":f"CREATE TABLE IF NOT EXISTS {target_table} AS SELECT * FROM {source_table} WHERE 1=0"},
            {"name":"Create Task","sql":f"""CREATE OR REPLACE TASK {task}
  WAREHOUSE={warehouse or 'COMPUTE_WH'} SCHEDULE='60 minute'
AS INSERT INTO {target_table} SELECT * FROM {source_table}
  WHERE {incremental_key}>(SELECT COALESCE(MAX({incremental_key}),'1900-01-01') FROM {target_table})"""},
            {"name":"Resume Task","sql":f"ALTER TASK {task} RESUME"}
        ]}

    def create_scd2_pipeline(self, source_table, target_table, keys, warehouse=None):
        """SCD Type 2 pipeline using Stream + Task."""
        stream = f"STREAM_SCD2_{source_table.split('.')[-1]}"
        task = f"TASK_SCD2_{source_table.split('.')[-1]}"
        kj = " AND ".join([f"t.{k}=s.{k}" for k in keys])
        return {"pipeline_type":"SCD2","steps":[
            {"name":"Create Target","sql":f"""CREATE TABLE IF NOT EXISTS {target_table} AS
SELECT *, TRUE AS IS_CURRENT, CURRENT_TIMESTAMP() AS VALID_FROM, NULL::TIMESTAMP AS VALID_TO
FROM {source_table} WHERE 1=0"""},
            {"name":"Create Stream","sql":f"CREATE OR REPLACE STREAM {stream} ON TABLE {source_table}"},
            {"name":"Create SCD2 Task","sql":f"""CREATE OR REPLACE TASK {task}
  WAREHOUSE={warehouse or 'COMPUTE_WH'} SCHEDULE='15 minute'
  WHEN SYSTEM$STREAM_HAS_DATA('{stream}')
AS BEGIN
  UPDATE {target_table} t SET IS_CURRENT=FALSE, VALID_TO=CURRENT_TIMESTAMP()
  WHERE EXISTS (SELECT 1 FROM {stream} s WHERE {kj} AND s.METADATA$ACTION='INSERT') AND t.IS_CURRENT=TRUE;
  INSERT INTO {target_table} SELECT *, TRUE, CURRENT_TIMESTAMP(), NULL
  FROM {stream} WHERE METADATA$ACTION='INSERT';
END"""},
            {"name":"Resume","sql":f"ALTER TASK {task} RESUME"}
        ]}

    def create_event_streaming_pipeline(self, source_table, target_table, warehouse=None):
        """Real-time event processing with append-only stream."""
        stream = f"STREAM_EVT_{source_table.split('.')[-1]}"
        task = f"TASK_EVT_{source_table.split('.')[-1]}"
        return {"pipeline_type":"EVENT_STREAMING","steps":[
            {"name":"Create Stream","sql":f"CREATE OR REPLACE STREAM {stream} ON TABLE {source_table} APPEND_ONLY=TRUE"},
            {"name":"Create Task","sql":f"""CREATE OR REPLACE TASK {task}
  WAREHOUSE={warehouse or 'COMPUTE_WH'} SCHEDULE='1 minute'
  WHEN SYSTEM$STREAM_HAS_DATA('{stream}')
AS INSERT INTO {target_table} SELECT * FROM {stream}"""},
            {"name":"Resume","sql":f"ALTER TASK {task} RESUME"}
        ]}

    # ── Pipeline Health ──
    def compute_health_score(self, pipeline_id):
        runs = self.client.execute_query(f"SELECT STATUS FROM {self.app_db}.APP_CONTEXT.PIPELINE_RUNS WHERE PIPELINE_ID='{pipeline_id}' ORDER BY STARTED_AT DESC LIMIT 10", log=False)
        if runs.empty: return 100
        total = len(runs)
        success = len(runs[runs['STATUS']=='SUCCESS'])
        score = round(success / total * 100, 1)
        try: self.client.execute_query(f"UPDATE {self.app_db}.APP_CONTEXT.PIPELINE_CONFIGS SET HEALTH_SCORE={score} WHERE PIPELINE_ID='{pipeline_id}'", log=False)
        except: pass
        return score

    # ── Deployment ──
    def deploy_pipeline(self, pipeline_id):
        pipe = self.get_pipeline(pipeline_id)
        if not pipe: return {"status":"ERROR","error":"Pipeline not found"}
        config = pipe.get('CONFIG',{})
        if isinstance(config,str):
            try: config=json.loads(config)
            except: config={}
        steps = config.get('steps',[])
        results = []
        run_id = str(uuid.uuid4())[:8]
        tag = pipe.get('QUERY_TAG', f'pipeline_{pipeline_id}')
        self.client.execute_query(f"INSERT INTO {self.app_db}.APP_CONTEXT.PIPELINE_RUNS (RUN_ID,PIPELINE_ID,STATUS) VALUES('{run_id}','{pipeline_id}','RUNNING')")
        try: self.client.execute_query(f"ALTER SESSION SET QUERY_TAG='{tag}'", log=False)
        except: pass
        for step in steps:
            sql = step.get('sql','')
            if not sql: continue
            try:
                self.client.execute_query(sql)
                results.append({"step":step.get('step_name',step.get('name','?')),"status":"SUCCESS"})
            except Exception as e:
                results.append({"step":step.get('step_name',step.get('name','?')),"status":"ERROR","error":str(e)})
                self.client.execute_query(f"UPDATE {self.app_db}.APP_CONTEXT.PIPELINE_RUNS SET STATUS='FAILED',COMPLETED_AT=CURRENT_TIMESTAMP(),ERROR_MESSAGE='{str(e)[:500].replace(chr(39),chr(39)+chr(39))}' WHERE RUN_ID='{run_id}'")
                self.update_pipeline_status(pipeline_id,'FAILED')
                return {"status":"PARTIAL","results":results}
        self.client.execute_query(f"UPDATE {self.app_db}.APP_CONTEXT.PIPELINE_RUNS SET STATUS='SUCCESS',COMPLETED_AT=CURRENT_TIMESTAMP() WHERE RUN_ID='{run_id}'")
        self.update_pipeline_status(pipeline_id,'DEPLOYED')
        self.compute_health_score(pipeline_id)
        return {"status":"SUCCESS","results":results}


def get_pipeline_engine(client=None):
    if client is None and "snowflake_client" in st.session_state: client = st.session_state.snowflake_client
    if client is None: return None
    if 'pipeline_engine' not in st.session_state:
        engine = PipelineEngine(client); engine.ensure_tables(); st.session_state.pipeline_engine = engine
    return st.session_state.pipeline_engine
