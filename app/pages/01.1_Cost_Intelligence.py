"""
Cost Intelligence Page
Comprehensive cost visibility, attribution, and forecasting
"""

import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime, timedelta
import numpy as np
import numpy as np
import sys
import os

# Add parent directory to path for imports
try:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
except (NameError, TypeError):
    pass

from utils.snowflake_client import get_snowflake_client
from utils.formatters import format_credits, format_bytes, dataframe_to_excel_bytes
from utils.styles import apply_global_styles, render_page_header, COLORS

st.set_page_config(
    page_title="Cost Intelligence | Snowflake Ops",
    page_icon="💰",
    layout="wide"
)

# --- SECURITY: ADMIN ONLY ---
from utils.auth import verify_page_access
verify_page_access('ADMIN')
# ----------------------------

# Apply unified Snowflake design system
apply_global_styles()
from utils.styles import render_sidebar
render_sidebar()


@st.cache_data(ttl=300)
def get_credit_trends(_client, days=30):
    """Get daily credit usage trends"""
    query = f"""
    SELECT 
        DATE(START_TIME) as usage_date,
        SUM(CREDITS_USED) as total_credits,
        SUM(CREDITS_USED_COMPUTE) as compute_credits,
        SUM(CREDITS_USED_CLOUD_SERVICES) as cloud_credits
    FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
    WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
    GROUP BY DATE(START_TIME)
    ORDER BY usage_date
    """
    return _client.execute_query(query)


@st.cache_data(ttl=300)
def get_warehouse_costs(_client, days=30):
    """Get credit usage by warehouse"""
    query = f"""
    SELECT 
        WAREHOUSE_NAME,
        SUM(CREDITS_USED) as total_credits,
        SUM(CREDITS_USED_COMPUTE) as compute_credits,
        SUM(CREDITS_USED_CLOUD_SERVICES) as cloud_credits,
        COUNT(DISTINCT DATE(START_TIME)) as active_days,
        AVG(CREDITS_USED) as avg_hourly_credits
    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
    WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
    GROUP BY WAREHOUSE_NAME
    ORDER BY total_credits DESC
    """
    return _client.execute_query(query)


@st.cache_data(ttl=300)
def get_user_costs(_client, days=30):
    """Get credit usage by user"""
    query = f"""
    SELECT 
        USER_NAME,
        COUNT(*) as query_count,
        SUM(TOTAL_ELAPSED_TIME) / 1000 / 60 as total_time_min,
        SUM(BYTES_SCANNED) / POWER(1024, 3) as total_gb_scanned,
        AVG(BYTES_SCANNED) / POWER(1024, 3) as avg_gb_per_query,
        SUM(CREDITS_USED_CLOUD_SERVICES) as cloud_credits,
        COUNT(CASE WHEN EXECUTION_STATUS = 'FAIL' THEN 1 END) as failed_queries
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        AND QUERY_TYPE NOT IN ('DESCRIBE', 'SHOW')
    GROUP BY USER_NAME
    ORDER BY total_gb_scanned DESC NULLS LAST
    """
    return _client.execute_query(query)


@st.cache_data(ttl=300)
def get_role_costs(_client, days=30):
    """Get credit usage by role"""
    query = f"""
    SELECT 
        ROLE_NAME,
        COUNT(*) as query_count,
        SUM(Total_ELAPSED_TIME) / 1000 / 60 as total_time_min,
        SUM(BYTES_SCANNED) / POWER(1024, 3) as total_gb_scanned,
        SUM(CREDITS_USED_CLOUD_SERVICES) as cloud_credits
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        AND QUERY_TYPE NOT IN ('DESCRIBE', 'SHOW')
    GROUP BY ROLE_NAME
    ORDER BY total_gb_scanned DESC NULLS LAST
    """
    return _client.execute_query(query)


@st.cache_data(ttl=300)
def get_hourly_pattern(_client, days=7):
    """Get hourly usage patterns"""
    query = f"""
    SELECT 
        HOUR(START_TIME) as hour_of_day,
        DAYNAME(START_TIME) as day_of_week,
        AVG(CREDITS_USED) as avg_credits
    FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
    WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
    GROUP BY HOUR(START_TIME), DAYNAME(START_TIME)
    ORDER BY hour_of_day
    """
    return _client.execute_query(query)


@st.cache_data(ttl=300)
def get_storage_costs(_client):
    """Get storage usage and costs"""
    query = """
    SELECT 
        USAGE_DATE,
        STORAGE_BYTES / POWER(1024, 4) as storage_tb,
        STAGE_BYTES / POWER(1024, 4) as stage_tb,
        FAILSAFE_BYTES / POWER(1024, 4) as failsafe_tb,
        (STORAGE_BYTES + STAGE_BYTES + FAILSAFE_BYTES) / POWER(1024, 4) as total_tb
    FROM SNOWFLAKE.ACCOUNT_USAGE.STORAGE_USAGE
    WHERE USAGE_DATE >= DATEADD(day, -30, CURRENT_DATE())
    ORDER BY USAGE_DATE DESC
    """
    return _client.execute_query(query)


@st.cache_data(ttl=300)
def get_cost_anomalies(_client, days=30, threshold=2.0):
    """Detect cost anomalies - days with credits > threshold * average"""
    # ... (existing code)
    query = f"""
    WITH daily_credits AS (
        SELECT 
            DATE(START_TIME) as usage_date,
            SUM(CREDITS_USED) as daily_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
        WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        GROUP BY DATE(START_TIME)
    ),
    stats AS (
        SELECT 
            AVG(daily_credits) as avg_credits,
            STDDEV(daily_credits) as stddev_credits
        FROM daily_credits
    )
    SELECT 
        dc.usage_date,
        dc.daily_credits,
        s.avg_credits,
        (dc.daily_credits - s.avg_credits) / NULLIF(s.stddev_credits, 0) as z_score
    FROM daily_credits dc, stats s
    WHERE dc.daily_credits > s.avg_credits * {threshold}
    ORDER BY dc.usage_date DESC
    """
    return _client.execute_query(query)

@st.cache_data(ttl=300)
def get_query_tag_costs(_client, days=30):
    """Get credit usage breakdown by Query Tag"""
    query = f"""
    SELECT 
        QUERY_TAG,
        COUNT(*) as query_count,
        SUM(TOTAL_ELAPSED_TIME) / 1000 / 60 as total_time_min,
        SUM(CREDITS_USED_CLOUD_SERVICES) as cloud_credits
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        AND QUERY_TYPE NOT IN ('DESCRIBE', 'SHOW')
        AND QUERY_TAG IS NOT NULL AND QUERY_TAG != ''
    GROUP BY QUERY_TAG
    ORDER BY total_time_min DESC
    LIMIT 20
    """
    return _client.execute_query(query)

@st.cache_data(ttl=300)
def get_expensive_queries(_client, days=30):
    """Get most expensive queries individually"""
    query = f"""
    SELECT 
        QUERY_ID,
        QUERY_TEXT,
        USER_NAME,
        WAREHOUSE_NAME,
        START_TIME,
        TOTAL_ELAPSED_TIME / 1000 as duration_sec,
        BYTES_SCANNED / POWER(1024, 3) as gb_scanned,
        CREDITS_USED_CLOUD_SERVICES as cloud_credits
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        AND TOTAL_ELAPSED_TIME > 10000 -- Only queries > 10s
    ORDER BY TOTAL_ELAPSED_TIME DESC
    LIMIT 50
    """
    return _client.execute_query(query)



@st.cache_data(ttl=300)
def get_user_warehouse_usage(_client, days=30):
    """Get usage breakdown by Warehouse AND User (for Sankey)"""
    query = f"""
    SELECT 
        WAREHOUSE_NAME,
        USER_NAME,
        SUM(TOTAL_ELAPSED_TIME) as total_time_ms
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        AND WAREHOUSE_NAME IS NOT NULL
        AND TOTAL_ELAPSED_TIME > 0
    GROUP BY WAREHOUSE_NAME, USER_NAME
    """
    return _client.execute_query(query)


@st.cache_data(ttl=300)
def get_dbt_costs(_client, days=30):
    """Get cost breakdown by dbt Model"""
    query = f"""
    WITH query_stats AS (
        SELECT 
            QUERY_TAG,
            -- Try to parse DBT Model from JSON tag (standard dbt format)
            TRY_PARSE_JSON(QUERY_TAG):node::STRING as DBT_NODE,
            
            -- Fallback for custom string tags like "dbt_model:my_model"
            CASE 
                WHEN DBT_NODE IS NOT NULL THEN DBT_NODE
                WHEN CONTAINS(QUERY_TAG, 'dbt_model:') THEN SPLIT_PART(QUERY_TAG, 'dbt_model:', 2)
                ELSE NULL 
            END as MODEL_NAME,
            
            -- Estimate Credits
            (EXECUTION_TIME / 1000.0 / 3600.0) * 
            CASE 
                WHEN WAREHOUSE_SIZE = 'X-Small' THEN 1
                WHEN WAREHOUSE_SIZE = 'Small' THEN 2
                WHEN WAREHOUSE_SIZE = 'Medium' THEN 4
                WHEN WAREHOUSE_SIZE = 'Large' THEN 8
                WHEN WAREHOUSE_SIZE = 'X-Large' THEN 16
                WHEN WAREHOUSE_SIZE = '2X-Large' THEN 32
                WHEN WAREHOUSE_SIZE = '3X-Large' THEN 64
                WHEN WAREHOUSE_SIZE = '4X-Large' THEN 128
                ELSE 1 
            END as EST_CREDITS
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        AND WAREHOUSE_NAME IS NOT NULL
        AND EXECUTION_TIME > 0
        AND (QUERY_TAG LIKE '%dbt%' OR TRY_PARSE_JSON(QUERY_TAG):node IS NOT NULL)
    )
    SELECT 
        MODEL_NAME,
        SUM(EST_CREDITS) as TOTAL_CREDITS,
        COUNT(*) as EXECUTION_COUNT,
        AVG(EST_CREDITS) as AVG_CREDITS_PER_RUN
    FROM query_stats
    WHERE MODEL_NAME IS NOT NULL
    GROUP BY 1
    ORDER BY 2 DESC
    LIMIT 100
    """
    return _client.execute_query(query)


# =====================================================
# COST GUARDIAN DATA QUERIES
# =====================================================

@st.cache_data(ttl=120)
def get_hourly_burst_data(_client, days=7):
    """Get hourly credit consumption per warehouse for burst detection."""
    query = f"""
    WITH hourly AS (
        SELECT 
            WAREHOUSE_NAME,
            DATE_TRUNC('hour', START_TIME) AS HOUR_BUCKET,
            SUM(CREDITS_USED) AS HOURLY_CREDITS
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        GROUP BY 1, 2
    ),
    stats AS (
        SELECT 
            WAREHOUSE_NAME,
            AVG(HOURLY_CREDITS) AS AVG_HOURLY,
            STDDEV(HOURLY_CREDITS) AS STD_HOURLY
        FROM hourly
        GROUP BY 1
    )
    SELECT 
        h.WAREHOUSE_NAME,
        h.HOUR_BUCKET,
        h.HOURLY_CREDITS,
        s.AVG_HOURLY,
        s.STD_HOURLY,
        CASE WHEN s.STD_HOURLY > 0 
             THEN (h.HOURLY_CREDITS - s.AVG_HOURLY) / s.STD_HOURLY 
             ELSE 0 END AS Z_SCORE,
        CASE 
            WHEN h.HOURLY_CREDITS > s.AVG_HOURLY * 3 THEN 'CRITICAL'
            WHEN h.HOURLY_CREDITS > s.AVG_HOURLY * 2 THEN 'WARNING'
            ELSE 'NORMAL'
        END AS SEVERITY
    FROM hourly h
    JOIN stats s ON h.WAREHOUSE_NAME = s.WAREHOUSE_NAME
    ORDER BY h.HOUR_BUCKET DESC
    """
    return _client.execute_query(query)


@st.cache_data(ttl=120)
def get_warehouse_live_status(_client):
    """Get current warehouse states and recent credit burn."""
    try:
        # Step 1: Get warehouse list via SHOW WAREHOUSES (returns DataFrame directly)
        wh_df = _client.execute_query("SHOW WAREHOUSES", log=False)
        
        if wh_df.empty:
            return pd.DataFrame()
        
        # Normalize column names (SHOW commands return lowercase sometimes)
        wh_df.columns = [c.upper() for c in wh_df.columns]
        
        # Extract relevant columns safely
        cols_map = {}
        for target, candidates in {
            'WAREHOUSE_NAME': ['NAME', 'WAREHOUSE_NAME'],
            'STATE': ['STATE', 'STATUS'],
            'SIZE': ['SIZE', 'WAREHOUSE_SIZE'],
            'AUTO_SUSPEND': ['AUTO_SUSPEND'],
            'AUTO_RESUME': ['AUTO_RESUME'],
        }.items():
            for c in candidates:
                if c in wh_df.columns:
                    cols_map[target] = c
                    break
        
        if 'WAREHOUSE_NAME' not in cols_map:
            return pd.DataFrame()
        
        result = pd.DataFrame()
        result['WAREHOUSE_NAME'] = wh_df[cols_map['WAREHOUSE_NAME']]
        result['STATE'] = wh_df[cols_map.get('STATE', cols_map['WAREHOUSE_NAME'])].astype(str) if 'STATE' in cols_map else 'UNKNOWN'
        result['SIZE'] = wh_df[cols_map.get('SIZE', cols_map['WAREHOUSE_NAME'])].astype(str) if 'SIZE' in cols_map else 'N/A'
        result['AUTO_SUSPEND'] = wh_df[cols_map['AUTO_SUSPEND']].astype(str) if 'AUTO_SUSPEND' in cols_map else 'N/A'
        result['AUTO_RESUME'] = wh_df[cols_map['AUTO_RESUME']].astype(str) if 'AUTO_RESUME' in cols_map else 'N/A'
        
        # Step 2: Get credit usage from metering history
        credit_query = """
        SELECT 
            WAREHOUSE_NAME,
            SUM(CASE WHEN START_TIME >= DATEADD(hour, -1, CURRENT_TIMESTAMP()) THEN CREDITS_USED ELSE 0 END) AS CREDITS_LAST_HOUR,
            SUM(CASE WHEN START_TIME >= DATE_TRUNC('day', CURRENT_TIMESTAMP()) THEN CREDITS_USED ELSE 0 END) AS CREDITS_TODAY
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE START_TIME >= DATEADD(day, -1, CURRENT_TIMESTAMP())
        GROUP BY 1
        """
        credits_df = _client.execute_query(credit_query, log=False)
        
        if not credits_df.empty:
            result = result.merge(credits_df, on='WAREHOUSE_NAME', how='left')
            result['CREDITS_LAST_HOUR'] = result['CREDITS_LAST_HOUR'].fillna(0)
            result['CREDITS_TODAY'] = result['CREDITS_TODAY'].fillna(0)
        else:
            result['CREDITS_LAST_HOUR'] = 0.0
            result['CREDITS_TODAY'] = 0.0
        
        return result.sort_values('CREDITS_TODAY', ascending=False).reset_index(drop=True)
        
    except Exception as e:
        # Ultimate fallback: just metering history
        try:
            fallback = """
            SELECT 
                WAREHOUSE_NAME,
                SUM(CASE WHEN START_TIME >= DATEADD(hour, -1, CURRENT_TIMESTAMP()) THEN CREDITS_USED ELSE 0 END) AS CREDITS_LAST_HOUR,
                SUM(CASE WHEN START_TIME >= DATE_TRUNC('day', CURRENT_TIMESTAMP()) THEN CREDITS_USED ELSE 0 END) AS CREDITS_TODAY
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
            WHERE START_TIME >= DATEADD(day, -1, CURRENT_TIMESTAMP())
            GROUP BY 1
            ORDER BY CREDITS_TODAY DESC
            """
            return _client.execute_query(fallback)
        except:
            return pd.DataFrame()


@st.cache_data(ttl=120)
def get_full_query_attribution(_client, days=7, limit=200):
    """Full query cost attribution table matching Snowflake native UI."""
    query = f"""
    SELECT 
        QUERY_ID,
        LEFT(QUERY_TEXT, 300) AS SQL_TEXT,
        EXECUTION_STATUS AS STATUS,
        USER_NAME,
        ROLE_NAME,
        WAREHOUSE_NAME,
        WAREHOUSE_SIZE,
        TOTAL_ELAPSED_TIME / 1000 AS DURATION_S,
        START_TIME,
        ROWS_PRODUCED AS ROWS_RETURNED,
        CREDITS_USED_CLOUD_SERVICES AS CLOUD_CREDITS,
        BYTES_SCANNED / POWER(1024, 3) AS GB_SCANNED,
        BYTES_WRITTEN / POWER(1024, 2) AS MB_WRITTEN,
        COMPILATION_TIME / 1000 AS COMPILE_S,
        EXECUTION_TIME / 1000 AS EXEC_S,
        QUEUED_PROVISIONING_TIME / 1000 AS QUEUE_S,
        -- Estimated compute credits
        (EXECUTION_TIME / 1000.0 / 3600.0) * 
        CASE 
            WHEN WAREHOUSE_SIZE = 'X-Small' THEN 1
            WHEN WAREHOUSE_SIZE = 'Small' THEN 2
            WHEN WAREHOUSE_SIZE = 'Medium' THEN 4
            WHEN WAREHOUSE_SIZE = 'Large' THEN 8
            WHEN WAREHOUSE_SIZE = 'X-Large' THEN 16
            WHEN WAREHOUSE_SIZE = '2X-Large' THEN 32
            WHEN WAREHOUSE_SIZE = '3X-Large' THEN 64
            ELSE 1 
        END AS EST_CREDITS
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        AND WAREHOUSE_NAME IS NOT NULL
    ORDER BY TOTAL_ELAPSED_TIME DESC
    LIMIT {limit}
    """
    return _client.execute_query(query)


