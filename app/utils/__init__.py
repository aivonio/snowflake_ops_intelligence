"""
Utils package initialization — SnowOps Intelligence V2.5
"""

from .snowflake_client import SnowflakeClient, get_snowflake_client
from .visualization_agent import VisualizationAgent
from .setup_wizard import SetupWizard, render_setup_wizard
from .data_service import get_account_metrics, get_daily_credits, get_daily_credits_by_warehouse
from .formatters import (
    format_credits,
    format_bytes,
    format_duration_ms,
    format_number,
    format_percentage,
    format_timestamp,
    format_time_ago,
    truncate_query,
    get_status_color,
    get_risk_color,
    dataframe_to_excel_bytes
)

# V2.5 Engine imports (lazy-loaded via getter functions)
from .coco_client import get_coco_client
from .cortex_agents import get_agent_manager
from .dbt_engine import get_dbt_engine
from .pipeline_engine import get_pipeline_engine
from .data_quality_engine import get_data_quality_engine
from .observability_engine import get_observability_engine
from .cost_optimizer import get_cost_optimizer
from .automation_engine import get_automation_engine

__all__ = [
    'SnowflakeClient',
    'get_snowflake_client',
    'VisualizationAgent',
    'SetupWizard',
    'render_setup_wizard',
    'get_account_metrics',
    'get_daily_credits',
    'get_daily_credits_by_warehouse',
    'format_credits',
    'format_bytes',
    'format_duration_ms',
    'format_number',
    'format_percentage',
    'format_timestamp',
    'format_time_ago',
    'truncate_query',
    'get_status_color',
    'get_risk_color',
    'dataframe_to_excel_bytes',
    # V2.5 engines
    'get_coco_client',
    'get_agent_manager',
    'get_dbt_engine',
    'get_pipeline_engine',
    'get_data_quality_engine',
    'get_observability_engine',
    'get_cost_optimizer',
    'get_automation_engine',
]
