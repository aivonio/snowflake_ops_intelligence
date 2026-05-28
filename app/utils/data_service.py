import streamlit as st
import pandas as pd

def get_account_metrics(session):
    """
    Get aggregated account metrics including Top Warehouse for the dashboard.
    """
    metrics = {
        'total_credits': 0.0,
        'compute_credits': 0.0, 
        'cloud_credits': 0.0,
        'warehouse_count': 0,
        'query_count': 0,
        'failed_queries': 0,
        'storage_tb': 0.0,
        'active_users': 0,
        'top_warehouse': 'N/A',
        'top_warehouse_credits': 0.0,
        'is_restricted': False,
        'error_detail': ''
    }

    if not session:
        return metrics

    try:
        # 1. Credits & Top Warehouse (Last 30 Days)
        credits_df = session.sql("""
            WITH wh_usage AS (
            SELECT 
                WAREHOUSE_NAME, 
                SUM(CREDITS_USED) as total_creds,
                SUM(CREDITS_USED_COMPUTE) as compute_creds,
                SUM(CREDITS_USED_CLOUD_SERVICES) as cloud_creds
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
            WHERE START_TIME >= DATEADD(day, -30, CURRENT_TIMESTAMP())
            GROUP BY 1
        )
        SELECT 
            (SELECT SUM(total_creds) FROM wh_usage) as total_credits,
            (SELECT SUM(compute_creds) FROM wh_usage) as compute_credits,
            (SELECT SUM(cloud_creds) FROM wh_usage) as cloud_credits,
            (SELECT MAX(total_creds) FROM wh_usage) as max_wh_credits,
            (SELECT WAREHOUSE_NAME FROM wh_usage ORDER BY total_creds DESC LIMIT 1) as top_wh_name
        FROM wh_usage
        LIMIT 1
        """).to_pandas()
        
        if not credits_df.empty:
            metrics['total_credits'] = float(credits_df.iloc[0]['TOTAL_CREDITS'] or 0)
            metrics['compute_credits'] = float(credits_df.iloc[0]['COMPUTE_CREDITS'] or 0)
            metrics['cloud_credits'] = float(credits_df.iloc[0]['CLOUD_CREDITS'] or 0)
            metrics['top_warehouse_credits'] = float(credits_df.iloc[0]['MAX_WH_CREDITS'] or 0)
            metrics['top_warehouse'] = credits_df.iloc[0]['TOP_WH_NAME'] or 'N/A'
            
        # Fallback if credits are 0 (Latency or new account)
        if metrics['total_credits'] == 0:
            try:
                fallback_df = session.sql("""
                WITH raw_data AS (
                    SELECT * FROM TABLE(INFORMATION_SCHEMA.WAREHOUSE_METERING_HISTORY(DATE_RANGE_START=>DATEADD('day', -14, CURRENT_DATE())))
                ),
                agg AS (
                    SELECT 
                        WAREHOUSE_NAME,
                        SUM(CREDITS_USED) as total_creds,
                        SUM(CREDITS_USED_COMPUTE) as compute_creds,
                        SUM(CREDITS_USED_CLOUD_SERVICES) as cloud_creds
                    FROM raw_data
                    GROUP BY 1
                )
                SELECT 
                    SUM(total_creds) as total_credits,
                    SUM(compute_creds) as compute_credits,
                    SUM(cloud_creds) as cloud_credits
                FROM agg
                """).to_pandas()
                
                if not fallback_df.empty:
                     # Update metrics if fallback has data
                     fallback_total = float(fallback_df.iloc[0]['TOTAL_CREDITS'] or 0)
                     if fallback_total > 0:
                         metrics['total_credits'] = fallback_total
                         metrics['compute_credits'] = float(fallback_df.iloc[0]['COMPUTE_CREDITS'] or 0)
                         metrics['cloud_credits'] = float(fallback_df.iloc[0]['CLOUD_CREDITS'] or 0)
                         
                         # Get Top Warehouse specifically from fallback if needed
                         try:
                             top_wh_df = session.sql("""
                                SELECT WAREHOUSE_NAME, SUM(CREDITS_USED) as total_creds
                                FROM TABLE(INFORMATION_SCHEMA.WAREHOUSE_METERING_HISTORY(DATE_RANGE_START=>DATEADD('day', -14, CURRENT_DATE())))
                                GROUP BY 1
                                ORDER BY total_creds DESC
                                LIMIT 1
                             """).to_pandas()
                             if not top_wh_df.empty:
                                 metrics['top_warehouse'] = top_wh_df.iloc[0]['WAREHOUSE_NAME']
                                 metrics['top_warehouse_credits'] = float(top_wh_df.iloc[0]['TOTAL_CREDS'] or 0)
                         except Exception as inner_e:
                             import logging
                             logging.getLogger(__name__).debug(f"Top WH fallback: {inner_e}")

                         metrics['used_fallback'] = True 
            except Exception as e:
                metrics['error_detail'] += f"Fallback: {e}; "

    except Exception as e:
        metrics['error_detail'] += f"Credits: {e}; "

    try:
        # 2. Daily Credits Trend (Helper for dialogs, not main metric)
        # We handle this in get_daily_credits separate function
        pass
    except:
        pass

    try:
        # 3. Warehouses Count
        wh_df = session.sql("SHOW WAREHOUSES").to_pandas()
        metrics['warehouse_count'] = len(wh_df)
    except Exception as e:
        metrics['error_detail'] += f"Warehouses: {e}; "

    try:
        # 4. Query Stats
        query_df = session.sql("""
        SELECT 
            COUNT(*) as total,
            COUNT_IF(EXECUTION_STATUS != 'SUCCESS') as failed,
            COUNT(DISTINCT USER_NAME) as users
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD(day, -30, CURRENT_TIMESTAMP())
        """).to_pandas()
        
        if not query_df.empty:
             metrics['query_count'] = int(query_df.iloc[0]['TOTAL'] or 0)
             metrics['failed_queries'] = int(query_df.iloc[0]['FAILED'] or 0)
             metrics['active_users'] = int(query_df.iloc[0]['USERS'] or 0)
    except Exception as e:
        metrics['error_detail'] += f"Queries: {e}; "
        metrics['is_restricted'] = True

    try:
        # 5. Storage
        storage_df = session.sql("""
        SELECT 
            SUM(AVERAGE_DATABASE_BYTES + AVERAGE_STAGE_BYTES + AVERAGE_FAILSAFE_BYTES) / 1e12 as tb_total
        FROM SNOWFLAKE.ACCOUNT_USAGE.STORAGE_USAGE
        WHERE USAGE_DATE = (SELECT MAX(USAGE_DATE) FROM SNOWFLAKE.ACCOUNT_USAGE.STORAGE_USAGE)
        """).to_pandas()
        if not storage_df.empty:
            metrics['storage_tb'] = float(storage_df.iloc[0]['TB_TOTAL'] or 0)
    except Exception as e:
        metrics['error_detail'] += f"Storage: {e}; "
        
    try:
        # 6. Active Alerts
        alerts_df = session.sql("SELECT COUNT(*) FROM APP_CONTEXT.BUDGET_ALERTS WHERE IS_ACTIVE = TRUE").to_pandas()
        metrics['active_alerts'] = int(alerts_df.iloc[0, 0]) if not alerts_df.empty else 0
    except:
        metrics['active_alerts'] = 0

    return metrics

