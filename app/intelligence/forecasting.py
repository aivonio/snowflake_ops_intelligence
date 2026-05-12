"""
Cost Forecasting and Predictive Analytics
Predicts future costs, query volumes, and resource needs
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta


class CostForecaster:
    """
    Forecasts future costs based on historical trends
    Uses simple time-series analysis and trend detection
    """
    
    def __init__(self, client):
        self.client = client
    
    def _check_cache(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieve forecast from METADATA_CACHE if valid"""
        try:
            # Check if cache table exists (it should, from self-healing)
            query = f"""
            SELECT CACHE_VALUE 
            FROM APP_ANALYTICS.METADATA_CACHE 
            WHERE CACHE_KEY = '{key}' 
            AND EXPIRY_TIME > CURRENT_TIMESTAMP()
            """
            result = self.client.execute_query(query)
            if not result.empty:
                import json
                return json.loads(result.iloc[0]['CACHE_VALUE'])
        except Exception:
            return None
        return None

    def _save_cache(self, key: str, data: Dict[str, Any], ttl_minutes: int = 60):
        """Save forecast to METADATA_CACHE"""
        try:
            import json
            import numpy as np
            from datetime import date
            # Ensure serialization of dates/timestamps and numpy types
            def json_serial(obj):
                if isinstance(obj, (datetime, pd.Timestamp, date)):
                    return obj.isoformat()
                if isinstance(obj, (np.int_, np.intc, np.intp, np.int8,
                    np.int16, np.int32, np.int64, np.uint8,
                    np.uint16, np.uint32, np.uint64)):
                    return int(obj)
                if isinstance(obj, (np.float16, np.float32, np.float64)):
                    return float(obj)
                if isinstance(obj, (np.bool_)):
                    return bool(obj)
                raise TypeError (f"Type {type(obj)} not serializable")

            json_str = json.dumps(data, default=json_serial)
            
            # Robust escaping for Snowflake string literal
            # 1. Escape backslashes first
            json_str_safe = json_str.replace("\\", "\\\\")
            # 2. Escape single quotes
            json_str_safe = json_str_safe.replace("'", "''")
            
            # Use $$ quoting if possible, but python f-string makes it tricky with curly braces
            # adhering to standard single quote escaping
            
            query = f"""
            MERGE INTO APP_ANALYTICS.METADATA_CACHE AS target
            USING (SELECT '{key}' AS key, PARSE_JSON('{json_str_safe}') AS val, 
                   DATEADD(minute, {ttl_minutes}, CURRENT_TIMESTAMP()) as expiry) AS source
            ON target.CACHE_KEY = source.key
            WHEN MATCHED THEN UPDATE SET CACHE_VALUE = source.val, EXPIRY_TIME = source.expiry
            WHEN NOT MATCHED THEN INSERT (CACHE_KEY, CACHE_VALUE, EXPIRY_TIME) 
            VALUES (source.key, source.val, source.expiry)
            """
            self.client.execute_query(query)
        except Exception as e:
            print(f"Cache save failed: {e}")

    def forecast_daily_credits(self, days_history: int = 30, days_forecast: int = 30) -> Dict[str, Any]:
        """
        Forecast daily credit usage with Seasonality and Caching
        """
        cache_key = f"forecast_daily_{days_history}_{days_forecast}"
        cached = self._check_cache(cache_key)
        if cached:
            # Rehydrate DataFrame from JSON
            cached['forecast'] = pd.DataFrame(cached['forecast'])
            if 'usage_date' in cached['forecast'].columns:
                cached['forecast']['usage_date'] = pd.to_datetime(cached['forecast']['usage_date'])
            # Don't return here if you want to verify; but for prod we return
            return cached

        # Get historical data
        query = f"""
        SELECT 
            DATE(START_TIME) as usage_date,
            SUM(CREDITS_USED) as daily_credits,
            DAYNAME(START_TIME) as day_name
        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
        WHERE START_TIME >= DATEADD(day, -{days_history}, CURRENT_TIMESTAMP())
            AND SERVICE_TYPE = 'WAREHOUSE_METERING'
        GROUP BY 1, 3
        ORDER BY usage_date
        """
        
        historical = self.client.execute_query(query)
        
        if historical.empty or len(historical) < 7:
            return {
                'success': False,
                'error': 'Insufficient historical data (need at least 7 days)',
                'forecast': pd.DataFrame()
            }
        
        # --- Seasonality Detection (Weekend Dip) ---
        historical['is_weekend'] = historical['DAY_NAME'].isin(['Sat', 'Sun'])
        
        avg_weekday = historical[~historical['is_weekend']]['DAILY_CREDITS'].mean()
        avg_weekend = historical[historical['is_weekend']]['DAILY_CREDITS'].mean()
        
        weekend_factor = 1.0
        if avg_weekday > 0 and avg_weekend > 0:
            weekend_factor = avg_weekend / avg_weekday
        
        # Dampen if weekend usage is < 85% of weekday
        apply_seasonality = weekend_factor < 0.85
        
        # Simple linear regression forecast
        historical['day_num'] = range(len(historical))
        
        # Calculate trend
        x = historical['day_num'].values
        y = historical['DAILY_CREDITS'].values
        
        # Linear regression
        coefficients = np.polyfit(x, y, 1)
        slope, intercept = coefficients
        
        # Generate forecast
        forecast_days = []
        forecast_credits = []
        last_day = len(historical)
        last_date = pd.to_datetime(historical['USAGE_DATE'].iloc[-1])
        
        for i in range(days_forecast):
            day_num = last_day + i
            base_forecast = slope * day_num + intercept
            forecast_date = last_date + timedelta(days=i+1)
            
            # Apply seasonality
            curr_forecast = max(0, base_forecast)
            if apply_seasonality and forecast_date.weekday() >= 5: # 5=Sat, 6=Sun
                curr_forecast *= weekend_factor
            
            forecast_days.append(forecast_date)
            forecast_credits.append(curr_forecast) 
        
            forecast_days.append(forecast_date)
            forecast_credits.append(curr_forecast) 
        
        forecast_df = pd.DataFrame({
            'USAGE_DATE': forecast_days,
            'FORECASTED_CREDITS': forecast_credits,
            'TYPE': 'forecast'
        })
        
        # Add historical data
        historical_df = historical[['USAGE_DATE', 'DAILY_CREDITS']].copy()
        historical_df['TYPE'] = 'historical'
        historical_df = historical_df.rename(columns={'DAILY_CREDITS': 'FORECASTED_CREDITS'})
        
        combined = pd.concat([historical_df, forecast_df], ignore_index=True)
        
        # Calculate statistics
        avg_daily = historical['DAILY_CREDITS'].mean()
        trend = 'increasing' if slope > 0 else 'decreasing' if slope < 0 else 'stable'
        trend_pct = (slope / avg_daily * 100) if avg_daily > 0 else 0
        
        result = {
            'success': True,
            'forecast': combined.to_dict('records'), # Convert to dict for caching
            'statistics': {
                'avg_daily_credits': avg_daily,
                'trend': trend,
                'trend_percentage': trend_pct,
                'slope': slope,
                'total_forecasted': sum(forecast_credits),
                'days_forecasted': days_forecast,
                'seasonality_applied': apply_seasonality,
                'weekend_factor': weekend_factor if apply_seasonality else 1.0
            }
        }
        
        # Save to cache
        self._save_cache(cache_key, result)
        
        # Convert back to DataFrame for return
        result['forecast'] = combined
        return result
    
    def predict_budget_exhaustion(self, total_budget: float, days_history: int = 30) -> Dict[str, Any]:
        """
        Predict when budget will be exhausted based on current burn rate
        """
        # Get recent usage
        query = f"""
        SELECT 
            SUM(CREDITS_USED) as total_used
        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
        WHERE START_TIME >= DATEADD(day, -{days_history}, CURRENT_TIMESTAMP())
            AND SERVICE_TYPE = 'WAREHOUSE_METERING'
        """
        
        usage = self.client.execute_query(query)
        
        if usage.empty:
            return {
                'success': False,
                'error': 'No usage data available'
            }
        
        total_used = usage.iloc[0]['TOTAL_USED']
        remaining = total_budget - total_used
        
        # Calculate daily burn rate
        daily_burn = total_used / days_history
        
        # Predict exhaustion
        if daily_burn <= 0:
            days_remaining = float('inf')
        else:
            days_remaining = remaining / daily_burn
        
        exhaustion_date = datetime.now() + timedelta(days=days_remaining) if days_remaining < 10000 else None
        
        # Risk level
        if days_remaining < 7:
            risk_level = 'CRITICAL'
        elif days_remaining < 30:
            risk_level = 'HIGH'
        elif days_remaining < 60:
            risk_level = 'MEDIUM'
        else:
            risk_level = 'LOW'
        
        return {
            'success': True,
            'total_budget': total_budget,
            'total_used': total_used,
            'remaining': remaining,
            'daily_burn_rate': daily_burn,
            'days_remaining': days_remaining if days_remaining < 10000 else None,
            'exhaustion_date': exhaustion_date,
            'risk_level': risk_level,
            'percentage_used': (total_used / total_budget * 100) if total_budget > 0 else 0
        }
    
    def forecast_query_volume(self, days_history: int = 30, days_forecast: int = 7) -> Dict[str, Any]:
        """
        Forecast query volume for capacity planning
        """
        cache_key = f"forecast_volume_{days_history}_{days_forecast}"
        cached = self._check_cache(cache_key)
        if cached:
            # Rehydrate DataFrames
            if 'forecast' in cached:
                 cached['forecast'] = pd.DataFrame(cached['forecast'])
                 if 'QUERY_DATE' in cached['forecast'].columns:
                     cached['forecast']['QUERY_DATE'] = pd.to_datetime(cached['forecast']['QUERY_DATE'])
            if 'historical' in cached:
                 cached['historical'] = pd.DataFrame(cached['historical'])
                 if 'QUERY_DATE' in cached['historical'].columns:
                     cached['historical']['QUERY_DATE'] = pd.to_datetime(cached['historical']['QUERY_DATE'])
            return cached

        query = f"""
        SELECT 
            DATE(START_TIME) as query_date,
            COUNT(*) as query_count,
            AVG(TOTAL_ELAPSED_TIME) as avg_time_ms
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD(day, -{days_history}, CURRENT_TIMESTAMP())
        GROUP BY DATE(START_TIME)
        ORDER BY query_date
        """
        
        historical = self.client.execute_query(query)
        
        if historical.empty or len(historical) < 7:
            return {
                'success': False,
                'error': 'Insufficient historical data'
            }
        
        # Calculate trend
        historical['day_num'] = range(len(historical))
        x = historical['day_num'].values
        y = historical['QUERY_COUNT'].values
        
        coefficients = np.polyfit(x, y, 1)
        slope, intercept = coefficients
        
        # Generate forecast
        forecast_dates = []
        forecast_counts = []
        last_day = len(historical)
        
        for i in range(days_forecast):
            day_num = last_day + i
            forecast_count = slope * day_num + intercept
            forecast_date = historical['QUERY_DATE'].iloc[-1] + timedelta(days=i+1)
            
            forecast_dates.append(forecast_date)
            forecast_counts.append(max(0, int(forecast_count)))
        
        forecast_df = pd.DataFrame({
            'QUERY_DATE': forecast_dates,
            'FORECASTED_COUNT': forecast_counts
        })
        
        avg_queries = historical['QUERY_COUNT'].mean()
        trend = 'increasing' if slope > 0 else 'decreasing' if slope < 0 else 'stable'
        
        result = {
            'success': True,
            'forecast': forecast_df.to_dict('records'),
            'historical': historical[['QUERY_DATE', 'QUERY_COUNT']].to_dict('records'),
            'statistics': {
                'avg_daily_queries': avg_queries,
                'trend': trend,
                'slope': slope,
                'total_forecasted': sum(forecast_counts)
            }
        }
        
        self._save_cache(cache_key, result)
        
        # Restore DFs for return
        result['forecast'] = forecast_df
        result['historical'] = historical[['QUERY_DATE', 'QUERY_COUNT']]
        
        return result
    
    def detect_anomalies(self, days: int = 30, threshold: float = 2.0) -> Dict[str, Any]:
        """
        Detect cost anomalies using statistical methods
        """
        query = f"""
        SELECT 
            DATE(START_TIME) as usage_date,
            SUM(CREDITS_USED) as daily_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
        WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            AND SERVICE_TYPE = 'WAREHOUSE_METERING'
        GROUP BY DATE(START_TIME)
        ORDER BY usage_date
        """
        
        data = self.client.execute_query(query)
        
        if data.empty or len(data) < 7:
            return {
                'success': False,
                'error': 'Insufficient data for anomaly detection'
            }
        
        # Calculate statistics
        mean = data['DAILY_CREDITS'].mean()
        std = data['DAILY_CREDITS'].std()
        
        # Detect anomalies (values beyond threshold * std from mean)
        data['z_score'] = (data['DAILY_CREDITS'] - mean) / std if std > 0 else 0
        data['is_anomaly'] = abs(data['z_score']) > threshold
        
        anomalies = data[data['is_anomaly']].copy()
        
        return {
            'success': True,
            'anomalies': anomalies,
            'statistics': {
                'mean': mean,
                'std': std,
                'threshold': threshold,
                'anomaly_count': len(anomalies),
                'total_days': len(data)
            }
        }
    
    def predict_warehouse_needs(self, days_history: int = 30) -> Dict[str, Any]:
        """
        Predict warehouse capacity needs based on query patterns
        """
        cache_key = f"predict_warehouse_{days_history}"
        cached = self._check_cache(cache_key)
        if cached:
            return cached

        query = f"""
        SELECT 
            WAREHOUSE_NAME,
            WAREHOUSE_SIZE,
            COUNT(*) as query_count,
            AVG(QUEUED_PROVISIONING_TIME + QUEUED_OVERLOAD_TIME) as avg_queue_ms,
            AVG(TOTAL_ELAPSED_TIME) as avg_execution_ms
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD(day, -{days_history}, CURRENT_TIMESTAMP())
            AND WAREHOUSE_NAME IS NOT NULL
        GROUP BY WAREHOUSE_NAME, WAREHOUSE_SIZE
        ORDER BY query_count DESC
        """
        
        data = self.client.execute_query(query)
        
        if data.empty:
            return {
                'success': False,
                'error': 'No warehouse usage data'
            }
        
        recommendations = []
        
        for _, row in data.iterrows():
            warehouse = row['WAREHOUSE_NAME']
            size = row['WAREHOUSE_SIZE']
            avg_queue = row['AVG_QUEUE_MS']
            query_count = row['QUERY_COUNT']
            
            recommendation = {
                'warehouse': warehouse,
                'current_size': size,
                'query_count': query_count,
                'avg_queue_ms': avg_queue
            }
            
            # High queue time suggests need for larger warehouse
            if avg_queue > 5000:  # > 5 seconds
                recommendation['action'] = 'SCALE_UP'
                recommendation['reason'] = f'High queue time ({avg_queue/1000:.1f}s avg)'
                recommendation['suggested_size'] = self._next_warehouse_size(size)
            # Low usage suggests potential for smaller warehouse
            elif query_count < 100 and avg_queue < 1000:
                recommendation['action'] = 'SCALE_DOWN'
                recommendation['reason'] = 'Low usage with minimal queuing'
                recommendation['suggested_size'] = self._prev_warehouse_size(size)
            else:
                recommendation['action'] = 'MAINTAIN'
                recommendation['reason'] = 'Current size appears optimal'
                recommendation['suggested_size'] = size
            
            recommendations.append(recommendation)
        
        result = {
            'success': True,
            'recommendations': recommendations
        }
        
        self._save_cache(cache_key, result, ttl_minutes=120) # Longer cache for recommendations
        return result
    
    def _next_warehouse_size(self, current: str) -> str:
        """Get next larger warehouse size"""
        sizes = ['X-SMALL', 'SMALL', 'MEDIUM', 'LARGE', 'X-LARGE', '2X-LARGE', '3X-LARGE', '4X-LARGE']
        try:
            idx = sizes.index(current.upper())
            return sizes[min(idx + 1, len(sizes) - 1)]
        except:
            return 'MEDIUM'
    
    def _prev_warehouse_size(self, current: str) -> str:
        """Get next smaller warehouse size"""
        sizes = ['X-SMALL', 'SMALL', 'MEDIUM', 'LARGE', 'X-LARGE', '2X-LARGE', '3X-LARGE', '4X-LARGE']
        try:
            idx = sizes.index(current.upper())
            return sizes[max(idx - 1, 0)]
        except:
            return 'SMALL'
