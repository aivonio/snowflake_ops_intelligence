
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
import json
import re
from typing import Dict, List, Any

class BIEncoder(json.JSONEncoder):
    """Custom JSON encoder for BI dashboards handling Snowflake/Numpy types."""
    def default(self, obj):
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        if hasattr(obj, 'tolist'):
            return obj.tolist()
        if isinstance(obj, (np.integer, np.floating)):
            return obj.item()
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        try:
            return str(obj)
        except:
            return super().default(obj)

def render_bi_chart(df, config=None):
    """
    Advanced Chart Renderer for AI/BI Builder.
    Supports a wide range of chart types with robust error handling and auto-formatting.
    """
    if df.empty or not config: return None
    
    try:
        # --- CONFIG EXTRACTION ---
        chart_type = config.get("type", "bar").lower()
        title = config.get("title", "")
        x = config.get("x")
        y = config.get("y")
        color = config.get("color")
        
        # Robust handling for list vs string
        if isinstance(x, list) and len(x) == 1: x = x[0]
        if isinstance(color, list) and len(color) == 1: color = color[0]
        
        # Y can be a list for multi-metric charts
        y_cols = y if isinstance(y, list) else ([y] if y else [])
        
        # Secondary Y axis
        sec_y = config.get("secondary_y")
        sec_y_cols = sec_y if isinstance(sec_y, list) else ([sec_y] if sec_y else [])
        
        # Colors
        base_colors = ['#29B5E8', '#00D4AA', '#FFD700', '#FF6B6B', '#9F7AEA', '#F6AD55', '#48BB78']
        
        fig = None
        
        # --- CHART DISPATCHER ---
        
        # 1. DISTRIBUTION & STANDARD (Bar, Line, Area, Scatter)
        if chart_type in ["bar", "line", "area", "scatter"]:
            common_args = {
                "data_frame": df, "x": x, "y": y_cols, "color": color, 
                "title": title, "color_discrete_sequence": base_colors
            }
            
            if chart_type == "bar":
                fig = px.bar(**common_args, barmode=config.get("barmode", "group"), orientation=config.get("orientation", "v"))
            elif chart_type == "line":
                fig = px.line(**common_args, markers=True)
            elif chart_type == "area":
                fig = px.area(**common_args)
            elif chart_type == "scatter":
                fig = px.scatter(**common_args, size=config.get("size"))

        # 2. PART-TO-WHOLE (Pie, Donut, Treemap, Sunburst)
        elif chart_type in ["pie", "donut"]:
            fig = px.pie(df, names=x, values=y_cols[0] if y_cols else None, title=title, 
                         color_discrete_sequence=base_colors, hole=0.4 if chart_type == "donut" else 0)
            fig.update_traces(textinfo='percent+label')
            
        elif chart_type in ["treemap", "sunburst"]:
            path = config.get("path", [x])
            if isinstance(path, str): path = [path]
             # Robust Null Handling for Hierarchies
            df_clean = df.copy()
            valid_path = [c for c in path if c in df.columns]
            for c in valid_path:
                df_clean[c] = df_clean[c].fillna("Unknown").astype(str).replace('', 'Unknown')
                
            val_col = y_cols[0] if y_cols else None
            
            if chart_type == "treemap":
                fig = px.treemap(df_clean, path=valid_path, values=val_col, title=title, color_discrete_sequence=base_colors)
            else:
                fig = px.sunburst(df_clean, path=valid_path, values=val_col, title=title, color_discrete_sequence=base_colors)

        # 3. STATISTICAL (Box, Violin, Histogram)
        elif chart_type == "histogram":
            fig = px.histogram(df, x=x, color=color, title=title, color_discrete_sequence=base_colors, barmode="overlay")
        elif chart_type in ["box", "violin"]:
            args = {"data_frame": df, "x": x, "y": y_cols[0] if y_cols else None, "color": color, "title": title, "color_discrete_sequence": base_colors}
            if chart_type == "box": fig = px.box(**args)
            else: fig = px.violin(**args, box=True, points="all")

        # 4. FLOW & PROCESS (Sankey, Funnel)
        elif chart_type == "funnel":
            fig = px.funnel(df, x=x, y=y_cols[0] if y_cols else None, color=color, title=title, color_discrete_sequence=base_colors)
            
        elif chart_type == "sankey":
            # Auto-detect source/target if not explicit
            src = x if isinstance(x, str) else (x[0] if isinstance(x, list) else df.columns[0])
            tgt = df.columns[1] if len(df.columns) > 1 and df.columns[1] != src else (df.columns[2] if len(df.columns) > 2 else src)
            val = y_cols[0] if y_cols else (df.columns[2] if len(df.columns) > 2 else None)
            
            if src and tgt and val:
                labels = list(set(df[src].astype(str).tolist() + df[tgt].astype(str).tolist()))
                src_idx = [labels.index(str(s)) for s in df[src]]
                tgt_idx = [labels.index(str(t)) for t in df[tgt]]
                
                fig = go.Figure(data=[go.Sankey(
                    node=dict(label=labels, pad=15, thickness=20, line=dict(color="black", width=0.5), color=base_colors[:len(labels)]),
                    link=dict(source=src_idx, target=tgt_idx, value=df[val])
                )])
                fig.update_layout(title_text=title)

        # 5. ADVANCED / SAAS SPECIFIC
        elif chart_type == "pareto":
            # Bar + Cumulative Line
            val = y_cols[0] if y_cols else df.columns[1]
            df_sorted = df.sort_values(by=val, ascending=False)
            df_sorted['CUMULATIVE'] = df_sorted[val].cumsum() / df_sorted[val].sum()
            
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            fig.add_trace(go.Bar(x=df_sorted[x], y=df_sorted[val], name=str(val), marker_color=base_colors[0]), secondary_y=False)
            fig.add_trace(go.Scatter(x=df_sorted[x], y=df_sorted['CUMULATIVE'], name='Cumulative %', mode='lines+markers', line=dict(color='red')), secondary_y=True)
            fig.update_yaxes(title_text="Cumulative %", tickformat=".0%", secondary_y=True)
            fig.update_layout(title_text=title)

        elif chart_type == "parallel":
            # Multi-dimensional
            params = [x] + y_cols + sec_y_cols
            dims = [c for c in params if c in df.columns]
            num_dims = [d for d in dims if pd.api.types.is_numeric_dtype(df[d])]
            if len(num_dims) > 1:
                fig = px.parallel_coordinates(df, dimensions=num_dims, color=num_dims[0], title=title, color_continuous_scale=px.colors.diverging.Tealrose)
            else:
                # Fallback to Categorical Parallel Categories
                fig = px.parallel_categories(df, dimensions=dims, title=title)

        elif chart_type == "bullet":
            # Metric vs Target
            val = y_cols[0] if y_cols else df.columns[1]
            current_val = float(df[val].iloc[0])
            target_val = float(df[sec_y_cols[0]].iloc[0]) if sec_y_cols else current_val * 1.1
            
            fig = go.Figure(go.Indicator(
                mode="number+gauge+delta", value=current_val,
                delta={'reference': target_val},
                gauge={'shape': "bullet", 'axis': {'range': [None, target_val * 1.5]}, 
                       'bar': {'color': base_colors[0]}, 
                       'threshold': {'line': {'color': "red", 'width': 2}, 'thickness': 0.75, 'value': target_val}},
                title={'text': title}
            ))
            fig.update_layout(height=250)

        elif chart_type == "radar":
            cat_col = x
            val_col = y_cols[0] if y_cols else df.columns[1]
            fig = px.line_polar(df, r=val_col, theta=cat_col, line_close=True, title=title)
            fig.update_traces(fill='toself')

        elif chart_type == "heatmap":
             z_col = y_cols[0] if y_cols else df.columns[2]
             fig = px.density_heatmap(df, x=x, y=config.get("y2", df.columns[1]), z=z_col, title=title, text_auto=True, color_continuous_scale='Viridis')

        # 6. GEOSPATIAL MAPS
        elif chart_type == "map":
            # Expecting LAT/LON
            lat_col = config.get("lat")
            lon_col = config.get("lon")
            if lat_col and lon_col and lat_col in df.columns and lon_col in df.columns:
                fig = px.scatter_mapbox(df, lat=lat_col, lon=lon_col, color=color, size=config.get("size"),
                                        color_continuous_scale=px.colors.cyclical.IceFire, size_max=15, zoom=3,
                                        mapbox_style="carto-positron", title=title)
        
        elif chart_type == "choropleth":
            # Expecting location codes
            loc_col = config.get("locations", x)
            if loc_col in df.columns:
                z_col = y_cols[0] if y_cols else None
                fig = px.choropleth(df, locations=loc_col, color=z_col,
                                    color_continuous_scale="Viridis", title=title)
                                    
        # --- PREDICTIVE FORECASTING OVERLAY ---
        if fig and config.get("forecast") and chart_type in ["line", "scatter"] and y_cols:
            # Very basic moving average forecast for responsive UI
            val_col = y_cols[0]
            if pd.api.types.is_numeric_dtype(df[val_col]):
                df_sorted = df.sort_values(by=x) if x in df.columns else df
                # Calculate a simple trendline / rolling mean and extend
                if len(df_sorted) > 5:
                    trend = df_sorted[val_col].rolling(window=3, min_periods=1).mean()
                    fig.add_trace(go.Scatter(x=df_sorted[x], y=trend, mode='lines', 
                                             line=dict(dash='dot', color='orange'), name='Trend/Forecast'))

        # --- LAYOUT POLISH ---
        if fig:
            # Apply Custom Labels
            if config.get("x_label"): fig.update_xaxes(title_text=config["x_label"])
            if config.get("y_label"): fig.update_yaxes(title_text=config["y_label"])
            
            # Global Layout Settings
            custom_height = config.get("height", 350)
            fig.update_layout(
                template="plotly_dark",
                margin=dict(l=20, r=20, t=40, b=20),
                height=custom_height,
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font=dict(family="Inter, sans-serif")
            )
            return fig
            
    except Exception as e:
        # Graceful Failure -> Return Error String or Basic Chart
        print(f"Viz Error: {e}")
        return None
    
    return None
