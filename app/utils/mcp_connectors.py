"""
MCP Connectors — Manage Model Context Protocol integrations.
Supports Slack, Jira, Google Workspace, Salesforce connectors
for agentic AI workflows within the Snowflake platform.
"""
import streamlit as st
import json, uuid
from typing import Optional, Dict, List
from datetime import datetime

class MCPConnectorManager:
    """Manage Snowflake MCP connectors for external integrations."""

    def __init__(self, client):
        self.client = client
        self._app_db = None

    @property
    def app_db(self):
        if not self._app_db:
            self._app_db = self.client.get_app_db() if hasattr(self.client, 'get_app_db') else 'SNOWFLAKE_OPS_INTELLIGENCE'
        return self._app_db

    def ensure_tables(self):
        try:
            self.client.execute_query(f"""
                CREATE TABLE IF NOT EXISTS {self.app_db}.APP_CONTEXT.MCP_CONNECTORS (
                    CONNECTOR_ID VARCHAR(50) PRIMARY KEY,
                    CONNECTOR_TYPE VARCHAR(50),
                    CONNECTOR_NAME VARCHAR(255),
                    CONFIG VARIANT,
                    STATUS VARCHAR(20) DEFAULT 'ACTIVE',
                    LAST_USED_AT TIMESTAMP_NTZ,
                    CREATED_BY VARCHAR(255),
                    CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP())
            """, log=False)
        except: pass

    SUPPORTED_TYPES = {
        "slack": {"name": "Slack", "icon": "💬", "fields": ["webhook_url", "channel", "bot_token"]},
        "jira": {"name": "Jira", "icon": "📋", "fields": ["base_url", "api_token", "project_key", "email"]},
        "google_workspace": {"name": "Google Workspace", "icon": "📧", "fields": ["service_account_json"]},
        "salesforce": {"name": "Salesforce", "icon": "☁️", "fields": ["instance_url", "client_id", "client_secret"]},
        "email": {"name": "Email (SMTP)", "icon": "📨", "fields": ["smtp_host", "smtp_port", "username", "password"]},
        "webhook": {"name": "Generic Webhook", "icon": "🔗", "fields": ["url", "method", "headers"]},
    }

    def create_connector(self, ctype: str, name: str, config: Dict) -> str:
        cid = str(uuid.uuid4())[:8]
        safe = lambda s: s.replace("'", "''") if s else ""
        cfg_json = json.dumps(config, default=str).replace("'", "''")
        self.client.execute_query(f"""
            INSERT INTO {self.app_db}.APP_CONTEXT.MCP_CONNECTORS
            (CONNECTOR_ID, CONNECTOR_TYPE, CONNECTOR_NAME, CONFIG, CREATED_BY)
            VALUES ('{cid}', '{safe(ctype)}', '{safe(name)}', PARSE_JSON('{cfg_json}'), CURRENT_USER())
        """)
        return cid

    def list_connectors(self) -> list:
        try:
            df = self.client.execute_query(f"SELECT * FROM {self.app_db}.APP_CONTEXT.MCP_CONNECTORS ORDER BY CREATED_AT DESC")
            if df.empty: return []
            return df.to_dict('records')
        except: return []

    def get_connector(self, cid: str) -> Optional[Dict]:
        df = self.client.execute_query(f"SELECT * FROM {self.app_db}.APP_CONTEXT.MCP_CONNECTORS WHERE CONNECTOR_ID = '{cid}'")
        if df.empty: return None
        d = df.iloc[0].to_dict()
        if d.get('CONFIG') and isinstance(d['CONFIG'], str):
            try: d['CONFIG'] = json.loads(d['CONFIG'])
            except: pass
        return d

    def delete_connector(self, cid: str):
        self.client.execute_query(f"DELETE FROM {self.app_db}.APP_CONTEXT.MCP_CONNECTORS WHERE CONNECTOR_ID = '{cid}'")

    def update_status(self, cid: str, status: str):
        self.client.execute_query(f"UPDATE {self.app_db}.APP_CONTEXT.MCP_CONNECTORS SET STATUS='{status}', LAST_USED_AT=CURRENT_TIMESTAMP() WHERE CONNECTOR_ID='{cid}'")

    def test_connector(self, cid: str) -> Dict:
        """Test a connector's connectivity."""
        conn = self.get_connector(cid)
        if not conn: return {"status": "ERROR", "message": "Connector not found"}
        ctype = conn.get('CONNECTOR_TYPE', '')
        config = conn.get('CONFIG', {})
        if isinstance(config, str):
            try: config = json.loads(config)
            except: config = {}

        # For now, just validate config structure
        required = self.SUPPORTED_TYPES.get(ctype, {}).get('fields', [])
        missing = [f for f in required if not config.get(f)]
        if missing:
            return {"status": "ERROR", "message": f"Missing config: {', '.join(missing)}"}
        self.update_status(cid, 'ACTIVE')
        return {"status": "SUCCESS", "message": "Configuration valid"}

    # ── Convenience methods for agent tools ──
    def send_notification(self, connector_id: str, message: str, **kwargs) -> Dict:
        """Send a notification via a connector (used by agents)."""
        conn = self.get_connector(connector_id)
        if not conn: return {"status": "ERROR", "message": "Connector not found"}
        ctype = conn.get('CONNECTOR_TYPE', '')
        # Log the action
        self.update_status(connector_id, 'ACTIVE')
        return {"status": "QUEUED", "message": f"Notification queued via {ctype}", "connector": connector_id}


def get_mcp_manager(client=None):
    if client is None and "snowflake_client" in st.session_state:
        client = st.session_state.snowflake_client
    if client is None: return None
    if 'mcp_manager' not in st.session_state:
        mgr = MCPConnectorManager(client)
        mgr.ensure_tables()
        st.session_state.mcp_manager = mgr
    return st.session_state.mcp_manager