@st.cache_data(ttl=300)
def get_failed_query_costs(_client, days=30):
    """Failed query cost calculator — total credits wasted on failures."""
    query = f"""
    SELECT 
        USER_NAME,
        WAREHOUSE_NAME,
        WAREHOUSE_SIZE,
        COUNT(*) AS FAILED_COUNT,
        SUM(CREDITS_USED_CLOUD_SERVICES) AS WASTED_CLOUD_CREDITS,
        SUM(TOTAL_ELAPSED_TIME) / 1000 AS TOTAL_DURATION_S,
        SUM(BYTES_SCANNED) / POWER(1024, 3) AS TOTAL_GB_SCANNED,
        -- Estimated compute credits wasted
        SUM(
            (EXECUTION_TIME / 1000.0 / 3600.0) * 
            CASE 
                WHEN WAREHOUSE_SIZE = 'X-Small' THEN 1
                WHEN WAREHOUSE_SIZE = 'Small' THEN 2
                WHEN WAREHOUSE_SIZE = 'Medium' THEN 4
                WHEN WAREHOUSE_SIZE = 'Large' THEN 8
                WHEN WAREHOUSE_SIZE = 'X-Large' THEN 16
                WHEN WAREHOUSE_SIZE = '2X-Large' THEN 32
                ELSE 1 
            END
        ) AS EST_WASTED_CREDITS
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE EXECUTION_STATUS = 'FAIL'
        AND START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        AND WAREHOUSE_NAME IS NOT NULL
    GROUP BY 1, 2, 3
    ORDER BY EST_WASTED_CREDITS DESC
    """
    return _client.execute_query(query)


@st.cache_data(ttl=300)
def get_failed_query_details(_client, days=7):
    """Individual failed queries with error messages."""
    query = f"""
    SELECT 
        QUERY_ID,
        LEFT(QUERY_TEXT, 200) AS SQL_PREVIEW,
        ERROR_MESSAGE,
        USER_NAME,
        WAREHOUSE_NAME,
        TOTAL_ELAPSED_TIME / 1000 AS DURATION_S,
        START_TIME,
        CREDITS_USED_CLOUD_SERVICES AS CLOUD_CREDITS
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE EXECUTION_STATUS = 'FAIL'
        AND START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        AND WAREHOUSE_NAME IS NOT NULL
    ORDER BY START_TIME DESC
    LIMIT 100
    """
    return _client.execute_query(query)


@st.cache_data(ttl=300)
def get_notebook_costs(_client, days=30):
    """Track Snowflake Notebook costs by session."""
    query = f"""
    SELECT 
        USER_NAME,
        WAREHOUSE_NAME,
        QUERY_TAG,
        DATE_TRUNC('hour', START_TIME) AS SESSION_HOUR,
        COUNT(*) AS QUERY_COUNT,
        SUM(TOTAL_ELAPSED_TIME) / 1000 AS TOTAL_DURATION_S,
        SUM(CREDITS_USED_CLOUD_SERVICES) AS CLOUD_CREDITS,
        SUM(
            (EXECUTION_TIME / 1000.0 / 3600.0) * 
            CASE 
                WHEN WAREHOUSE_SIZE = 'X-Small' THEN 1
                WHEN WAREHOUSE_SIZE = 'Small' THEN 2
                WHEN WAREHOUSE_SIZE = 'Medium' THEN 4
                WHEN WAREHOUSE_SIZE = 'Large' THEN 8
                WHEN WAREHOUSE_SIZE = 'X-Large' THEN 16
                WHEN WAREHOUSE_SIZE = '2X-Large' THEN 32
                ELSE 1 
            END
        ) AS EST_CREDITS,
        SUM(CASE WHEN EXECUTION_STATUS = 'FAIL' THEN 1 ELSE 0 END) AS FAILED_QUERIES,
        SUM(BYTES_SCANNED) / POWER(1024, 3) AS GB_SCANNED
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        AND (
            QUERY_TAG ILIKE '%notebook%' 
            OR QUERY_TEXT ILIKE '%-- Notebook%'
            OR QUERY_TEXT ILIKE '%-- Snowsight%'
            OR QUERY_TAG ILIKE '%worksheets%'
        )
        AND WAREHOUSE_NAME IS NOT NULL
    GROUP BY 1, 2, 3, 4
    ORDER BY EST_CREDITS DESC
    LIMIT 200
    """
    return _client.execute_query(query)


@st.cache_data(ttl=300)
def get_warehouse_optimization_scan(_client, days=14):
    """Deep warehouse health scan for optimization opportunities."""
    query = f"""
    WITH wh_metrics AS (
        SELECT 
            q.WAREHOUSE_NAME,
            COUNT(*) AS TOTAL_QUERIES,
            AVG(q.TOTAL_ELAPSED_TIME) / 1000 AS AVG_DURATION_S,
            MAX(q.TOTAL_ELAPSED_TIME) / 1000 AS MAX_DURATION_S,
            AVG(q.BYTES_SCANNED) / POWER(1024, 3) AS AVG_GB_SCANNED,
            SUM(CASE WHEN q.EXECUTION_STATUS = 'FAIL' THEN 1 ELSE 0 END) AS FAILED_QUERIES,
            SUM(CASE WHEN q.EXECUTION_STATUS = 'FAIL' THEN 1.0 ELSE 0.0 END) / NULLIF(COUNT(*), 0) * 100 AS FAIL_RATE_PCT,
            AVG(q.QUEUED_PROVISIONING_TIME + q.QUEUED_OVERLOAD_TIME + q.QUEUED_REPAIR_TIME) / 1000 AS AVG_QUEUE_S,
            MAX(q.QUEUED_PROVISIONING_TIME + q.QUEUED_OVERLOAD_TIME + q.QUEUED_REPAIR_TIME) / 1000 AS MAX_QUEUE_S,
            AVG(q.BYTES_SPILLED_TO_LOCAL_STORAGE) / POWER(1024, 3) AS AVG_SPILL_LOCAL_GB,
            AVG(q.BYTES_SPILLED_TO_REMOTE_STORAGE) / POWER(1024, 3) AS AVG_SPILL_REMOTE_GB,
            SUM(CASE WHEN q.BYTES_SPILLED_TO_REMOTE_STORAGE > 0 THEN 1 ELSE 0 END) AS REMOTE_SPILL_COUNT,
            AVG(q.PERCENTAGE_SCANNED_FROM_CACHE) AS AVG_CACHE_HIT_PCT,
            COUNT(DISTINCT q.USER_NAME) AS UNIQUE_USERS
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            AND q.WAREHOUSE_NAME IS NOT NULL
            AND q.TOTAL_ELAPSED_TIME > 0
        GROUP BY 1
    ),
    wh_credits AS (
        SELECT 
            WAREHOUSE_NAME,
            SUM(CREDITS_USED) AS TOTAL_CREDITS,
            SUM(CREDITS_USED_COMPUTE) AS COMPUTE_CREDITS,
            SUM(CREDITS_USED_CLOUD_SERVICES) AS CLOUD_CREDITS
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        GROUP BY 1
    ),
    wh_load AS (
        SELECT 
            WAREHOUSE_NAME,
            AVG(AVG_RUNNING) AS AVG_LOAD,
            AVG(AVG_QUEUED_LOAD) AS AVG_QUEUED,
            MAX(AVG_RUNNING) AS PEAK_LOAD
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_LOAD_HISTORY
        WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        GROUP BY 1
    )
    SELECT 
        m.WAREHOUSE_NAME,
        COALESCE(c.TOTAL_CREDITS, 0) AS TOTAL_CREDITS,
        m.TOTAL_QUERIES,
        m.AVG_DURATION_S,
        m.MAX_DURATION_S,
        m.FAILED_QUERIES,
        m.FAIL_RATE_PCT,
        m.AVG_QUEUE_S,
        m.MAX_QUEUE_S,
        m.AVG_SPILL_LOCAL_GB,
        m.AVG_SPILL_REMOTE_GB,
        m.REMOTE_SPILL_COUNT,
        m.AVG_CACHE_HIT_PCT,
        m.AVG_GB_SCANNED,
        m.UNIQUE_USERS,
        COALESCE(l.AVG_LOAD, 0) AS AVG_LOAD,
        COALESCE(l.AVG_QUEUED, 0) AS AVG_QUEUED_LOAD,
        COALESCE(l.PEAK_LOAD, 0) AS PEAK_LOAD,
        -- OPTIMIZATION SCORE (0-100, lower = needs more optimization)
        GREATEST(0, LEAST(100,
            100 
            - (CASE WHEN m.FAIL_RATE_PCT > 10 THEN 20 WHEN m.FAIL_RATE_PCT > 5 THEN 10 ELSE 0 END)
            - (CASE WHEN m.AVG_QUEUE_S > 10 THEN 20 WHEN m.AVG_QUEUE_S > 3 THEN 10 ELSE 0 END)
            - (CASE WHEN m.AVG_SPILL_REMOTE_GB > 0.1 THEN 20 WHEN m.AVG_SPILL_LOCAL_GB > 1 THEN 10 ELSE 0 END)
            - (CASE WHEN m.AVG_CACHE_HIT_PCT < 30 THEN 15 WHEN m.AVG_CACHE_HIT_PCT < 60 THEN 5 ELSE 0 END)
            - (CASE WHEN COALESCE(l.AVG_LOAD, 0) < 0.05 AND COALESCE(c.TOTAL_CREDITS, 0) > 1 THEN 15 ELSE 0 END)
        )) AS HEALTH_SCORE
    FROM wh_metrics m
    LEFT JOIN wh_credits c ON m.WAREHOUSE_NAME = c.WAREHOUSE_NAME
    LEFT JOIN wh_load l ON m.WAREHOUSE_NAME = l.WAREHOUSE_NAME
    ORDER BY COALESCE(c.TOTAL_CREDITS, 0) DESC
    """
    return _client.execute_query(query)


@st.cache_data(ttl=300)
def get_existing_alerts(_client):
    """Get existing Snowflake alerts."""
    try:
        return _client.execute_query("SHOW ALERTS", log=False)
    except:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def get_user_performance_scorecard(_client, days=14):
    """User Performance Scorecard — identify who's running unoptimized queries."""
    query = f"""
    SELECT 
        USER_NAME,
        COUNT(*) AS TOTAL_QUERIES,
        SUM(CASE WHEN EXECUTION_STATUS = 'FAIL' THEN 1 ELSE 0 END) AS FAILED_QUERIES,
        ROUND(SUM(CASE WHEN EXECUTION_STATUS = 'FAIL' THEN 1.0 ELSE 0 END) / NULLIF(COUNT(*), 0) * 100, 1) AS FAIL_RATE_PCT,
        ROUND(AVG(TOTAL_ELAPSED_TIME) / 1000, 2) AS AVG_DURATION_S,
        ROUND(MAX(TOTAL_ELAPSED_TIME) / 1000, 2) AS MAX_DURATION_S,
        ROUND(AVG(BYTES_SCANNED) / POWER(1024, 3), 4) AS AVG_GB_SCANNED,
        ROUND(SUM(BYTES_SCANNED) / POWER(1024, 3), 3) AS TOTAL_GB_SCANNED,
        ROUND(AVG(PERCENTAGE_SCANNED_FROM_CACHE), 1) AS AVG_CACHE_HIT_PCT,
        SUM(CASE WHEN BYTES_SPILLED_TO_REMOTE_STORAGE > 0 THEN 1 ELSE 0 END) AS REMOTE_SPILL_QUERIES,
        SUM(CASE WHEN BYTES_SPILLED_TO_LOCAL_STORAGE > 0 THEN 1 ELSE 0 END) AS LOCAL_SPILL_QUERIES,
        ROUND(SUM(CREDITS_USED_CLOUD_SERVICES), 4) AS TOTAL_CLOUD_CREDITS,
        -- Estimated compute credits
        ROUND(SUM(
            (EXECUTION_TIME / 1000.0 / 3600.0) * 
            CASE 
                WHEN WAREHOUSE_SIZE = 'X-Small' THEN 1
                WHEN WAREHOUSE_SIZE = 'Small' THEN 2
                WHEN WAREHOUSE_SIZE = 'Medium' THEN 4
                WHEN WAREHOUSE_SIZE = 'Large' THEN 8
                WHEN WAREHOUSE_SIZE = 'X-Large' THEN 16
                WHEN WAREHOUSE_SIZE = '2X-Large' THEN 32
                ELSE 1 
            END
        ), 4) AS EST_TOTAL_CREDITS,
        COUNT(DISTINCT WAREHOUSE_NAME) AS WAREHOUSES_USED,
        COUNT(DISTINCT DATE(START_TIME)) AS ACTIVE_DAYS,
        -- User efficiency score (0-100)
        GREATEST(0, LEAST(100,
            100 
            - (CASE WHEN SUM(CASE WHEN EXECUTION_STATUS='FAIL' THEN 1.0 ELSE 0 END)/NULLIF(COUNT(*),0)*100 > 20 THEN 30 
                    WHEN SUM(CASE WHEN EXECUTION_STATUS='FAIL' THEN 1.0 ELSE 0 END)/NULLIF(COUNT(*),0)*100 > 10 THEN 20 
                    WHEN SUM(CASE WHEN EXECUTION_STATUS='FAIL' THEN 1.0 ELSE 0 END)/NULLIF(COUNT(*),0)*100 > 5 THEN 10 ELSE 0 END)
            - (CASE WHEN AVG(TOTAL_ELAPSED_TIME)/1000 > 300 THEN 15 WHEN AVG(TOTAL_ELAPSED_TIME)/1000 > 60 THEN 5 ELSE 0 END)
            - (CASE WHEN AVG(PERCENTAGE_SCANNED_FROM_CACHE) < 20 THEN 15 WHEN AVG(PERCENTAGE_SCANNED_FROM_CACHE) < 50 THEN 5 ELSE 0 END)
            - (CASE WHEN SUM(CASE WHEN BYTES_SPILLED_TO_REMOTE_STORAGE > 0 THEN 1 ELSE 0 END) > 10 THEN 20 
                    WHEN SUM(CASE WHEN BYTES_SPILLED_TO_REMOTE_STORAGE > 0 THEN 1 ELSE 0 END) > 3 THEN 10 ELSE 0 END)
            - (CASE WHEN MAX(TOTAL_ELAPSED_TIME)/1000 > 3600 THEN 10 ELSE 0 END)
        )) AS EFFICIENCY_SCORE
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        AND WAREHOUSE_NAME IS NOT NULL
        AND TOTAL_ELAPSED_TIME > 0
    GROUP BY 1
    ORDER BY EST_TOTAL_CREDITS DESC
    """
    return _client.execute_query(query)


def main():
    st.title("💰 Cost Intelligence")
    st.markdown("*Real-time visibility, attribution, and cost optimization insights*")
    
    # Get client
    client = get_snowflake_client()
    
    if not client.session:
        st.error("⚠️ Could not connect to Snowflake")
        return
    
    # Time range selector
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        time_range = st.selectbox(
            "Time Range",
            options=[7, 14, 30, 60, 90],
            format_func=lambda x: f"Last {x} days",
            index=2
        )
    
    with col2:
        if st.button("🔄 Refresh Data"):
            st.cache_data.clear()
            st.rerun()
    
    # Tabs for different views
    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9, tab10, tab11, tab12, tab13, tab14, tab15 = st.tabs([
        "📊 Overview", 
        "🏭 By Warehouse",
        "📥 Ingestion", 
        "👤 By User",
        "🛡️ By Role",
        "📈 Patterns",
        "🕵️ Deep Dive",
        "⚠️ Anomalies",
        "🔮 Forecast",
        "🟧 dbt Models",
        "🚨 Cost Guardian",
        "📋 Query Attribution",
        "🔔 Alert Builder",
        "🏥 Warehouse Optimizer",
        "🛡️ Resource Monitors"
    ])
    
    with tab1:
        render_cost_overview(client, time_range)
    
    with tab2:
        render_warehouse_costs(client, time_range)
    
    with tab3:
        render_ingestion_costs(client, time_range)
        
    with tab4:
        render_user_costs(client, time_range)
        
    with tab5:
        render_role_costs(client, time_range)
    
    with tab6:
        render_usage_patterns(client)
        
    with tab7:
        render_deep_dive(client, time_range)
    
    with tab8:
        render_anomalies(client, time_range)

    with tab9:
        render_forecast(client, time_range)
        
    with tab10:
        render_dbt_models(client, time_range)
    
    with tab11:
        render_cost_guardian(client, time_range)
    
    with tab12:
        render_query_attribution(client, time_range)
    
    with tab13:
        render_alert_builder(client)
    
    with tab14:
        render_warehouse_optimizer(client, time_range)
    
    with tab15:
        render_resource_monitors(client)


def get_budget_config(client):
    """Fetch total budget from APP_CONFIG or default to 400"""
    try:
        # Check if we have a config override
        res = client.execute_query("SELECT CONFIG_VALUE FROM APP_CONTEXT.APP_CONFIG WHERE CONFIG_KEY = 'TOTAL_BUDGET'")
        if not res.empty:
            return float(res.iloc[0]['CONFIG_VALUE'])
    except:
        pass
    return 400.0


