"""
Snowflake Cortex AI Integration
Uses Snowflake's native AI capabilities for intelligent query analysis and optimization
"""

import pandas as pd
from typing import Dict, List, Any, Optional
import json


class CortexAI:
    """
    Wrapper for Snowflake Cortex AI functions
    Provides natural language query explanation, optimization suggestions, and more
    """
    
    def __init__(self, client):
        self.client = client
        self.model = 'llama3-70b'  # Default model
        self.available_models = [
            'llama3-70b',
            'llama3-8b',
            'mistral-large',
            'mixtral-8x7b',
            'gemma-7b'
        ]
        self._regional_error = False
        self._edition_restricted = False
        self._needs_cross_region = False
    
    def is_cortex_available(self) -> bool:
        """Check if Cortex AI is available in current region/edition"""
        try:
            test_query = "SELECT SNOWFLAKE.CORTEX.COMPLETE('llama3-8b', 'test') as result"
            result = self.client.execute_query(test_query)
            return not result.empty
        except Exception as e:
            error_msg = str(e).lower()
            
            # 1. Regional Restriction (Enterprise+ accounts in restricted regions)
            if 'region' in error_msg and ('unavailable' in error_msg or 'cross region' in error_msg):
                self._regional_error = True
                self._needs_cross_region = True
                return False

            # 2. Edition Restriction (Standard Edition or strictly disabled cortex)
            if 'invalid property' in error_msg or 'not authorized' in error_msg or 'unsupported' in error_msg:
                # If they are on Enterprise, they should see 'region' error instead of 'invalid property'
                # if they use the correct parameter.
                self._edition_restricted = True
                return False
                
            # 3. Missing service/general error
            if 'does not exist' in error_msg or 'not found' in error_msg:
                return False
            return False
    
    def explain_query(self, query: str) -> Dict[str, Any]:
        """
        Use Cortex AI to explain what a query does in simple terms
        """
        if not self.is_cortex_available():
            return {
                'available': False,
                'explanation': 'Cortex AI not available in this region',
                'error': 'Cortex AI requires specific Snowflake regions'
            }
        
        prompt = f"""Analyze this SQL query and explain:
1. What it does in simple, non-technical terms
2. What data it retrieves
3. Any potential performance concerns
4. Estimated complexity (Simple/Medium/Complex)

Query:
{query}

Provide a clear, concise explanation."""
        
        try:
            ai_query = f"""
            SELECT SNOWFLAKE.CORTEX.COMPLETE(
                '{self.model}',
                '{self._escape_sql(prompt)}'
            ) as explanation
            """
            
            result = self.client.execute_query(ai_query)
            
            if not result.empty:
                return {
                    'available': True,
                    'explanation': result.iloc[0]['EXPLANATION'],
                    'model': self.model
                }
            
            return {
                'available': False,
                'explanation': 'No response from AI',
                'error': 'Empty result'
            }
            
        except Exception as e:
            return {
                'available': False,
                'explanation': f'Error: {str(e)}',
                'error': str(e)
            }
    
    def suggest_optimizations(self, query: str, context: Dict = None) -> Dict[str, Any]:
        """
        Use Cortex AI to suggest query optimizations
        """
        if not self.is_cortex_available():
            return {
                'available': False,
                'suggestions': [],
                'error': 'Cortex AI not available'
            }
        
        context_str = ""
        if context:
            context_str = f"""
Context:
- Warehouse Size: {context.get('warehouse_size', 'Unknown')}
- Estimated Bytes: {context.get('estimated_bytes', 'Unknown')}
- Historical Executions: {context.get('execution_count', 0)}
- Average Cache Hit: {context.get('avg_cache_hit', 0)}%
"""
        
        prompt = f"""You are a Snowflake query optimization expert. Analyze this query and provide specific, actionable optimization suggestions.

{context_str}

Query:
{query}

Provide 3-5 specific optimization suggestions in this format:
1. [Optimization Type]: [Specific suggestion]
   Impact: [Expected performance/cost improvement]
   
Focus on:
- Reducing data scanned
- Improving partition pruning
- Leveraging caching
- Warehouse sizing
- Query structure improvements

Be specific and actionable."""
        
        try:
            ai_query = f"""
            SELECT SNOWFLAKE.CORTEX.COMPLETE(
                '{self.model}',
                '{self._escape_sql(prompt)}'
            ) as suggestions
            """
            
            result = self.client.execute_query(ai_query)
            
            if not result.empty:
                suggestions_text = result.iloc[0]['SUGGESTIONS']
                
                # Parse suggestions (simple parsing)
                suggestions = self._parse_suggestions(suggestions_text)
                
                return {
                    'available': True,
                    'suggestions': suggestions,
                    'raw_text': suggestions_text,
                    'model': self.model
                }
            
            return {
                'available': False,
                'suggestions': [],
                'error': 'Empty result'
            }
            
        except Exception as e:
            return {
                'available': False,
                'suggestions': [],
                'error': str(e)
            }
    
    def generate_optimized_query(self, original_query: str, optimization_goal: str = 'cost') -> Dict[str, Any]:
        """
        Use Cortex AI to generate an optimized version of the query
        """
        if not self.is_cortex_available():
            return {
                'available': False,
                'optimized_query': original_query,
                'error': 'Cortex AI not available'
            }
        
        goal_descriptions = {
            'cost': 'minimize cost by reducing data scanned',
            'speed': 'maximize speed by optimizing execution',
            'both': 'balance cost and speed'
        }
        
        goal_desc = goal_descriptions.get(optimization_goal, goal_descriptions['cost'])
        
        prompt = f"""You are a Snowflake SQL expert. Rewrite this query to {goal_desc}.

Original Query:
{original_query}

Provide:
1. The optimized query (valid SQL only)
2. Brief explanation of changes made
3. Expected improvement

Format:
OPTIMIZED QUERY:
[SQL here]

CHANGES:
[explanation]

EXPECTED IMPROVEMENT:
[improvement description]"""
        
        try:
            ai_query = f"""
            SELECT SNOWFLAKE.CORTEX.COMPLETE(
                '{self.model}',
                '{self._escape_sql(prompt)}'
            ) as response
            """
            
            result = self.client.execute_query(ai_query)
            
            if not result.empty:
                response = result.iloc[0]['RESPONSE']
                
                # Parse response
                parsed = self._parse_optimized_query_response(response)
                
                return {
                    'available': True,
                    'optimized_query': parsed.get('query', original_query),
                    'changes': parsed.get('changes', ''),
                    'expected_improvement': parsed.get('improvement', ''),
                    'raw_response': response,
                    'model': self.model
                }
            
            return {
                'available': False,
                'optimized_query': original_query,
                'error': 'Empty result'
            }
            
        except Exception as e:
            return {
                'available': False,
                'optimized_query': original_query,
                'error': str(e)
            }
    
    def analyze_error(self, query: str, error_message: str) -> Dict[str, Any]:
        """
        Use Cortex AI to analyze query errors and suggest fixes
        """
        if not self.is_cortex_available():
            return {
                'available': False,
                'analysis': 'Cortex AI not available',
                'error': 'Cortex AI not available'
            }
        
        prompt = f"""You are a Snowflake expert. A query failed with an error. Analyze and provide:
1. What caused the error (in simple terms)
2. How to fix it (specific steps)
3. The corrected query (if possible)

Query:
{query}

Error:
{error_message}

Provide clear, actionable guidance."""
        
        try:
            ai_query = f"""
            SELECT SNOWFLAKE.CORTEX.COMPLETE(
                '{self.model}',
                '{self._escape_sql(prompt)}'
            ) as analysis
            """
            
            result = self.client.execute_query(ai_query)
            
            if not result.empty:
                return {
                    'available': True,
                    'analysis': result.iloc[0]['ANALYSIS'],
                    'model': self.model
                }
            
            return {
                'available': False,
                'analysis': 'No response',
                'error': 'Empty result'
            }
            
        except Exception as e:
            return {
                'available': False,
                'analysis': f'Error: {str(e)}',
                'error': str(e)
            }
    
    def summarize_query_patterns(self, queries: List[str]) -> Dict[str, Any]:
        """
        Use Cortex AI to analyze and summarize common query patterns
        """
        if not self.is_cortex_available():
            return {
                'available': False,
                'summary': 'Cortex AI not available',
                'error': 'Cortex AI not available'
            }
        
        # Limit to first 10 queries to avoid token limits
        query_sample = queries[:10]
        queries_text = "\n\n".join([f"Query {i+1}:\n{q}" for i, q in enumerate(query_sample)])
        
        prompt = f"""Analyze these SQL queries and identify:
1. Common patterns (what types of queries are these?)
2. Common tables/data sources accessed
3. Potential optimization opportunities across all queries
4. Recommendations for standardization

Queries:
{queries_text}

Provide a concise summary."""
        
        try:
            ai_query = f"""
            SELECT SNOWFLAKE.CORTEX.COMPLETE(
                '{self.model}',
                '{self._escape_sql(prompt)}'
            ) as summary
            """
            
            result = self.client.execute_query(ai_query)
            
            if not result.empty:
                return {
                    'available': True,
                    'summary': result.iloc[0]['SUMMARY'],
                    'queries_analyzed': len(query_sample),
                    'model': self.model
                }
            
            return {
                'available': False,
                'summary': 'No response',
                'error': 'Empty result'
            }
            
        except Exception as e:
            return {
                'available': False,
                'summary': f'Error: {str(e)}',
                'error': str(e)
            }
    
    def _escape_sql(self, text: str) -> str:
        """Escape text for SQL string"""
        return text.replace("'", "''").replace("\\", "\\\\")
    
    def _parse_suggestions(self, text: str) -> List[Dict[str, str]]:
        """Parse AI suggestions into structured format"""
        suggestions = []
        
        # Simple parsing - split by numbered items
        lines = text.split('\n')
        current_suggestion = None
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Check if line starts with a number
            if line[0].isdigit() and '.' in line[:3]:
                if current_suggestion:
                    suggestions.append(current_suggestion)
                
                current_suggestion = {
                    'text': line,
                    'type': 'optimization'
                }
            elif current_suggestion and line.lower().startswith('impact:'):
                current_suggestion['impact'] = line.replace('Impact:', '').strip()
        
        if current_suggestion:
            suggestions.append(current_suggestion)
        
        return suggestions if suggestions else [{'text': text, 'type': 'general'}]
    
    def _parse_optimized_query_response(self, response: str) -> Dict[str, str]:
        """Parse optimized query response"""
        result = {
            'query': '',
            'changes': '',
            'improvement': ''
        }
        
        # Simple parsing
        sections = response.split('OPTIMIZED QUERY:')
        if len(sections) > 1:
            rest = sections[1]
            
            # Extract query
            if 'CHANGES:' in rest:
                query_part, rest = rest.split('CHANGES:', 1)
                result['query'] = query_part.strip()
                
                # Extract changes
                if 'EXPECTED IMPROVEMENT:' in rest:
                    changes_part, improvement_part = rest.split('EXPECTED IMPROVEMENT:', 1)
                    result['changes'] = changes_part.strip()
                    result['improvement'] = improvement_part.strip()
                else:
                    result['changes'] = rest.strip()
            else:
                result['query'] = rest.strip()
        
        return result
