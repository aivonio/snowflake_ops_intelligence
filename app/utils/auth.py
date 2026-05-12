
import streamlit as st

def get_user_role():
    """Get the current user's role from session state."""
    # Ensure session state is initialized
    if 'user_context' not in st.session_state:
        return 'UNKNOWN'
        
    return st.session_state.user_context.get('role', 'UNKNOWN')

def is_admin():
    """Check if the current user is an Admin."""
    role = get_user_role()
    return role in ['ACCOUNTADMIN', 'SYSADMIN', 'SECURITYADMIN']

def verify_page_access(required_role='ADMIN'):
    """
    Strictly enforce page access control.
    Place this at the top of any sensitive page.
    """
    # If unauthenticated, stop
    if not st.session_state.get('authenticated', False):
        st.warning("Please log in to access this page.")
        st.stop()

    current_role = get_user_role()
    
    # Define role hierarchy basics
    # For now, just check if ADMIN is required and user has it
    if required_role == 'ADMIN':
        if not is_admin():
            st.error(f"⛔ Access Denied: This page requires ADMIN privileges. Your role: {current_role}")
            st.info("Please contact your Snowflake Account Administrator if you believe this is an error.")
            st.stop()
            
    # Add more role checks here if needed
    return True