def render_cost_overview(client, days):
    """Render cost overview section"""
    st.markdown("### 💳 Credit Usage & Cost Estimates")
    
    # 1. Fetch Data
    trends = get_credit_trends(client, days)
    storage = get_storage_costs(client)
    
    if trends.empty:
        st.info("No credit usage data available for the selected period.")
        return
    
    # 2. Key Metrics Calculation
    total_credits = float(trends['TOTAL_CREDITS'].sum())
    compute_credits = float(trends['COMPUTE_CREDITS'].sum())
    cloud_credits = float(trends['CLOUD_CREDITS'].sum())
    avg_daily = float(trends['TOTAL_CREDITS'].mean())
    
    # Forecast (Monthly extrapolation based on avg daily)
    projected_monthly = avg_daily * 30
    
    # Storage (Latest)
    latest_storage_tb = 0.0
    if not storage.empty:
        latest_storage_tb = float(storage.iloc[0]['TOTAL_TB'])

    # Cost Estimates
    COST_PER_CREDIT = 3.00 
    COST_PER_TB = 23.00
    try:
        path = client.get_schema_path("APP_CONTEXT")
        settings_res = client.session.sql(f"SELECT SETTING_KEY, SETTING_VALUE FROM {path}.PLATFORM_SETTINGS WHERE SETTING_KEY IN ('COST_PER_CREDIT', 'COST_PER_TB')").collect()
        for r in settings_res:
            if r['SETTING_KEY'] == 'COST_PER_CREDIT':
                COST_PER_CREDIT = float(r['SETTING_VALUE'])
            elif r['SETTING_KEY'] == 'COST_PER_TB':
                COST_PER_TB = float(r['SETTING_VALUE'])
    except Exception as e:
        pass
    
    est_cost = total_credits * COST_PER_CREDIT
    est_storage_cost = latest_storage_tb * COST_PER_TB
    total_est_spend = est_cost + est_storage_cost
    
    # DYNAMIC BUDGET
    TOTAL_BUDGET = get_budget_config(client)
    estimated_remaining = TOTAL_BUDGET - total_credits
    
    # 3. Render Metrics (2 Rows for specialized breakdown)
    
    # Row 1: High Level Spend & Forecast
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("💰 Total Est. Spend", f"${total_est_spend:,.2f}", help=f"Credits (${COST_PER_CREDIT}/cr) + Storage (${COST_PER_TB}/TB)")
    with c2:
        st.metric("📉 Total Credits", f"{total_credits:,.2f}", f"{days} days")
    with c3:
        st.metric("🔮 Projected Monthly", f"${(projected_monthly * COST_PER_CREDIT) + est_storage_cost:,.2f}", help="Extrapolated from avg daily burn")
    with c4:
        st.metric(f"🏦 Budget Left ({TOTAL_BUDGET} Cr)", f"{estimated_remaining:,.0f} Cr",
                delta=f"{(estimated_remaining/TOTAL_BUDGET)*100:.0f}%" if estimated_remaining > 0 else "Exceeded!",
                delta_color="normal" if estimated_remaining > 0 else "inverse")
        if st.button("⚙️ Edit Budget"):
            new_budget = st.number_input("Set Total Budget (Credits)", value=TOTAL_BUDGET)
            if st.button("Save Budget"):
                try:
                    client.execute_query(f"MERGE INTO APP_CONTEXT.APP_CONFIG AS target USING (SELECT 'TOTAL_BUDGET' AS KEY, '{new_budget}' AS VALUE) AS source ON target.CONFIG_KEY = source.KEY WHEN MATCHED THEN UPDATE SET target.CONFIG_VALUE = source.VALUE WHEN NOT MATCHED THEN INSERT (CONFIG_KEY, CONFIG_VALUE) VALUES (source.KEY, source.VALUE)")
                    st.success("Budget updated!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to save: {e}")

    st.divider()
    
    # Row 2: Operational Breakdown
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.metric("🖥️ Compute Credits", f"{compute_credits:,.2f}", f"{(compute_credits/total_credits)*100:.1f}% of total")
    with k2:
        st.metric("☁️ Cloud Services", f"{cloud_credits:,.2f}", f"{(cloud_credits/total_credits)*100:.1f}% of total")
    with k3:
        st.metric("💾 Storage Size", f"{latest_storage_tb:.3f} TB", f"${est_storage_cost:,.2f}/mo")
    with k4:
        st.metric("🔥 Daily Burn Rate", f"{avg_daily:,.2f} Cr/day", help="Average daily credit consumption")

    st.divider()
    
    # SANKEY FLOW VISUALIZATION (Visual Intelligence)
    st.markdown("### 🌊 Cost Flow Analysis")
    st.caption("Visualize how credits are consumed from total budget down to individual warehouses.")
    
    try:
        import plotly.graph_objects as go
        
        # 1. Fetch Data
        wh_costs_df = get_warehouse_costs(client, days)
        user_wh_df = get_user_warehouse_usage(client, days)
        
        if not wh_costs_df.empty and not user_wh_df.empty:
            
            # --- PREPARE NODES & LINKS ---
            
            # Level 0: Source (Total Budget/Compute)
            # Level 1: Warehouses
            # Level 2: Users
            
            labels = ["Total Compute"] 
            
            # Get unique warehouses and users
            warehouses = wh_costs_df['WAREHOUSE_NAME'].unique().tolist()
            # Sort warehouses by cost for better visual
            warehouses.sort(key=lambda x: wh_costs_df[wh_costs_df['WAREHOUSE_NAME']==x]['TOTAL_CREDITS'].sum(), reverse=True)
            
            # Get top users per warehouse or overall to avoid clutter
            # For simplicity, let's take top 15 users overall, others as "Other Users"
            top_users = user_wh_df.groupby('USER_NAME')['TOTAL_TIME_MS'].sum().nlargest(15).index.tolist()
            user_wh_df['DISPLAY_USER'] = user_wh_df['USER_NAME'].apply(lambda x: x if x in top_users else 'Other Users')
            
            unique_users = user_wh_df['DISPLAY_USER'].unique().tolist()
            
            # Master Label List
            # Indices: 0 is Total. 1..N is Warehouses. N+1..M is Users.
            labels.extend(warehouses)
            labels.extend(unique_users)
            
            label_map = {name: i for i, name in enumerate(labels)}
            
            sources = []
            targets = []
            values = []
            colors = []
            
            # LINK SET 1: Total -> Warehouses
            # Value = Credits Used
            root_idx = label_map["Total Compute"]
            
            wh_credit_map = {} # Store credit usage for next step weighting
            
            for _, row in wh_costs_df.iterrows():
                wh_name = row['WAREHOUSE_NAME']
                credits = float(row['TOTAL_CREDITS'])

                if credits > 0.1: # Show significant only
                    sources.append(root_idx)
                    targets.append(label_map[wh_name])
                    values.append(credits)
                    colors.append("rgba(41, 181, 232, 0.4)") # Blue-ish
                    wh_credit_map[wh_name] = credits

            # LINK SET 2: Warehouses -> Users
            # We don't have credits per user directly in this view, so we distribute WH credits based on Time Share
            
            for wh in warehouses:
                if wh not in wh_credit_map: continue
                
                wh_credits = wh_credit_map[wh]
                wh_usage = user_wh_df[user_wh_df['WAREHOUSE_NAME'] == wh]
                total_time = wh_usage['TOTAL_TIME_MS'].sum()
                
                if total_time > 0:
                    # Aggregate by Display User (grouping 'Others')
                    user_agg = wh_usage.groupby('DISPLAY_USER')['TOTAL_TIME_MS'].sum().reset_index()

                    for _, u_row in user_agg.iterrows():
                        user_name = u_row['DISPLAY_USER']
                        time_share = float(u_row['TOTAL_TIME_MS']) / float(total_time)
                        user_credits = float(wh_credits) * time_share
                        
                        if user_credits > 0.05: # Minimum visual threshold
                            sources.append(label_map[wh])
                            targets.append(label_map[user_name])
                            values.append(user_credits)
                            colors.append("rgba(113, 217, 255, 0.3)") # Lighter blue

            # Create Sankey
            fig = go.Figure(data=[go.Sankey(
                node = {
                  "pad": 15,
                  "thickness": 20,
                  "line": {"color": "black", "width": 0.5},
                  "label": labels,
                  "color": "#29B5E8"
                },
                link = {
                  "source": sources,
                  "target": targets,
                  "value": values,
                  "color": colors
                }
            )])
            
            fig.update_layout(
                title_text=f"Credit Flow: Compute → Warehouse → User (Last {days} Days)", 
                font_size=12, 
                height=500,
                margin=dict(l=10, r=10, t=40, b=10)
            )
            st.plotly_chart(fig, use_container_width=True)
            
        else:
            st.info("Not enough data for Cost Flow.")
            
    except ImportError:
        st.warning("Plotly is not installed. Sankey diagram unavailable.")
    except Exception as e:
        st.error(f"Could not render Sankey: {e}")

    st.divider()
    
    # 4. Trends Chart (Larger)
    st.markdown("### 📈 Daily Credit Consumption Trend")
    
    chart = alt.Chart(trends).mark_area(
        interpolate='monotone',
        line={'color': '#29B5E8'},
        color=alt.Gradient(
            gradient='linear',
            stops=[
                alt.GradientStop(color='rgba(41, 181, 232, 0.1)', offset=0),
                alt.GradientStop(color='rgba(41, 181, 232, 0.6)', offset=1)
            ],
            x1=1, x2=1, y1=1, y2=0
        )
    ).encode(
        x=alt.X('USAGE_DATE:T', title='Date', axis=alt.Axis(format='%b %d', tickCount=days)),
        y=alt.Y('TOTAL_CREDITS:Q', title='Credits Used'),
        tooltip=[
            alt.Tooltip('USAGE_DATE:T', title='Date', format='%Y-%m-%d'),
            alt.Tooltip('TOTAL_CREDITS:Q', title='Total', format=',.2f'),
            alt.Tooltip('COMPUTE_CREDITS:Q', title='Compute', format=',.2f'),
            alt.Tooltip('CLOUD_CREDITS:Q', title='Cloud', format=',.2f')
        ]
    ).properties(
        height=450, # Increased height
        title="Daily Usage (Last " + str(days) + " Days)"
    )
    
    st.altair_chart(chart, use_container_width=True)
    
    # Storage Details moved to bottom or collapsed? User wanted "metrics... breakdown by styling like select.dev".
    # I already included Storage Metrics above. I will hide the explicit storage table unless expanded.
    with st.expander("📦 Detailed Storage Breakdown"):
        if not storage.empty:
            st.dataframe(storage, use_container_width=True)
        else:
            st.info("No storage data.")
    
    # Export button
    st.divider()
    col1, col2 = st.columns([3, 1])
    with col2:
        excel_data = dataframe_to_excel_bytes(trends, "Credit_Trends")
        st.download_button(
            label="📥 Export to Excel",
            data=excel_data,
            file_name=f"cost_trends_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )


def render_ingestion_costs(client, days):
    """Render Ingestion (Copy/Pipe) Costs"""
    st.markdown("### 📥 Ingestion Costs (Snowpipe & Copy)")
    st.caption("Tracking the cost of loading data into Snowflake.")
    
    # Metric Queries
    q_copy = f"""
    SELECT 
        count(*) as FILE_COUNT,
        sum(ROW_COUNT) as TOTAL_ROWS,
        sum(FILE_SIZE) as TOTAL_BYTES
    FROM SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY
    WHERE LAST_LOAD_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
    """
    
    q_pipe = f"""
    SELECT 
        sum(CREDITS_USED) as PIPE_CREDITS,
        sum(BYTES_INSERTED) as PIPE_BYTES
    FROM SNOWFLAKE.ACCOUNT_USAGE.PIPE_USAGE_HISTORY
    WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
    """
    
    try:
        copy_res = client.execute_query(q_copy).iloc[0]
        pipe_res = client.execute_query(q_pipe).iloc[0]
        
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Files Loaded", f"{copy_res['FILE_COUNT']:,}")
        with c2:
            st.metric("Rows Loaded", f"{copy_res['TOTAL_ROWS']:,}")
        with c3:
            total_gb = (copy_res['TOTAL_BYTES'] or 0) / (1024**3)
            st.metric("COPY Data Volume", f"{total_gb:.2f} GB")
        with c4:
            pipe_credits = pipe_res['PIPE_CREDITS'] or 0
            st.metric("Snowpipe Cost", f"{pipe_credits:.4f} Cr")
            
        st.divider()
        
        # Detailed COPY History
        st.markdown("#### Recent COPY History")
        hist = client.execute_query(f"SELECT TABLE_NAME, FILE_NAME, ROW_COUNT, FILE_SIZE, STATUS FROM SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY WHERE LAST_LOAD_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP()) ORDER BY LAST_LOAD_TIME DESC LIMIT 20")
        st.dataframe(hist, use_container_width=True)
        
    except Exception as e:
        st.error(f"Error fetching ingestion data: {e}")


def render_warehouse_costs(client, days):
    """Render warehouse cost breakdown"""
    st.markdown("### Credit Usage by Warehouse")
    
    wh_costs = get_warehouse_costs(client, days)
    
    if wh_costs.empty:
        st.info("No warehouse usage data available.")
        return
    
    # cost_per_credit = client.get_cost_per_credit()
    # wh_costs['ESTIMATED_COST'] = wh_costs['TOTAL_CREDITS'] * cost_per_credit
    
    # Pie chart for warehouse distribution
    col1, col2 = st.columns([1, 1])
    
    with col1:
        pie_chart = alt.Chart(wh_costs).mark_arc(innerRadius=50).encode(
            theta=alt.Theta('TOTAL_CREDITS:Q'),
            color=alt.Color('WAREHOUSE_NAME:N', 
                          legend=alt.Legend(title='Warehouse'),
                          scale=alt.Scale(scheme='blues')),
            tooltip=[
                alt.Tooltip('WAREHOUSE_NAME:N', title='Warehouse'),
                alt.Tooltip('TOTAL_CREDITS:Q', title='Total Credits', format=',.2f')
            ]
        ).properties(height=300, title='Credit Distribution')
        
        st.altair_chart(pie_chart, use_container_width=True)
    
    with col2:
        # Bar chart
        bar_chart = alt.Chart(wh_costs).mark_bar(color='#29B5E8').encode(
            x=alt.X('TOTAL_CREDITS:Q', title='Total Credits'),
            y=alt.Y('WAREHOUSE_NAME:N', title='', sort='-x'),
            tooltip=[
                alt.Tooltip('WAREHOUSE_NAME:N', title='Warehouse'),
                alt.Tooltip('TOTAL_CREDITS:Q', title='Credits', format=',.2f'),
                alt.Tooltip('ACTIVE_DAYS:Q', title='Active Days')
            ]
        ).properties(height=300, title='Credits by Warehouse')
        
        st.altair_chart(bar_chart, use_container_width=True)
    
    # Detailed table
    st.markdown("### Warehouse Details")
    
    display_df = wh_costs.copy()
    display_df = display_df[['WAREHOUSE_NAME', 'TOTAL_CREDITS', 'COMPUTE_CREDITS', 'CLOUD_CREDITS', 'ACTIVE_DAYS', 'AVG_HOURLY_CREDITS']]
    display_df.columns = ['Warehouse', 'Total Credits', 'Compute Credits', 'Cloud Credits', 'Active Days', 'Avg Hourly']
    
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Total Credits": st.column_config.NumberColumn(format="%.2f"),
            "Compute Credits": st.column_config.NumberColumn(format="%.2f"),
            "Cloud Credits": st.column_config.NumberColumn(format="%.4f"),
            "Avg Hourly": st.column_config.NumberColumn(format="%.4f")
        }
    )
    
    # Export
    col1, col2 = st.columns([3, 1])
    with col2:
        excel_data = dataframe_to_excel_bytes(wh_costs, "Warehouse_Costs")
        st.download_button(
            label="📥 Export to Excel",
            data=excel_data,
            file_name=f"warehouse_costs_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )


def render_user_costs(client, days):
    """Render user cost attribution"""
    st.markdown("### Usage by User")
    st.caption("*Attribute resource usage to specific users for cost allocation*")
    
    user_costs = get_user_costs(client, days)
    
    if user_costs.empty:
        st.info("No user query data available.")
        return
    
    # Summary metrics
    total_queries = user_costs['QUERY_COUNT'].sum()
    total_users = len(user_costs)
    total_gb = user_costs['TOTAL_GB_SCANNED'].sum()
    total_cloud_credits = user_costs['CLOUD_CREDITS'].sum()
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Queries", f"{total_queries:,}")
    with col2:
        st.metric("Active Users", f"{total_users}")
    with col3:
        st.metric("Data Scanned", f"{total_gb:,.1f} GB")
    with col4:
        st.metric("Cloud Services Credits", f"{total_cloud_credits:,.2f}")
    
    st.divider()
    
    # User breakdown chart
    top_users = user_costs.head(10)
    
    chart = alt.Chart(top_users).mark_bar(color='#29B5E8').encode(
        x=alt.X('TOTAL_GB_SCANNED:Q', title='GB Scanned'),
        y=alt.Y('USER_NAME:N', title='', sort='-x'),
        tooltip=[
            alt.Tooltip('USER_NAME:N', title='User'),
            alt.Tooltip('QUERY_COUNT:Q', title='Queries'),
            alt.Tooltip('TOTAL_GB_SCANNED:Q', title='GB Scanned', format=',.2f'),
            alt.Tooltip('CLOUD_CREDITS:Q', title='Cloud Credits', format=',.4f')
        ]
    ).properties(height=350, title='Top 10 Users by Data Scanned')
    
    st.altair_chart(chart, use_container_width=True)
    
    # Full table
    st.markdown("### All Users")
    
    display_df = user_costs.copy()
    display_df.columns = ['User', 'Queries', 'Total Time (min)', 'GB Scanned', 'Avg GB/Query', 'Cloud Credits', 'Failed']
    
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Total Time (min)": st.column_config.NumberColumn(format="%.1f"),
            "GB Scanned": st.column_config.NumberColumn(format="%.2f"),
            "Avg GB/Query": st.column_config.NumberColumn(format="%.4f"),
            "Cloud Credits": st.column_config.NumberColumn(format="%.4f")
        }
    )
    
    # Export
    col1, col2 = st.columns([3, 1])
    with col2:
        excel_data = dataframe_to_excel_bytes(user_costs, "User_Costs")
        st.download_button(
            label="📥 Export to Excel",
            data=excel_data,
            file_name=f"user_costs_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )


def render_role_costs(client, days):
    """Render role cost attribution"""
    st.markdown("### Usage by Role")
    st.caption("*Attribute resource usage to functional roles*")
    
    role_costs = get_role_costs(client, days)
    
    if role_costs.empty:
        st.info("No role usage data available.")
        return
    
    # Bar chart
    chart = alt.Chart(role_costs).mark_bar(color='#71D9FF').encode(
        x=alt.X('CLOUD_CREDITS:Q', title='Cloud Services Credits'),
        y=alt.Y('ROLE_NAME:N', title='', sort='-x'),
        tooltip=[
            alt.Tooltip('ROLE_NAME:N', title='Role'),
            alt.Tooltip('QUERY_COUNT:Q', title='Queries'),
            alt.Tooltip('CLOUD_CREDITS:Q', title='Cloud Credits', format=',.4f')
        ]
    ).properties(height=300, title='Cloud Credits by Role')
    
    st.altair_chart(chart, use_container_width=True)
    
    # Table
    display_df = role_costs.copy()
    display_df.columns = ['Role', 'Queries', 'Total Time (min)', 'GB Scanned', 'Cloud Credits']
    
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Total Time (min)": st.column_config.NumberColumn(format="%.1f"),
            "GB Scanned": st.column_config.NumberColumn(format="%.2f"),
            "Cloud Credits": st.column_config.NumberColumn(format="%.4f")
        }
    )
    
    col1, col2 = st.columns([3, 1])
    with col2:
        excel_data = dataframe_to_excel_bytes(role_costs, "Role_Costs")
        st.download_button(
            label="📥 Export to Excel",
            data=excel_data,
            file_name=f"role_costs_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )


def render_usage_patterns(client):
    """Render usage patterns analysis"""
    st.markdown("### Usage Patterns")
    st.caption("*Identify peak usage times to optimize warehouse scheduling*")
    
    patterns = get_hourly_pattern(client)
    
    if patterns.empty:
        st.info("Not enough data to identify usage patterns.")
        return
    
    # Heatmap of hourly usage
    heatmap = alt.Chart(patterns).mark_rect().encode(
        x=alt.X('HOUR_OF_DAY:O', title='Hour of Day'),
        y=alt.Y('DAY_OF_WEEK:O', title='Day of Week',
               sort=['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']),
        color=alt.Color('AVG_CREDITS:Q', 
                       scale=alt.Scale(scheme='blues'),
                       legend=alt.Legend(title='Avg Credits')),
        tooltip=[
            alt.Tooltip('DAY_OF_WEEK:N', title='Day'),
            alt.Tooltip('HOUR_OF_DAY:O', title='Hour'),
            alt.Tooltip('AVG_CREDITS:Q', title='Avg Credits', format=',.4f')
        ]
    ).properties(height=300, title='Credit Usage by Day and Hour')
    
    st.altair_chart(heatmap, use_container_width=True)
    
    # Insights
    st.altair_chart(heatmap, use_container_width=True)
    
    # Insights
    st.markdown("### 💡 Optimization Insights")


def render_deep_dive(client, days):
    """Render Deep Dive Attribution (Tags & Expensive Queries)"""
    st.markdown("### 🕵️ Deep Dive Attribution")
    st.caption("*Granular visibility into Query Tags and Individual Query Costs*")
    
    # 1. Query Tags
    st.markdown("#### Cost by Query Tag")
    tags_df = get_query_tag_costs(client, days)
    
    if not tags_df.empty:
        c1, c2 = st.columns([2, 1])
        with c1:
            chart = alt.Chart(tags_df).mark_bar(color='#FF6D00').encode(
                x=alt.X('TOTAL_TIME_MIN:Q', title='Total Runtime (min)'),
                y=alt.Y('QUERY_TAG:N', title='Tag', sort='-x'),
                tooltip=['QUERY_TAG', 'QUERY_COUNT', 'TOTAL_TIME_MIN']
            ).properties(title="Top Tags by Runtime")
            st.altair_chart(chart, use_container_width=True)
        with c2:
            st.dataframe(tags_df, use_container_width=True, hide_index=True)
    else:
        st.info("No Query Tags found. Use 'ALTER SESSION SET QUERY_TAG = ...' to tag your workloads.")
        
    st.divider()
    
    # 2. Expensive Queries
    st.markdown("#### 💸 Most Expensive Queries")
    exp_queries = get_expensive_queries(client, days)
    
    if not exp_queries.empty:
        st.dataframe(
            exp_queries, 
            use_container_width=True,
            column_config={
                "START_TIME": st.column_config.DatetimeColumn("Start", format="MMM DD HH:mm:ss"),
                "DURATION_SEC": st.column_config.NumberColumn("Duration (s)", format="%.1f"),
                "GB_SCANNED": st.column_config.NumberColumn("GB Scanned", format="%.2f"),
                "QUERY_TEXT": st.column_config.TextColumn("SQL", width="large")
            }
        )
    else:
        st.info("No expensive queries found (Duration > 10s).")

    
    # Find peak hours
    patterns = get_hourly_pattern(client)
    if patterns.empty:
         st.info("No pattern data for peak hour analysis.")
         return

    peak_hour = patterns.loc[patterns['AVG_CREDITS'].idxmax()]
    low_hour = patterns.loc[patterns['AVG_CREDITS'].idxmin()]
    
    col1, col2 = st.columns(2)
    with col1:
        st.info(f"""
        **Peak Usage**: {peak_hour['DAY_OF_WEEK']} at {int(peak_hour['HOUR_OF_DAY'])}:00
        
        Consider using larger warehouses during peak times for faster execution.
        """)
    
    with col2:
        st.success(f"""
        **Low Usage**: {low_hour['DAY_OF_WEEK']} at {int(low_hour['HOUR_OF_DAY'])}:00
        
        Schedule non-urgent batch jobs during off-peak hours to reduce costs.
        """)


def render_anomalies(client, days):
    """Render cost anomaly detection"""
    st.markdown("### Cost Anomaly Detection")
    st.caption("*Automatically detect unusual credit usage spikes*")
    
    col1, col2 = st.columns([1, 3])
    with col1:
        threshold = st.slider("Anomaly Threshold", 1.5, 3.0, 2.0, 0.1,
                            help="Days with credits > threshold × average will be flagged")
    
    anomalies = get_cost_anomalies(client, days, threshold)
    
    if anomalies.empty:
        st.success("✅ No cost anomalies detected in the selected period.")
        return
    
    st.warning(f"⚠️ Found {len(anomalies)} days with unusual credit usage")
    
    # Anomaly chart
    chart = alt.Chart(anomalies).mark_bar(color='#FF4B4B').encode(
        x=alt.X('USAGE_DATE:T', title='Date'),
        y=alt.Y('DAILY_CREDITS:Q', title='Credits Used'),
        tooltip=[
            alt.Tooltip('USAGE_DATE:T', title='Date'),
            alt.Tooltip('DAILY_CREDITS:Q', title='Credits', format=',.2f'),
            alt.Tooltip('AVG_CREDITS:Q', title='Average', format=',.2f'),
            alt.Tooltip('Z_SCORE:Q', title='Z-Score', format=',.2f')
        ]
    ).properties(height=250)
    
    # Add average line
    avg_line = alt.Chart(anomalies).mark_rule(color='#00D4AA', strokeDash=[5,5]).encode(
        y='mean(AVG_CREDITS):Q'
    )
    
    st.altair_chart(chart + avg_line, use_container_width=True)
    
    # Anomaly table
    st.markdown("### Anomaly Details")
    
    display_df = anomalies.copy()
    display_df['VARIANCE'] = ((display_df['DAILY_CREDITS'] - display_df['AVG_CREDITS']) / display_df['AVG_CREDITS'] * 100)
    display_df = display_df[['USAGE_DATE', 'DAILY_CREDITS', 'AVG_CREDITS', 'VARIANCE', 'Z_SCORE']]
    display_df.columns = ['Date', 'Credits Used', 'Average', 'Variance %', 'Z-Score']
    
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Date": st.column_config.DateColumn(),
            "Credits Used": st.column_config.NumberColumn(format="%.2f"),
            "Average": st.column_config.NumberColumn(format="%.2f"),
            "Variance %": st.column_config.NumberColumn(format="+%.1f%%"),
            "Z-Score": st.column_config.NumberColumn(format="%.2f")
        }
    )


