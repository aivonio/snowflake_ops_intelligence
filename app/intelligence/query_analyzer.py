"""
Query Analyzer Module
Analyzes SQL queries and provides optimization suggestions
"""

import re
import sqlparse
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class QueryIssue:
    """Represents an issue found in a query"""
    severity: str  # 'HIGH', 'MEDIUM', 'LOW'
    category: str  # 'PERFORMANCE', 'COST', 'BEST_PRACTICE'
    message: str
    suggestion: str
    impact_score: int  # 0-25 contribution to risk score


@dataclass
class QueryAnalysis:
    """Complete analysis of a query"""
    issues: List[QueryIssue]
    risk_score: int  # 0-100
    complexity: str  # 'LOW', 'MEDIUM', 'HIGH', 'VERY_HIGH'
    tables_referenced: List[str]
    join_count: int
    has_aggregations: bool
    has_subqueries: bool
    estimated_scan_level: str  # 'MINIMAL', 'MODERATE', 'FULL_SCAN'


class QueryAnalyzer:
    """Analyzes SQL queries for optimization opportunities"""
    
    def __init__(self):
        self.patterns = self._compile_patterns()
    
    def _compile_patterns(self) -> Dict[str, re.Pattern]:
        """Compile regex patterns for query analysis"""
        return {
            'select_star': re.compile(r'\bSELECT\s+\*', re.IGNORECASE),
            'leading_wildcard': re.compile(r"LIKE\s+'%[^%]", re.IGNORECASE),
            'trailing_wildcard': re.compile(r"LIKE\s+'[^%]+%'", re.IGNORECASE),
            'order_by': re.compile(r'\bORDER\s+BY\b', re.IGNORECASE),
            'limit': re.compile(r'\bLIMIT\b', re.IGNORECASE),
            'where': re.compile(r'\bWHERE\b', re.IGNORECASE),
            'join': re.compile(r'\bJOIN\b', re.IGNORECASE),
            'left_join': re.compile(r'\bLEFT\s+(?:OUTER\s+)?JOIN\b', re.IGNORECASE),
            'cross_join': re.compile(r'\bCROSS\s+JOIN\b', re.IGNORECASE),
            'union': re.compile(r'\bUNION\b(?!\s+ALL)', re.IGNORECASE),
            'union_all': re.compile(r'\bUNION\s+ALL\b', re.IGNORECASE),
            'distinct': re.compile(r'\bSELECT\s+DISTINCT\b', re.IGNORECASE),
            'group_by': re.compile(r'\bGROUP\s+BY\b', re.IGNORECASE),
            'having': re.compile(r'\bHAVING\b', re.IGNORECASE),
            'subquery': re.compile(r'\(\s*SELECT\b', re.IGNORECASE),
            'correlated_subquery': re.compile(r'WHERE.*\(\s*SELECT.*WHERE.*\)', re.IGNORECASE | re.DOTALL),
            'function_in_where': re.compile(r'WHERE.*(?:DATE|YEAR|MONTH|DAY|UPPER|LOWER|TRIM|SUBSTRING)\s*\(', re.IGNORECASE),
            'not_in': re.compile(r'\bNOT\s+IN\s*\(', re.IGNORECASE),
            'or_condition': re.compile(r'\bWHERE\b.*\bOR\b', re.IGNORECASE | re.DOTALL),
            'cartesian': re.compile(r'FROM\s+\w+\s*,\s*\w+', re.IGNORECASE),
            'count_distinct': re.compile(r'COUNT\s*\(\s*DISTINCT\b', re.IGNORECASE),
            'cte': re.compile(r'\bWITH\b.*\bAS\s*\(', re.IGNORECASE | re.DOTALL),
            'window_function': re.compile(r'\bOVER\s*\(', re.IGNORECASE),
            'table_name': re.compile(r'\bFROM\s+(\w+(?:\.\w+)?)', re.IGNORECASE),
            'join_table': re.compile(r'\bJOIN\s+(\w+(?:\.\w+)?)', re.IGNORECASE),
        }
    
    def analyze(self, query: str) -> QueryAnalysis:
        """Analyze a query and return comprehensive results"""
        if not query or not query.strip():
            return QueryAnalysis(
                issues=[],
                risk_score=0,
                complexity='LOW',
                tables_referenced=[],
                join_count=0,
                has_aggregations=False,
                has_subqueries=False,
                estimated_scan_level='MINIMAL'
            )
        
        query_upper = query.upper()
        issues = []
        
        # Check for SELECT *
        if self.patterns['select_star'].search(query):
            issues.append(QueryIssue(
                severity='MEDIUM',
                category='PERFORMANCE',
                message='Query uses SELECT * which retrieves all columns',
                suggestion='Specify only the columns you need to reduce data transfer and improve performance',
                impact_score=15
            ))
        
        # Check for missing WHERE clause
        has_where = self.patterns['where'].search(query)
        has_limit = self.patterns['limit'].search(query)
        if not has_where and not has_limit and 'SELECT' in query_upper and 'FROM' in query_upper:
            issues.append(QueryIssue(
                severity='HIGH',
                category='COST',
                message='No WHERE clause or LIMIT - may perform full table scan',
                suggestion='Add filter conditions to reduce data scanned and lower costs',
                impact_score=25
            ))
        
        # Check for leading wildcard in LIKE
        if self.patterns['leading_wildcard'].search(query):
            issues.append(QueryIssue(
                severity='MEDIUM',
                category='PERFORMANCE',
                message='LIKE pattern with leading wildcard prevents pruning optimization',
                suggestion='Consider using CONTAINS() or restructuring to avoid leading wildcards',
                impact_score=20
            ))
        
        # Check for ORDER BY without LIMIT
        if self.patterns['order_by'].search(query) and not has_limit:
            issues.append(QueryIssue(
                severity='LOW',
                category='PERFORMANCE',
                message='ORDER BY without LIMIT on potentially large result set',
                suggestion='Add LIMIT clause if you only need top N results',
                impact_score=10
            ))
        
        # Count JOINs
        join_count = len(self.patterns['join'].findall(query))
        if join_count > 5:
            issues.append(QueryIssue(
                severity='HIGH',
                category='PERFORMANCE',
                message=f'Complex query with {join_count} JOINs - may cause performance issues',
                suggestion='Consider breaking into CTEs or materializing intermediate results',
                impact_score=min(join_count * 5, 25)
            ))
        elif join_count > 3:
            issues.append(QueryIssue(
                severity='MEDIUM',
                category='PERFORMANCE',
                message=f'Query has {join_count} JOINs',
                suggestion='Monitor execution time and consider optimizing join order',
                impact_score=join_count * 3
            ))
        
        # Check for CROSS JOIN
        if self.patterns['cross_join'].search(query):
            issues.append(QueryIssue(
                severity='HIGH',
                category='COST',
                message='CROSS JOIN detected - creates Cartesian product',
                suggestion='Ensure CROSS JOIN is intentional; add conditions if possible',
                impact_score=25
            ))
        
        # Check for Cartesian join (comma-separated tables without join condition)
        if self.patterns['cartesian'].search(query) and 'JOIN' not in query_upper:
            issues.append(QueryIssue(
                severity='HIGH',
                category='COST',
                message='Possible Cartesian join detected (comma-separated tables)',
                suggestion='Use explicit JOIN syntax with proper conditions',
                impact_score=25
            ))
        
        # Check for correlated subquery
        if self.patterns['correlated_subquery'].search(query):
            issues.append(QueryIssue(
                severity='MEDIUM',
                category='PERFORMANCE',
                message='Correlated subquery may execute once per row',
                suggestion='Consider rewriting as JOIN or using window functions',
                impact_score=20
            ))
        
        # Check for function in WHERE clause
        if self.patterns['function_in_where'].search(query):
            issues.append(QueryIssue(
                severity='MEDIUM',
                category='PERFORMANCE',
                message='Function applied to column in WHERE clause prevents pruning',
                suggestion='Transform the comparison value instead of the column, or create a computed column',
                impact_score=15
            ))
        
        # Check for NOT IN
        if self.patterns['not_in'].search(query):
            issues.append(QueryIssue(
                severity='LOW',
                category='BEST_PRACTICE',
                message='NOT IN may have unexpected behavior with NULLs',
                suggestion='Consider using NOT EXISTS or LEFT JOIN with NULL check',
                impact_score=5
            ))
        
        # Check for UNION without ALL
        if self.patterns['union'].search(query) and not self.patterns['union_all'].search(query):
            issues.append(QueryIssue(
                severity='LOW',
                category='PERFORMANCE',
                message='UNION removes duplicates; use UNION ALL if duplicates are acceptable',
                suggestion='UNION ALL is faster as it skips the deduplication step',
                impact_score=5
            ))
        
        # Check for DISTINCT
        if self.patterns['distinct'].search(query):
            issues.append(QueryIssue(
                severity='LOW',
                category='PERFORMANCE',
                message='DISTINCT requires additional processing to remove duplicates',
                suggestion='Verify DISTINCT is necessary; consider filtering earlier in the query',
                impact_score=10
            ))
        
        # Check for COUNT(DISTINCT)
        if self.patterns['count_distinct'].search(query):
            issues.append(QueryIssue(
                severity='MEDIUM',
                category='PERFORMANCE',
                message='COUNT(DISTINCT) can be expensive on large datasets',
                suggestion='Consider using APPROX_COUNT_DISTINCT() for large datasets if exact count is not required',
                impact_score=15
            ))
        
        # Calculate risk score
        risk_score = min(sum(issue.impact_score for issue in issues), 100)
        
        # Determine complexity
        complexity = 'LOW'
        if risk_score >= 60 or join_count >= 5:
            complexity = 'VERY_HIGH'
        elif risk_score >= 40 or join_count >= 3:
            complexity = 'HIGH'
        elif risk_score >= 20 or join_count >= 2:
            complexity = 'MEDIUM'
        
        # Extract tables
        tables = self._extract_tables(query)
        
        # Check for subqueries and aggregations
        has_subqueries = bool(self.patterns['subquery'].search(query))
        has_aggregations = bool(self.patterns['group_by'].search(query))
        
        # Estimate scan level
        scan_level = 'MINIMAL'
        if not has_where:
            scan_level = 'FULL_SCAN'
        elif any(issue.category == 'COST' and issue.severity == 'HIGH' for issue in issues):
            scan_level = 'FULL_SCAN'
        elif join_count > 2 or has_subqueries:
            scan_level = 'MODERATE'
        
        return QueryAnalysis(
            issues=issues,
            risk_score=risk_score,
            complexity=complexity,
            tables_referenced=tables,
            join_count=join_count,
            has_aggregations=has_aggregations,
            has_subqueries=has_subqueries,
            estimated_scan_level=scan_level
        )
    
    def _extract_tables(self, query: str) -> List[str]:
        """Extract table names from query"""
        tables = []
        
        # Find tables after FROM
        from_matches = self.patterns['table_name'].findall(query)
        tables.extend(from_matches)
        
        # Find tables after JOIN
        join_matches = self.patterns['join_table'].findall(query)
        tables.extend(join_matches)
        
        # Clean up and deduplicate
        tables = list(set(t.upper() for t in tables if t.upper() not in (
            'DUAL', 'SELECT', 'FROM', 'WHERE', 'AND', 'OR', 'JOIN', 'TABLE'
        )))
        
        return tables
    
    def format_query(self, query: str) -> str:
        """Format a query for better readability"""
        return sqlparse.format(
            query,
            reindent=True,
            keyword_case='upper',
            identifier_case='lower',
            strip_comments=False,
            indent_width=2
        )
    
    def get_optimization_suggestions(self, analysis: QueryAnalysis) -> List[str]:
        """Generate prioritized optimization suggestions"""
        suggestions = []
        
        # Sort issues by impact
        sorted_issues = sorted(analysis.issues, key=lambda x: x.impact_score, reverse=True)
        
        for issue in sorted_issues[:5]:  # Top 5 suggestions
            suggestions.append(f"• {issue.suggestion}")
        
        # Add general suggestions based on analysis
        if analysis.estimated_scan_level == 'FULL_SCAN':
            suggestions.append("• Consider adding clustering keys to frequently filtered tables")
        
        if analysis.join_count > 2:
            suggestions.append("• Review join order - start with the most selective table")
        
        if analysis.has_subqueries:
            suggestions.append("• Evaluate if subqueries can be converted to JOINs for better optimizer hints")
        
        return suggestions


# Singleton instance
_analyzer = None

def get_analyzer() -> QueryAnalyzer:
    """Get singleton analyzer instance"""
    global _analyzer
    if _analyzer is None:
        _analyzer = QueryAnalyzer()
    return _analyzer
