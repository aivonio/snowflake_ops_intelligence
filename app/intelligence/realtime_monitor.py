"""
Real-Time Monitoring and Alerting
Monitors queries, warehouses, and costs in near real-time using INFORMATION_SCHEMA functions.
"""

import pandas as pd
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta

class RealtimeMonitor:
    """
    Real-time monitoring of Snowflake resources using a Hybrid Approach:
    1. INFORMATION_SCHEMA: For live alerts, active queries, and immediate load (Latency: ~seconds)
    2. ACCOUNT_USAGE: For historical trends and deeper aggregation (Latency: ~45 mins)
    """
    
    def __init__(self, client):
        self.client = client
        self.alert_thresholds = {
            'query_time_ms': 60000,  # 1 minute
            'queue_time_ms': 5000,   # 5 seconds
            'credits_per_hour': 10,  # 10 credits/hour
            'failed_query_rate': 0.05
        }
    
    def _execute_silent(self, query):
        try:
            return self.client.execute_query(query, log=False)
        except:
            return pd.DataFrame()

    def get_active_queries(self) -> Dict[str, Any]:
        """
        Get currently executing and recent queries using INFORMATION_SCHEMA.
        """
        # Fetch recent queries (last 1000 for better context)
        query = """
        SELECT 
            QUERY_ID,
            QUERY_TEXT,
            USER_NAME,
            WAREHOUSE_NAME,
            WAREHOUSE_SIZE,
            EXECUTION_STATUS,
            START_TIME,
            TOTAL_ELAPSED_TIME,
            BYTES_SCANNED,
            ROWS_PRODUCED,
            ERROR_CODE,
            ERROR_MESSAGE,
            QUEUED_PROVISIONING_TIME,
            QUEUED_REPAIR_TIME,
            QUEUED_OVERLOAD_TIME
        FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY(RESULT_LIMIT => 1000))
        ORDER BY START_TIME DESC
        """
        
        queries = self._execute_silent(query)
        
        summary = {'total': 0, 'running': 0, 'completed': 0, 'failed': 0, 'queued': 0}
        
        if queries.empty:
            return {'success': True, 'queries': pd.DataFrame(), 'summary': summary}
        
        # Calculate real-time stats
        running = queries[queries['EXECUTION_STATUS'] == 'RUNNING']
        completed = queries[queries['EXECUTION_STATUS'] == 'SUCCESS']
        failed = queries[queries['EXECUTION_STATUS'].isin(['FAIL', 'FAILED', 'INCIDENT'])] 
        queued = queries[queries['EXECUTION_STATUS'] == 'QUEUED'] # If status shows QUEUED
        
        # Calculate derived queue metrics if status is not explicitly QUEUED
        # (Sometimes stuck in 'RUNNING' but effectively queued/provisioning)
        
        return {
            'success': True,
            'queries': queries,
            'summary': {
                'total': len(queries),
                'running': len(running), 
                'completed': len(completed),
                'failed': len(failed),
                'queued': len(queued)
            }
        }

    def monitor_warehouse_load(self) -> Dict[str, Any]:
        """
        Monitor warehouse load using WAREHOUSE_LOAD_HISTORY (Real-time) 
        AND aggregate current query statistics.
        """
        try:
            # 1. Real-time Load (Concurrency)
            load_query = """
            SELECT 
                WAREHOUSE_NAME,
                AVG(AVG_RUNNING) as AVG_RUNNING,
                AVG(AVG_QUEUED_LOAD) as AVG_QUEUED,
                AVG(AVG_QUEUED_PROVISIONING) as AVG_PROVISIONING
            FROM TABLE(INFORMATION_SCHEMA.WAREHOUSE_LOAD_HISTORY(
                DATE_RANGE_START => DATEADD('minute', -30, CURRENT_TIMESTAMP())
            ))
            GROUP BY 1
            """
            load_df = self._execute_silent(load_query)

            # 2. Performance Stats (Latency from Query History)
            perf_query = """
            SELECT 
                WAREHOUSE_NAME,
                COUNT(*) as QUERY_COUNT,
                AVG(TOTAL_ELAPSED_TIME) as AVG_DURATION_MS,
                AVG(QUEUED_PROVISIONING_TIME + QUEUED_REPAIR_TIME + QUEUED_OVERLOAD_TIME) as AVG_QUEUE_MS
            FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY(RESULT_LIMIT => 1000))
            WHERE WAREHOUSE_NAME IS NOT NULL
              AND START_TIME >= DATEADD('minute', -30, CURRENT_TIMESTAMP())
            GROUP BY 1
            """
            perf_df = self._execute_silent(perf_query)
            
            # Merge datasets if possible
            merged_df = pd.DataFrame()
            if not load_df.empty and not perf_df.empty:
                # Normalize column cases just in case
                load_df.columns = [c.upper() for c in load_df.columns]
                perf_df.columns = [c.upper() for c in perf_df.columns]
                merged_df = pd.merge(load_df, perf_df, on='WAREHOUSE_NAME', how='outer').fillna(0)
            elif not load_df.empty:
                merged_df = load_df
            elif not perf_df.empty:
                merged_df = perf_df

            alerts = []
            if not merged_df.empty:
                for _, row in merged_df.iterrows():
                    wh = row.get('WAREHOUSE_NAME', 'UNKNOWN')
                    queued_load = row.get('AVG_QUEUED', 0)
                    queue_ms = row.get('AVG_QUEUE_MS', 0)
                    
                    if queued_load > 0.5 or queue_ms > self.alert_thresholds['queue_time_ms']:
                        alerts.append({
                            'type': 'WAREHOUSE_OVERLOAD',
                            'severity': 'WARNING',
                            'warehouse': wh,
                            'message': f"High Load on {wh}: {queued_load:.2f} avg queued, {queue_ms:.0f}ms wait"
                        })
            
            return {'success': True, 'warehouse_load': merged_df, 'alerts': alerts}
            
        except Exception as e:
            return {'success': False, 'error': str(e), 'warehouse_load': pd.DataFrame(), 'alerts': []}

    def monitor_credit_burn_rate(self, hours: int = 24) -> Dict[str, Any]:
        """
        Monitor credit usage. Uses ACCOUNT_USAGE for broader billing context.
        """
        try:
            # Use WAREHOUSE_METERING_HISTORY for accurate credit stats
            query = f"""
            SELECT 
                WAREHOUSE_NAME,
                SUM(CREDITS_USED) as CREDITS_USED,
                SUM(CREDITS_USED_CLOUD_SERVICES) as CLOUD_SERVICES_CREDITS
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
            WHERE START_TIME >= DATEADD(hour, -{hours}, CURRENT_TIMESTAMP())
            GROUP BY 1
            ORDER BY 2 DESC
            """
            
            usage = self._execute_silent(query)
            alerts = []
            
            total_credits = 0.0
            wh_count = 0
            
            if not usage.empty:
                total_credits = float(usage['CREDITS_USED'].sum())
                wh_count = len(usage)
                
                # Check for rapid spikes (simple heuristic: if last hour > avg)
                # For now, just total threshold
                burn_rate = total_credits / hours
                if burn_rate > self.alert_thresholds['credits_per_hour']:
                    alerts.append({
                        'type': 'HIGH_CREDIT_BURN', 
                        'severity': 'WARNING',
                        'message': f"High credit burn: {burn_rate:.1f} credits/hr"
                    })
            
            return {
                'success': True,
                'credits_used': total_credits,
                'credits_per_hour': total_credits / hours if hours > 0 else 0,
                'warehouses_used': wh_count,
                'alerts': alerts,
                'detail_df': usage
            }
        except Exception as e:
             return {'success': False, 'error': str(e), 'alerts': []}

    def detect_slow_queries(self) -> Dict[str, Any]:
        """Detect slow queries from real-time history."""
        limit_ms = self.alert_thresholds['query_time_ms']
        
        query = f"""
        SELECT QUERY_ID, USER_NAME, TOTAL_ELAPSED_TIME, START_TIME, QUERY_TEXT, WAREHOUSE_NAME
        FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY(RESULT_LIMIT => 1000))
        WHERE TOTAL_ELAPSED_TIME > {limit_ms}
          AND EXECUTION_STATUS = 'SUCCESS'
        ORDER BY TOTAL_ELAPSED_TIME DESC
        LIMIT 50
        """
        
        df = self._execute_silent(query)
        alerts = []
        for _, row in df.iterrows():
            elapsed = row['TOTAL_ELAPSED_TIME']
            alerts.append({
                'type': 'SLOW_QUERY',
                'severity': 'WARNING',
                'message': f"Slow query ({elapsed/1000:.1f}s) by {row['USER_NAME']} on {row['WAREHOUSE_NAME']}"
            })
            
        return {'success': True, 'alerts': alerts, 'count': len(alerts), 'queries': df}

    def detect_high_queue(self) -> Dict[str, Any]:
        """Detect specifically queued queries."""
        thresh_ms = self.alert_thresholds['queue_time_ms']
        
        # Try to use queue columns if available
        # If columns missing (standard edition?), this might return partial data or we catch error
        query = f"""
        SELECT QUERY_ID, USER_NAME, QUEUED_PROVISIONING_TIME, QUEUED_OVERLOAD_TIME, START_TIME, WAREHOUSE_NAME
        FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY(RESULT_LIMIT => 1000))
        WHERE (QUEUED_PROVISIONING_TIME + QUEUED_REPAIR_TIME + QUEUED_OVERLOAD_TIME) > {thresh_ms}
        ORDER BY START_TIME DESC
        """
        
        df = self._execute_silent(query)
        alerts = []
        if not df.empty and 'QUEUED_PROVISIONING_TIME' in df.columns:
            for _, row in df.iterrows():
                q_time = row['QUEUED_PROVISIONING_TIME'] + row.get('QUEUED_OVERLOAD_TIME', 0)
                alerts.append({
                    'type': 'HIGH_QUEUE',
                    'severity': 'WARNING',
                    'message': f"High Queue Time ({q_time/1000:.1f}s) for {row['USER_NAME']}"
                })
                
        return {'success': True, 'alerts': alerts, 'count': len(alerts)}

    def get_failed_queries(self) -> Dict[str, Any]:
        """Get recent failures with error codes."""
        query = """
        SELECT QUERY_ID, USER_NAME, ERROR_CODE, ERROR_MESSAGE, START_TIME, WAREHOUSE_NAME
        FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY(RESULT_LIMIT => 1000))
        WHERE EXECUTION_STATUS != 'SUCCESS' AND EXECUTION_STATUS != 'RUNNING'
        ORDER BY START_TIME DESC
        """
        df = self._execute_silent(query)
        
        error_summary = {}
        if not df.empty:
            error_summary = df['ERROR_MESSAGE'].value_counts().head(5).to_dict()
            
        return {'success': True, 'count': len(df), 'failed_queries': df, 'error_summary': error_summary}

    def generate_health_report(self) -> Dict[str, Any]:
        """Generate full health report."""
        active = self.get_active_queries()
        load = self.monitor_warehouse_load()
        credits = self.monitor_credit_burn_rate()
        slow = self.detect_slow_queries()
        failed = self.get_failed_queries()
        queue_check = self.detect_high_queue()
        
        # Score Calc
        score = 100
        score -= (len(load['alerts']) * 10)
        score -= (len(credits['alerts']) * 10)
        score -= (len(slow['alerts']) * 2) # Reduced penalty for slow queries
        score -= (failed['count'] * 1)    # Reduced penalty for failures (common in dev checking)
        score -= (len(queue_check['alerts']) * 5)
        score = max(0, score)
        
        status = 'HEALTHY'
        if score < 70: status = 'WARNING'
        if score < 40: status = 'CRITICAL'
        
        all_alerts = load['alerts'] + credits['alerts'] + slow['alerts'] + queue_check['alerts']
        
        return {
            'success': True,
            'health_score': score,
            'health_status': status,
            'timestamp': datetime.now(),
            'summary': {
                'active_queries': active['summary']['running'], # Real ACTIVE (Running)
                'recent_queries': active['summary']['total'],   # Total fetched history
                'running_queries': active['summary']['running'],
                'failed_queries': failed['count'],
                'slow_queries': slow['count'],
                'high_queue_queries': queue_check['count'],
                'warehouse_alerts': len(load['alerts']),
                'credit_alerts': len(credits['alerts'])
            },
            'alerts': all_alerts,
            'details': {
                'warehouse_load': load,
                'credit_burn': credits,
                'active_details': active,
                'failed_details': failed
            }
        }

    def set_alert_threshold(self, metric: str, value: float):
        if metric in self.alert_thresholds:
            self.alert_thresholds[metric] = value
    
    def get_alert_thresholds(self):
        return self.alert_thresholds

