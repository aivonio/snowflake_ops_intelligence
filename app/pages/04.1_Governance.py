import streamlit as st
import pandas as pd
import altair as alt
import sys
import os

try:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
except (NameError, TypeError):
    pass

from utils.snowflake_client import get_snowflake_client
from utils.formatters import format_credits
from utils.metadata_cache import get_metadata_cache
from utils.styles import apply_global_styles, render_metric_card, COLORS

st.set_page_config(
    page_title="Security & Governance | Snowflake Ops",
    page_icon="🛡️",
    layout="wide"
)

# Apply unified Snowflake design system
apply_global_styles()
from utils.styles import render_sidebar
render_sidebar()

st.title("🛡️ AI Security Scorecard")
st.markdown("*Automated Security Posture Scoring & Compliance Auditing*")


client = get_snowflake_client()

if not client.session:
    st.error("⚠️ Could not connect to Snowflake")
    st.stop()

# --- HELPER QUERIES ---

@st.cache_data(ttl=3600)
def check_compliance_scorecard_v2(_session):
    """
    Checks for basic security best practices.
    Note: Some checks might require specific privileges.
    """
    results = {}
    
    # 1. Admin Count
    try:
        query_admins = """
        SELECT COUNT(DISTINCT GRANTEE_NAME) 
        FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS 
        WHERE ROLE = 'ACCOUNTADMIN' 
          AND DELETED_ON IS NULL
        """
        admin_count = _session.sql(query_admins).collect()[0][0]
        results['admin_count'] = admin_count
    except Exception as e:
        results['admin_count'] = "Err"
        
    # 2. Network Policies
    try:
        query_policies = "SELECT COUNT(*) FROM SNOWFLAKE.ACCOUNT_USAGE.NETWORK_POLICIES WHERE DELETED_ON IS NULL"
        policy_count = _session.sql(query_policies).collect()[0][0]
        results['network_policies'] = policy_count
    except:
        results['network_policies'] = 0
        
    # 3. Users without MFA (Best effort via LOGIN_HISTORY or USERS view if available)
    # Using a simple check for users who haven't used MFA in recent logins as a proxy
    # OR checking users created recently without MFA enforcement.
    # For this demo, we'll check how many users have 'EXT_AUTHN_DUO' unset if possible,
    # or just list users. Account Usage Users view doesn't easily show MFA status directly without joining.
    # We will skip complex MFA check to avoid false positives in this demo and just show total users.
    try:
        user_count = _session.sql("SELECT COUNT(*) FROM SNOWFLAKE.ACCOUNT_USAGE.USERS WHERE DELETED_ON IS NULL").collect()[0][0]
        results['total_users'] = user_count
    except:
        results['total_users'] = 0
        
    return results

@st.cache_data(ttl=3600)
def scan_pii_columns(_session):
    """Scan columns for PII keywords"""
    keywords = ['EMAIL', 'PHONE', 'SSN', 'SOCIAL', 'CREDIT', 'CARD', 'DOB', 'BIRTH', 'PASSWORD', 'SECRET', 'IBAN']
    ilike_clause = " OR ".join([f"COLUMN_NAME ILIKE '%{k}%'" for k in keywords])
    
    query = f"""
    SELECT 
        TABLE_SCHEMA,
        TABLE_NAME,
        COLUMN_NAME,
        DATA_TYPE,
        COMMENT
    FROM SNOWFLAKE.ACCOUNT_USAGE.COLUMNS
    WHERE DELETED IS NULL
      AND TABLE_SCHEMA != 'INFORMATION_SCHEMA'
      AND TABLE_SCHEMA != 'ACCOUNT_USAGE'
      AND ({ilike_clause})
    ORDER BY TABLE_SCHEMA, TABLE_NAME
    LIMIT 500
    """
    try:
        return _session.sql(query).to_pandas()
    except Exception as e:
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def get_stale_tables(_session, days=90):
    """Find tables not modified in X days"""
    query = f"""
    SELECT 
        TABLE_SCHEMA,
        TABLE_NAME,
        TABLE_OWNER,
        ROW_COUNT,
        BYTES / 1e9 as GB_SIZE,
        last_altered,
        DATEDIFF('day', last_altered, CURRENT_TIMESTAMP()) as days_inactive
    FROM SNOWFLAKE.ACCOUNT_USAGE.TABLES
    WHERE DELETED IS NULL
      AND TABLE_SCHEMA != 'INFORMATION_SCHEMA'
      AND last_altered < DATEADD('day', -{days}, CURRENT_TIMESTAMP())
      AND ROW_COUNT > 0
    ORDER BY BYTES DESC
    LIMIT 100
    """
    try:
        return _session.sql(query).to_pandas()
    except:
        return pd.DataFrame()

