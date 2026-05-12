
import streamlit as st
import pandas as pd
import altair as alt
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.snowflake_client import get_snowflake_client
from utils.styles import apply_global_styles, render_sidebar
from utils.auth import verify_page_access

st.set_page_config(
    page_title="Security Scorecard | Snowflake Ops",
    page_icon="🛡️",
    layout="wide"
)

# Apply styles
apply_global_styles()
render_sidebar()

# Verify Access
verify_page_access('ADMIN')

st.title("🛡️ Security Scorecard")
st.markdown("*Monitor security posture, failed logins, and privilege risks.*")

client = get_snowflake_client()

# 1. Failed Logins
st.markdown("### 🚨 Failed Login Attempts (Last 7 Days)")

query_logins = """
SELECT 
    USER_NAME,
    CLIENT_IP,
    REPORTED_CLIENT_TYPE,
    ERROR_MESSAGE,
    COUNT(*) as FAIL_COUNT,
    MAX(EVENT_TIMESTAMP) as LAST_ATTEMPT
FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
WHERE IS_SUCCESS = 'NO'
  AND EVENT_TIMESTAMP >= DATEADD(day, -7, CURRENT_TIMESTAMP())
GROUP BY 1, 2, 3, 4
ORDER BY FAIL_COUNT DESC
LIMIT 50
"""

try:
    logins_df = client.execute_query(query_logins)
    if not logins_df.empty:
        st.dataframe(logins_df, use_container_width=True)
        
        # Brute force visual
        chart = alt.Chart(logins_df).mark_bar(color='#FF4B4B').encode(
            x=alt.X('FAIL_COUNT:Q', title='Failed Attempts'),
            y=alt.Y('USER_NAME:N', sort='-x', title='User'),
            tooltip=['USER_NAME', 'CLIENT_IP', 'FAIL_COUNT']
        ).properties(title="Potential Brute Force Targets")
        st.altair_chart(chart, use_container_width=True)
    else:
        st.success("✅ No failed logins detected in the last 7 days.")
except Exception as e:
    st.error(f"Error fetching login history: {e}")

st.divider()

# 2. Admin Risk
st.markdown("### 🔑 Admin Privilege Usage")
st.markdown("Users with `ACCOUNTADMIN` role and when they last used it.")

query_admins = """
SELECT 
    USER_NAME,
    ROLE_NAME,
    MAX(START_TIME) as LAST_USED
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE ROLE_NAME = 'ACCOUNTADMIN'
GROUP BY 1, 2
ORDER BY LAST_USED DESC
"""

try:
    admin_df = client.execute_query(query_admins)
    if not admin_df.empty:
        st.dataframe(admin_df, use_container_width=True)
    else:
        st.info("No ACCOUNTADMIN usage detected in query history.")
except Exception as e:
    st.error(f"Error checking admin usage: {e}")

st.divider()

# 3. Network Policy Gaps (Mock/Placeholder logic for now as POLICY_REFERENCES is complex)
# We can check if users are logging in without a policy if we had that data easily.
# For now, let's just list Network Policies.

st.markdown("### 🌐 Network Policies")
try:
    policies_df = client.execute_query("SHOW NETWORK POLICIES")
    if not policies_df.empty:
        st.dataframe(policies_df)
    else:
        st.warning("⚠️ No Network Policies found! Your account is open to the world.")
except Exception as e:
    st.error(f"Could not list network policies: {e}")