def render_deep_dive(client, days):
    """Render deep dive query-level attribution."""
    st.markdown("### 🔎 Query-Level Cost Attribution")
    st.caption("*Estimated cost based on execution time and warehouse size credits.*")
    
    with st.spinner("Analyzing query history..."):
        query = f"""
        WITH query_stats AS (
            SELECT 
                QUERY_ID,
                QUERY_TEXT,
                USER_NAME,
                ROLE_NAME,
                WAREHOUSE_NAME,
                WAREHOUSE_SIZE,
                EXECUTION_TIME, 
                -- Estimate Credits: (Exec Time hrs) * (Credits/hr)
                (EXECUTION_TIME / 1000.0 / 3600.0) * 
                CASE 
                    WHEN WAREHOUSE_SIZE = 'X-Small' THEN 1
                    WHEN WAREHOUSE_SIZE = 'Small' THEN 2
                    WHEN WAREHOUSE_SIZE = 'Medium' THEN 4
                    WHEN WAREHOUSE_SIZE = 'Large' THEN 8
                    WHEN WAREHOUSE_SIZE = 'X-Large' THEN 16
                    WHEN WAREHOUSE_SIZE = '2X-Large' THEN 32
                    WHEN WAREHOUSE_SIZE = '3X-Large' THEN 64
                    WHEN WAREHOUSE_SIZE = '4X-Large' THEN 128
                    ELSE 1 
                END as EST_CREDITS,
                QUERY_TAG,
                -- Try to parse DBT Model from JSON tag
                TRY_PARSE_JSON(QUERY_TAG):node::STRING as DBT_NODE,
                TRY_PARSE_JSON(QUERY_TAG):dbt_version::STRING as DBT_VERSION
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            AND WAREHOUSE_NAME IS NOT NULL
            AND EXECUTION_TIME > 0
        )
        SELECT * FROM query_stats ORDER BY EST_CREDITS DESC LIMIT 500
        """
        
        try:
            df = client.execute_query(query)
            if df.empty:
                st.info("No query history found.")
                return

            # dbt Model Costs - MOVED TO DEDICATED TAB
            # See 'render_dbt_models' function


            # Top Expensive Queries
            st.markdown("#### 💸 Most Expensive Queries")
            
            # Interactive Drill-down
            # Create a selection list for the selectbox
            df['display_label'] = df.apply(lambda x: f"[{x['EST_CREDITS']:.2f} Cr] {x['QUERY_TEXT'][:60]}... ({x['USER_NAME']})", axis=1)
            
            selected_query_label = st.selectbox(
                "🔎 Inspect a Query (Select to view details):",
                options=df['display_label'].tolist(),
                index=None,
                placeholder="Select a query to view full SQL and stats..."
            )
            
            if selected_query_label:
                selected_row = df[df['display_label'] == selected_query_label].iloc[0]
                
                with st.container():
                    st.info(f"**Query ID:** `{selected_row['QUERY_ID']}` | **User:** `{selected_row['USER_NAME']}` | **Warehouse:** `{selected_row['WAREHOUSE_NAME']}` ({selected_row['WAREHOUSE_SIZE']})")
                    
                    q1, q2, q3 = st.columns(3)
                    with q1:
                        st.metric("Est. Cost", f"${selected_row['EST_CREDITS']*3.00:.2f}", f"{selected_row['EST_CREDITS']:.4f} Credits")
                    with q2:
                        st.metric("Duration", f"{selected_row['EXECUTION_TIME']/1000:.2f}s")
                    with q3:
                        st.metric("dbt Model", selected_row['DBT_NODE'] if pd.notna(selected_row['DBT_NODE']) else "N/A")
                        
                    st.markdown("**SQL Text:**")
                    st.code(selected_row['QUERY_TEXT'], language='sql')
                    st.divider()

            st.dataframe(
                df[['QUERY_TEXT', 'USER_NAME', 'WAREHOUSE_NAME', 'EST_CREDITS', 'EXECUTION_TIME']].head(50),
                use_container_width=True,
                column_config={
                    "QUERY_TEXT": st.column_config.TextColumn("Query", width="large"),
                    "EST_CREDITS": st.column_config.NumberColumn("Est. Credits", format="%.4f"),
                    "EXECUTION_TIME": st.column_config.NumberColumn("Duration (ms)")
                }
            )
            
            # Tag Attribution (General)
            st.markdown("#### 🏷️ Cost by Query Tag")
            if 'QUERY_TAG' in df.columns:
                # Handle null tags
                df['QUERY_TAG'] = df['QUERY_TAG'].fillna('No Tag').replace('', 'No Tag')
                # If tag is JSON, use it as string
                df['QUERY_TAG'] = df['QUERY_TAG'].astype(str)
                
                tag_spend = df.groupby('QUERY_TAG')['EST_CREDITS'].sum().reset_index().sort_values('EST_CREDITS', ascending=False)
                
                chart = alt.Chart(tag_spend.head(10)).mark_bar().encode(
                    x=alt.X('EST_CREDITS:Q', title='Est. Credits'),
                    y=alt.Y('QUERY_TAG:N', sort='-x', title='Tag'),
                    color=alt.Color('EST_CREDITS:Q', scale=alt.Scale(scheme='tealblues')),
                    tooltip=['QUERY_TAG', 'EST_CREDITS']
                )
                st.altair_chart(chart, use_container_width=True)
                
        except Exception as e:
            st.error(f"Error fetching deep dive data: {e}")



