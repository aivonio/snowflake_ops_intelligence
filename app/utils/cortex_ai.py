"""
Cortex AI Integration Module
Provides natural language explanations and AI-powered insights
"""

import streamlit as st
from typing import Optional


class CortexAI:
    """Integration with Snowflake Cortex AI functions"""
    
    def __init__(self, session):
        self.session = session
        self._available = None
    
    @property
    def is_available(self) -> bool:
        """Check if Cortex AI is available in this region"""
        if self._available is None:
            self._available = self._check_availability()
        return self._available
    
    def _check_availability(self) -> bool:
        """Test if Cortex functions work"""
        try:
            query = "SELECT SNOWFLAKE.CORTEX.COMPLETE('snowflake-arctic', 'test') as response LIMIT 1"
            self.session.sql(query).collect()
            return True
        except Exception:
            return False
    
    def complete(self, prompt: str, model: str = 'snowflake-arctic') -> Optional[str]:
        """
        Generate text completion using Cortex AI
        
        Models available:
        - snowflake-arctic (Snowflake's LLM)
        - mistral-large
        - mixtral-8x7b
        """
        if not self.is_available:
            return None
        
        try:
            # Escape single quotes in prompt
            safe_prompt = prompt.replace("'", "''")
            
            query = f"""
            SELECT SNOWFLAKE.CORTEX.COMPLETE(
                '{model}',
                '{safe_prompt}'
            ) as response
            """
            
            result = self.session.sql(query).collect()
            if result:
                return result[0]['RESPONSE']
            return None
            
        except Exception as e:
            st.warning(f"Cortex AI error: {e}")
            return None
    
    def summarize(self, text: str) -> Optional[str]:
        """Summarize text using Cortex SUMMARIZE function"""
        if not self.is_available:
            return None
        
        try:
            safe_text = text.replace("'", "''")[:10000]  # Limit text length
            
            query = f"""
            SELECT SNOWFLAKE.CORTEX.SUMMARIZE('{safe_text}') as summary
            """
            
            result = self.session.sql(query).collect()
            if result:
                return result[0]['SUMMARY']
            return None
            
        except Exception as e:
            st.warning(f"Cortex summarize error: {e}")
            return None
    
    def explain_query(self, query_text: str) -> Optional[str]:
        """Generate a natural language explanation of a SQL query"""
        prompt = f"""Explain this SQL query in simple terms. Focus on:
1. What data it retrieves
2. What tables are involved
3. Any filtering or aggregation
4. Potential performance concerns

Query:
{query_text[:2000]}

Provide a concise explanation in 2-3 sentences."""
        
        return self.complete(prompt)

    def generate_sql_explanation(self, query_text: str) -> Optional[str]:
        """Alias for explain_query to support legacy calls"""
        return self.explain_query(query_text)
    
    def suggest_optimizations(self, query_text: str, issues: list) -> Optional[str]:
        """Generate AI-powered optimization suggestions"""
        issues_text = "\n".join(f"- {issue}" for issue in issues)
        
        prompt = f"""Given this SQL query and its issues, provide specific optimization suggestions.

Query:
{query_text[:1500]}

Issues found:
{issues_text}

Provide 2-3 specific, actionable optimization suggestions."""
        
        return self.complete(prompt)
    
    def generate_cost_insight(self, metrics: dict) -> Optional[str]:
        """Generate insights about cost metrics"""
        prompt = f"""Analyze these Snowflake cost metrics and provide insights:

Total Credits (30 days): {metrics.get('total_credits', 0):.2f}
Compute Credits: {metrics.get('compute_credits', 0):.2f}
Cloud Services: {metrics.get('cloud_credits', 0):.2f}
Active Warehouses: {metrics.get('warehouse_count', 0)}
Total Queries: {metrics.get('query_count', 0)}

Provide 2-3 key insights about cost patterns and potential optimizations."""
        
        return self.complete(prompt)


# Session-based singleton
_cortex_instance = None

def get_cortex_ai(session) -> CortexAI:
    """Get Cortex AI instance for the given session"""
    global _cortex_instance
    if _cortex_instance is None or _cortex_instance.session != session:
        _cortex_instance = CortexAI(session)
    return _cortex_instance
