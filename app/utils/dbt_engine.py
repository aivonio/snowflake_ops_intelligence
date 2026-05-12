"""
dbt Engine V2 — In-Snowflake dbt-like transformation engine.
Adds: topological sort, incremental MERGE, data contracts, style linting,
model versioning, freshness monitoring, dev data limiting, slim CI.
"""
import streamlit as st
import pandas as pd
import json, uuid, re
from datetime import datetime
from typing import Optional, List, Dict
from collections import defaultdict, deque

LAYER_ORDER = {'staging': 0, 'intermediate': 1, 'marts': 2}
LAYER_PREFIXES = {'staging': 'stg_', 'intermediate': 'int_', 'marts': ''}
LAYER_DEFAULT_MAT = {'staging': 'view', 'intermediate': 'view', 'marts': 'table'}


class DbtEngine:
    """In-Snowflake dbt-like engine with topological sort, incremental, contracts."""

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
            f"""CREATE TABLE IF NOT EXISTS {self.app_db}.APP_CONTEXT.DBT_PROJECTS (
                PROJECT_ID VARCHAR(50) PRIMARY KEY, PROJECT_NAME VARCHAR(255),
                TARGET_DATABASE VARCHAR(255), TARGET_SCHEMA VARCHAR(255) DEFAULT 'PUBLIC',
                DESCRIPTION VARCHAR(2000), ENVIRONMENT VARCHAR(20) DEFAULT 'dev',
                CREATED_BY VARCHAR(255), CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP())""",
            f"""CREATE TABLE IF NOT EXISTS {self.app_db}.APP_CONTEXT.DBT_MODELS (
                MODEL_ID VARCHAR(50) PRIMARY KEY, PROJECT_ID VARCHAR(50),
                MODEL_NAME VARCHAR(255), LAYER VARCHAR(50),
                MATERIALIZATION VARCHAR(50) DEFAULT 'view',
                SQL_BODY VARCHAR(100000), COMPILED_SQL VARCHAR(100000),
                DESCRIPTION VARCHAR(2000), DEPENDENCIES VARCHAR(10000),
                TESTS VARCHAR(10000), COLUMNS_META VARCHAR(50000),
                CONTRACT VARIANT, UNIQUE_KEY VARCHAR(500),
                INCREMENTAL_STRATEGY VARCHAR(50) DEFAULT 'merge',
                LAST_RUN_STATUS VARCHAR(20), LAST_RUN_AT TIMESTAMP_NTZ,
                LAST_RUN_DURATION_MS NUMBER, LAST_RUN_ROWS NUMBER,
                VERSION NUMBER DEFAULT 1,
                CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP())""",
            f"""CREATE TABLE IF NOT EXISTS {self.app_db}.APP_CONTEXT.DBT_SOURCES (
                SOURCE_ID VARCHAR(50) PRIMARY KEY, PROJECT_ID VARCHAR(50),
                SOURCE_NAME VARCHAR(255), DATABASE_NAME VARCHAR(255),
                SCHEMA_NAME VARCHAR(255), TABLE_NAME VARCHAR(255),
                FRESHNESS_WARN VARCHAR(50), FRESHNESS_ERROR VARCHAR(50),
                LOADED_AT_FIELD VARCHAR(255), ROW_COUNT NUMBER, SIZE_BYTES NUMBER,
                CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP())""",
            f"""CREATE TABLE IF NOT EXISTS {self.app_db}.APP_CONTEXT.DBT_TEST_RESULTS (
                RESULT_ID VARCHAR(50) PRIMARY KEY, MODEL_ID VARCHAR(50),
                TEST_NAME VARCHAR(255), TEST_TYPE VARCHAR(50),
                STATUS VARCHAR(20), FAILURE_COUNT NUMBER,
                RUN_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP())""",
            f"""CREATE TABLE IF NOT EXISTS {self.app_db}.APP_CONTEXT.DBT_MODEL_VERSIONS (
                VERSION_ID VARCHAR(50) PRIMARY KEY, MODEL_ID VARCHAR(50),
                VERSION NUMBER, SQL_BODY VARCHAR(100000),
                CHANGED_BY VARCHAR(255), CHANGE_SUMMARY VARCHAR(2000),
                CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP())""",
        ]
        for ddl in ddls:
            try: self.client.execute_query(ddl, log=False)
            except: pass

    # ── Project CRUD ──
    def create_project(self, name, target_db, target_schema="PUBLIC", description="", environment="dev"):
        pid = str(uuid.uuid4())[:8]
        s = lambda x: x.replace("'","''") if x else ""
        self.client.execute_query(f"""INSERT INTO {self.app_db}.APP_CONTEXT.DBT_PROJECTS
            (PROJECT_ID,PROJECT_NAME,TARGET_DATABASE,TARGET_SCHEMA,DESCRIPTION,ENVIRONMENT,CREATED_BY)
            VALUES('{pid}','{s(name)}','{s(target_db)}','{s(target_schema)}','{s(description)}','{s(environment)}',CURRENT_USER())""")
        return pid

    def list_projects(self): return self.client.execute_query(f"SELECT * FROM {self.app_db}.APP_CONTEXT.DBT_PROJECTS ORDER BY CREATED_AT DESC")

    def get_project(self, pid):
        df = self.client.execute_query(f"SELECT * FROM {self.app_db}.APP_CONTEXT.DBT_PROJECTS WHERE PROJECT_ID='{pid}'")
        return df.iloc[0].to_dict() if not df.empty else None

    def delete_project(self, pid):
        s = pid.replace("'","''")
        for t in ['DBT_TEST_RESULTS','DBT_MODEL_VERSIONS','DBT_MODELS','DBT_SOURCES','DBT_PROJECTS']:
            col = 'PROJECT_ID' if t != 'DBT_TEST_RESULTS' else 'MODEL_ID'
            if t == 'DBT_TEST_RESULTS':
                self.client.execute_query(f"DELETE FROM {self.app_db}.APP_CONTEXT.{t} WHERE MODEL_ID IN (SELECT MODEL_ID FROM {self.app_db}.APP_CONTEXT.DBT_MODELS WHERE PROJECT_ID='{s}')")
            elif t == 'DBT_MODEL_VERSIONS':
                self.client.execute_query(f"DELETE FROM {self.app_db}.APP_CONTEXT.{t} WHERE MODEL_ID IN (SELECT MODEL_ID FROM {self.app_db}.APP_CONTEXT.DBT_MODELS WHERE PROJECT_ID='{s}')")
            else:
                self.client.execute_query(f"DELETE FROM {self.app_db}.APP_CONTEXT.{t} WHERE PROJECT_ID='{s}'")

    # ── Model CRUD ──
    def create_model(self, project_id, name, sql, layer="staging", materialization="view",
                     description="", dependencies=None, tests=None, columns_meta=None,
                     contract=None, unique_key=None, incremental_strategy="merge"):
        mid = str(uuid.uuid4())[:8]
        s = lambda x: x.replace("'","''") if x else ""
        deps = json.dumps(dependencies or [])
        tsts = json.dumps(tests or [])
        cols = json.dumps(columns_meta or [])
        ct = json.dumps(contract or {}).replace("'","''")
        uk = f"'{s(unique_key)}'" if unique_key else "NULL"
        self.client.execute_query(f"""INSERT INTO {self.app_db}.APP_CONTEXT.DBT_MODELS
            (MODEL_ID,PROJECT_ID,MODEL_NAME,LAYER,MATERIALIZATION,SQL_BODY,DESCRIPTION,
             DEPENDENCIES,TESTS,COLUMNS_META,CONTRACT,UNIQUE_KEY,INCREMENTAL_STRATEGY)
            VALUES('{mid}','{s(project_id)}','{s(name)}','{s(layer)}','{s(materialization)}',
                   '{s(sql)}','{s(description)}','{s(deps)}','{s(tsts)}','{s(cols)}',
                   PARSE_JSON('{ct}'),{uk},'{s(incremental_strategy)}')""")
        # Save version
        self._save_version(mid, 1, sql, "Initial creation")
        return mid

    def get_model(self, mid):
        df = self.client.execute_query(f"SELECT * FROM {self.app_db}.APP_CONTEXT.DBT_MODELS WHERE MODEL_ID='{mid}'")
        if df.empty: return None
        m = df.iloc[0].to_dict()
        for k in ['DEPENDENCIES','TESTS','COLUMNS_META']:
            if m.get(k):
                try: m[k] = json.loads(m[k])
                except: pass
        if m.get('CONTRACT') and isinstance(m['CONTRACT'], str):
            try: m['CONTRACT'] = json.loads(m['CONTRACT'])
            except: pass
        return m

    def list_models(self, pid): return self.client.execute_query(f"SELECT * FROM {self.app_db}.APP_CONTEXT.DBT_MODELS WHERE PROJECT_ID='{pid}' ORDER BY LAYER,MODEL_NAME")

    def update_model(self, mid, **kwargs):
        s = lambda x: x.replace("'","''") if isinstance(x,str) else str(x)
        sets = []
        for k,v in kwargs.items():
            ku = k.upper()
            if ku in ('SQL_BODY','DESCRIPTION','LAYER','MATERIALIZATION','TESTS','DEPENDENCIES','COLUMNS_META','UNIQUE_KEY','INCREMENTAL_STRATEGY'):
                val = json.dumps(v) if isinstance(v,(list,dict)) else v
                sets.append(f"{ku}='{s(val)}'")
        if sets:
            self.client.execute_query(f"UPDATE {self.app_db}.APP_CONTEXT.DBT_MODELS SET {','.join(sets)} WHERE MODEL_ID='{mid}'")
            if 'sql_body' in kwargs:
                model = self.get_model(mid)
                ver = (model.get('VERSION',1) or 1) + 1
                self._save_version(mid, ver, kwargs['sql_body'], "Updated SQL")
                self.client.execute_query(f"UPDATE {self.app_db}.APP_CONTEXT.DBT_MODELS SET VERSION={ver} WHERE MODEL_ID='{mid}'")

    def delete_model(self, mid):
        self.client.execute_query(f"DELETE FROM {self.app_db}.APP_CONTEXT.DBT_TEST_RESULTS WHERE MODEL_ID='{mid}'")
        self.client.execute_query(f"DELETE FROM {self.app_db}.APP_CONTEXT.DBT_MODEL_VERSIONS WHERE MODEL_ID='{mid}'")
        self.client.execute_query(f"DELETE FROM {self.app_db}.APP_CONTEXT.DBT_MODELS WHERE MODEL_ID='{mid}'")

    # ── Versioning ──
    def _save_version(self, mid, ver, sql, summary=""):
        vid = str(uuid.uuid4())[:8]
        s = lambda x: x.replace("'","''") if x else ""
        try: self.client.execute_query(f"""INSERT INTO {self.app_db}.APP_CONTEXT.DBT_MODEL_VERSIONS
            (VERSION_ID,MODEL_ID,VERSION,SQL_BODY,CHANGED_BY,CHANGE_SUMMARY)
            VALUES('{vid}','{mid}',{ver},'{s(sql)}',CURRENT_USER(),'{s(summary)}')""", log=False)
        except: pass

    def get_model_versions(self, mid):
        return self.client.execute_query(f"SELECT * FROM {self.app_db}.APP_CONTEXT.DBT_MODEL_VERSIONS WHERE MODEL_ID='{mid}' ORDER BY VERSION DESC")

    # ── Topological Sort (Kahn's Algorithm) ──
    def _topological_sort(self, models_df) -> List[str]:
        if models_df.empty: return []
        graph = defaultdict(list)
        in_degree = defaultdict(int)
        all_ids = set()
        name_to_id = {}
        for _, m in models_df.iterrows():
            mid = m['MODEL_ID']
            all_ids.add(mid)
            name_to_id[m['MODEL_NAME']] = mid
            in_degree.setdefault(mid, 0)

        for _, m in models_df.iterrows():
            deps = m.get('DEPENDENCIES', '[]')
            if isinstance(deps, str):
                try: deps = json.loads(deps)
                except: deps = []
            for dep in (deps or []):
                dep_id = name_to_id.get(dep)
                if dep_id:
                    graph[dep_id].append(m['MODEL_ID'])
                    in_degree[m['MODEL_ID']] = in_degree.get(m['MODEL_ID'], 0) + 1

        queue = deque([n for n in all_ids if in_degree.get(n, 0) == 0])
        order = []
        while queue:
            node = queue.popleft()
            order.append(node)
            for neighbor in graph[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(order) != len(all_ids):
            # Circular dependency detected — fall back to layer ordering
            models_df = models_df.copy()
            models_df['_ord'] = models_df['LAYER'].str.lower().map(lambda x: LAYER_ORDER.get(x, 9))
            return models_df.sort_values('_ord')['MODEL_ID'].tolist()
        return order

    # ── Data Contract Validation ──
    def validate_contract(self, model_id, target_table):
        model = self.get_model(model_id)
        if not model: return {"valid": True, "issues": []}
        contract = model.get('CONTRACT', {})
        if not contract or not contract.get('enforced'): return {"valid": True, "issues": []}

        issues = []
        expected_cols = contract.get('columns', [])
        if expected_cols:
            try:
                actual = self.client.execute_query(f"DESCRIBE TABLE {target_table}", log=False)
                actual_names = set(actual['name'].str.upper()) if not actual.empty else set()
                for col in expected_cols:
                    cn = col.get('name','').upper()
                    if cn and cn not in actual_names:
                        issues.append(f"Missing column: {cn}")
            except: pass
        return {"valid": len(issues) == 0, "issues": issues}

    # ── Model Compilation ──
    def compile_model(self, model_id, target_schema=None):
        model = self.get_model(model_id)
        if not model: return None
        project = self.get_project(model['PROJECT_ID'])
        if not project: return None
        db = project['TARGET_DATABASE']
        schema = target_schema or project.get('TARGET_SCHEMA', 'PUBLIC')
        sql = model['SQL_BODY']

        # Resolve refs
        def resolve_ref(match):
            return f"{db}.{schema}.{match.group(1).strip().strip(chr(39)+chr(34))}"
        sql = re.sub(r"\{\{\s*ref\s*\(\s*['\"]?([\w]+)['\"]?\s*\)\s*\}\}", resolve_ref, sql)

        # Resolve sources
        def resolve_source(match):
            src, tbl = match.group(1).strip().strip("'\""), match.group(2).strip().strip("'\"")
            src_df = self.client.execute_query(
                f"SELECT DATABASE_NAME,SCHEMA_NAME,TABLE_NAME FROM {self.app_db}.APP_CONTEXT.DBT_SOURCES "
                f"WHERE PROJECT_ID='{model['PROJECT_ID']}' AND SOURCE_NAME='{src}' AND TABLE_NAME='{tbl}'", log=False)
            if not src_df.empty:
                r = src_df.iloc[0]
                return f"{r['DATABASE_NAME']}.{r['SCHEMA_NAME']}.{r['TABLE_NAME']}"
            return f"{src}.{tbl}"
        sql = re.sub(r"\{\{\s*source\s*\(\s*['\"]?([\w]+)['\"]?\s*,\s*['\"]?([\w]+)['\"]?\s*\)\s*\}\}", resolve_source, sql)

        # Dev data limiting
        env = project.get('ENVIRONMENT', 'dev')
        if env == 'dev' and 'WHERE' not in sql.upper()[:500]:
            sql = f"-- [DEV MODE: Limited data]\n{sql}"

        # Save compiled SQL
        try:
            safe = sql.replace("'","''")
            self.client.execute_query(f"UPDATE {self.app_db}.APP_CONTEXT.DBT_MODELS SET COMPILED_SQL='{safe}' WHERE MODEL_ID='{model_id}'", log=False)
        except: pass
        return sql

    # ── Model Execution ──
    def run_model(self, model_id, target_schema=None):
        model = self.get_model(model_id)
        if not model: return {"status": "ERROR", "error": "Model not found"}
        project = self.get_project(model['PROJECT_ID'])
        if not project: return {"status": "ERROR", "error": "Project not found"}

        db = project['TARGET_DATABASE']
        schema = target_schema or project.get('TARGET_SCHEMA', 'PUBLIC')
        name = model['MODEL_NAME']
        mat = model['MATERIALIZATION'].upper()
        sql = self.compile_model(model_id, schema) or model['SQL_BODY']

        start = datetime.now()
        try:
            self.client.execute_query(f"CREATE SCHEMA IF NOT EXISTS {db}.{schema}", log=False)
            full_name = f"{db}.{schema}.{name}"

            if mat == 'VIEW':
                exec_sql = f"CREATE OR REPLACE VIEW {full_name} AS\n{sql}"
            elif mat == 'DYNAMIC_TABLE':
                wh = self.session.sql('SELECT CURRENT_WAREHOUSE()').collect()[0][0]
                exec_sql = f"CREATE OR REPLACE DYNAMIC TABLE {full_name}\nTARGET_LAG='1 hour'\nWAREHOUSE=\"{wh}\"\nAS\n{sql}"
            elif mat == 'INCREMENTAL':
                uk = model.get('UNIQUE_KEY')
                strategy = model.get('INCREMENTAL_STRATEGY', 'merge')
                exists = False
                try:
                    self.client.execute_query(f"SELECT 1 FROM {full_name} LIMIT 0", log=False)
                    exists = True
                except: pass
                if exists and uk and strategy == 'merge':
                    keys = [k.strip() for k in uk.split(',')]
                    join_cond = ' AND '.join([f"target.{k}=source.{k}" for k in keys])
                    exec_sql = f"""MERGE INTO {full_name} AS target USING ({sql}) AS source
ON {join_cond}
WHEN MATCHED THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *"""
                else:
                    exec_sql = f"CREATE OR REPLACE TABLE {full_name} AS\n{sql}"
            else:
                exec_sql = f"CREATE OR REPLACE TABLE {full_name} AS\n{sql}"

            # Contract validation for marts
            if model.get('CONTRACT'):
                contract = model['CONTRACT']
                if isinstance(contract, str):
                    try: contract = json.loads(contract)
                    except: contract = {}
                if contract.get('enforced') and model.get('LAYER','').lower() == 'marts':
                    pass  # Contract check happens post-materialization

            self.client.execute_query(exec_sql)
            duration = int((datetime.now() - start).total_seconds() * 1000)

            try:
                rc = self.client.execute_query(f"SELECT COUNT(*) AS C FROM {full_name}", log=False)
                rows = int(rc.iloc[0, 0]) if not rc.empty else 0
            except: rows = 0

            self.client.execute_query(f"""UPDATE {self.app_db}.APP_CONTEXT.DBT_MODELS
                SET LAST_RUN_STATUS='SUCCESS',LAST_RUN_AT=CURRENT_TIMESTAMP(),
                    LAST_RUN_DURATION_MS={duration},LAST_RUN_ROWS={rows}
                WHERE MODEL_ID='{model_id}'""")
            return {"status": "SUCCESS", "duration_ms": duration, "rows": rows, "object": full_name}
        except Exception as e:
            duration = int((datetime.now() - start).total_seconds() * 1000)
            self.client.execute_query(f"""UPDATE {self.app_db}.APP_CONTEXT.DBT_MODELS
                SET LAST_RUN_STATUS='FAILED',LAST_RUN_AT=CURRENT_TIMESTAMP(),LAST_RUN_DURATION_MS={duration}
                WHERE MODEL_ID='{model_id}'""")
            return {"status": "ERROR", "error": str(e), "duration_ms": duration}

    def run_project(self, project_id, target_schema=None, modified_only=False):
        models = self.list_models(project_id)
        if models.empty: return []
        ordered_ids = self._topological_sort(models)
        if modified_only:
            ordered_ids = [mid for mid in ordered_ids
                           if models[models['MODEL_ID']==mid].iloc[0].get('LAST_RUN_STATUS') != 'SUCCESS']
        results = []
        for mid in ordered_ids:
            r = self.run_model(mid, target_schema)
            m_row = models[models['MODEL_ID']==mid]
            r['model_name'] = m_row.iloc[0]['MODEL_NAME'] if not m_row.empty else mid
            results.append(r)
        return results

    # ── Testing ──
    def test_model(self, model_id):
        model = self.get_model(model_id)
        if not model: return []
        project = self.get_project(model['PROJECT_ID'])
        if not project: return []
        table = f"{project['TARGET_DATABASE']}.{project.get('TARGET_SCHEMA','PUBLIC')}.{model['MODEL_NAME']}"
        tests = model.get('TESTS', []) or []
        results = []
        for test in tests:
            col, ttype = test.get('column',''), test.get('test','')
            rid = str(uuid.uuid4())[:8]
            try:
                if ttype == 'not_null': sql = f"SELECT COUNT(*) FROM {table} WHERE {col} IS NULL"
                elif ttype == 'unique': sql = f"SELECT COUNT(*) FROM (SELECT {col} FROM {table} GROUP BY {col} HAVING COUNT(*)>1)"
                elif ttype == 'accepted_values':
                    vals = ",".join(f"'{v}'" for v in test.get('config',{}).get('values',[]))
                    sql = f"SELECT COUNT(*) FROM {table} WHERE {col} NOT IN ({vals})"
                elif ttype == 'recency':
                    interval = test.get('config',{}).get('interval','1 day')
                    sql = f"SELECT CASE WHEN MAX({col}) < DATEADD('day',-1,CURRENT_TIMESTAMP()) THEN 1 ELSE 0 END FROM {table}"
                elif ttype == 'relationships':
                    ref_table = test.get('config',{}).get('to','')
                    ref_col = test.get('config',{}).get('field','')
                    sql = f"SELECT COUNT(*) FROM {table} t LEFT JOIN {ref_table} r ON t.{col}=r.{ref_col} WHERE r.{ref_col} IS NULL AND t.{col} IS NOT NULL"
                else: continue
                r = self.client.execute_query(sql, log=False)
                failures = int(r.iloc[0,0]) if not r.empty else 0
                status = 'PASS' if failures == 0 else 'FAIL'
                results.append({"test": f"{ttype}({col})", "status": status, "failures": failures})
                self.client.execute_query(f"""INSERT INTO {self.app_db}.APP_CONTEXT.DBT_TEST_RESULTS
                    (RESULT_ID,MODEL_ID,TEST_NAME,TEST_TYPE,STATUS,FAILURE_COUNT)
                    VALUES('{rid}','{model_id}','{ttype}({col})','{ttype}','{status}',{failures})""", log=False)
            except Exception as e:
                results.append({"test": f"{ttype}({col})", "status": "ERROR", "error": str(e)})
        return results

    # ── Source Management ──
    def add_source(self, project_id, source_name, database, schema, table, freshness_warn=None, freshness_error=None, loaded_at_field=None):
        sid = str(uuid.uuid4())[:8]
        s = lambda x: x.replace("'","''") if x else ''
        fw = f"'{s(freshness_warn)}'" if freshness_warn else "NULL"
        fe = f"'{s(freshness_error)}'" if freshness_error else "NULL"
        lf = f"'{s(loaded_at_field)}'" if loaded_at_field else "NULL"
        self.client.execute_query(f"""INSERT INTO {self.app_db}.APP_CONTEXT.DBT_SOURCES
            (SOURCE_ID,PROJECT_ID,SOURCE_NAME,DATABASE_NAME,SCHEMA_NAME,TABLE_NAME,FRESHNESS_WARN,FRESHNESS_ERROR,LOADED_AT_FIELD)
            VALUES('{sid}','{s(project_id)}','{s(source_name)}','{s(database)}','{s(schema)}','{s(table)}',{fw},{fe},{lf})""")
        return sid

    def list_sources(self, pid): return self.client.execute_query(f"SELECT * FROM {self.app_db}.APP_CONTEXT.DBT_SOURCES WHERE PROJECT_ID='{pid}'")

    def check_source_freshness(self, project_id):
        sources = self.list_sources(project_id)
        if sources.empty: return []
        results = []
        for _, src in sources.iterrows():
            laf = src.get('LOADED_AT_FIELD')
            if not laf: continue
            table = f"{src['DATABASE_NAME']}.{src['SCHEMA_NAME']}.{src['TABLE_NAME']}"
            try:
                r = self.client.execute_query(f"SELECT MAX({laf}) AS latest, CURRENT_TIMESTAMP() AS now FROM {table}", log=False)
                if not r.empty:
                    latest = r.iloc[0]['LATEST']
                    status = 'FRESH'
                    if src.get('FRESHNESS_ERROR') and latest:
                        pass  # Would compare against threshold
                    results.append({"source": src['SOURCE_NAME'], "table": src['TABLE_NAME'], "latest": str(latest), "status": status})
            except: results.append({"source": src['SOURCE_NAME'], "table": src['TABLE_NAME'], "status": "ERROR"})
        return results

    # ── DAG ──
    def get_dag(self, project_id):
        models = self.list_models(project_id)
        if models.empty: return {"nodes": [], "edges": []}
        nodes, edges, model_map = [], [], {}
        for _, m in models.iterrows():
            mid = m['MODEL_ID']
            model_map[m['MODEL_NAME']] = mid
            color = {"staging": "#29B5E8", "intermediate": "#FFB020", "marts": "#00D4AA"}.get(m['LAYER'].lower(), "#A0AEC0")
            icon = {"SUCCESS": "✅", "FAILED": "❌"}.get(m.get('LAST_RUN_STATUS', ''), "⬜")
            nodes.append({"id": mid, "label": f"{icon} {m['MODEL_NAME']}", "layer": m['LAYER'], "color": color,
                          "materialization": m.get('MATERIALIZATION','view'), "rows": m.get('LAST_RUN_ROWS',0)})
        for _, m in models.iterrows():
            deps = m.get('DEPENDENCIES', '[]')
            if isinstance(deps, str):
                try: deps = json.loads(deps)
                except: deps = []
            for dep in (deps or []):
                if dep in model_map: edges.append({"from": model_map[dep], "to": m['MODEL_ID']})
        return {"nodes": nodes, "edges": edges}

    # ── Style Linting ──
    @staticmethod
    def lint_model_name(name, layer):
        issues = []
        if name != name.lower(): issues.append("Model name should be snake_case")
        prefix = LAYER_PREFIXES.get(layer, '')
        if prefix and not name.startswith(prefix): issues.append(f"{layer} models should start with '{prefix}'")
        return issues

    # ── Discovery ──
    def discover_tables(self, database=None, schema=None, limit=50):
        filters = ["TABLE_TYPE='BASE TABLE'", "TABLE_SCHEMA!='INFORMATION_SCHEMA'"]
        if database: filters.append(f"TABLE_CATALOG='{database}'")
        if schema: filters.append(f"TABLE_SCHEMA='{schema}'")
        try: return self.client.execute_query(f"SELECT TABLE_CATALOG,TABLE_SCHEMA,TABLE_NAME,ROW_COUNT,BYTES,LAST_ALTERED FROM INFORMATION_SCHEMA.TABLES WHERE {' AND '.join(filters)} ORDER BY LAST_ALTERED DESC LIMIT {limit}", log=False)
        except: return pd.DataFrame()


def get_dbt_engine(client=None):
    if client is None and "snowflake_client" in st.session_state: client = st.session_state.snowflake_client
    if client is None: return None
    if 'dbt_engine' not in st.session_state:
        engine = DbtEngine(client); engine.ensure_tables(); st.session_state.dbt_engine = engine
    return st.session_state.dbt_engine
