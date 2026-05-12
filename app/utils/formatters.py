"""
Data Formatting Utilities
Helper functions for formatting data for display
"""

import pandas as pd
from typing import Union, Optional
from datetime import datetime, timedelta


def format_credits(credits: Union[float, int, None], precision: int = 2) -> str:
    """Format credit amount for display"""
    if credits is None:
        return "N/A"
    return f"{credits:,.{precision}f}"


def format_bytes(bytes_value: Union[int, float, None]) -> str:
    """Format bytes to human readable format (KB, MB, GB, TB)"""
    if bytes_value is None or bytes_value == 0:
        return "0 B"
    
    units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
    unit_index = 0
    value = float(bytes_value)
    
    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1
    
    return f"{value:,.2f} {units[unit_index]}"


def format_duration_ms(ms: Union[int, float, None]) -> str:
    """Format milliseconds to human readable duration"""
    if ms is None:
        return "N/A"
    
    ms = float(ms)
    
    if ms < 1000:
        return f"{ms:.0f}ms"
    elif ms < 60000:
        return f"{ms/1000:.1f}s"
    elif ms < 3600000:
        minutes = int(ms // 60000)
        seconds = int((ms % 60000) // 1000)
        return f"{minutes}m {seconds}s"
    else:
        hours = int(ms // 3600000)
        minutes = int((ms % 3600000) // 60000)
        return f"{hours}h {minutes}m"


def format_number(value: Union[int, float, None], precision: int = 0) -> str:
    """Format number with thousands separator"""
    if value is None:
        return "N/A"
    
    if precision == 0:
        return f"{int(value):,}"
    return f"{value:,.{precision}f}"


def format_percentage(value: Union[float, None], precision: int = 1) -> str:
    """Format value as percentage"""
    if value is None:
        return "N/A"
    return f"{value:.{precision}f}%"


def format_timestamp(ts: Optional[datetime], format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Format timestamp for display"""
    if ts is None:
        return "N/A"
    return ts.strftime(format_str)


def format_time_ago(ts: Optional[datetime]) -> str:
    """Format timestamp as 'time ago' string"""
    if ts is None:
        return "N/A"
    
    now = datetime.utcnow()
    diff = now - ts
    
    if diff.total_seconds() < 60:
        return "just now"
    elif diff.total_seconds() < 3600:
        minutes = int(diff.total_seconds() // 60)
        return f"{minutes}m ago"
    elif diff.total_seconds() < 86400:
        hours = int(diff.total_seconds() // 3600)
        return f"{hours}h ago"
    elif diff.days < 30:
        return f"{diff.days}d ago"
    else:
        return ts.strftime("%Y-%m-%d")


def truncate_query(query: str, max_length: int = 100) -> str:
    """Truncate query text for display"""
    if not query:
        return ""
    
    # Clean up whitespace
    query = ' '.join(query.split())
    
    if len(query) <= max_length:
        return query
    
    return query[:max_length-3] + "..."


def get_status_color(status: str) -> str:
    """Get color code for status display"""
    if status is None or pd.isna(status):
        return '#A0AEC0'  # Default gray for None/NaN
    
    status_colors = {
        'SUCCESS': '#00D4AA',
        'RUNNING': '#29B5E8',
        'QUEUED': '#FFB020',
        'FAILED': '#FF4B4B',
        'CANCELLED': '#A0AEC0',
        'STARTED': '#00D4AA',
        'SUSPENDED': '#FFB020',
        'STOPPED': '#A0AEC0',
        'HEALTHY': '#00D4AA',
        'WARNING': '#FFB020',
        'CRITICAL': '#FF4B4B'
    }
    return status_colors.get(str(status).upper(), '#A0AEC0')


def get_risk_color(risk_score: Union[int, float]) -> str:
    """Get color for risk score (1-100)"""
    if risk_score < 30:
        return '#00D4AA'  # Green - low risk
    elif risk_score < 70:
        return '#FFB020'  # Yellow - medium risk
    else:
        return '#FF4B4B'  # Red - high risk


def calculate_cost_estimate(bytes_scanned: int, warehouse_size: str) -> float:
    """Estimate query cost based on bytes scanned and warehouse size"""
    # Credit cost per second by warehouse size
    credits_per_second = {
        'X-SMALL': 1/3600,
        'SMALL': 2/3600,
        'MEDIUM': 4/3600,
        'LARGE': 8/3600,
        'X-LARGE': 16/3600,
        '2X-LARGE': 32/3600,
        '3X-LARGE': 64/3600,
        '4X-LARGE': 128/3600
    }
    
    # Estimate scan time based on bytes (rough approximation)
    # Snowflake can scan ~200MB/s per credit of compute
    gb_scanned = bytes_scanned / (1024 ** 3)
    estimated_seconds = max(gb_scanned / 0.2, 1)  # At least 1 second
    
    credit_rate = credits_per_second.get(warehouse_size.upper(), credits_per_second['MEDIUM'])
    
    return estimated_seconds * credit_rate


def create_sparkline_data(values: list, max_points: int = 20) -> list:
    """Create data points for a sparkline chart"""
    if len(values) <= max_points:
        return values
    
    # Sample evenly
    step = len(values) / max_points
    return [values[int(i * step)] for i in range(max_points)]


def dataframe_to_excel_bytes(df: pd.DataFrame, sheet_name: str = "Data") -> bytes:
    """Convert DataFrame to Excel file bytes for download"""
    import io
    
    # Try to import xlsxwriter, fail gracefully if not present
    try:
        import xlsxwriter
    except ImportError:
        st.error("The 'xlsxwriter' package is required for Excel exports. Please add it to your Snowflake Streamlit environment.")
        return None

    # Create copy to avoid modifying original
    df_export = df.copy()
    
    # Remove timezones from datetime columns (Excel doesn't support them)
    for col in df_export.columns:
        if pd.api.types.is_datetime64_any_dtype(df_export[col]):
            try:
                # Attempt to remove timezone info
                df_export[col] = df_export[col].dt.tz_localize(None)
            except Exception:
                # Fallback for mixed types or other issues
                pass
    
    buffer = io.BytesIO()
    try:
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            df_export.to_excel(writer, sheet_name=sheet_name, index=False)
            
            # Auto-adjust column widths
            worksheet = writer.sheets[sheet_name]
            for idx, col in enumerate(df_export.columns):
                max_length = max(
                    df_export[col].astype(str).apply(len).max() if not df_export[col].empty else 0,
                    len(str(col))
                ) + 2
                worksheet.set_column(idx, idx, min(max_length, 50))
        
        return buffer.getvalue()
    except Exception as e:
        st.error(f"Error generating Excel file: {e}")
        return None
