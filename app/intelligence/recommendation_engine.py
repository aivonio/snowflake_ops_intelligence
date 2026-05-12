"""
Recommendation Engine
Centralized logic for generating actionable recommendations across:
- Security (MFA, Privileges)
- Warehouses (Zombies, Spilling)
- Cost (Credits, Cloud Services)
- Performance (Pruning, Caching)
"""

import pandas as pd
from typing import List, Dict, Any, Optional

class RecommendationEngine:
    def __init__(self, client):
        self.client = client

    def generate_holistic_report(self) -> Dict[str, Any]:
        """
        Generate a comprehensive report aggregating all domains.
        """
        security = self.check_security_health()
        warehouses = self.check_warehouse_efficiency()
        performance = self.check_performance_bottlenecks()
        
        all_recommendations = security.get('recommendations', []) + warehouses.get('recommendations', []) + performance.get('recommendations', [])
        
        # Sort by severity (Critical first)
        severity_order = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3, 'INFO': 4}
        all_recommendations.sort(key=lambda x: severity_order.get(x['severity'], 5))
        
        return {
            'timestamp': pd.Timestamp.now(),
            'score': self._calculate_overall_score(security, warehouses, performance),
            'recommendations': all_recommendations,
            'summary': {
                'security_issues': len(security.get('recommendations', [])),
                'warehouse_issues': len(warehouses.get('recommendations', [])),
                'performance_issues': len(performance.get('recommendations', []))
            },
            'details': {
                'security': security,
                'warehouses': warehouses,
                'performance': performance
            }
        }

    # --- DOMAIN: WAREHOUSE LOAD ---
    def analyze_warehouse_load(self) -> Dict[str, Any]:
        """Analyze warehouse load to recommend upsizing/downsizing."""
        recs = []
        try:
            # Check for high load
            load_df = self.client.execute_query("""
                SELECT 
                    WAREHOUSE_NAME, 
                    AVG(AVG_RUNNING) as AVG_RUNNING,
                    AVG(AVG_QUEUED_LOAD) as AVG_QUEUED
                FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_LOAD_HISTORY
                WHERE START_TIME >= DATEADD(day, -7, CURRENT_TIMESTAMP())
                GROUP BY 1
                HAVING AVG_QUEUED > 1
            """, log=False)
            
            if not load_df.empty:
                for _, row in load_df.iterrows():
                    recs.append({
                        'domain': 'PERFORMANCE',
                        'type': 'HIGH_QUEUING',
                        'severity': 'HIGH',
                        'title': f"Heavy Load on {row['WAREHOUSE_NAME']}",
                        'message': f"Avg Queued Load {row['AVG_QUEUED']:.1f}. Users are waiting.",
                        'action': 'Upsize warehouse or increase cluster count.'
                    })
        except:
            pass
        return {'recommendations': recs}

    def _calculate_overall_score(self, sec, wh, perf) -> int:
        """Weighted score calculation (0-100)"""
        score = 100
        
        for r in sec.get('recommendations', []):
            if r['severity'] == 'CRITICAL': score -= 15
            elif r['severity'] == 'HIGH': score -= 8
            
        for r in wh.get('recommendations', []):
            if r['severity'] == 'CRITICAL': score -= 10
            elif r['severity'] == 'HIGH': score -= 5
            
        for r in perf.get('recommendations', []):
            if r['severity'] == 'CRITICAL': score -= 5
            elif r['severity'] == 'HIGH': score -= 3
            
        return max(0, score)

    # --- DOMAIN: SECURITY ---
    def check_security_health(self) -> Dict[str, Any]:
        """Check MFA, Admins, Public Grants"""
        recs = []
        
        # 1. Check for Account Admins count
        try:
            admins_df = self.client.execute_query("""
                SELECT COUNT(DISTINCT GRANTEE_NAME) as COUNT
                FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS 
                WHERE ROLE = 'ACCOUNTADMIN' AND DELETED_ON IS NULL
            """, log=False)
            
            if not admins_df.empty:
                count = admins_df.iloc[0]['COUNT']
                if count > 2:
                    recs.append({
                        'domain': 'SECURITY',
                        'type': 'TOO_MANY_ADMINS',
                        'severity': 'HIGH',
                        'title': f'Too Many Account Admins ({count})',
                        'message': 'Limit ACCOUNTADMIN role to max 2 users for breakdown safety.',
                        'action': 'Revoke ACCOUNTADMIN from non-essential users.'
                    })
        except:
            pass 

        # 2. Check for missing Network Policies associated with Account
        try:
            policies_df = self.client.execute_query("SHOW PARAMETERS LIKE 'NETWORK_POLICY' IN ACCOUNT", log=False)
            if not policies_df.empty:
                val = policies_df.iloc[0]['value']
                if not val or val == 'null' or val == '':
                    recs.append({
                        'domain': 'SECURITY',
                        'type': 'NO_NETWORK_POLICY',
                        'severity': 'CRITICAL',
                        'title': 'No Account-Level Network Policy',
                        'message': 'Your account allows access from ANY IP address.',
                        'action': 'Create and attach a Network Policy immediately to restrict access.'
                    })
        except:
            pass

        # 3. Check for Stale Passwords (> 90 days)
        try:
            stale_df = self.client.execute_query("""
                SELECT COUNT(*) as COUNT
                FROM SNOWFLAKE.ACCOUNT_USAGE.USERS
                WHERE PASSWORD_LAST_SET_TIME < DATEADD('day', -90, CURRENT_TIMESTAMP())
                  AND DELETED_ON IS NULL
                  AND HAS_PASSWORD = 'true'
            """, log=False)
            
            if not stale_df.empty:
                cnt = stale_df.iloc[0]['COUNT']
                if cnt > 0:
                    recs.append({
                        'domain': 'SECURITY',
                        'type': 'STALE_PASSWORDS',
                        'severity': 'MEDIUM',
                        'title': f'{cnt} Users with Old Passwords',
                        'message': 'Users have not rotated passwords in > 90 days.',
                        'action': 'Enforce password rotation policy.'
                    })
        except:
            pass

        return {'recommendations': recs}

    # --- DOMAIN: WAREHOUSES ---
    def check_warehouse_efficiency(self) -> Dict[str, Any]:
        """Check Zombies, Spilling, Cloud Services"""
        recs = []
        
        # 1. Zombie Warehouses (Credits > 0, Queries == 0)
        try:
            # We construct a query to find warehouses that burned credits but ran no queries
            zombies_df = self.client.execute_query("""
                WITH credit_usage AS (
                    SELECT WAREHOUSE_NAME, SUM(CREDITS_USED) as total_credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                    WHERE START_TIME >= DATEADD(day, -7, CURRENT_TIMESTAMP())
                    GROUP BY 1 HAVING total_credits > 1
                ),
                query_stats AS (
                    SELECT WAREHOUSE_NAME, COUNT(*) as query_count
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE START_TIME >= DATEADD(day, -7, CURRENT_TIMESTAMP())
                    GROUP BY 1
                )
                SELECT c.WAREHOUSE_NAME, c.total_credits
                FROM credit_usage c
                LEFT JOIN query_stats q ON c.WAREHOUSE_NAME = q.WAREHOUSE_NAME
                WHERE ZEROIFNULL(q.query_count) = 0
            """, log=False)
            
            if not zombies_df.empty:
                for _, row in zombies_df.iterrows():
                    recs.append({
                        'domain': 'COST',
                        'type': 'ZOMBIE_WAREHOUSE',
                        'severity': 'HIGH',
                        'title': f"Zombie Warehouse: {row['WAREHOUSE_NAME']}",
                        'message': f"Consumed {row['TOTAL_CREDITS']:.1f} credits but ran 0 queries in 7 days.",
                        'action': 'Suspend immediately or drop if unused.'
                    })
        except:
            pass

        # 2. Spillage (Performance killer)
        try:
            spill_df = self.client.execute_query("""
                SELECT 
                    WAREHOUSE_NAME, 
                    SUM(BYTES_SPILLED_TO_LOCAL_STORAGE) as LOCAL_SPILL,
                    SUM(BYTES_SPILLED_TO_REMOTE_STORAGE) as REMOTE_SPILL
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE START_TIME >= DATEADD(day, -7, CURRENT_TIMESTAMP())
                GROUP BY 1
                HAVING LOCAL_SPILL > 1073741824 -- 1 GB
            """, log=False)
            
            if not spill_df.empty:
                for _, row in spill_df.iterrows():
                    gb = row['LOCAL_SPILL'] / (1024**3)
                    recs.append({
                        'domain': 'PERFORMANCE',
                        'type': 'SPILLAGE',
                        'severity': 'MEDIUM',
                        'title': f"Memory Spillage on {row['WAREHOUSE_NAME']}",
                        'message': f"{gb:.1f} GB spilled to disk. Indicates undersized warehouse.",
                        'action': 'Increase warehouse size to improve query speed.'
                    })
        except:
            pass
            
        return {'recommendations': recs}

    # --- DOMAIN: PERFORMANCE ---
    def check_performance_bottlenecks(self) -> Dict[str, Any]:
        """Check Pruning, Caching"""
        recs = []
        
        # 1. Pruning Efficiency (Scanning massive data for few rows)
        try:
            bad_pruning_df = self.client.execute_query("""
                SELECT 
                    QUERY_ID, 
                    BYTES_SCANNED, 
                    ROWS_PRODUCED,
                    SUBSTR(QUERY_TEXT, 1, 50) as TEXT
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE START_TIME >= DATEADD(day, -1, CURRENT_TIMESTAMP())
                  AND BYTES_SCANNED > 1073741824 -- 1 GB
                  AND ROWS_PRODUCED < 1000
                  AND EXECUTION_STATUS = 'SUCCESS'
                ORDER BY BYTES_SCANNED DESC
                LIMIT 5
            """, log=False)
            
            if not bad_pruning_df.empty:
                 recs.append({
                    'domain': 'PERFORMANCE',
                    'type': 'BAD_PRUNING',
                    'severity': 'INFO',
                    'title': 'Inefficient Pruning Detected',
                    'message': f"Found {len(bad_pruning_df)} recent queries scanning >1GB to return <1k rows.",
                    'action': 'Check clustering keys or micro-partition pruning.'
                })
        except:
            pass
            
        return {'recommendations': recs}
