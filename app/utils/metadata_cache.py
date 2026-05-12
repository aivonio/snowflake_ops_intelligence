"""
Metadata Cache Utility
Persistent caching for expensive Snowflake queries to save credits and improve UI speed.
"""

import json
from datetime import datetime, timedelta
from typing import Any, Optional
from .snowflake_client import get_snowflake_client

class MetadataCache:
    """
    Handles persistent caching of query results and metadata.
    Uses APP_ANALYTICS.METADATA_CACHE table for storage.
    """
    
    def __init__(self):
        self.client = get_snowflake_client()
        self._schema_path = None

    @property
    def schema_path(self):
        if not self._schema_path:
            self._schema_path = self.client.get_schema_path("APP_ANALYTICS")
        return self._schema_path

    def get(self, key: str) -> Optional[Any]:
        """Retrieve a value from cache if it hasn't expired"""
        try:
            query = f"""
            SELECT CACHE_VALUE, EXPIRY_TIME 
            FROM {self.schema_path}.METADATA_CACHE 
            WHERE CACHE_KEY = '{key}'
            """
            df = self.client.execute_query(query, log=False)
            
            if df.empty:
                return None
            
            row = df.iloc[0]
            expiry = row['EXPIRY_TIME']
            
            # Check if expired
            if expiry and expiry < datetime.now():
                return None
                
            val = row['CACHE_VALUE']
            return json.loads(val) if isinstance(val, str) else val
            
        except Exception:
            return None

    def set(self, key: str, value: Any, ttl_hours: int = 24):
        """Store a value in cache with a TTL"""
        try:
            expiry = datetime.now() + timedelta(hours=ttl_hours)
            # Convert to JSON if it's a dict or list
            json_val = json.dumps(value) if isinstance(value, (dict, list)) else value
            
            # MERDE logic
            query = f"""
            MERGE INTO {self.schema_path}.METADATA_CACHE t
            USING (SELECT '{key}' as K, PARSE_JSON('{json_val.replace("'", "''")}') as V, '{expiry.isoformat()}'::TIMESTAMP_NTZ as E) s
            ON t.CACHE_KEY = s.K
            WHEN MATCHED THEN UPDATE SET CACHE_VALUE = s.V, EXPIRY_TIME = s.E
            WHEN NOT MATCHED THEN INSERT (CACHE_KEY, CACHE_VALUE, EXPIRY_TIME) VALUES (s.K, s.V, s.E)
            """
            self.client.execute_write(query)
            return True
        except Exception as e:
            print(f"Cache write error: {e}")
            return False

    def clear(self, key: str = None):
        """Clear specific or all cache entries"""
        try:
            if key:
                query = f"DELETE FROM {self.schema_path}.METADATA_CACHE WHERE CACHE_KEY = '{key}'"
            else:
                query = f"DELETE FROM {self.schema_path}.METADATA_CACHE"
            self.client.execute_write(query)
        except Exception:
            pass

# Singleton instance
_cache = None

def get_metadata_cache() -> MetadataCache:
    global _cache
    if _cache is None:
        _cache = MetadataCache()
    return _cache