def get_daily_credits(session, days=30):
    try:
        df = session.sql(f"""
        SELECT 
            DATE(START_TIME) as usage_date,
            SUM(CREDITS_USED) as credits_used
        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
        WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        GROUP BY 1
        ORDER BY 1
        """).to_pandas()
        
        if df.empty or df['CREDITS_USED'].sum() == 0:
            # Fallback to Information Schema (Real-time, up to 14 days)
            days = min(days, 14)
            df = session.sql(f"""
            SELECT 
                DATE(START_TIME) as usage_date,
                SUM(CREDITS_USED) as credits_used
            FROM TABLE(INFORMATION_SCHEMA.WAREHOUSE_METERING_HISTORY(DATE_RANGE_START=>DATEADD('day', -{days}, CURRENT_DATE())))
            GROUP BY 1
            ORDER BY 1
            """).to_pandas()
        return df
    except:
        return pd.DataFrame()

def get_daily_credits_by_warehouse(session, days=30):
    """Get daily credits broken down by warehouse for stacked charts"""
    try:
        # Try Account Usage first
        query = f"""
        WITH top_wh AS (
            SELECT WAREHOUSE_NAME 
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
            WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            GROUP BY 1
            ORDER BY SUM(CREDITS_USED) DESC
            LIMIT 5
        )
        SELECT 
            DATE(START_TIME) as usage_date,
            CASE 
                WHEN WAREHOUSE_NAME IN (SELECT WAREHOUSE_NAME FROM top_wh) THEN WAREHOUSE_NAME 
                ELSE 'Other' 
            END as warehouse_group,
            SUM(CREDITS_USED) as credits_used
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        GROUP BY 1, 2
        HAVING SUM(CREDITS_USED) > 0
        ORDER BY 1
        """
        df = session.sql(query).to_pandas()
        
        if df.empty or df['CREDITS_USED'].sum() == 0:
             # Fallback to Information Schema
             days = min(days, 14)
             query_fallback = f"""
                WITH raw_data AS (
                    SELECT * 
                    FROM TABLE(INFORMATION_SCHEMA.WAREHOUSE_METERING_HISTORY(DATE_RANGE_START=>DATEADD('day', -{days}, CURRENT_DATE())))
                ),
                top_wh AS (
                    SELECT WAREHOUSE_NAME 
                    FROM raw_data
                    GROUP BY 1
                    ORDER BY SUM(CREDITS_USED) DESC
                    LIMIT 5
                )
                SELECT 
                    DATE(START_TIME) as usage_date,
                    CASE 
                        WHEN WAREHOUSE_NAME IN (SELECT WAREHOUSE_NAME FROM top_wh) THEN WAREHOUSE_NAME 
                        ELSE 'Other' 
                    END as warehouse_group,
                    SUM(CREDITS_USED) as credits_used
                FROM raw_data
                GROUP BY 1, 2
                ORDER BY 1
             """
             df = session.sql(query_fallback).to_pandas()

        return df
    except:
        return pd.DataFrame()