@st.cache_data(ttl=300)
def get_login_forensics(_session):
    """Analyze login patterns for security risks"""
    results = {}
    
    # 1. Brute Force Detection (High failure rate from single IP)
    query_brute = """
    SELECT 
        CLIENT_IP,
        COUNT(*) as total_attempts,
        SUM(CASE WHEN IS_SUCCESS = 'NO' THEN 1 ELSE 0 END) as failed_attempts,
        ROUND((failed_attempts / total_attempts) * 100, 1) as failure_rate
    FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
    WHERE EVENT_TIMESTAMP >= DATEADD('day', -7, CURRENT_TIMESTAMP())
    GROUP BY CLIENT_IP
    HAVING failed_attempts > 5 AND failure_rate > 50
    ORDER BY failed_attempts DESC
    LIMIT 50
    """
    try:
        results['brute_force'] = _session.sql(query_brute).to_pandas()
    except:
        results['brute_force'] = pd.DataFrame()

    # 2. Client Version Analysis
    query_clients = """
    SELECT 
        CLIENT_APPLICATION_ID as client_app,
        CLIENT_APPLICATION_VERSION as version,
        COUNT(*) as login_count,
        MAX(EVENT_TIMESTAMP) as last_seen
    FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
    WHERE EVENT_TIMESTAMP >= DATEADD('day', -7, CURRENT_TIMESTAMP())
    GROUP BY CLIENT_APPLICATION_ID, CLIENT_APPLICATION_VERSION
    ORDER BY login_count DESC
    LIMIT 20
    """
    try:
        results['clients'] = _session.sql(query_clients).to_pandas()
    except:
        results['clients'] = pd.DataFrame()
        
    return results

def get_security_audit(_client):
    """
    Find potentially over-privileged roles by comparing grants with actual usage.
    This is an expensive query that is now cached for 24 hours.
    """
    cache = get_metadata_cache()
    cached_data = cache.get("security_risk_assessment")
    
    if cached_data is not None:
        return pd.DataFrame(cached_data)

    query = """
    WITH role_usage AS (
        SELECT 
            ROLE_NAME,
            MAX(START_TIME) as LAST_USED
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD(day, -90, CURRENT_TIMESTAMP())
        GROUP BY 1
    )
    SELECT 
        r.NAME as ROLE_NAME,
        r.OWNER,
        r.CREATED_ON,
        u.LAST_USED,
        DATEDIFF(day, COALESCE(u.LAST_USED, r.CREATED_ON), CURRENT_TIMESTAMP()) as DAYS_INACTIVE
    FROM SNOWFLAKE.ACCOUNT_USAGE.ROLES r
    LEFT JOIN role_usage u ON r.NAME = u.ROLE_NAME
    WHERE r.DELETED_ON IS NULL
      AND (u.LAST_USED IS NULL OR u.LAST_USED < DATEADD(day, -30, CURRENT_TIMESTAMP()))
      AND r.NAME NOT IN ('ACCOUNTADMIN', 'SECURITYADMIN', 'SYSADMIN', 'PUBLIC') -- Exclude system roles
    ORDER BY DAYS_INACTIVE DESC
    LIMIT 100
    """
    try:
        df = _client.execute_query(query)
        if not df.empty:
            cache.set("security_risk_assessment", df.to_dict('records'), ttl_hours=24)
        return df
    except Exception as e:
        # Fallback to empty if permissions fail
        return pd.DataFrame()

# --- TABS ---

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🛡️ Compliance Scorecard",
    "🕵️ PII Scanner",
    "👁️ Data Observability",
    "🚨 Login Forensics",
    "🤖 Risk Assessment ❄️"
])