def render_forecast(client, days):
    """Enhanced cost forecasting with warehouse-level projections and scenario modeling."""
    st.markdown("### 🔮 Advanced Cost Forecast & Budget Projection")
    st.caption("*Per-warehouse projections, scenario modeling, and budget runway analysis*")
    
    import numpy as np
    import plotly.express as px
    import plotly.graph_objects as go
    
    # 1. Get Historical Data (overall and per-warehouse)
    trends = get_credit_trends(client, days)
    wh_trends = get_warehouse_costs(client, days)
    
    if trends.empty:
        st.info("Not enough data to generate forecast.")
        return

    # 2. Calculate Basics
    total_credits = float(trends['TOTAL_CREDITS'].sum())
    avg_daily_burn = float(trends['TOTAL_CREDITS'].mean())

    COST_PER_CREDIT = 3.00
    try:
        path = client.get_schema_path("APP_CONTEXT")
        settings_res = client.session.sql(f"SELECT SETTING_VALUE FROM {path}.PLATFORM_SETTINGS WHERE SETTING_KEY = 'COST_PER_CREDIT'").collect()
        if settings_res:
            COST_PER_CREDIT = float(settings_res[0]['SETTING_VALUE'])
    except Exception as e:
        pass
    
    # Linear Regression for overall trend
    trends['days_from_start'] = (pd.to_datetime(trends['USAGE_DATE']) - pd.to_datetime(trends['USAGE_DATE']).min()).dt.days
    
    slope = 0
    if len(trends) > 1:
        x = trends['days_from_start'].values
        y = trends['TOTAL_CREDITS'].values
        try:
            slope, intercept = np.polyfit(x, y, 1)
            last_day = x.max()
            future_days = np.arange(last_day + 1, last_day + 31)
            predicted_credits = np.maximum(slope * future_days + intercept, 0)
            projected_avg = predicted_credits.mean()
            if projected_avg > 0:
                avg_daily_burn = projected_avg
            trend_direction = "Increasing 📈" if slope > 0.1 else ("Decreasing 📉" if slope < -0.1 else "Stable ➡️")
        except:
            trend_direction = "Stable (Flat)"
            predicted_credits = np.array([avg_daily_burn] * 30)
    else:
        trend_direction = "Insufficient Data"
        predicted_credits = np.array([avg_daily_burn] * 30)
    
    # Budget Analysis
    TOTAL_BUDGET = get_budget_config(client)
    budget_remaining = TOTAL_BUDGET - total_credits
    days_until_exhaustion = int(budget_remaining / avg_daily_burn) if avg_daily_burn > 0 else 999
    
    # 3. Top Metrics Row
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("🔥 Daily Burn Rate", f"{avg_daily_burn:.2f} Cr", 
                  delta=f"{slope:.3f}/day" if slope != 0 else None,
                  delta_color="inverse" if slope > 0 else "normal")
    with c2:
        projected_30 = avg_daily_burn * 30 * COST_PER_CREDIT
        st.metric("💰 Projected 30-Day Cost", f"${projected_30:,.2f}")
    with c3:
        runway_label = f"{days_until_exhaustion} days" if days_until_exhaustion < 365 else "365+ days"
        st.metric("⏰ Budget Runway", runway_label, 
                  delta="⚠️ Low!" if days_until_exhaustion < 30 else "✅ OK",
                  delta_color="inverse" if days_until_exhaustion < 30 else "normal")
    with c4:
        st.metric("📊 Trend", trend_direction)
    
    st.divider()
    
    # 4. Scenario Modeling
    st.markdown("#### 📐 Scenario Projections")
    
    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        optimistic_factor = st.slider("Optimistic (reduction %)", 5, 50, 20, key="opt_factor")
    with sc2:
        pessimistic_factor = st.slider("Pessimistic (increase %)", 5, 100, 30, key="pes_factor")
    with sc3:
        st.caption("**Planned** = current trajectory")
        new_wh_credits = st.number_input("New warehouse daily credits", 0.0, 100.0, 0.0, key="new_wh_cr",
                                          help="If you're adding new warehouses, estimate their daily credit burn")
    
    last_date = pd.to_datetime(trends['USAGE_DATE']).max()
    future_dates = [last_date + timedelta(days=int(i)) for i in range(1, 31)]
    
    # Build scenario data
    base_forecast = predicted_credits[:30] if len(predicted_credits) >= 30 else np.array([avg_daily_burn] * 30)
    
    scenarios = pd.DataFrame({'Date': future_dates})
    scenarios['Planned'] = base_forecast + new_wh_credits
    scenarios['Optimistic'] = base_forecast * (1 - optimistic_factor/100)
    scenarios['Pessimistic'] = base_forecast * (1 + pessimistic_factor/100) + new_wh_credits
    
    # History for combined chart
    history_dates = pd.to_datetime(trends['USAGE_DATE']).tolist()
    history_credits = trends['TOTAL_CREDITS'].tolist()
    
    # Plot with Plotly
    fig = go.Figure()
    
    # History
    fig.add_trace(go.Scatter(x=history_dates, y=history_credits, mode='lines+markers',
                             name='History', line=dict(color='#29B5E8', width=2),
                             marker=dict(size=4), hovertemplate='%{x|%b %d}<br>Credits: %{y:.2f}<extra>History</extra>'))
    
    # Pessimistic band (fill between)
    fig.add_trace(go.Scatter(x=scenarios['Date'], y=scenarios['Pessimistic'], mode='lines',
                             name='Pessimistic', line=dict(color='#FF4B4B', dash='dot'),
                             hovertemplate='%{x|%b %d}<br>Credits: %{y:.2f}<extra>Pessimistic</extra>'))
    
    # Planned
    fig.add_trace(go.Scatter(x=scenarios['Date'], y=scenarios['Planned'], mode='lines',
                             name='Planned', line=dict(color='#FFD700', width=3),
                             hovertemplate='%{x|%b %d}<br>Credits: %{y:.2f}<extra>Planned</extra>'))
    
    # Optimistic
    fig.add_trace(go.Scatter(x=scenarios['Date'], y=scenarios['Optimistic'], mode='lines',
                             name='Optimistic', line=dict(color='#00D4AA', dash='dash'),
                             hovertemplate='%{x|%b %d}<br>Credits: %{y:.2f}<extra>Optimistic</extra>'))
    
    # Budget line
    if TOTAL_BUDGET > 0 and avg_daily_burn > 0:
        daily_budget = TOTAL_BUDGET / 30
        fig.add_hline(y=daily_budget, line_dash="dash", line_color="white", opacity=0.5,
                     annotation_text=f"Daily Budget: {daily_budget:.1f} Cr")
    
    fig.update_layout(
        title="30-Day Spend Trajectory with Scenarios",
        plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
        font=dict(color='white'), height=400,
        margin=dict(l=60, r=20, t=50, b=60),
        legend=dict(orientation="h", yanchor="bottom", y=-0.2),
        hovermode='x unified'
    )
    st.plotly_chart(fig, use_container_width=True)
    
    # Scenario comparison table
    st.markdown("**30-Day Projected Totals:**")
    sc_data = {
        "Scenario": ["🟢 Optimistic", "🟡 Planned", "🔴 Pessimistic"],
        "Total Credits": [float(scenarios['Optimistic'].sum()), float(scenarios['Planned'].sum()), float(scenarios['Pessimistic'].sum())],
        "Est. Cost": [f"${float(scenarios['Optimistic'].sum())*COST_PER_CREDIT:,.2f}", 
                     f"${float(scenarios['Planned'].sum())*COST_PER_CREDIT:,.2f}",
                     f"${float(scenarios['Pessimistic'].sum())*COST_PER_CREDIT:,.2f}"],
        "Budget Status": [
            "✅ Under" if float(scenarios['Optimistic'].sum()) < TOTAL_BUDGET else "⚠️ Over",
            "✅ Under" if float(scenarios['Planned'].sum()) < TOTAL_BUDGET else "⚠️ Over",
            "✅ Under" if float(scenarios['Pessimistic'].sum()) < TOTAL_BUDGET else "⚠️ Over"
        ]
    }
    st.dataframe(pd.DataFrame(sc_data), use_container_width=True, hide_index=True)
    
    st.divider()
    
    # 5. Per-Warehouse Forecast Breakdown
    st.markdown("#### 🏭 Per-Warehouse Cost Trajectory")
    st.caption("*Which warehouses are driving cost growth?*")
    
    if not wh_trends.empty and 'WAREHOUSE_NAME' in wh_trends.columns and 'TOTAL_CREDITS' in wh_trends.columns:
        wh_sorted = wh_trends.sort_values('TOTAL_CREDITS', ascending=False)
        
        fig_wh = px.bar(
            wh_sorted, x='WAREHOUSE_NAME', y='TOTAL_CREDITS',
            color='TOTAL_CREDITS',
            color_continuous_scale=['#00D4AA', '#FFD700', '#FF4B4B'],
            title="Credit Distribution by Warehouse",
            hover_data=wh_sorted.columns.tolist()
        )
        fig_wh.update_layout(
            plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
            font=dict(color='white'), height=350,
            xaxis_tickangle=-45, margin=dict(b=100)
        )
        st.plotly_chart(fig_wh, use_container_width=True)
        
        # Yearly projection per warehouse
        if 'TOTAL_CREDITS' in wh_sorted.columns:
            wh_sorted_copy = wh_sorted.copy()
            multiplier = 365 / max(days, 1)
            wh_sorted_copy['YEARLY_PROJECTION'] = wh_sorted_copy['TOTAL_CREDITS'].astype(float) * multiplier
            wh_sorted_copy['YEARLY_COST'] = wh_sorted_copy['YEARLY_PROJECTION'] * COST_PER_CREDIT
            
            display_wh_cols = [c for c in ['WAREHOUSE_NAME', 'TOTAL_CREDITS', 'YEARLY_PROJECTION', 'YEARLY_COST'] if c in wh_sorted_copy.columns]
            st.dataframe(
                wh_sorted_copy[display_wh_cols],
                use_container_width=True, hide_index=True,
                column_config={
                    "TOTAL_CREDITS": st.column_config.NumberColumn(f"Credits ({days}d)", format="%.2f"),
                    "YEARLY_PROJECTION": st.column_config.NumberColumn("Yearly Projection", format="%.1f"),
                    "YEARLY_COST": st.column_config.NumberColumn("Yearly Cost ($)", format="$%.2f"),
                }
            )
    else:
        st.info("No per-warehouse data available.")
    
    st.info("""
    **Forecast Logic**: Uses **Linear Regression** on historical daily usage with **scenario modeling**.
    New warehouse additions and optimization efforts are factored into projections.
    """)





def render_dbt_models(client, days):
    """Render dbt Model Cost Analysis"""
    st.markdown("### 🟧 dbt Model & Integration Costs")
    st.caption("*Deep cost visibility and attribution for dbt, Looker, and other integrated tools via Query Tags.*")
    
    dbt_costs = get_dbt_costs(client, days)
    
    if dbt_costs.empty:
        st.info("ℹ️ No dbt or tool tags detected. Configure dbt or Looker to write query tags (JSON) to see model-level costs.")
        st.markdown("""
        **How to Enable:**
        Add this to your `dbt_project.yml`:
        ```yaml
        models:
          +query_tag: '{"node": "{{ model.name }}", "dbt_version": "{{ dbt_version }}"}'
        ```
        """)
        return
        
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Total dbt Spend", f"{dbt_costs['TOTAL_CREDITS'].sum():.2f} Cr")
    with c2:
        st.metric("Active Models", f"{len(dbt_costs)}")
    with c3:
        if not dbt_costs.empty:
            top_model = dbt_costs.iloc[0]['MODEL_NAME']
            st.metric("Costliest Model", top_model)
        
    st.divider()
    
    # Chart
    chart = alt.Chart(dbt_costs.head(20)).mark_bar(color='#FF6C37').encode(
        x=alt.X('TOTAL_CREDITS:Q', title='Credits Used'),
        y=alt.Y('MODEL_NAME:N', sort='-x', title='Model'),
        tooltip=['MODEL_NAME', 'TOTAL_CREDITS', 'EXECUTION_COUNT']
    ).properties(title="Top 20 dbt Models by Cost")
    
    st.altair_chart(chart, use_container_width=True)
    
    # Table
    st.dataframe(
        dbt_costs, 
        use_container_width=True,
        column_config={
            "TOTAL_CREDITS": st.column_config.NumberColumn("Total Credits", format="%.4f"),
            "AVG_CREDITS_PER_RUN": st.column_config.NumberColumn("Avg/Run", format="%.6f")
        }
    )


# =====================================================
# COST GUARDIAN TAB
# =====================================================

def render_cost_guardian(client, days):
    """Render the Cost Guardian: Burst Detection, Live Status, Emergency Controls."""
    st.markdown("### 🚨 Cost Guardian — Burst Detection & Protection")
    st.caption("*Real-time monitoring of credit burn rates with automatic anomaly flagging.*")
    
    import plotly.express as px
    import plotly.graph_objects as go
    
    # --- Section 1: Live Warehouse Burn Rate ---
    st.markdown("#### 🔥 Live Warehouse Status")
    
    try:
        live_status = get_warehouse_live_status(client)
        if not live_status.empty:
            # Summary metrics
            total_today = live_status['CREDITS_TODAY'].sum() if 'CREDITS_TODAY' in live_status.columns else 0
            total_last_hour = live_status['CREDITS_LAST_HOUR'].sum() if 'CREDITS_LAST_HOUR' in live_status.columns else 0
            
            m1, m2, m3, m4 = st.columns(4)
            with m1:
                st.metric("Credits Today", f"{total_today:.2f}")
            with m2:
                st.metric("Credits Last Hour", f"{total_last_hour:.2f}", 
                          delta=f"{'🔴 HIGH' if total_last_hour > 2 else '🟢 Normal'}")
            with m3:
                try:
                    active_wh = len(live_status[live_status['STATE'].str.upper() == 'STARTED']) if 'STATE' in live_status.columns else 0
                except:
                    active_wh = 0
                st.metric("Active Warehouses", active_wh)
            with m4:
                st.metric("Total Warehouses", len(live_status))
            
            # Warehouse table with status
            st.dataframe(
                live_status,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "CREDITS_LAST_HOUR": st.column_config.NumberColumn("Credits/Hour", format="%.4f"),
                    "CREDITS_TODAY": st.column_config.NumberColumn("Credits Today", format="%.2f"),
                }
            )
            
            # Emergency Controls
            st.divider()
            st.markdown("#### ⚡ Emergency Controls")
            
            ec1, ec2 = st.columns([2, 1])
            with ec1:
                wh_names = live_status['WAREHOUSE_NAME'].tolist() if 'WAREHOUSE_NAME' in live_status.columns else []
                target_wh = st.selectbox("Select Warehouse", wh_names, key="guardian_wh_select")
            with ec2:
                st.write("")
                st.write("")
                if st.button("🔴 SUSPEND Warehouse", key="guardian_suspend", type="primary"):
                    if target_wh:
                        try:
                            client.execute_query(f"ALTER WAREHOUSE {target_wh} SUSPEND")
                            st.success(f"✅ {target_wh} suspended!")
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to suspend: {e}")
        else:
            st.info("No warehouse status data available.")
    except Exception as e:
        st.warning(f"Could not fetch live status: {e}")
    
    st.divider()
    
    # --- Section 2: Hourly Burst Detection ---
    st.markdown("#### 📊 Hourly Burst Detection")
    st.caption("*Hours where credit consumption exceeded 2x the historical average are flagged.*")
    
    burst_data = get_hourly_burst_data(client, min(days, 7))
    
    if not burst_data.empty:
        # Burst summary
        critical_count = len(burst_data[burst_data['SEVERITY'] == 'CRITICAL'])
        warning_count = len(burst_data[burst_data['SEVERITY'] == 'WARNING'])
        
        b1, b2, b3 = st.columns(3)
        with b1:
            if critical_count > 0:
                st.error(f"🔴 {critical_count} Critical Bursts (>3x avg)")
            else:
                st.success("🟢 No Critical Bursts")
        with b2:
            if warning_count > 0:
                st.warning(f"🟡 {warning_count} Warning Bursts (>2x avg)")
            else:
                st.success("🟢 No Warning Bursts")
        with b3:
            st.metric("Total Hours Analyzed", len(burst_data))
        
        # Burst chart per warehouse
        wh_filter = st.selectbox(
            "Filter by Warehouse", 
            ["All Warehouses"] + burst_data['WAREHOUSE_NAME'].unique().tolist(),
            key="burst_wh_filter"
        )
        
        chart_data = burst_data if wh_filter == "All Warehouses" else burst_data[burst_data['WAREHOUSE_NAME'] == wh_filter]
        
        if not chart_data.empty:
            # Aggregate by hour for the chart
            hourly_agg = chart_data.groupby('HOUR_BUCKET').agg(
                HOURLY_CREDITS=('HOURLY_CREDITS', 'sum'),
                AVG_HOURLY=('AVG_HOURLY', 'mean'),
                SEVERITY=('SEVERITY', lambda x: 'CRITICAL' if 'CRITICAL' in x.values else ('WARNING' if 'WARNING' in x.values else 'NORMAL'))
            ).reset_index()
            
            color_map = {'NORMAL': '#00D4AA', 'WARNING': '#FFD700', 'CRITICAL': '#FF4B4B'}
            
            fig = px.bar(
                hourly_agg, x='HOUR_BUCKET', y='HOURLY_CREDITS',
                color='SEVERITY', color_discrete_map=color_map,
                title="Hourly Credit Consumption with Anomaly Zones"
            )
            
            # Add average line
            avg_val = hourly_agg['AVG_HOURLY'].mean()
            fig.add_hline(y=avg_val, line_dash="dash", line_color="#29B5E8", 
                         annotation_text=f"Avg: {avg_val:.2f}")
            fig.add_hline(y=avg_val * 2, line_dash="dot", line_color="#FFD700",
                         annotation_text="Warning (2x)")
            fig.add_hline(y=avg_val * 3, line_dash="dot", line_color="#FF4B4B", 
                         annotation_text="Critical (3x)")
            
            fig.update_layout(
                plot_bgcolor='rgba(0,0,0,0)',
                paper_bgcolor='rgba(0,0,0,0)',
                font=dict(color='white'),
                height=400,
                margin=dict(l=60, r=20, t=50, b=60)
            )
            st.plotly_chart(fig, use_container_width=True)
        
        # Burst events table
        anomaly_events = burst_data[burst_data['SEVERITY'].isin(['CRITICAL', 'WARNING'])].head(30)
        if not anomaly_events.empty:
            with st.expander(f"📋 Burst Event Log ({len(anomaly_events)} events)", expanded=False):
                st.dataframe(
                    anomaly_events[['WAREHOUSE_NAME', 'HOUR_BUCKET', 'HOURLY_CREDITS', 'AVG_HOURLY', 'Z_SCORE', 'SEVERITY']],
                    use_container_width=True, hide_index=True,
                    column_config={
                        "HOURLY_CREDITS": st.column_config.NumberColumn("Credits", format="%.3f"),
                        "AVG_HOURLY": st.column_config.NumberColumn("Avg", format="%.3f"),
                        "Z_SCORE": st.column_config.NumberColumn("Z-Score", format="%.2f"),
                    }
                )
    else:
        st.info("No burst data available for the selected period.")


# =====================================================
# QUERY ATTRIBUTION TAB
# =====================================================

