"""
Cortex Code (CoCo) Client V2 — Agentic AI Integration
Wraps Snowflake Cortex LLM functions with circuit breaker, model rotation,
usage tracking, and extended generation for DMFs, stored procedures,
semantic models, query plans, and task graphs.
"""
import streamlit as st
import json, re, time
from typing import Optional, List, Dict, Any
from datetime import datetime

# ── System Prompts ──
SYSTEM_PROMPTS = {
    "sql": "You are CoCo, a Snowflake SQL expert. Generate precise, production-ready Snowflake SQL. Use CTEs, qualify table names, add comments. Return ONLY SQL code blocks.",
    "dbt": "You are CoCo, a dbt+Snowflake expert. Follow SIM architecture (staging/intermediate/marts). Use ref() and source(). Return JSON with keys: model_name, sql, description, columns, tests, dependencies.",
    "pipeline": "You are CoCo, a Snowflake Pipeline Architect. Use Dynamic Tables, Tasks, Streams, Snowpipe. Return pipeline configs as structured JSON.",
    "debug": "You are CoCo, a Snowflake Debugging Expert. Provide: 1) Root cause 2) Fix SQL 3) Prevention. Be concise.",
    "script": "You are CoCo, a Snowflake Script Writer. Generate complete, idempotent, production-ready SQL scripts with error handling and logging.",
    "optimize": "You are CoCo, a Query Optimizer. Suggest partition pruning, clustering keys, join order fixes, materialization strategy. Return optimized SQL.",
    "migrate": "You are CoCo, a SQL Migration Expert. Convert other SQL dialects to Snowflake. Handle data types, functions, procedural code.",
    "dmf": "You are CoCo, a Data Quality Expert. Generate Snowflake Data Metric Functions (DMFs). Return CREATE FUNCTION SQL using SNOWFLAKE.CORE patterns.",
    "stored_proc": "You are CoCo, a Snowflake Stored Procedure Expert. Generate Snowflake Scripting or Snowpark Python procedures. Return complete, production-ready CREATE PROCEDURE statements.",
    "semantic": "You are CoCo, a Cortex Analyst Semantic Model Expert. Generate YAML semantic models for Cortex Analyst. Return valid YAML with tables, dimensions, measures, and time_dimensions.",
    "task_graph": "You are CoCo, a Snowflake Task DAG Expert. Design multi-step task graphs with proper dependencies. Return JSON with tasks array: [{name, sql, schedule, after, warehouse}].",
    "query_plan": "You are CoCo, a Snowflake Query Plan Expert. Parse EXPLAIN output and suggest optimizations: clustering keys, search optimization, materialized views, warehouse sizing.",
    "lint": "You are CoCo, a dbt SQL Style Linter. Check SQL against dbt Labs style guide: snake_case, CTEs, column ordering (ids→strings→numerics→booleans→dates→timestamps), no abbreviations. Return JSON: {issues: [{line, severity, message, fix}], score: 0-100}.",
    "cost": "You are CoCo, a Snowflake Cost Analyst. Estimate query cost based on warehouse size and data volume. Return JSON: {estimated_credits, optimization_tips: [string], alternative_approaches: [string]}.",
}

CORTEX_MODELS = [
    "llama3.1-70b", "mistral-large2", "mistral-large",
    "llama3.1-8b", "llama3-70b", "mistral-7b", "snowflake-arctic",
]


