import json
import pandas as pd
import streamlit as st

class VisualizationAgent:
    """Simplified for debugging ImportError"""
    def __init__(self, client):
        self.client = client
        self.default_colors = ['#00D4AA', '#29B5E8']

    def suggest_visualizations(self, df, user_prompt):
        # Basic fallback to ensure something shows up
        cols = df.columns.tolist()
        return [{
            "type": "bar",
            "x": cols[0],
            "y": cols[-1],
            "title": "Debug View"
        }]