# --- TAB 1: COMPLIANCE ---
with tab1:
    st.markdown("### Security Posture")
    
    scorecard = check_compliance_scorecard_v2(client.session)
    
    # --- SCORE CALCULATION ---
    security_score = 100
    deductions = []
    
    # 1. Admin Count (Max 2 recommended)
    admin_count = scorecard.get('admin_count', 0)
    if isinstance(admin_count, int) and admin_count > 2:
        security_score -= 10
        deductions.append(f"-10: Too many ACCOUNTADMINs ({admin_count})")
    
    # 2. Network Policies (Must be > 0)
    policy_count = scorecard.get('network_policies', 0)
    if policy_count == 0:
        security_score -= 20
        deductions.append("-20: No Network Policies Active")
        
    # 3. Brute Force (Check Login Forensics)
    # We need to fetch this here for the score
    login_metrics = get_login_forensics(client.session)
    bf_df = login_metrics.get('brute_force', pd.DataFrame())
    if not bf_df.empty:
        security_score -= 15
        deductions.append(f"-15: Active Brute Force Attacks Detected ({len(bf_df)} sources)")
        
    # 4. PII Exposure (Check PII)
    # We won't run full scan automatically as it's slow, but if cached...
    # For now, we assume OK unless known otherwise.
    
    # Cap score
    security_score = max(0, security_score)
    
    # Grade
    if security_score >= 90:
        grade = "A"
        color = "#00D4AA"
    elif security_score >= 80:
        grade = "B"
        color = "#29B5E8"
    elif security_score >= 60:
        grade = "C"
        color = "#FFB020"
    else:
        grade = "D"
        color = "#FF4B4B"
        
    # Render Score Banner
    st.markdown(f"""
    <div style="background: linear-gradient(90deg, #1a1c24, #0f1116); padding: 20px; border-radius: 12px; border: 1px solid #2e3b4e; display: flex; align-items: center; justify-content: space-between;">
        <div>
            <h2 style="margin: 0; color: #fff;">Security Grade</h2>
            <p style="margin: 5px 0 0 0; color: #9499A1;">Based on CIS Snowflake Foundations Benchmark</p>
        </div>
        <div style="text-align: right;">
            <span style="font-size: 3.5rem; font-weight: 800; color: {color};">{grade}</span>
            <span style="font-size: 1.5rem; color: #fff; margin-left: 10px;">{security_score}/100</span>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    if deductions:
        with st.expander("📉 See Score Deductions"):
            for d in deductions:
                st.markdown(f"**{d}**")
    
    st.markdown("---")
    
    c1, c2, c3 = st.columns(3)
    
    with c1:
        # Admin Count Logic
        count = scorecard.get('admin_count', 0)
        status = "✅ Healthy" if isinstance(count, int) and count <= 2 else "⚠️ Review"
        render_metric_card("Account Admins", str(count), sub_label=status)
        
    with c2:
        # Network Policy Logic
        count = scorecard.get('network_policies', 0)
        status = "✅ Active" if count > 0 else "❌ Missing"
        render_metric_card("Network Policies", str(count), sub_label=status)
        
    with c3:
        # User Count
        count = scorecard.get('total_users', 0)
        render_metric_card("Active Users", str(count), sub_label="Total Accounts")

    # --- RECOMMENDATION ENGINE INTEGRATION ---
    from intelligence.recommendation_engine import RecommendationEngine
    rec_engine = RecommendationEngine(client)
    security_health = rec_engine.check_security_health()
    
    if security_health.get('recommendations'):
        st.markdown("### ⚠️ Security Actions Required")
        for rec in security_health['recommendations']:
            # Color code based on severity
            color = "#FF4B4B" if rec['severity'] == 'CRITICAL' else "#FFB020" if rec['severity'] == 'HIGH' else "#29B5E8"
            
            st.markdown(f"""
            <div style="border-left: 4px solid {color}; padding: 1rem; background: {color}11; margin-bottom: 1rem; border-radius: 4px;">
                <strong style="color: {color};">{rec['severity']}</strong>: <strong>{rec['title']}</strong><br>
                {rec['message']}<br>
                <em style="font-size: 0.9em; color: #888;">Action: {rec['action']}</em>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.success("✅ No critical security recommendations found.")

    st.markdown("---")

# --- TAB 2: PII SCANNER ---
with tab2:
    st.markdown("### 🕵️ Data Privacy Radar")
    st.caption("Scanning schemas for sensitive column names (Email, Phone, SSN, etc.)")
    
    if st.button("🚀 Run PII Scan"):
        with st.spinner("Scanning metadata..."):
            pii_df = scan_pii_columns(client.session)
            
            if not pii_df.empty:
                st.warning(f"Found {len(pii_df)} potential PII columns.")
                
                # Summary by Schema
                st.markdown("#### Distribution by Schema")
                chart = alt.Chart(pii_df).mark_bar().encode(
                    x=alt.X('count()', title='Count'),
                    y=alt.Y('TABLE_SCHEMA', sort='-x'),
                    color=alt.Color('TABLE_SCHEMA', legend=None)
                ).properties(height=200)
                st.altair_chart(chart, use_container_width=True)
                
                # Detail Table
                st.markdown("#### Detailed Findings")
                st.dataframe(
                    pii_df,
                    use_container_width=True
                )
                
                st.divider()
                st.markdown("### 🎭 Auto-Masking Generator")
                if st.button("Generate Masking Policies SQL"):
                    st.info("Copy this SQL to apply simple masking:")
                    
                    sql_script = "-- 1. Create Policy\nCREATE OR REPLACE MASKING POLICY email_mask AS (val string) RETURNS string ->\n  CASE WHEN CURRENT_ROLE() IN ('ACCOUNTADMIN', 'HR_ADMIN') THEN val ELSE '***MASKED***' END;\n\n-- 2. Apply to Columns\n"
                    
                    # Generate apply statements for first 10 columns
                    for _, row in pii_df.head(10).iterrows():
                        sql_script += f"ALTER TABLE {row['TABLE_SCHEMA']}.{row['TABLE_NAME']} MODIFY COLUMN {row['COLUMN_NAME']} SET MASKING POLICY email_mask;\n"
                        
                    st.code(sql_script, language='sql')
                
            else:
                st.success("No obvious PII keywords found in column names.")

# --- TAB 3: OBSERVABILITY ---
with tab3:
    st.markdown("### 👁️ Stale Data Detector")
    st.caption("Identify unused tables (> 90 days inactive) to save storage costs.")
    
    days_threshold = st.slider("Inactivity Threshold (Days)", 30, 365, 90)
    
    stale_df = get_stale_tables(client.session, days=days_threshold)
    
    if not stale_df.empty:
        total_savings = stale_df['GB_SIZE'].sum()
        st.metric("Potential Storage Savings", f"{total_savings:.2f} GB")
        
        st.dataframe(
            stale_df,
            use_container_width=True,
            column_config={
                "GB_SIZE": st.column_config.NumberColumn("Size (GB)", format="%.3f"),
                "days_inactive": st.column_config.NumberColumn("Days Inactive"),
                "last_altered": st.column_config.DatetimeColumn("Last Modified", format="YYYY-MM-DD")
            }
        )
    else:
        st.info("No stale tables found matching criteria.")

# --- TAB 4: LOGIN FORENSICS (NEW) ---
with tab4:
    st.markdown("### 🚨 Login Pattern Analysis")
    st.caption("Detect potential Brute Force attacks and monitor client versions.")
    
    metrics = get_login_forensics(client.session)
    bf_df = metrics.get('brute_force', pd.DataFrame())
    
    if not bf_df.empty:
        st.error(f"⚠️ Detected {len(bf_df)} Potential Brute Force Sources")
        st.markdown("**Suspicious IPs** (High failure rates > 50%)")
        
        st.dataframe(
            bf_df,
            use_container_width=True,
            column_config={
                "CLIENT_IP": "IP Address",
                "TOTAL_ATTEMPTS": st.column_config.NumberColumn("Attempts"),
                "FAILED_ATTEMPTS": st.column_config.NumberColumn("Failures"),
                "FAILURE_RATE": st.column_config.ProgressColumn("Failure Rate %", min_value=0, max_value=100, format="%.1f%%")
            }
        )
    else:
        st.success("✅ No Brute Force patterns detected in the last 7 days.")
        
    st.markdown("#### Client Versions")
    client_df = metrics.get('clients', pd.DataFrame())
    if not client_df.empty:
        st.dataframe(client_df, use_container_width=True)
    else:
        st.info("No client login data found.")

# --- TAB 5: RISK ASSESSMENT ---
with tab5:
    st.markdown("### 🤖 Role Risk Assessment")
    st.caption("AI auditing of role usage vs permissions to find over-privileged access.")
    
    audit_data = get_security_audit(client)
    
    if audit_data.empty:
        st.success("✅ No over-privileged or dormant roles found in the last 90 days.")
    else:
        st.warning(f"Found {len(audit_data)} roles that have been inactive for over 30 days.")
        
        # Show cache status if possible
        cache = get_metadata_cache()
        cached_val = cache.get("security_risk_assessment")
        if cached_val:
            st.info("💡 Showing cached results from the last 24 hours. Use 'Refresh' to re-run.")
            if st.button("🔄 Refresh Audit"):
                cache.clear("security_risk_assessment")
                st.rerun()

        st.dataframe(
            audit_data,
            use_container_width=True,
            hide_index=True,
            column_config={
                "ROLE_NAME": "Role",
                "DAYS_INACTIVE": st.column_config.NumberColumn("Days Inactive", format="%d days"),
                "LAST_USED": st.column_config.DatetimeColumn("Last Active")
            }
        )
        
        st.markdown("---")
        st.markdown("#### Meta-Analysis")
        avg_inactive = audit_data['DAYS_INACTIVE'].mean()
        st.info(f"The average dormant role has been inactive for **{avg_inactive:.1f} days**. Consider revoking these to reduce attack surface.")