def render_query_attribution(client, days):
    """Full query cost attribution table + failed query cost calculator + user performance scorecard."""
    st.markdown("### 📋 Query Cost Attribution")
    st.caption("*Every query, its cost, duration, and status — click on any element to drill down.*")
    
    import plotly.express as px
    
    # Filters
    f1, f2, f3, f4, f5 = st.columns(5)
    with f1:
        attr_days = st.selectbox("Time Range", [1, 3, 7, 14, 30], index=2, key="attr_days",
                                  format_func=lambda x: f"Last {x} days")
    with f2:
        status_filter = st.selectbox("Status", ["All", "SUCCESS", "FAIL"], key="attr_status")
    with f3:
        limit = st.selectbox("Max Rows", [50, 100, 200, 500], index=1, key="attr_limit")
    with f4:
        sort_by = st.selectbox("Sort By", ["Duration", "Credits", "Data Scanned", "Start Time"], key="attr_sort")
    with f5:
        if st.button("🔄 Refresh", key="attr_refresh"):
            st.cache_data.clear()
    
    # Fetch data
    attr_data = get_full_query_attribution(client, attr_days, limit)
    
    if attr_data.empty:
        st.info("No query data available.")
        return
    
    # Apply status filter
    if status_filter != "All":
        attr_data = attr_data[attr_data['STATUS'] == status_filter]
    
    # User filter (interactive cross-filter)
    if 'USER_NAME' in attr_data.columns:
        users = ["All Users"] + sorted(attr_data['USER_NAME'].unique().tolist())
        user_filter = st.selectbox("🔍 Filter by User", users, key="attr_user_filter")
        if user_filter != "All Users":
            attr_data = attr_data[attr_data['USER_NAME'] == user_filter]
    
    # Warehouse filter
    if 'WAREHOUSE_NAME' in attr_data.columns:
        warehouses = ["All Warehouses"] + sorted(attr_data['WAREHOUSE_NAME'].unique().tolist())
        wh_filter_attr = st.selectbox("🏭 Filter by Warehouse", warehouses, key="attr_wh_filter")
        if wh_filter_attr != "All Warehouses":
            attr_data = attr_data[attr_data['WAREHOUSE_NAME'] == wh_filter_attr]
    
    if attr_data.empty:
        st.info("No queries match the selected filters.")
        return
    
    # Summary metrics
    total_est_credits = attr_data['EST_CREDITS'].sum() if 'EST_CREDITS' in attr_data.columns else 0
    total_queries = len(attr_data)
    failed = len(attr_data[attr_data['STATUS'] == 'FAIL']) if 'STATUS' in attr_data.columns else 0
    avg_duration = attr_data['DURATION_S'].mean() if 'DURATION_S' in attr_data.columns else 0
    total_gb = attr_data['GB_SCANNED'].sum() if 'GB_SCANNED' in attr_data.columns else 0
    
    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        st.metric("Queries", total_queries)
    with m2:
        st.metric("Est. Credits", f"{total_est_credits:.4f}")
    with m3:
        st.metric("Failed", failed, delta_color="inverse")
    with m4:
        st.metric("Avg Duration", f"{avg_duration:.1f}s")
    with m5:
        st.metric("Total GB Scanned", f"{total_gb:.3f}")
    
    st.divider()
    
    # Main query table — ENRICHED with more columns
    display_cols = ['QUERY_ID', 'SQL_TEXT', 'STATUS', 'USER_NAME', 'ROLE_NAME', 'WAREHOUSE_NAME', 
                    'WAREHOUSE_SIZE', 'DURATION_S', 'COMPILE_S', 'EXEC_S', 'QUEUE_S',
                    'START_TIME', 'ROWS_RETURNED', 'EST_CREDITS', 'CLOUD_CREDITS', 'GB_SCANNED', 'MB_WRITTEN']
    available_cols = [c for c in display_cols if c in attr_data.columns]
    
    st.dataframe(
        attr_data[available_cols],
        use_container_width=True,
        hide_index=True,
        column_config={
            "QUERY_ID": st.column_config.TextColumn("Query ID", width="small"),
            "SQL_TEXT": st.column_config.TextColumn("SQL Text", width="large"),
            "STATUS": st.column_config.TextColumn("Status"),
            "USER_NAME": st.column_config.TextColumn("User"),
            "ROLE_NAME": st.column_config.TextColumn("Role"),
            "WAREHOUSE_NAME": st.column_config.TextColumn("Warehouse"),
            "WAREHOUSE_SIZE": st.column_config.TextColumn("WH Size"),
            "DURATION_S": st.column_config.NumberColumn("Duration (s)", format="%.1f"),
            "COMPILE_S": st.column_config.NumberColumn("Compile (s)", format="%.2f"),
            "EXEC_S": st.column_config.NumberColumn("Execute (s)", format="%.2f"),
            "QUEUE_S": st.column_config.NumberColumn("Queue (s)", format="%.2f"),
            "EST_CREDITS": st.column_config.NumberColumn("Est Credits", format="%.6f"),
            "CLOUD_CREDITS": st.column_config.NumberColumn("Cloud Cr", format="%.6f"),
            "GB_SCANNED": st.column_config.NumberColumn("GB Scanned", format="%.3f"),
            "MB_WRITTEN": st.column_config.NumberColumn("MB Written", format="%.1f"),
            "ROWS_RETURNED": st.column_config.NumberColumn("Rows", format="%d"),
        }
    )
    
    # Interactive: Click to inspect a query
    if 'QUERY_ID' in attr_data.columns and not attr_data.empty:
        with st.expander("🔎 Inspect Query Detail", expanded=False):
            query_options = attr_data.apply(
                lambda r: f"[{r.get('EST_CREDITS', 0):.4f} Cr] {str(r.get('SQL_TEXT', ''))[:80]}... ({r.get('USER_NAME', '')})", axis=1
            ).tolist()
            selected_idx = st.selectbox("Select Query", range(len(query_options)), format_func=lambda i: query_options[i], key="inspect_q")
            
            row = attr_data.iloc[selected_idx]
            d1, d2, d3 = st.columns(3)
            with d1:
                st.markdown(f"**Query ID:** `{row.get('QUERY_ID', 'N/A')}`")
                st.markdown(f"**User:** `{row.get('USER_NAME', 'N/A')}`")
                st.markdown(f"**Role:** `{row.get('ROLE_NAME', 'N/A')}`")
            with d2:
                st.markdown(f"**Warehouse:** `{row.get('WAREHOUSE_NAME', 'N/A')}` ({row.get('WAREHOUSE_SIZE', 'N/A')})")
                st.markdown(f"**Duration:** {row.get('DURATION_S', 0):.1f}s (Compile: {row.get('COMPILE_S', 0):.2f}s + Exec: {row.get('EXEC_S', 0):.2f}s)")
                st.markdown(f"**Queue Wait:** {row.get('QUEUE_S', 0):.2f}s")
            with d3:
                st.markdown(f"**Est. Credits:** {row.get('EST_CREDITS', 0):.6f}")
                st.markdown(f"**GB Scanned:** {row.get('GB_SCANNED', 0):.3f}")
                st.markdown(f"**Status:** {row.get('STATUS', 'N/A')}")
            
            st.code(str(row.get('SQL_TEXT', 'N/A')), language='sql')
    
    st.divider()
    
    # --- Failed Query Cost Calculator ---
    st.markdown("### 💸 Failed Query Cost Calculator")
    st.caption("*Total credits wasted on failed queries — money that produced no results.*")
    
    failed_costs = get_failed_query_costs(client, days)
    
    if not failed_costs.empty:
        total_wasted = failed_costs['EST_WASTED_CREDITS'].sum() if 'EST_WASTED_CREDITS' in failed_costs.columns else 0
        total_failed = failed_costs['FAILED_COUNT'].sum() if 'FAILED_COUNT' in failed_costs.columns else 0
        
        w1, w2, w3 = st.columns(3)
        with w1:
            st.metric("💰 Total Wasted Credits", f"{total_wasted:.4f}", delta_color="inverse")
        with w2:
            st.metric("Est Wasted Cost ($3/cr)", f"${total_wasted * 3:.2f}", delta_color="inverse")
        with w3:
            st.metric("Total Failed Queries", int(total_failed))
        
        st.dataframe(
            failed_costs, use_container_width=True, hide_index=True,
            column_config={
                "EST_WASTED_CREDITS": st.column_config.NumberColumn("Wasted Credits", format="%.6f"),
                "WASTED_CLOUD_CREDITS": st.column_config.NumberColumn("Cloud Credits", format="%.6f"),
                "TOTAL_DURATION_S": st.column_config.NumberColumn("Duration (s)", format="%.1f"),
                "TOTAL_GB_SCANNED": st.column_config.NumberColumn("GB Scanned", format="%.3f"),
            }
        )
        
        with st.expander("🔍 Failed Query Details (Last 7 days)", expanded=False):
            failed_details = get_failed_query_details(client, min(days, 7))
            if not failed_details.empty:
                st.dataframe(failed_details, use_container_width=True, hide_index=True)
            else:
                st.info("No failed query details.")
    else:
        st.success("✅ No failed queries found — zero wasted credits!")
    
    st.divider()
    
    # --- USER PERFORMANCE SCORECARD ---
    st.markdown("### 👤 User Performance Scorecard")
    st.caption("*Who's running unoptimized queries? Efficiency scores based on fail rate, cache usage, spillage, and duration.*")
    
    scorecard = get_user_performance_scorecard(client, attr_days)
    
    if scorecard.empty:
        st.info("No user performance data available.")
        return
    
    # Overall summary
    avg_eff = scorecard['EFFICIENCY_SCORE'].mean() if 'EFFICIENCY_SCORE' in scorecard.columns else 0
    worst_user = scorecard.loc[scorecard['EFFICIENCY_SCORE'].idxmin()] if 'EFFICIENCY_SCORE' in scorecard.columns else None
    top_spender = scorecard.loc[scorecard['EST_TOTAL_CREDITS'].idxmax()] if 'EST_TOTAL_CREDITS' in scorecard.columns else None
    
    u1, u2, u3, u4 = st.columns(4)
    with u1:
        eff_icon = "🟢" if avg_eff >= 75 else ("🟡" if avg_eff >= 50 else "🔴")
        st.metric(f"{eff_icon} Avg Efficiency", f"{avg_eff:.0f}/100")
    with u2:
        st.metric("Users Active", len(scorecard))
    with u3:
        if worst_user is not None:
            st.metric("⚠️ Lowest Score", f"{worst_user.get('USER_NAME', 'N/A')}", 
                      f"Score: {worst_user.get('EFFICIENCY_SCORE', 0):.0f}")
    with u4:
        if top_spender is not None:
            st.metric("💰 Top Spender", f"{top_spender.get('USER_NAME', 'N/A')}",
                      f"{top_spender.get('EST_TOTAL_CREDITS', 0):.4f} Cr")
    
    st.divider()
    
    # Efficiency chart
    if 'EFFICIENCY_SCORE' in scorecard.columns:
        fig_users = px.bar(
            scorecard.sort_values('EFFICIENCY_SCORE'),
            x='EFFICIENCY_SCORE', y='USER_NAME', orientation='h',
            color='EFFICIENCY_SCORE',
            color_continuous_scale=['#FF4B4B', '#FFD700', '#00D4AA'],
            range_color=[0, 100],
            title="User Efficiency Scores (Higher = Better)"
        )
        fig_users.update_layout(
            plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
            font=dict(color='white'), height=max(250, len(scorecard) * 35),
            margin=dict(l=120, r=20, t=50, b=30),
            yaxis_title="", xaxis_title="Efficiency Score"
        )
        st.plotly_chart(fig_users, use_container_width=True)
    
    # Full scorecard table
    score_cols = ['USER_NAME', 'EFFICIENCY_SCORE', 'TOTAL_QUERIES', 'FAILED_QUERIES', 'FAIL_RATE_PCT',
                  'AVG_DURATION_S', 'MAX_DURATION_S', 'TOTAL_GB_SCANNED', 'AVG_CACHE_HIT_PCT',
                  'REMOTE_SPILL_QUERIES', 'EST_TOTAL_CREDITS', 'WAREHOUSES_USED', 'ACTIVE_DAYS']
    avail_score_cols = [c for c in score_cols if c in scorecard.columns]
    
    st.dataframe(
        scorecard[avail_score_cols],
        use_container_width=True, hide_index=True,
        column_config={
            "EFFICIENCY_SCORE": st.column_config.ProgressColumn("Efficiency", min_value=0, max_value=100, format="%d"),
            "FAIL_RATE_PCT": st.column_config.NumberColumn("Fail %", format="%.1f%%"),
            "AVG_DURATION_S": st.column_config.NumberColumn("Avg Duration (s)", format="%.1f"),
            "MAX_DURATION_S": st.column_config.NumberColumn("Max Duration (s)", format="%.1f"),
            "TOTAL_GB_SCANNED": st.column_config.NumberColumn("GB Scanned", format="%.3f"),
            "AVG_CACHE_HIT_PCT": st.column_config.NumberColumn("Cache Hit %", format="%.1f%%"),
            "EST_TOTAL_CREDITS": st.column_config.NumberColumn("Est Credits", format="%.4f"),
        }
    )
    
    # Per-user issues
    with st.expander("💡 User Optimization Insights", expanded=False):
        for _, user_row in scorecard.iterrows():
            name = user_row.get('USER_NAME', 'Unknown')
            score = user_row.get('EFFICIENCY_SCORE', 100)
            issues = []
            
            fr = user_row.get('FAIL_RATE_PCT', 0) or 0
            if fr > 20:
                issues.append(f"🔴 **{fr:.1f}% fail rate** — {int(user_row.get('FAILED_QUERIES', 0))} failed queries")
            elif fr > 5:
                issues.append(f"🟡 **{fr:.1f}% fail rate** — review error patterns")
            
            ch = user_row.get('AVG_CACHE_HIT_PCT', 100) or 100
            if ch < 20:
                issues.append(f"🔴 **{ch:.0f}% cache hit** — queries are scanning too much raw data")
            
            rs = user_row.get('REMOTE_SPILL_QUERIES', 0) or 0
            if rs > 10:
                issues.append(f"🔴 **{int(rs)} queries spilled to remote storage** — warehouse undersized for this user's workload")
            elif rs > 0:
                issues.append(f"🟡 **{int(rs)} queries with remote spillage**")
            
            md = user_row.get('MAX_DURATION_S', 0) or 0
            if md > 3600:
                issues.append(f"🔴 **Longest query: {md/60:.0f} min** — possible runaway query")
            
            if issues:
                icon = "🔴" if score < 50 else ("🟡" if score < 75 else "🟢")
                st.markdown(f"**{icon} {name}** (Score: {score:.0f}/100)")
                for issue in issues:
                    st.markdown(f"  - {issue}")
                st.markdown("---")


# =====================================================
# ALERT BUILDER TAB
# =====================================================

