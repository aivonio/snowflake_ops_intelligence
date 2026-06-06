"""
PostHog Analytics Wrapper for SnowOps Intelligence
===================================================
Server-side event tracking for the Streamlit app running inside Snowflake.

Requires:
  1. External Access Integration (setup/setup_posthog.sql)
  2. PostHog API key stored in APP_CONTEXT.PLATFORM_SETTINGS
  3. `posthog` package in environment.yml (or fallback to `requests`)

Usage:
  from utils.analytics import track_page_view, track_feature_use

  track_page_view("Cost Intelligence")
  track_feature_use("export_excel", {"page": "Cost Intelligence", "rows": 500})
"""

import streamlit as st
import hashlib
import datetime
import json
import logging

logger = logging.getLogger(__name__)

# ── PostHog Client (Lazy Init) ──

_posthog_client = None
_posthog_init_attempted = False


def _get_posthog():
    """Lazy-initialize PostHog client. Returns None if unavailable.
    
    API key is read ONLY from Snowflake's PLATFORM_SETTINGS table.
    This ensures the key is never exposed in source code on GitHub.
    Users configure it once via: setup/setup_posthog.sql
    
    Respects the TELEMETRY_ENABLED setting — if set to FALSE, returns None.
    """
    global _posthog_client, _posthog_init_attempted

    if _posthog_init_attempted:
        return _posthog_client

    _posthog_init_attempted = True

    try:
        import posthog as ph

        api_key = None
        host = "https://us.i.posthog.com"
        telemetry_enabled = True  # Default to enabled if setting not found

        try:
            client = st.session_state.get("snowflake_client")
            if client and client.session:
                result = client.session.sql(
                    "SELECT SETTING_KEY, SETTING_VALUE FROM APP_CONTEXT.PLATFORM_SETTINGS "
                    "WHERE SETTING_KEY IN ('POSTHOG_API_KEY', 'POSTHOG_HOST', 'TELEMETRY_ENABLED')"
                ).collect()
                for row in result:
                    key, val = row[0], row[1]
                    if key == "POSTHOG_API_KEY":
                        api_key = val
                    elif key == "POSTHOG_HOST":
                        host = val
                    elif key == "TELEMETRY_ENABLED":
                        telemetry_enabled = val.upper().strip() not in ("FALSE", "0", "NO", "OFF")
        except Exception:
            pass

        # Respect user's telemetry preference
        if not telemetry_enabled:
            logger.info("Telemetry disabled by user (TELEMETRY_ENABLED=FALSE) — analytics off")
            return None

        if not api_key:
            logger.info("PostHog API key not configured in PLATFORM_SETTINGS — analytics disabled")
            return None

        ph.api_key = api_key
        ph.host = host
        ph.debug = False
        ph.on_error = lambda e, items: None  # Silence errors

        _posthog_client = ph
        logger.info("PostHog initialized successfully")
        return ph

    except ImportError:
        logger.info("PostHog SDK not available — analytics disabled")
        return None
    except Exception as e:
        logger.warning(f"PostHog init failed: {e}")
        return None


def _get_user_id():
    """Generate a consistent anonymous user ID from Snowflake session context."""
    try:
        client = st.session_state.get("snowflake_client")
        if client and client.session:
            user = client.session.sql("SELECT CURRENT_USER()").collect()[0][0]
            account = client.session.sql("SELECT CURRENT_ACCOUNT()").collect()[0][0]
            return hashlib.sha256(f"{account}:{user}".encode()).hexdigest()[:16]
    except Exception:
        pass
    return "anonymous"


def _get_context():
    """Get common context properties for all events.
    
    The 'source' field allows differentiation between Streamlit app 
    and website events in the PostHog dashboard.
    """
    ctx = {
        "source": "streamlit_app",
        "platform": "streamlit_in_snowflake",
        "app": "snowops_intelligence",
        "timestamp": datetime.datetime.utcnow().isoformat(),
    }
    try:
        client = st.session_state.get("snowflake_client")
        if client and client.session:
            ctx["account"] = client.session.sql("SELECT CURRENT_ACCOUNT()").collect()[0][0]
            ctx["role"] = client.session.sql("SELECT CURRENT_ROLE()").collect()[0][0]
            ctx["warehouse"] = client.session.sql("SELECT CURRENT_WAREHOUSE()").collect()[0][0]
    except Exception:
        pass
    return ctx


# ── Public API ──

def track_page_view(page_name: str, properties: dict = None):
    """Track a page view event."""
    ph = _get_posthog()
    if not ph:
        return

    try:
        props = {
            "page_name": page_name,
            **_get_context(),
            **(properties or {}),
        }
        ph.capture(_get_user_id(), "page_view", props)
    except Exception:
        pass  # Never let analytics break the app


def track_feature_use(feature_name: str, properties: dict = None):
    """Track when a user uses a specific feature."""
    ph = _get_posthog()
    if not ph:
        return

    try:
        props = {
            "feature": feature_name,
            **_get_context(),
            **(properties or {}),
        }
        ph.capture(_get_user_id(), "feature_use", props)
    except Exception:
        pass


def track_export(export_type: str, page: str = "", row_count: int = 0):
    """Track data export events."""
    ph = _get_posthog()
    if not ph:
        return

    try:
        props = {
            "export_type": export_type,
            "page": page,
            "row_count": row_count,
            **_get_context(),
        }
        ph.capture(_get_user_id(), "data_export", props)
    except Exception:
        pass


def track_error(error_type: str, error_message: str, page: str = ""):
    """Track error events."""
    ph = _get_posthog()
    if not ph:
        return

    try:
        props = {
            "error_type": error_type,
            "error_message": error_message[:500],
            "page": page,
            **_get_context(),
        }
        ph.capture(_get_user_id(), "error", props)
    except Exception:
        pass


def identify_user():
    """Identify the current user with their Snowflake context."""
    ph = _get_posthog()
    if not ph:
        return

    try:
        user_id = _get_user_id()
        ctx = _get_context()
        ph.identify(user_id, {
            "platform": ctx.get("platform"),
            "account": ctx.get("account"),
            "role": ctx.get("role"),
        })
    except Exception:
        pass


def track_session_start():
    """Track session start — call once when app loads."""
    ph = _get_posthog()
    if not ph:
        return

    if not st.session_state.get("_posthog_session_tracked"):
        try:
            identify_user()
            props = _get_context()
            ph.capture(_get_user_id(), "session_start", props)
            st.session_state["_posthog_session_tracked"] = True
        except Exception:
            pass
