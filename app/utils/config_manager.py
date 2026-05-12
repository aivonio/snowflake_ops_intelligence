import pandas as pd
import streamlit as st
from utils.snowflake_client import SnowflakeClient

class ConfigManager:
    def __init__(self, client: SnowflakeClient):
        self.client = client
        self.ensure_config_table()

    def ensure_config_table(self):
        """Ensure the APP_CONFIG table exists."""
        try:
            path = self.client.get_schema_path("APP_CONTEXT")
            # Create Schema if needed (idempotent)
            self.client.execute_query("CREATE SCHEMA IF NOT EXISTS APP_CONTEXT", log=False)
            
            ddl = f"""
            CREATE TABLE IF NOT EXISTS {path}.APP_CONFIG (
                CONFIG_KEY VARCHAR(255) PRIMARY KEY,
                CONFIG_VALUE VARCHAR(10000),
                CATEGORY VARCHAR(50),
                DESCRIPTION VARCHAR(255),
                UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
            )
            """
            self.client.execute_query(ddl, log=False)
        except Exception as e:
            # print(f"Config Table Init Warning: {e}")
            pass

    def get_config(self, key: str) -> str | None:
        """Retrieve a specific config value."""
        try:
            path = self.client.get_schema_path("APP_CONTEXT")
            query = f"SELECT CONFIG_VALUE FROM {path}.APP_CONFIG WHERE CONFIG_KEY = '{key}'"
            df = self.client.execute_query(query, log=False)
            if not df.empty:
                return str(df.iloc[0]['CONFIG_VALUE'])
            return None
        except:
            return None

    def get_all_configs(self, category: str | None = None) -> pd.DataFrame:
        """Retrieve all configs, optionally filtered by category."""
        try:
            path = self.client.get_schema_path("APP_CONTEXT")
            where = f"WHERE CATEGORY = '{category}'" if category else ""
            query = f"SELECT CONFIG_KEY, CONFIG_VALUE, CATEGORY, UPDATED_AT FROM {path}.APP_CONFIG {where} ORDER BY CONFIG_KEY"
            return self.client.execute_query(query, log=False)
        except:
            return pd.DataFrame()

    def set_config(self, key: str, value: str, category: str = 'GENERAL', description: str = ''):
        """Upsert a configuration value."""
        try:
            path = self.client.get_schema_path("APP_CONTEXT")
            # Using MERGE for Upsert
            query = f"""
            MERGE INTO {path}.APP_CONFIG t
            USING (SELECT '{key}' as K, '{value}' as V, '{category}' as C, '{description}' as D) s
            ON t.CONFIG_KEY = s.K
            WHEN MATCHED THEN UPDATE SET
                CONFIG_VALUE = s.V,
                CATEGORY = s.C,
                DESCRIPTION = s.D,
                UPDATED_AT = CURRENT_TIMESTAMP()
            WHEN NOT MATCHED THEN INSERT (CONFIG_KEY, CONFIG_VALUE, CATEGORY, DESCRIPTION)
            VALUES (s.K, s.V, s.C, s.D)
            """
            self.client.execute_write(query)
            return True
        except Exception as e:
            st.error(f"Failed to save {key}: {e}")
            return False

    def delete_config(self, key: str):
        """Delete a config key."""
        try:
            path = self.client.get_schema_path("APP_CONTEXT")
            self.client.execute_write(f"DELETE FROM {path}.APP_CONFIG WHERE CONFIG_KEY = '{key}'")
            return True
        except:
            return False