def render_alert_builder(client):
    """Custom metric-based alert creation leveraging Snowflake's native ALERT system."""
    st.markdown("### 🔔 Alert Builder — Custom Metric Triggers")
    st.caption("*Create Snowflake-native alerts that fire when your custom conditions are met.*")
    
    # Ensure alert log table exists on page load (prevents query errors)
    try:
        client.execute_query("""
            CREATE TABLE IF NOT EXISTS APP_ANALYTICS.ALERT_LOG (
                ALERT_NAME VARCHAR,
                TRIGGERED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
                DETAILS VARIANT
            )
        """, log=False)
    except:
        pass  # May lack permissions, that's OK
    
    # Info about how it works
    with st.expander("ℹ️ How Alerts Work", expanded=False):
        st.markdown("""
        **Snowflake Alerts** run a SQL condition on a schedule. When the condition returns rows, the alert fires.
        
        - Alerts are created as `CREATE ALERT` objects in Snowflake
        - They run on a schedule (e.g., every 5 minutes, every hour)
        - When triggered, they can log to a table, call a procedure, or execute any SQL
        - Alerts use a **serverless compute** model (no warehouse needed)
        
        **Supported Triggers:**
        - Credit burn > threshold per hour
        - Failed query count > threshold
        - Queue time > threshold seconds
        - Warehouse running with no queries
        - Custom SQL condition
        """)
    
    st.divider()
    
    # --- Create New Alert ---
    st.markdown("#### ➕ Create New Alert")
    
    # Pre-built templates
    alert_templates = {
        "🔥 Credit Burst Alert": {
            "description": "Fires when hourly credit usage exceeds threshold",
            "schedule": "5",
            "condition": """SELECT WAREHOUSE_NAME, SUM(CREDITS_USED) AS HOURLY_CREDITS
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE START_TIME >= DATEADD(hour, -1, CURRENT_TIMESTAMP())
GROUP BY 1
HAVING SUM(CREDITS_USED) > {threshold}""",
            "default_threshold": "5.0"
        },
        "❌ Failed Query Spike": {
            "description": "Fires when failed query count exceeds threshold in last hour",
            "schedule": "15",
            "condition": """SELECT COUNT(*) AS FAIL_COUNT
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE START_TIME >= DATEADD(hour, -1, CURRENT_TIMESTAMP())
AND EXECUTION_STATUS = 'FAIL'
HAVING COUNT(*) > {threshold}""",
            "default_threshold": "10"
        },
        "⏳ Queue Time Alert": {
            "description": "Fires when avg queue time exceeds threshold seconds",
            "schedule": "10",
            "condition": """SELECT WAREHOUSE_NAME, 
    AVG(QUEUED_PROVISIONING_TIME + QUEUED_OVERLOAD_TIME) / 1000 AS AVG_QUEUE_S
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE START_TIME >= DATEADD(hour, -1, CURRENT_TIMESTAMP())
AND WAREHOUSE_NAME IS NOT NULL
GROUP BY 1
HAVING AVG_QUEUE_S > {threshold}""",
            "default_threshold": "30"
        },
        "💤 Idle Warehouse Waste": {
            "description": "Fires when warehouse is running but had zero queries in last 30 min",
            "schedule": "30",
            "condition": """SELECT wm.WAREHOUSE_NAME, SUM(wm.CREDITS_USED) AS CREDITS_BURNED
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY wm
WHERE wm.START_TIME >= DATEADD(minute, -30, CURRENT_TIMESTAMP())
AND wm.CREDITS_USED > 0
AND wm.WAREHOUSE_NAME NOT IN (
    SELECT DISTINCT WAREHOUSE_NAME 
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE START_TIME >= DATEADD(minute, -30, CURRENT_TIMESTAMP())
)
GROUP BY 1
HAVING SUM(wm.CREDITS_USED) > {threshold}""",
            "default_threshold": "0.1"
        },
        "📝 Custom SQL Condition": {
            "description": "Write your own SQL condition",
            "schedule": "60",
            "condition": "-- Your custom SQL here\nSELECT 1 WHERE 1=0",
            "default_threshold": "0"
        }
    }
    
    selected_template = st.selectbox("Alert Template", list(alert_templates.keys()), key="alert_template")
    template = alert_templates[selected_template]
    
    st.info(f"**{template['description']}**")
    
    ac1, ac2, ac3 = st.columns([2, 1, 1])
    with ac1:
        alert_name = st.text_input("Alert Name", value=selected_template.split(" ", 1)[1].replace(" ", "_").upper(), key="alert_name")
    with ac2:
        threshold = st.text_input("Threshold", value=template['default_threshold'], key="alert_threshold")
    with ac3:
        schedule_min = st.text_input("Check Every (min)", value=template['schedule'], key="alert_schedule")
    
    # SQL condition preview
    condition_sql = template['condition'].replace("{threshold}", threshold)
    condition_sql = st.text_area("Condition SQL (returns rows = alert fires)", value=condition_sql, height=200, key="alert_sql")
    
    # Action on trigger
    action_type = st.selectbox("Action When Triggered", [
        "Log to Alert Table",
        "Suspend Warehouse",
        "Log + Suspend Warehouse"
    ], key="alert_action")
    
    if st.button("🚀 Create Alert", type="primary", key="create_alert_btn"):
        try:
            # Sanitize alert name
            safe_name = re.sub(r'[^A-Za-z0-9_]', '_', alert_name).upper()
            
            # Build action SQL
            if action_type == "Log to Alert Table":
                action_sql = f"""
                BEGIN
                    INSERT INTO APP_ANALYTICS.ALERT_LOG (ALERT_NAME, TRIGGERED_AT, DETAILS)
                    SELECT '{safe_name}', CURRENT_TIMESTAMP(), OBJECT_CONSTRUCT('data', ARRAY_AGG(OBJECT_CONSTRUCT(*)))
                    FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));
                END"""
            elif action_type == "Suspend Warehouse":
                action_sql = f"""
                BEGIN
                    LET c1 CURSOR FOR {condition_sql};
                    FOR row_data IN c1 DO
                        ALTER WAREHOUSE IF EXISTS IDENTIFIER(row_data.WAREHOUSE_NAME) SUSPEND;
                    END FOR;
                END"""
            else:
                action_sql = f"""
                BEGIN
                    INSERT INTO APP_ANALYTICS.ALERT_LOG (ALERT_NAME, TRIGGERED_AT, DETAILS)
                    VALUES ('{safe_name}', CURRENT_TIMESTAMP(), 'Triggered');
                    LET c1 CURSOR FOR {condition_sql};
                    FOR row_data IN c1 DO
                        ALTER WAREHOUSE IF EXISTS IDENTIFIER(row_data.WAREHOUSE_NAME) SUSPEND;
                    END FOR;
                END"""
            
            # Ensure alert log table exists
            try:
                client.execute_query("""
                    CREATE TABLE IF NOT EXISTS APP_ANALYTICS.ALERT_LOG (
                        ALERT_NAME VARCHAR,
                        TRIGGERED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
                        DETAILS VARIANT
                    )
                """, log=False)
            except:
                pass
            
            # Create the Snowflake alert
            create_sql = f"""
            CREATE OR REPLACE ALERT APP_CONTEXT.ALERT_{safe_name}
            WAREHOUSE = COMPUTE_WH
            SCHEDULE = '{schedule_min} MINUTE'
            IF (EXISTS ({condition_sql}))
            THEN {action_sql}
            """
            
            client.execute_query(create_sql)
            
            # Resume the alert
            client.execute_query(f"ALTER ALERT APP_CONTEXT.ALERT_{safe_name} RESUME")
            
            st.success(f"✅ Alert `ALERT_{safe_name}` created and activated! Checking every {schedule_min} minutes.")
            st.cache_data.clear()
        except Exception as e:
            st.error(f"Failed to create alert: {e}")
            with st.expander("Debug"):
                st.code(str(e))
    
    st.divider()
    
    # --- Existing Alerts ---
    st.markdown("#### 📋 Existing Alerts")
    
    existing = get_existing_alerts(client)
    if not existing.empty:
        st.dataframe(existing, use_container_width=True, hide_index=True)
        
        # Alert management
        alert_names = existing['name'].tolist() if 'name' in existing.columns else []
        if alert_names:
            man_col1, man_col2 = st.columns([2, 1])
            with man_col1:
                manage_alert = st.selectbox("Manage Alert", alert_names, key="manage_alert")
            with man_col2:
                st.write("")
                st.write("")
                mc1, mc2 = st.columns(2)
                with mc1:
                    if st.button("⏸️ Suspend", key="suspend_alert"):
                        try:
                            client.execute_query(f"ALTER ALERT {manage_alert} SUSPEND")
                            st.success(f"Alert {manage_alert} suspended")
                            st.cache_data.clear()
                        except Exception as e:
                            st.error(f"Error: {e}")
                with mc2:
                    if st.button("🗑️ Drop", key="drop_alert"):
                        try:
                            client.execute_query(f"DROP ALERT IF EXISTS {manage_alert}")
                            st.success(f"Alert {manage_alert} dropped")
                            st.cache_data.clear()
                        except Exception as e:
                            st.error(f"Error: {e}")
    else:
        st.info("No alerts configured yet. Create one above!")
    
    # Alert history
    st.divider()
    st.markdown("#### 📜 Alert Trigger History")
    try:
        alert_log = client.execute_query("SELECT * FROM APP_ANALYTICS.ALERT_LOG ORDER BY TRIGGERED_AT DESC LIMIT 50")
        if not alert_log.empty:
            st.dataframe(alert_log, use_container_width=True, hide_index=True)
        else:
            st.info("No alert triggers recorded yet.")
    except:
        st.info("Alert log table not yet created. It will be created when you create your first alert.")


# =====================================================
# WAREHOUSE OPTIMIZER TAB
# =====================================================

def render_warehouse_optimizer(client, days):
    """Deep warehouse health scan with actionable optimization recommendations."""
    st.markdown("### 🏥 Warehouse Health Optimizer")
    st.caption("*Comprehensive scan of every warehouse with health scores and actionable recommendations.*")
    
    import plotly.express as px
    import plotly.graph_objects as go
    
    scan_data = get_warehouse_optimization_scan(client, min(days, 14))
    
    if scan_data.empty:
        st.info("No warehouse data available for optimization scan.")
        return
    
    # Overall health summary
    avg_health = scan_data['HEALTH_SCORE'].mean() if 'HEALTH_SCORE' in scan_data.columns else 0
    worst_wh = scan_data.iloc[-1]['WAREHOUSE_NAME'] if not scan_data.empty else "N/A"
    worst_score = scan_data['HEALTH_SCORE'].min() if 'HEALTH_SCORE' in scan_data.columns else 0
    total_credits = scan_data['TOTAL_CREDITS'].sum() if 'TOTAL_CREDITS' in scan_data.columns else 0
    
    h1, h2, h3, h4 = st.columns(4)
    with h1:
        score_color = "🟢" if avg_health >= 75 else ("🟡" if avg_health >= 50 else "🔴")
        st.metric(f"{score_color} Avg Health Score", f"{avg_health:.0f}/100")
    with h2:
        st.metric("Warehouses Scanned", len(scan_data))
    with h3:
        st.metric("Total Credits Used", f"{total_credits:.2f}")
    with h4:
        st.metric("⚠️ Worst Warehouse", worst_wh, f"Score: {worst_score:.0f}")
    
    st.divider()
    
    # Health score chart
    st.markdown("#### 📊 Health Score by Warehouse")
    
    fig = px.bar(
        scan_data.sort_values('HEALTH_SCORE'),
        x='HEALTH_SCORE', y='WAREHOUSE_NAME',
        orientation='h',
        color='HEALTH_SCORE',
        color_continuous_scale=['#FF4B4B', '#FFD700', '#00D4AA'],
        range_color=[0, 100],
        title="Warehouse Health Scores (Higher = Healthier)"
    )
    fig.update_layout(
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        font=dict(color='white'),
        height=max(250, len(scan_data) * 40),
        margin=dict(l=150, r=20, t=50, b=30),
        yaxis_title="", xaxis_title="Health Score"
    )
    st.plotly_chart(fig, use_container_width=True)
    
    st.divider()
    
    # Detailed metrics per warehouse
    st.markdown("#### 🔬 Detailed Warehouse Metrics")
    
    metric_cols = ['WAREHOUSE_NAME', 'HEALTH_SCORE', 'TOTAL_CREDITS', 'TOTAL_QUERIES', 'FAIL_RATE_PCT',
                   'AVG_QUEUE_S', 'AVG_SPILL_LOCAL_GB', 'AVG_SPILL_REMOTE_GB', 'AVG_CACHE_HIT_PCT',
                   'AVG_LOAD', 'PEAK_LOAD']
    available_metrics = [c for c in metric_cols if c in scan_data.columns]
    
    st.dataframe(
        scan_data[available_metrics],
        use_container_width=True,
        hide_index=True,
        column_config={
            "HEALTH_SCORE": st.column_config.ProgressColumn("Health", min_value=0, max_value=100, format="%d"),
            "TOTAL_CREDITS": st.column_config.NumberColumn("Credits", format="%.2f"),
            "FAIL_RATE_PCT": st.column_config.NumberColumn("Fail %", format="%.1f%%"),
            "AVG_QUEUE_S": st.column_config.NumberColumn("Avg Queue (s)", format="%.1f"),
            "AVG_SPILL_LOCAL_GB": st.column_config.NumberColumn("Spill Local (GB)", format="%.3f"),
            "AVG_SPILL_REMOTE_GB": st.column_config.NumberColumn("Spill Remote (GB)", format="%.3f"),
            "AVG_CACHE_HIT_PCT": st.column_config.NumberColumn("Cache Hit %", format="%.1f%%"),
            "AVG_LOAD": st.column_config.NumberColumn("Avg Load", format="%.3f"),
            "PEAK_LOAD": st.column_config.NumberColumn("Peak Load", format="%.3f"),
        }
    )
    
    st.divider()
    
    # Per-warehouse recommendations
    st.markdown("#### 💡 Optimization Recommendations")
    
    for _, row in scan_data.iterrows():
        wh_name = row['WAREHOUSE_NAME']
        score = row.get('HEALTH_SCORE', 100)
        issues = []
        
        # Check each metric for issues
        fail_rate = row.get('FAIL_RATE_PCT', 0) or 0
        if fail_rate > 10:
            issues.append(("🔴 High Failure Rate", f"{fail_rate:.1f}% of queries are failing. Investigate error patterns and fix failing queries to stop wasting credits."))
        elif fail_rate > 5:
            issues.append(("🟡 Elevated Failure Rate", f"{fail_rate:.1f}% failure rate. Review recent failed queries in the Query Attribution tab."))
        
        avg_queue = row.get('AVG_QUEUE_S', 0) or 0
        if avg_queue > 10:
            issues.append(("🔴 Severe Queue Times", f"Avg {avg_queue:.1f}s queue wait. Scale UP the warehouse size or enable multi-cluster (auto-scale)."))
        elif avg_queue > 3:
            issues.append(("🟡 Noticeable Queue Times", f"Avg {avg_queue:.1f}s queue. Consider scaling up during peak hours."))
        
        spill_remote = row.get('AVG_SPILL_REMOTE_GB', 0) or 0
        spill_local = row.get('AVG_SPILL_LOCAL_GB', 0) or 0
        if spill_remote > 0.1:
            issues.append(("🔴 Remote Disk Spillage", f"Avg {spill_remote:.3f} GB spilling to remote storage. Warehouse is TOO SMALL — scale UP immediately. This causes massive slowdowns."))
        elif spill_local > 1:
            issues.append(("🟡 Local Disk Spillage", f"Avg {spill_local:.3f} GB spilling to local disk. Consider scaling up for heavy queries."))
        
        cache_hit = row.get('AVG_CACHE_HIT_PCT', 100) or 100
        if cache_hit < 30:
            issues.append(("🟡 Low Cache Hit Rate", f"Only {cache_hit:.1f}% of data served from cache. Reduce auto-suspend time to keep cache warm, or pre-warm the warehouse."))
        
        avg_load = row.get('AVG_LOAD', 0) or 0
        total_credits = row.get('TOTAL_CREDITS', 0) or 0
        if avg_load < 0.05 and total_credits > 1:
            issues.append(("🟡 Underutilized Warehouse", f"Very low avg load ({avg_load:.3f}) but {total_credits:.2f} credits used. Consider reducing auto-suspend time or downsizing."))
        
        peak_load = row.get('PEAK_LOAD', 0) or 0
        if peak_load > 5 and avg_load < 1:
            issues.append(("🟡 Bursty Workload", f"Peak load ({peak_load:.1f}) >> avg load ({avg_load:.2f}). Consider enabling multi-cluster auto-scaling."))
        
        if issues:
            with st.expander(f"{'🔴' if score < 50 else '🟡' if score < 75 else '🟢'} **{wh_name}** — Score: {score:.0f}/100 ({len(issues)} issues)", expanded=(score < 50)):
                for title, detail in issues:
                    st.markdown(f"**{title}**: {detail}")
        elif score >= 90:
            st.success(f"✅ **{wh_name}** — Score: {score:.0f}/100 — No issues detected!")


# =====================================================
# RESOURCE MONITOR MANAGER TAB
# =====================================================