def get_top_users(session, limit=5):
    """Get top users by query count (last 7 days)."""
    limit = int(limit)
    try:
        query = f"""
        SELECT
            USER_NAME,
            COUNT(*) as query_count,
            SUM(CREDITS_USED_CLOUD_SERVICES) as credits_approx
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD(day, -7, CURRENT_TIMESTAMP())
        GROUP BY 1
        ORDER BY 2 DESC
        LIMIT {limit}
        """
        return session.sql(query).to_pandas()
    except Exception:
        return pd.DataFrame()


def get_storage_trend(session, days=30):
    """Get storage usage trend in TB."""
    days = int(days)
    try:
        query = f"""
        SELECT
            USAGE_DATE,
            AVERAGE_DATABASE_BYTES / 1e12 as db_tb,
            AVERAGE_STAGE_BYTES / 1e12 as stage_tb,
            AVERAGE_FAILSAFE_BYTES / 1e12 as failsafe_tb
        FROM SNOWFLAKE.ACCOUNT_USAGE.STORAGE_USAGE
        WHERE USAGE_DATE >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        ORDER BY USAGE_DATE
        """
        return session.sql(query).to_pandas()
    except Exception:
        return pd.DataFrame()


def get_workload_metrics(session, days=7):
    """Get top workloads grouped by Query Tag or Pattern."""
    days = int(days)
    try:
        query = f"""
        SELECT
            COALESCE(NULLIF(QUERY_TAG, ''), LEFT(QUERY_TEXT, 40)) as workload,
            'Query' as type,
            COUNT(DISTINCT USER_NAME) as users,
            COUNT(DISTINCT WAREHOUSE_NAME) as warehouses,
            AVG(TOTAL_ELAPSED_TIME)/1000 as avg_duration_s,
            COUNT(*) as run_count
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            AND TOTAL_ELAPSED_TIME > 0
        GROUP BY 1, 2
        ORDER BY run_count DESC
        LIMIT 10
        """
        return session.sql(query).to_pandas()
    except Exception:
        return pd.DataFrame()


def get_warehouse_status(client):
    """Get current warehouse status using the client's normalized execution."""
    df = client.execute_query("SHOW WAREHOUSES")

    if not df.empty:
        if 'NAME' in df.columns:
            df['WAREHOUSE_NAME'] = df['NAME']

        if 'STATUS' in df.columns:
            df['STATE'] = df['STATUS']
        elif 'STATE' not in df.columns:
            df['STATE'] = 'UNKNOWN'

        return df
    return pd.DataFrame()