class CircuitBreaker:
    """Circuit breaker pattern for Cortex API resilience."""

    def __init__(self, failure_threshold: int = 3, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failures = 0
        self._last_failure_time = 0
        self._state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN

    @property
    def state(self) -> str:
        if self._state == "OPEN":
            if time.time() - self._last_failure_time > self.recovery_timeout:
                self._state = "HALF_OPEN"
        return self._state

    def record_success(self):
        self._failures = 0
        self._state = "CLOSED"

    def record_failure(self):
        self._failures += 1
        self._last_failure_time = time.time()
        if self._failures >= self.failure_threshold:
            self._state = "OPEN"

    def allow_request(self) -> bool:
        return self.state != "OPEN"


class CocoClient:
    """Cortex Code (CoCo) integration — AI-powered SQL/pipeline/dbt generation with resilience."""

    def __init__(self, session):
        self.session = session
        self._available = None
        self._best_model = None
        self._context = {}
        self._circuit_breaker = CircuitBreaker()
        self._usage_log = []

    @property
    def is_available(self) -> bool:
        if self._available is None:
            self._available, self._best_model = self._discover_models()
        return self._available and self._circuit_breaker.allow_request()

    @property
    def best_model(self) -> str:
        if self._best_model is None:
            self._available, self._best_model = self._discover_models()
        return self._best_model or "mistral-large"

    @property
    def circuit_state(self) -> str:
        return self._circuit_breaker.state

    def _discover_models(self):
        for model in CORTEX_MODELS:
            try:
                r = self.session.sql(f"SELECT SNOWFLAKE.CORTEX.COMPLETE('{model}','reply OK') AS r").collect()
                if r:
                    return True, model
            except:
                continue
        return False, None

    def _get_context(self) -> str:
        if not self._context:
            try:
                ctx = self.session.sql(
                    "SELECT CURRENT_ACCOUNT(),CURRENT_USER(),CURRENT_ROLE(),"
                    "CURRENT_WAREHOUSE(),CURRENT_DATABASE()"
                ).collect()
                if ctx:
                    r = ctx[0]
                    self._context = dict(
                        account=str(r[0]), user=str(r[1]), role=str(r[2]),
                        warehouse=str(r[3]), database=str(r[4])
                    )
            except:
                pass
        if self._context:
            return (f"\nCONTEXT: Role={self._context.get('role','?')}, "
                    f"WH={self._context.get('warehouse','?')}, "
                    f"DB={self._context.get('database','?')}")
        return ""

    def _complete(self, prompt: str, system: str = "", model: str = None) -> Optional[str]:
        """Core completion with circuit breaker and model rotation."""
        if not self._circuit_breaker.allow_request():
            return None

        # Build prompt
        if system:
            full = f"[SYSTEM]\n{system}\n\n[USER]\n{prompt}{self._get_context()}"
        else:
            full = f"{prompt}{self._get_context()}"

        # Try primary model, then rotate on failure
        models_to_try = [model or self.best_model]
        for m in CORTEX_MODELS:
            if m not in models_to_try:
                models_to_try.append(m)
            if len(models_to_try) >= 3:
                break

        for try_model in models_to_try:
            try:
                safe = full.replace("'", "''")
                start = time.time()
                r = self.session.sql(
                    f"SELECT SNOWFLAKE.CORTEX.COMPLETE('{try_model}','{safe}') AS response"
                ).collect()
                duration_ms = int((time.time() - start) * 1000)

                if r:
                    self._circuit_breaker.record_success()
                    # Track usage
                    self._usage_log.append({
                        "model": try_model,
                        "duration_ms": duration_ms,
                        "prompt_len": len(full),
                        "timestamp": datetime.now().isoformat(),
                    })
                    return r[0]["RESPONSE"]
            except Exception as e:
                self._circuit_breaker.record_failure()
                continue

        return None

    # ── SQL Generation ──
    def generate_sql(self, intent: str, tables: List[str] = None) -> Optional[str]:
        ctx = f"TABLES: {', '.join(tables)}\n\n" if tables else ""
        return self._extract_sql(self._complete(f"{ctx}TASK: {intent}", SYSTEM_PROMPTS["sql"]))

    # ── dbt Model ──
    def generate_dbt_model(self, description: str, source_tables: List[str],
                           layer: str = "staging", materialization: str = "view") -> Optional[Dict]:
        p = (f"Generate a dbt {layer} model.\nSOURCES: {', '.join(source_tables)}\n"
             f"MATERIALIZATION: {materialization}\nDESCRIPTION: {description}\n"
             f"Return JSON: model_name, sql, description, columns, tests, dependencies")
        return self._parse_json(self._complete(p, SYSTEM_PROMPTS["dbt"]))

    def suggest_dbt_tests(self, sql: str, columns: List[str]) -> Optional[List]:
        p = (f"Suggest tests for this model.\nSQL:\n```sql\n{sql[:3000]}\n```\n"
             f"COLUMNS: {', '.join(columns)}\nReturn JSON array: [{{column, test, config}}]")
        r = self._parse_json(self._complete(p, SYSTEM_PROMPTS["dbt"]))
        return r if isinstance(r, list) else None

    def generate_dbt_docs(self, sql: str, model_name: str) -> Optional[Dict]:
        p = (f"Generate docs for model {model_name}.\nSQL:\n```sql\n{sql[:3000]}\n```\n"
             f"Return JSON: description, columns[{{name, description, tests}}]")
        return self._parse_json(self._complete(p, SYSTEM_PROMPTS["dbt"]))

    # ── Pipeline ──
    def generate_pipeline_config(self, description: str, source_tables: List[str] = None,
                                 target: str = None) -> Optional[Dict]:
        p = (f"Design pipeline.\nDESCRIPTION: {description}\n"
             f"SOURCES: {', '.join(source_tables or [])}\nTARGET: {target or 'auto'}\n"
             f"Return JSON: pipeline_name, pipeline_type, steps[{{step_name, step_type, sql, config}}], recommendations")
        return self._parse_json(self._complete(p, SYSTEM_PROMPTS["pipeline"]))

    def suggest_dynamic_table(self, query: str, freshness: str = "1 hour") -> Optional[str]:
        p = f"Convert to Dynamic Table with TARGET_LAG={freshness}.\n```sql\n{query[:3000]}\n```"
        return self._extract_sql(self._complete(p, SYSTEM_PROMPTS["pipeline"]))

    # ── Debugging ──
    def explain_error(self, error: str, query: str = None) -> Optional[str]:
        p = f"ERROR: {error}"
        if query:
            p += f"\nSQL:\n```sql\n{query[:2000]}\n```"
        return self._complete(p, SYSTEM_PROMPTS["debug"])

    def debug_task_failure(self, task_name: str, error_code: str,
                           error_msg: str, sql: str = "") -> Optional[str]:
        p = f"Task: {task_name}\nError Code: {error_code}\nError: {error_msg}\nSQL: {sql[:2000]}"
        return self._complete(p, SYSTEM_PROMPTS["debug"])

    def diagnose_query(self, stats: Dict) -> Optional[str]:
        p = (f"Query: {stats.get('query_text','')[:2000]}\n"
             f"Duration: {stats.get('total_elapsed_time',0)/1000:.2f}s\n"
             f"Bytes: {stats.get('bytes_scanned',0)/1e6:.2f}MB\n"
             f"Partitions: {stats.get('partitions_scanned',0)}/{stats.get('partitions_total',0)}\n"
             f"WH: {stats.get('warehouse_name','?')} ({stats.get('warehouse_size','?')})")
        return self._complete(p, SYSTEM_PROMPTS["debug"])

    # ── Script Writing ──
    def write_script(self, description: str, script_type: str = "etl") -> Optional[str]:
        return self._complete(f"TYPE: {script_type}\nDESCRIPTION: {description}", SYSTEM_PROMPTS["script"])

    def optimize_sql(self, sql: str, profile: Dict = None) -> Optional[str]:
        p = f"```sql\n{sql[:4000]}\n```"
        if profile:
            p += f"\nDuration: {profile.get('duration_ms','?')}ms, Bytes: {profile.get('bytes_scanned','?')}"
        return self._complete(p, SYSTEM_PROMPTS["optimize"])

    def migrate_sql(self, sql: str, dialect: str = "auto") -> Optional[str]:
        return self._complete(f"Source dialect: {dialect}\n```sql\n{sql[:4000]}\n```", SYSTEM_PROMPTS["migrate"])

    # ── NEW V2: DMF Generation ──
    def generate_dmf(self, table_name: str, columns: List[str] = None,
                     check_type: str = "comprehensive") -> Optional[str]:
        """Generate Data Metric Functions for quality monitoring."""
        cols = f"\nCOLUMNS: {', '.join(columns)}" if columns else ""
        p = (f"Generate DMFs for table {table_name}.{cols}\n"
             f"CHECK_TYPE: {check_type}\n"
             f"Use SNOWFLAKE.CORE system DMFs where possible (NULL_COUNT, DUPLICATE_COUNT, FRESHNESS).\n"
             f"For custom checks, create user-defined DMFs.\n"
             f"Return SQL for CREATE OR REPLACE DATA METRIC FUNCTION statements.")
        return self._extract_sql(self._complete(p, SYSTEM_PROMPTS["dmf"]))

    # ── NEW V2: Task Graph ──
    def generate_task_graph(self, description: str, source_tables: List[str] = None) -> Optional[Dict]:
        """Design multi-step task DAGs from natural language."""
        p = (f"Design a Snowflake Task Graph.\nDESCRIPTION: {description}\n"
             f"SOURCES: {', '.join(source_tables or [])}\n"
             f"Return JSON: {{dag_name, warehouse, tasks: [{{name, sql, schedule, after, comment}}]}}")
        return self._parse_json(self._complete(p, SYSTEM_PROMPTS["task_graph"]))

    # ── NEW V2: Semantic Model ──
    def generate_semantic_model(self, tables: List[str],
                                description: str = "") -> Optional[str]:
        """Create Cortex Analyst YAML semantic models."""
        p = (f"Generate a Cortex Analyst semantic model YAML.\n"
             f"TABLES: {', '.join(tables)}\nDESCRIPTION: {description}\n"
             f"Include: name, tables with dimensions, measures, time_dimensions, relationships.")
        return self._complete(p, SYSTEM_PROMPTS["semantic"])

    # ── NEW V2: Query Plan Analysis ──
    def explain_query_plan(self, query: str, explain_output: str = "") -> Optional[str]:
        """Parse EXPLAIN output and suggest optimizations."""
        p = f"QUERY:\n```sql\n{query[:3000]}\n```"
        if explain_output:
            p += f"\n\nEXPLAIN OUTPUT:\n{explain_output[:3000]}"
        p += ("\n\nAnalyze and suggest:\n1. Clustering keys\n2. Search optimization\n"
              "3. Materialized views\n4. Warehouse sizing\n5. Join optimizations")
        return self._complete(p, SYSTEM_PROMPTS["query_plan"])

    # ── NEW V2: Stored Procedure ──
    def generate_stored_procedure(self, description: str, language: str = "sql",
                                   params: List[Dict] = None) -> Optional[str]:
        """Generate Snowflake stored procedures."""
        params_desc = ""
        if params:
            params_desc = "\nPARAMETERS:\n" + "\n".join(
                f"  - {p.get('name','?')} {p.get('type','VARCHAR')}: {p.get('description','')}"
                for p in params
            )
        p = (f"Generate a {language.upper()} stored procedure.\n"
             f"DESCRIPTION: {description}{params_desc}\n"
             f"Include error handling, logging, and RETURN statement.")
        return self._extract_sql(self._complete(p, SYSTEM_PROMPTS["stored_proc"]))

    # ── NEW V2: SQL Linter ──
    def lint_sql(self, sql: str) -> Optional[Dict]:
        """Check SQL against dbt Labs style guide."""
        p = (f"Lint this SQL against dbt Labs style guide:\n```sql\n{sql[:4000]}\n```\n"
             f"Check: snake_case, CTE structure, column ordering, naming conventions, "
             f"no abbreviations, explicit primary key naming.\n"
             f"Return JSON: {{issues: [{{line, severity, message, fix}}], score: 0-100}}")
        return self._parse_json(self._complete(p, SYSTEM_PROMPTS["lint"]))

    # ── NEW V2: Cost Estimation ──
    def estimate_cost(self, sql: str, warehouse_size: str = "MEDIUM") -> Optional[Dict]:
        """Estimate query cost and suggest optimizations."""
        p = (f"Estimate cost for this query on a {warehouse_size} warehouse:\n"
             f"```sql\n{sql[:4000]}\n```\n"
             f"Return JSON: {{estimated_credits, estimated_duration_s, "
             f"optimization_tips: [string], alternative_approaches: [string]}}")
        return self._parse_json(self._complete(p, SYSTEM_PROMPTS["cost"]))

    # ── Scaffolding ──
    def scaffold_project(self, project_type: str, params: Dict) -> Optional[Dict]:
        p = (f"Scaffold a {project_type} project.\nPARAMS: {json.dumps(params, default=str)}\n"
             f"Return JSON: project_name, files[{{path, content}}], config, setup_sql")
        return self._parse_json(self._complete(p, SYSTEM_PROMPTS["pipeline"]))

    # ── Usage Metrics ──
    def get_usage_stats(self) -> Dict:
        """Return usage statistics for the current session."""
        if not self._usage_log:
            return {"total_calls": 0}
        return {
            "total_calls": len(self._usage_log),
            "total_duration_ms": sum(u["duration_ms"] for u in self._usage_log),
            "avg_duration_ms": sum(u["duration_ms"] for u in self._usage_log) // len(self._usage_log),
            "models_used": list(set(u["model"] for u in self._usage_log)),
            "circuit_state": self._circuit_breaker.state,
        }

    # ── Helpers ──
    @staticmethod
    def _extract_sql(text):
        if not text:
            return None
        m = re.search(r"```sql\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
        if m:
            return m.group(1).strip()
        m = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
        if m:
            return m.group(1).strip()
        c = text.strip()
        return c if c.upper().startswith(("SELECT", "WITH", "CREATE", "INSERT", "MERGE", "ALTER", "DEFINE")) else text

    @staticmethod
    def _parse_json(text):
        if not text:
            return None
        m = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
        if m:
            text = m.group(1)
        else:
            s = text.find("{")
            e = text.rfind("}") + 1
            if s == -1:
                s = text.find("[")
                e = text.rfind("]") + 1
            if s != -1 and e > s:
                text = text[s:e]
        try:
            return json.loads(text)
        except:
            return None


_coco = None


def get_coco_client(session=None) -> CocoClient:
    global _coco
    if session is None and "snowflake_client" in st.session_state:
        session = st.session_state.snowflake_client.session
    if session is None:
        return None
    if _coco is None or _coco.session != session:
        _coco = CocoClient(session)
    return _coco
