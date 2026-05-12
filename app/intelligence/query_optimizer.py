"""
AI-Powered Query Optimizer
Uses Snowflake Cortex AI and historical data for intelligent query optimization
Provides contextual awareness of warehouses, cache, partitions, and historical patterns
"""

import pandas as pd
import hashlib
import re
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta


class QueryOptimizer:
    """
    Intelligent query optimizer with contextual awareness
    Analyzes queries before execution and suggests optimizations
    """
    
    def __init__(self, client):
        self.client = client
        self.optimization_cache = {}
    
    def analyze_query_comprehensive(self, query: str, warehouse: str = None) -> Dict[str, Any]:
        """
        Comprehensive query analysis with all contextual factors
        Returns detailed analysis and optimization recommendations
        """
        analysis = {
            'query_hash': hashlib.md5(query.encode()).hexdigest(),
            'timestamp': datetime.now(),
            'original_query': query,
            'warehouse': warehouse,
            'issues': [],
            'optimizations': [],
            'cost_analysis': {},
            'cache_analysis': {},
            'historical_analysis': {},
            'partition_analysis': {},
            'estimated_savings': {},
            'ai_analysis': {}
        }
        
        # 1. Static query analysis
        static_issues = self._analyze_query_static(query)
        analysis['issues'].extend(static_issues)
        
        # 2. Historical query analysis
        historical = self._analyze_historical_patterns(query)
        analysis['historical_analysis'] = historical
        
        # 3. Cache analysis
        cache_info = self._analyze_cache_opportunity(query)
        analysis['cache_analysis'] = cache_info
        
        # 4. Cortex AI Analysis (Generative)
        ai_insights = self._analyze_with_cortex(query)
        if ai_insights:
            analysis['ai_analysis'] = ai_insights
            # Merge AI findings into optimizations if they are structured
            if 'recommendations' in ai_insights:
                for rec in ai_insights['recommendations']:
                     analysis['optimizations'].append(rec)
        
        # 5. Cost estimation
        if warehouse:
            cost_est = self.client.estimate_query_cost(query, warehouse)
            analysis['cost_analysis'] = cost_est
        
        # 6. Generate optimized alternatives
        alternatives = self._generate_optimized_alternatives(query, analysis)
        analysis['alternative_queries'] = alternatives
        
        # 7. Calculate potential savings
        savings = self._calculate_potential_savings(analysis)
        analysis['estimated_savings'] = savings
        
        # 8. Generate actionable recommendations (Rule-based)
        # Note: We append these to existing optimizations (which might include AI ones)
        rule_recommendations = self._generate_recommendations(analysis)
        for rec in rule_recommendations:
            # Avoid duplicates based on title
            if not any(r['title'] == rec['title'] for r in analysis['optimizations']):
                analysis['optimizations'].append(rec)
        
        return analysis
    
    def _analyze_query_static(self, query: str) -> List[Dict[str, Any]]:
        """Static analysis of query structure"""
        issues = []
        query_upper = query.upper()
        
        # SELECT * detection
        if re.search(r'\bSELECT\s+\*', query_upper):
            issues.append({
                'type': 'COLUMN_SELECTION',
                'severity': 'MEDIUM',
                'issue': 'Using SELECT * retrieves all columns unnecessarily',
                'impact': 'Increased data transfer and processing time',
                'fix': 'Specify only required columns',
                'savings_potential': '20-50%'
            })
        
        # Missing WHERE clause
        if 'WHERE' not in query_upper and 'LIMIT' not in query_upper:
            if 'SELECT' in query_upper and 'FROM' in query_upper:
                issues.append({
                    'type': 'FILTERING',
                    'severity': 'HIGH',
                    'issue': 'No WHERE clause or LIMIT - full table scan',
                    'impact': 'Scanning entire table wastes credits',
                    'fix': 'Add filter conditions (WHERE) or LIMIT',
                    'savings_potential': '50-95%'
                })
        
        # LIKE with leading wildcard
        if re.search(r"LIKE\s+'%", query_upper):
            issues.append({
                'type': 'PATTERN_MATCHING',
                'severity': 'MEDIUM',
                'issue': 'LIKE with leading wildcard prevents pruning',
                'impact': 'Cannot use micro-partitions efficiently',
                'fix': 'Use CONTAINS() or restructure pattern',
                'savings_potential': '30-60%'
            })
        
        # ORDER BY without LIMIT
        if 'ORDER BY' in query_upper and 'LIMIT' not in query_upper:
            issues.append({
                'type': 'SORTING',
                'severity': 'MEDIUM',
                'issue': 'ORDER BY without LIMIT on potentially large result',
                'impact': 'Sorting entire result set is expensive',
                'fix': 'Add LIMIT or ensure this is necessary',
                'savings_potential': '10-30%'
            })
        
        # Multiple JOINs
        join_count = len(re.findall(r'\bJOIN\b', query_upper))
        if join_count > 3:
            issues.append({
                'type': 'COMPLEXITY',
                'severity': 'MEDIUM',
                'issue': f'Complex query with {join_count} JOINs',
                'impact': 'High memory usage and processing time',
                'fix': 'Consider CTEs or materializing intermediate results',
                'savings_potential': '15-40%'
            })
        
        # Subqueries in WHERE
        if re.search(r'WHERE.*\(\s*SELECT', query_upper):
            issues.append({
                'type': 'SUBQUERY',
                'severity': 'HIGH',
                'issue': 'Correlated subquery in WHERE clause',
                'impact': 'Executes subquery for each row',
                'fix': 'Convert to JOIN or use CTE',
                'savings_potential': '40-80%'
            })
        
        # DISTINCT usage
        if 'DISTINCT' in query_upper:
            issues.append({
                'type': 'DEDUPLICATION',
                'severity': 'LOW',
                'issue': 'DISTINCT requires additional processing',
                'impact': 'Extra sorting and comparison operations',
                'fix': 'Verify DISTINCT is necessary, filter earlier if possible',
                'savings_potential': '5-20%'
            })
        
        # Functions on filtered columns
        if re.search(r'WHERE.*\b(DATE|YEAR|MONTH|UPPER|LOWER|TRIM)\s*\([^)]+\)\s*(=|>|<|IN)', query_upper):
            issues.append({
                'type': 'PARTITION_PRUNING',
                'severity': 'HIGH',
                'issue': 'Function applied to column in WHERE clause',
                'impact': 'Prevents partition pruning - scans all data',
                'fix': 'Transform data or restructure filter',
                'savings_potential': '60-90%'
            })
        
        # UNION without ALL
        if re.search(r'\bUNION\b(?!\s+ALL)', query_upper):
            issues.append({
                'type': 'SET_OPERATIONS',
                'severity': 'LOW',
                'issue': 'UNION removes duplicates (implicit DISTINCT)',
                'impact': 'Additional processing for deduplication',
                'fix': 'Use UNION ALL if duplicates are acceptable',
                'savings_potential': '10-25%'
            })
        
        # Cross joins
        if 'CROSS JOIN' in query_upper or re.search(r'FROM\s+\w+\s*,\s*\w+', query_upper):
            issues.append({
                'type': 'JOIN_TYPE',
                'severity': 'HIGH',
                'issue': 'Potential cartesian product (CROSS JOIN)',
                'impact': 'Exponential data explosion',
                'fix': 'Add proper JOIN conditions',
                'savings_potential': '70-99%'
            })
        
        return issues
    
    def _analyze_historical_patterns(self, query: str) -> Dict[str, Any]:
        """Analyze historical executions of similar queries"""
        query_hash = hashlib.md5(query.encode()).hexdigest()
        
        # Get similar queries from history
        similar_queries = self.client.get_similar_queries(query_hash, limit=20)
        
        if similar_queries.empty:
            return {
                'has_history': False,
                'message': 'No historical data for this query pattern'
            }
        
        # Analyze patterns
        avg_time = similar_queries['TOTAL_ELAPSED_TIME'].mean()
        min_time = similar_queries['TOTAL_ELAPSED_TIME'].min()
        max_time = similar_queries['TOTAL_ELAPSED_TIME'].max()
        avg_bytes = similar_queries['BYTES_SCANNED'].mean()
        avg_cache = similar_queries['PERCENTAGE_SCANNED_FROM_CACHE'].mean()
        
        # Find best performing execution
        best_execution = similar_queries.loc[similar_queries['TOTAL_ELAPSED_TIME'].idxmin()]
        
        # Warehouse analysis
        warehouse_performance = similar_queries.groupby('WAREHOUSE_SIZE').agg({
            'TOTAL_ELAPSED_TIME': 'mean',
            'BYTES_SCANNED': 'mean',
            'CREDITS_USED_CLOUD_SERVICES': 'mean'
        }).reset_index()
        
        # Partition Pruning Analysis
        avg_partitions_scanned = similar_queries['PARTITIONS_SCANNED'].mean() if 'PARTITIONS_SCANNED' in similar_queries.columns else 0
        avg_partitions_total = similar_queries['PARTITIONS_TOTAL'].mean() if 'PARTITIONS_TOTAL' in similar_queries.columns else 0
        pruning_ratio = (avg_partitions_scanned / avg_partitions_total) if avg_partitions_total > 0 else 0
        
        # Result Size Analysis (Explosion)
        avg_rows = similar_queries['ROWS_PRODUCED'].mean() if 'ROWS_PRODUCED' in similar_queries.columns else 0
        avg_bytes = similar_queries['BYTES_SCANNED'].mean()
        
        # Find optimal warehouse
        warehouse_performance['cost_efficiency'] = (
            warehouse_performance['TOTAL_ELAPSED_TIME'] * 
            warehouse_performance['CREDITS_USED_CLOUD_SERVICES']
        )
        optimal_warehouse = warehouse_performance.loc[
            warehouse_performance['cost_efficiency'].idxmin()
        ]['WAREHOUSE_SIZE']
        
        return {
            'has_history': True,
            'execution_count': len(similar_queries),
            'avg_time_ms': avg_time,
            'min_time_ms': min_time,
            'max_time_ms': max_time,
            'time_variance': max_time - min_time,
            'avg_bytes_scanned': avg_bytes,
            'avg_cache_hit': avg_cache,
            'best_execution': {
                'query_id': best_execution['QUERY_ID'],
                'time_ms': best_execution['TOTAL_ELAPSED_TIME'],
                'warehouse': best_execution['WAREHOUSE_NAME'],
                'warehouse_size': best_execution['WAREHOUSE_SIZE'],
                'cache_hit': best_execution['PERCENTAGE_SCANNED_FROM_CACHE']
            },
            'optimal_warehouse': optimal_warehouse,
            'warehouse_performance': warehouse_performance.to_dict('records'),
            'pruning': {
                'avg_scanned': avg_partitions_scanned,
                'avg_total': avg_partitions_total,
                'ratio': pruning_ratio,
                'is_poor': pruning_ratio > 0.8 and avg_partitions_total > 50
            },
            'result_stats': {
                'avg_rows': avg_rows,
                'is_exploding': avg_rows > 1000000 # > 1M rows
            }
        }
    
    def _analyze_with_cortex(self, query: str) -> Dict[str, Any]:
        """
        Use Snowflake Cortex AI to analyze query logic and intent.
        Falls back to None if Cortex is not available.
        """
        try:
            # Construct a prompt for the LLM
            prompt = f"""
            Analyze the following Snowflake SQL query for performance and logic issues.
            Provide a brief summary of what the query does.
            Identify 1-2 optimization opportunities if any exist.
            
            Query:
            {query}
            
            Response format:
            Summary: [Brief description]
            Optimization: [Suggestion 1]
            """
            
            # Use SNOWFLAKE.CORTEX.COMPLETE (assuming 'snowflake-arctic' or 'llama3-70b')
            # Note: We wrap this in SQL because snowpark python functions for cortex might vary
            prompt_escaped = prompt.replace("'", "''")
            cortex_query = f"SELECT SNOWFLAKE.CORTEX.COMPLETE('llama3-70b', '{prompt_escaped}')"
            
            result = self.client.execute_query(cortex_query, log=False)
            
            if not result.empty:
                response_text = result.iloc[0, 0]
                return {
                    'used_cortex': True,
                    'model': 'llama3-70b',
                    'explanation': response_text,
                    'recommendations': []  # Could parse text to structured recs if needed
                }
                
        except Exception as e:
            error_msg = str(e)
            if "unavailable in your region" in error_msg:
                return {
                    'used_cortex': False,
                    'message': 'Cortex AI model (llama3-70b) is not available in your Snowflake region. Enable Cross-Region Inference to use this feature.'
                }
            # Silently fail for other errors but log if needed
            print(f"Cortex error: {e}")
            pass
            
        return {
            'used_cortex': False,
            'message': 'AI analysis unavailable (Cortex not enabled)'
        }

    def _analyze_cache_opportunity(self, query: str) -> Dict[str, Any]:
        """Analyze result cache opportunities"""
        cache_info = self.client.check_result_cache(query)
        
        if cache_info['in_cache']:
            return {
                'cached': True,
                'cache_percentage': cache_info['cache_percentage'],
                'recommendation': 'Query result is cached - re-execution will be instant and free',
                'savings': '100% cost savings on re-execution',
                'last_execution': cache_info.get('last_execution', {})
            }
        
        # Check if query is cacheable
        query_upper = query.upper()
        non_deterministic_functions = [
            'CURRENT_TIMESTAMP', 'CURRENT_DATE', 'CURRENT_TIME',
            'SYSDATE', 'GETDATE', 'RANDOM', 'UUID_STRING'
        ]
        
        is_cacheable = not any(func in query_upper for func in non_deterministic_functions)
        
        return {
            'cached': False,
            'cache_percentage': 0,
            'is_cacheable': is_cacheable,
            'recommendation': 'Query is cacheable - standardize query text for better cache hits' if is_cacheable else 'Query uses non-deterministic functions - not cacheable',
            'tip': 'Identical queries within 24 hours will use cached results'
        }
    
    def _generate_optimized_alternatives(self, query: str, analysis: Dict) -> List[Dict[str, Any]]:
        """Generate optimized query alternatives"""
        alternatives = []
        query_upper = query.upper()
        
        # Alternative 1: Add LIMIT if missing
        if 'LIMIT' not in query_upper and 'SELECT' in query_upper:
            optimized = query.rstrip(';') + '\nLIMIT 1000;'
            alternatives.append({
                'name': 'Add LIMIT for testing',
                'query': optimized,
                'benefit': 'Reduces data scanned for initial testing',
                'estimated_savings': '50-90%',
                'use_case': 'Development and testing'
            })
        
        # Alternative 2: Replace SELECT * with specific columns
        if 'SELECT *' in query_upper:
            # This is a placeholder - would need table schema to be accurate
            optimized = query.replace('SELECT *', 'SELECT col1, col2, col3  -- Specify actual columns')
            alternatives.append({
                'name': 'Specify columns instead of SELECT *',
                'query': optimized,
                'benefit': 'Reduces data transfer and processing',
                'estimated_savings': '20-50%',
                'use_case': 'Production queries'
            })
        
        # Alternative 3: Use smaller warehouse if historical data suggests
        if analysis.get('historical_analysis', {}).get('has_history'):
            optimal_wh = analysis['historical_analysis'].get('optimal_warehouse')
            if optimal_wh:
                alternatives.append({
                    'name': f'Use {optimal_wh} warehouse',
                    'query': f'-- USE WAREHOUSE {optimal_wh};\n{query}',
                    'benefit': f'Historical data shows {optimal_wh} is most cost-efficient',
                    'estimated_savings': '10-40%',
                    'use_case': 'Cost optimization'
                })
        
        # Alternative 4: Add WHERE clause template
        if 'WHERE' not in query_upper and 'FROM' in query_upper:
            # Extract table name
            from_match = re.search(r'FROM\s+(\w+)', query_upper)
            if from_match:
                table = from_match.group(1)
                optimized = query.rstrip(';') + f'\nWHERE date_column >= DATEADD(day, -7, CURRENT_DATE());  -- Add appropriate filter'
                alternatives.append({
                    'name': 'Add time-based filter',
                    'query': optimized,
                    'benefit': 'Leverages partition pruning to scan less data',
                    'estimated_savings': '60-90%',
                    'use_case': 'Time-series data'
                })
        
        return alternatives
    
    def _calculate_potential_savings(self, analysis: Dict) -> Dict[str, Any]:
        """Calculate potential cost savings from optimizations"""
        savings = {
            'total_potential_savings_pct': 0,
            'total_potential_credits': 0,
            'breakdown': []
        }
        
        # Calculate from issues
        for issue in analysis['issues']:
            if 'savings_potential' in issue:
                # Parse percentage range (e.g., "20-50%")
                savings_str = issue['savings_potential']
                if '-' in savings_str:
                    low, high = savings_str.replace('%', '').split('-')
                    avg_savings = (float(low) + float(high)) / 2
                else:
                    avg_savings = float(savings_str.replace('%', ''))
                
                savings['breakdown'].append({
                    'issue_type': issue['type'],
                    'savings_pct': avg_savings,
                    'severity': issue['severity']
                })
        
        # Calculate total (not additive - use highest impact)
        if savings['breakdown']:
            savings['total_potential_savings_pct'] = max(
                item['savings_pct'] for item in savings['breakdown']
            )
        
        # Calculate credit savings if cost analysis available
        if 'cost_analysis' in analysis and 'estimated_credits' in analysis['cost_analysis']:
            estimated_credits = analysis['cost_analysis']['estimated_credits']
            savings['total_potential_credits'] = (
                estimated_credits * savings['total_potential_savings_pct'] / 100
            )
            savings['total_potential_cost_usd'] = savings['total_potential_credits'] * 3.0
        
        return savings
    
    def _generate_recommendations(self, analysis: Dict) -> List[Dict[str, Any]]:
        """Generate prioritized, actionable recommendations"""
        recommendations = []
        
        # Priority 1: Critical issues
        critical_issues = [i for i in analysis['issues'] if i['severity'] == 'HIGH']
        for issue in critical_issues:
            recommendations.append({
                'priority': 'HIGH',
                'category': issue['type'],
                'title': issue['issue'],
                'action': issue['fix'],
                'impact': issue['impact'],
                'savings': issue.get('savings_potential', 'Unknown')
            })
        
        # Priority 2: Cache opportunities
        if analysis['cache_analysis'].get('cached'):
            recommendations.append({
                'priority': 'INFO',
                'category': 'CACHING',
                'title': 'Result is cached',
                'action': 'Re-run this query for instant, free results',
                'impact': 'Zero cost and near-instant execution',
                'savings': '100%'
            })
        
        # Priority 3: Historical insights
        if analysis['historical_analysis'].get('has_history'):
            hist = analysis['historical_analysis']
            if hist.get('optimal_warehouse'):
                recommendations.append({
                    'priority': 'MEDIUM',
                    'category': 'WAREHOUSE_OPTIMIZATION',
                    'title': f'Use {hist["optimal_warehouse"]} warehouse',
                    'action': f'Switch to {hist["optimal_warehouse"]} for better cost efficiency',
                    'impact': f'Based on {hist["execution_count"]} historical executions',
                    'savings': '10-40%'
                })
            
            # Pruning Issues
            if hist.get('pruning', {}).get('is_poor'):
                p_stats = hist['pruning']
                recommendations.append({
                    'priority': 'HIGH',
                    'category': 'PARTITIONING',
                    'title': 'Poor Partition Pruning',
                    'action': f'Query scans {p_stats["ratio"]:.0%} of partitions ({p_stats["avg_scanned"]:.0f}/{p_stats["avg_total"]:.0f}). Add filters on clustering keys.',
                    'impact': 'Full table scans waste significant credits',
                    'savings': '50-90%'
                })
                
            # Exploding Joins / Large Results
            if hist.get('result_stats', {}).get('is_exploding'):
                row_count = hist['result_stats']['avg_rows']
                recommendations.append({
                    'priority': 'MEDIUM',
                    'category': 'DATA_VOLUME',
                    'title': 'Massive Result Set',
                    'action': f'Query produces ~{row_count:,.0f} rows. Apply stricter filters or aggregation.',
                    'impact': 'High network transfer and client-side memory usage',
                    'savings': '20-50%'
                })
        
        # Priority 4: Medium severity issues
        medium_issues = [i for i in analysis['issues'] if i['severity'] == 'MEDIUM']
        for issue in medium_issues:
            recommendations.append({
                'priority': 'MEDIUM',
                'category': issue['type'],
                'title': issue['issue'],
                'action': issue['fix'],
                'impact': issue['impact'],
                'savings': issue.get('savings_potential', 'Unknown')
            })
        
        return recommendations
    
    def compare_query_alternatives(self, original_query: str, 
                                   alternative_query: str,
                                   warehouse: str) -> Dict[str, Any]:
        """
        Compare two queries and estimate which is more cost-effective
        """
        original_analysis = self.analyze_query_comprehensive(original_query, warehouse)
        alternative_analysis = self.analyze_query_comprehensive(alternative_query, warehouse)
        
        comparison = {
            'original': {
                'estimated_cost': original_analysis['cost_analysis'].get('estimated_credits', 0),
                'issues_count': len(original_analysis['issues']),
                'high_severity_issues': len([i for i in original_analysis['issues'] if i['severity'] == 'HIGH'])
            },
            'alternative': {
                'estimated_cost': alternative_analysis['cost_analysis'].get('estimated_credits', 0),
                'issues_count': len(alternative_analysis['issues']),
                'high_severity_issues': len([i for i in alternative_analysis['issues'] if i['severity'] == 'HIGH'])
            },
            'recommendation': '',
            'savings': {}
        }
        
        # Calculate savings
        cost_diff = comparison['original']['estimated_cost'] - comparison['alternative']['estimated_cost']
        cost_diff_pct = (cost_diff / comparison['original']['estimated_cost'] * 100) if comparison['original']['estimated_cost'] > 0 else 0
        
        comparison['savings'] = {
            'credits': cost_diff,
            'percentage': cost_diff_pct,
            'usd': cost_diff * 3.0
        }
        
        # Generate recommendation
        if cost_diff > 0:
            comparison['recommendation'] = f"Alternative query is {cost_diff_pct:.1f}% more cost-effective"
        elif cost_diff < 0:
            comparison['recommendation'] = f"Original query is {abs(cost_diff_pct):.1f}% more cost-effective"
        else:
            comparison['recommendation'] = "Both queries have similar cost"
        
        return comparison