def render_resource_monitors(client):
    """Resource Monitor Manager — Safe cost protection that doesn't break pipelines."""
    st.markdown("### 🛡️ Resource Monitor Manager")
    st.caption("*Snowflake-native cost protection that safely limits spend without breaking dbt, pipelines, or tasks.*")
    
    # Answer the user's key question about notifications
    with st.expander("ℹ️ How Automated Notifications Work (Even When App Is Closed)", expanded=False):
        st.markdown("""
        **Great question!** The Streamlit app DOES close when not in use. Here's how we solve it:
        
        | Method | Runs Without App? | How |
        |--------|-------------------|-----|
        | **Snowflake Resource Monitor** | ✅ YES | Native Snowflake object, always active |
        | **Snowflake ALERT** | ✅ YES | Serverless scheduled SQL check |
        | **Snowflake Task** | ✅ YES | Scheduled stored procedure |
        | **SYSTEM$SEND_EMAIL** | ✅ YES | Snowflake sends email directly via AWS SES |
        | **Notification Integration** | ✅ YES | Webhook to Slack/Teams/PagerDuty |
        | **App-based check** | ❌ NO | Only when someone has the app open |
        
        **All the methods below create server-side Snowflake objects that run 24/7 independently.**
        """)
    
    rm_tab1, rm_tab2, rm_tab3, rm_tab4 = st.tabs([
        "📊 Existing Monitors",
        "➕ Create Monitor", 
        "🛡️ Warehouse Protection",
        "📧 Automated Notifications"
    ])
    
    # ---- TAB 1: View Existing Resource Monitors ----
    with rm_tab1:
        st.markdown("#### Current Resource Monitors")
        try:
            monitors = client.execute_query("SHOW RESOURCE MONITORS", log=False)
            if not monitors.empty:
                monitors.columns = [c.upper() for c in monitors.columns]
                display_cols = [c for c in ['NAME', 'CREDIT_QUOTA', 'USED_CREDITS', 'REMAINING_CREDITS', 
                                            'LEVEL', 'FREQUENCY', 'START_TIME', 'END_TIME', 'SUSPEND_AT',
                                            'SUSPEND_IMMEDIATE_AT', 'NOTIFY_AT'] if c in monitors.columns]
                st.dataframe(monitors[display_cols] if display_cols else monitors, 
                           use_container_width=True, hide_index=True)
                
                # Quick actions
                st.divider()
                monitor_names = monitors['NAME'].tolist() if 'NAME' in monitors.columns else []
                if monitor_names:
                    ac1, ac2 = st.columns([2, 1])
                    with ac1:
                        selected_rm = st.selectbox("Select Monitor", monitor_names, key="rm_select")
                    with ac2:
                        st.write("")
                        st.write("")
                        if st.button("🗑️ Drop Monitor", key="drop_rm"):
                            try:
                                client.execute_query(f"DROP RESOURCE MONITOR IF EXISTS {selected_rm}")
                                st.success(f"Dropped {selected_rm}")
                                st.cache_data.clear()
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")
            else:
                st.info("No resource monitors configured. Create one in the next tab!")
        except Exception as e:
            st.warning(f"Could not fetch resource monitors: {e}")
    
    # ---- TAB 2: Create Resource Monitor ----
    with rm_tab2:
        st.markdown("#### Create a Resource Monitor")
        st.caption("*Resource Monitors are Snowflake's native and safest way to control costs.*")
        
        st.info("""
        **How it works safely:**
        - `NOTIFY` → Just sends an alert, nothing breaks
        - `SUSPEND` → Waits for running queries to finish, THEN suspends (safe for dbt/pipelines)
        - `SUSPEND_IMMEDIATELY` → Emergency kill, last resort only
        """)
        
        c1, c2, c3 = st.columns(3)
        with c1:
            rm_name = st.text_input("Monitor Name", value="COST_GUARDIAN", key="rm_name")
        with c2:
            credit_quota = st.number_input("Credit Quota", min_value=1, value=50, key="rm_quota",
                                           help="Maximum credits allowed in the frequency period")
        with c3:
            frequency = st.selectbox("Reset Frequency", ["MONTHLY", "WEEKLY", "DAILY"], key="rm_freq")
        
        st.markdown("**Trigger Actions:**")
        
        t1, t2, t3, t4 = st.columns(4)
        with t1:
            notify_pct = st.number_input("Notify at %", min_value=10, max_value=100, value=75, key="rm_notify")
        with t2:
            notify2_pct = st.number_input("Urgent Notify %", min_value=10, max_value=100, value=90, key="rm_notify2")
        with t3:
            suspend_pct = st.number_input("Suspend at %", min_value=10, max_value=200, value=100, key="rm_suspend",
                                          help="SUSPEND waits for running queries to finish")
        with t4:
            kill_pct = st.number_input("Kill at %", min_value=10, max_value=200, value=110, key="rm_kill",
                                       help="SUSPEND_IMMEDIATELY kills running queries")
        
        # Warehouse assignment
        st.markdown("**Assign to Warehouses:**")
        try:
            wh_list = client.execute_query("SHOW WAREHOUSES", log=False)
            wh_list.columns = [c.upper() for c in wh_list.columns]
            wh_names = wh_list['NAME'].tolist() if 'NAME' in wh_list.columns else []
        except:
            wh_names = []
        
        selected_whs = st.multiselect("Select Warehouses", wh_names, key="rm_warehouses",
                                       help="Leave empty to apply at account level")
        
        if st.button("🚀 Create Resource Monitor", type="primary", key="create_rm"):
            try:
                safe_name = re.sub(r'[^A-Za-z0-9_]', '_', rm_name).upper()
                
                create_sql = f"""
                CREATE OR REPLACE RESOURCE MONITOR {safe_name}
                WITH CREDIT_QUOTA = {credit_quota}
                FREQUENCY = {frequency}
                START_TIMESTAMP = IMMEDIATELY
                TRIGGERS
                    ON {notify_pct} PERCENT DO NOTIFY
                    ON {notify2_pct} PERCENT DO NOTIFY
                    ON {suspend_pct} PERCENT DO SUSPEND
                    ON {kill_pct} PERCENT DO SUSPEND_IMMEDIATELY
                """
                
                client.execute_query(create_sql)
                st.success(f"✅ Resource Monitor `{safe_name}` created!")
                
                # Assign to warehouses
                for wh in selected_whs:
                    try:
                        client.execute_query(f"ALTER WAREHOUSE {wh} SET RESOURCE_MONITOR = {safe_name}")
                        st.success(f"  → Assigned to `{wh}`")
                    except Exception as e:
                        st.warning(f"  → Could not assign to {wh}: {e}")
                
                st.cache_data.clear()
            except Exception as e:
                st.error(f"Failed to create: {e}")
    
    # ---- TAB 3: Warehouse Protection Classification ----
    with rm_tab3:
        st.markdown("#### Warehouse Protection & Statement Controls")
        st.caption("*Set safe limits per warehouse to prevent runaway queries without killing the warehouse.*")
        
        try:
            wh_list = client.execute_query("SHOW WAREHOUSES", log=False)
            wh_list.columns = [c.upper() for c in wh_list.columns]
        except:
            st.error("Could not fetch warehouses.")
            return
        
        if wh_list.empty:
            st.info("No warehouses found.")
            return
        
        wh_name_col = 'NAME' if 'NAME' in wh_list.columns else wh_list.columns[0]
        
        for _, wh_row in wh_list.iterrows():
            wh_name = wh_row[wh_name_col]
            current_size = wh_row.get('SIZE', 'N/A')
            current_suspend = wh_row.get('AUTO_SUSPEND', 'N/A')
            
            with st.expander(f"⚙️ **{wh_name}** (Size: {current_size}, Auto-Suspend: {current_suspend}s)"):
                sc1, sc2, sc3 = st.columns(3)
                
                with sc1:
                    stmt_timeout = st.number_input(
                        "Statement Timeout (s)", 
                        min_value=0, max_value=86400, value=900,
                        key=f"timeout_{wh_name}",
                        help="Kill individual queries after this many seconds (0 = no limit)"
                    )
                
                with sc2:
                    queue_timeout = st.number_input(
                        "Queue Timeout (s)",
                        min_value=0, max_value=3600, value=120,
                        key=f"queue_{wh_name}",
                        help="Cancel queries waiting in queue longer than this"
                    )
                
                with sc3:
                    new_auto_suspend = st.number_input(
                        "Auto-Suspend (s)",
                        min_value=0, max_value=3600, value=120,
                        key=f"suspend_{wh_name}",
                        help="Suspend warehouse after this many idle seconds"
                    )
                
                if st.button(f"Apply to {wh_name}", key=f"apply_{wh_name}"):
                    try:
                        alter_parts = []
                        if stmt_timeout > 0:
                            alter_parts.append(f"STATEMENT_TIMEOUT_IN_SECONDS = {stmt_timeout}")
                        if queue_timeout > 0:
                            alter_parts.append(f"STATEMENT_QUEUED_TIMEOUT_IN_SECONDS = {queue_timeout}")
                        alter_parts.append(f"AUTO_SUSPEND = {new_auto_suspend}")
                        
                        alter_sql = f"ALTER WAREHOUSE {wh_name} SET {' '.join(alter_parts)}"
                        client.execute_query(alter_sql)
                        st.success(f"✅ Applied to {wh_name}")
                    except Exception as e:
                        st.error(f"Failed: {e}")
    
    # ---- TAB 4: Automated Notifications ----
    with rm_tab4:
        st.markdown("#### 📧 Automated Notification System")
        st.caption("*These run 24/7 inside Snowflake — they work even when the app is closed.*")
        
        notif_method = st.selectbox("Notification Method", [
            "📧 Email (via Snowflake Email Integration)",
            "📝 Log to Table Only",
            "🔗 Webhook (Slack/Teams/PagerDuty)"
        ], key="notif_method")
        
        st.divider()
        
        # --- Email Setup ---
        if "Email" in notif_method:
            st.markdown("##### 📧 Email Notification Setup")
            st.info("""
            **How it works:** Snowflake can send emails directly using `SYSTEM$SEND_EMAIL()` 
            via an Email Notification Integration (backed by AWS SES, Azure, or GCP).
            
            **Prerequisites:**
            1. An ACCOUNTADMIN must create a Notification Integration
            2. The email address must be verified in the email service
            """)
            
            e1, e2 = st.columns(2)
            with e1:
                email_integration = st.text_input("Integration Name", value="cost_email_alerts", key="email_int")
            with e2:
                email_address = st.text_input("Recipient Email", placeholder="ops@company.com", key="email_addr")
            
            # Setup email integration
            if st.button("1️⃣ Create Email Integration", key="setup_email"):
                try:
                    setup_sql = f"""
                    CREATE OR REPLACE NOTIFICATION INTEGRATION {email_integration}
                    TYPE = EMAIL
                    ENABLED = TRUE
                    ALLOWED_RECIPIENTS = ('{email_address}')
                    """
                    client.execute_query(setup_sql)
                    st.success(f"✅ Email integration `{email_integration}` created!")
                except Exception as e:
                    st.error(f"Failed (may need ACCOUNTADMIN): {e}")
            
            st.divider()
            
            # Monitoring metrics selection
            st.markdown("##### Select Monitoring Metrics")
            
            mc1, mc2 = st.columns(2)
            with mc1:
                monitor_credits = st.checkbox("💰 Credit Burst (> threshold/hour)", value=True, key="mon_credits")
                credit_threshold = st.number_input("Credit threshold/hour", value=5.0, key="credit_thresh") if monitor_credits else 5.0
                
                monitor_failures = st.checkbox("❌ Failed Query Spike", value=True, key="mon_failures")
                fail_threshold = st.number_input("Max failed queries/hour", value=10, key="fail_thresh") if monitor_failures else 10
            
            with mc2:
                monitor_queue = st.checkbox("⏳ High Queue Times", value=False, key="mon_queue")
                queue_threshold = st.number_input("Queue threshold (sec)", value=30, key="queue_thresh") if monitor_queue else 30
                
                monitor_idle = st.checkbox("💤 Idle Warehouse Waste", value=False, key="mon_idle")
            
            check_interval = st.selectbox("Check Frequency", [5, 10, 15, 30, 60], index=2, key="check_freq",
                                           format_func=lambda x: f"Every {x} minutes")
            
            if st.button("2️⃣ Deploy Automated Monitor Task", type="primary", key="deploy_monitor"):
                try:
                    # Build the monitoring conditions
                    conditions = []
                    
                    if monitor_credits:
                        conditions.append(f"""
                        -- Credit Burst Check
                        LET credit_check RESULTSET := (
                            SELECT WAREHOUSE_NAME, SUM(CREDITS_USED) AS HOURLY_CREDITS
                            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                            WHERE START_TIME >= DATEADD(hour, -1, CURRENT_TIMESTAMP())
                            GROUP BY 1
                            HAVING SUM(CREDITS_USED) > {credit_threshold}
                        );
                        LET c1 CURSOR FOR credit_check;
                        FOR row_data IN c1 DO
                            alert_msg := alert_msg || '🔥 CREDIT BURST: ' || row_data.WAREHOUSE_NAME || ' used ' || row_data.HOURLY_CREDITS::VARCHAR || ' credits in last hour\\n';
                            has_alert := TRUE;
                        END FOR;""")
                    
                    if monitor_failures:
                        conditions.append(f"""
                        -- Failed Query Check
                        LET fail_count NUMBER := (
                            SELECT COUNT(*)
                            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                            WHERE START_TIME >= DATEADD(hour, -1, CURRENT_TIMESTAMP())
                            AND EXECUTION_STATUS = 'FAIL'
                        );
                        IF (fail_count > {fail_threshold}) THEN
                            alert_msg := alert_msg || '❌ FAILED QUERIES: ' || fail_count::VARCHAR || ' queries failed in last hour\\n';
                            has_alert := TRUE;
                        END IF;""")
                    
                    if monitor_queue:
                        conditions.append(f"""
                        -- Queue Time Check
                        LET queue_check RESULTSET := (
                            SELECT WAREHOUSE_NAME, AVG(QUEUED_PROVISIONING_TIME + QUEUED_OVERLOAD_TIME) / 1000 AS AVG_QUEUE_S
                            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                            WHERE START_TIME >= DATEADD(hour, -1, CURRENT_TIMESTAMP())
                            AND WAREHOUSE_NAME IS NOT NULL
                            GROUP BY 1
                            HAVING AVG_QUEUE_S > {queue_threshold}
                        );
                        LET c2 CURSOR FOR queue_check;
                        FOR row_data IN c2 DO
                            alert_msg := alert_msg || '⏳ HIGH QUEUE: ' || row_data.WAREHOUSE_NAME || ' avg queue ' || row_data.AVG_QUEUE_S::VARCHAR || 's\\n';
                            has_alert := TRUE;
                        END FOR;""")
                    
                    if monitor_idle:
                        conditions.append("""
                        -- Idle Warehouse Check
                        LET idle_check RESULTSET := (
                            SELECT wm.WAREHOUSE_NAME, SUM(wm.CREDITS_USED) AS WASTED
                            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY wm
                            WHERE wm.START_TIME >= DATEADD(minute, -30, CURRENT_TIMESTAMP())
                            AND wm.CREDITS_USED > 0
                            AND wm.WAREHOUSE_NAME NOT IN (
                                SELECT DISTINCT WAREHOUSE_NAME 
                                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                                WHERE START_TIME >= DATEADD(minute, -30, CURRENT_TIMESTAMP())
                            )
                            GROUP BY 1
                        );
                        LET c3 CURSOR FOR idle_check;
                        FOR row_data IN c3 DO
                            alert_msg := alert_msg || '💤 IDLE WASTE: ' || row_data.WAREHOUSE_NAME || ' burning credits with no queries\\n';
                            has_alert := TRUE;
                        END FOR;""")
                    
                    conditions_sql = "\n".join(conditions)
                    
                    # Create the stored procedure  
                    proc_sql = f"""
                    CREATE OR REPLACE PROCEDURE APP_CONTEXT.COST_MONITOR_CHECK()
                    RETURNS STRING
                    LANGUAGE SQL
                    EXECUTE AS CALLER
                    AS
                    $$
                    DECLARE
                        alert_msg VARCHAR DEFAULT '';
                        has_alert BOOLEAN DEFAULT FALSE;
                    BEGIN
                        {conditions_sql}
                        
                        IF (has_alert) THEN
                            -- Log the alert
                            INSERT INTO APP_ANALYTICS.ALERT_LOG (ALERT_NAME, TRIGGERED_AT, DETAILS)
                            VALUES ('COST_MONITOR', CURRENT_TIMESTAMP(), PARSE_JSON('{{"message": "' || REPLACE(alert_msg, '\\n', ' | ') || '"}}'));
                            
                            -- Send email notification
                            CALL SYSTEM$SEND_EMAIL(
                                '{email_integration}',
                                '{email_address}',
                                '🚨 Snowflake Cost Alert - Action Required',
                                'Cost Guardian Alert\\n\\n' || alert_msg || '\\n\\nTimestamp: ' || CURRENT_TIMESTAMP()::VARCHAR || '\\n\\nReview in: Snowflake Ops Intelligence → Cost Intelligence → Cost Guardian'
                            );
                            
                            RETURN 'ALERT SENT: ' || alert_msg;
                        ELSE
                            RETURN 'All clear - no alerts triggered';
                        END IF;
                    END;
                    $$;
                    """
                    
                    # Ensure log table exists
                    try:
                        client.execute_query("""
                            CREATE TABLE IF NOT EXISTS APP_ANALYTICS.ALERT_LOG (
                                ALERT_NAME VARCHAR,
                                TRIGGERED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
                                DETAILS VARIANT
                            )
                        """, log=False)
                    except:
                        pass
                    
                    # Create the procedure
                    client.execute_query(proc_sql)
                    
                    # Create the scheduled task
                    task_sql = f"""
                    CREATE OR REPLACE TASK APP_CONTEXT.COST_MONITOR_TASK
                    WAREHOUSE = COMPUTE_WH
                    SCHEDULE = '{check_interval} MINUTE'
                    AS
                    CALL APP_CONTEXT.COST_MONITOR_CHECK();
                    """
                    client.execute_query(task_sql)
                    client.execute_query("ALTER TASK APP_CONTEXT.COST_MONITOR_TASK RESUME")
                    
                    st.success(f"""
                    ✅ **Automated Cost Monitor Deployed!**
                    
                    - Checking every **{check_interval} minutes**
                    - Sending alerts to **{email_address}**
                    - Running 24/7 inside Snowflake (no app needed!)
                    """)
                    
                except Exception as e:
                    st.error(f"Failed to deploy: {e}")
                    with st.expander("Debug"):
                        st.code(str(e))
        
        # --- Webhook Setup ---
        elif "Webhook" in notif_method:
            st.markdown("##### 🔗 Webhook Notification Setup")
            st.info("""
            **Send alerts to Slack, Teams, or PagerDuty via webhooks.**
            
            Create a Notification Integration that sends HTTP POST requests 
            to your webhook URL when alerts fire.
            """)
            
            webhook_url = st.text_input("Webhook URL", placeholder="https://hooks.slack.com/services/...", key="webhook_url")
            webhook_name = st.text_input("Integration Name", value="cost_webhook", key="webhook_name")
            
            if st.button("Create Webhook Integration", key="create_webhook"):
                try:
                    # For webhooks, we use a Notification Integration with QUEUE type
                    # and a stored procedure that uses SYSTEM$SEND_NOTIFICATION
                    webhook_sql = f"""
                    CREATE OR REPLACE NOTIFICATION INTEGRATION {webhook_name}
                    TYPE = QUEUE
                    NOTIFICATION_PROVIDER = AWS_SNS
                    ENABLED = TRUE
                    AWS_SNS_TOPIC_ARN = '{webhook_url}'
                    AWS_SNS_ROLE_ARN = 'arn:aws:iam::role/snowflake_notifications'
                    """
                    st.warning("⚠️ Webhook integration requires AWS SNS, Azure Event Grid, or GCP Pub/Sub configuration by your cloud admin.")
                    st.code(webhook_sql, language="sql")
                    st.info("Copy the SQL above and have your ACCOUNTADMIN run it with the correct ARN/endpoint values for your cloud provider.")
                except Exception as e:
                    st.error(f"Error: {e}")
        
        # --- Log Only ---
        else:
            st.markdown("##### 📝 Log-Only Monitoring")
            st.info("Alerts will be logged to `APP_ANALYTICS.ALERT_LOG` only. You can view them in the Alert Builder tab.")
        
        st.divider()
        
        # --- Existing Task Status ---
        st.markdown("#### 📋 Active Monitoring Tasks")
        try:
            tasks = client.execute_query("SHOW TASKS IN SCHEMA APP_CONTEXT", log=False)
            if not tasks.empty:
                tasks.columns = [c.upper() for c in tasks.columns]
                display_t = [c for c in ['NAME', 'STATE', 'SCHEDULE', 'DEFINITION', 'WAREHOUSE'] if c in tasks.columns]
                st.dataframe(tasks[display_t] if display_t else tasks, use_container_width=True, hide_index=True)
                
                # Task controls
                task_names = tasks['NAME'].tolist() if 'NAME' in tasks.columns else []
                if task_names:
                    tc1, tc2 = st.columns([2, 1])
                    with tc1:
                        sel_task = st.selectbox("Select Task", task_names, key="sel_task")
                    with tc2:
                        st.write("")
                        st.write("")
                        tmc1, tmc2, tmc3 = st.columns(3)
                        with tmc1:
                            if st.button("▶️ Resume", key="resume_task"):
                                try:
                                    client.execute_query(f"ALTER TASK APP_CONTEXT.{sel_task} RESUME")
                                    st.success(f"Resumed {sel_task}")
                                except Exception as e:
                                    st.error(str(e))
                        with tmc2:
                            if st.button("⏸️ Suspend", key="suspend_task"):
                                try:
                                    client.execute_query(f"ALTER TASK APP_CONTEXT.{sel_task} SUSPEND")
                                    st.success(f"Suspended {sel_task}")
                                except Exception as e:
                                    st.error(str(e))
                        with tmc3:
                            if st.button("🗑️ Drop", key="drop_task"):
                                try:
                                    client.execute_query(f"DROP TASK IF EXISTS APP_CONTEXT.{sel_task}")
                                    st.success(f"Dropped {sel_task}")
                                    st.cache_data.clear()
                                except Exception as e:
                                    st.error(str(e))
            else:
                st.info("No monitoring tasks deployed yet.")
        except Exception as e:
            st.info(f"Could not fetch tasks: {e}")


# Need re import at module level if not already
import re

if __name__ == "__main__":
    main()
