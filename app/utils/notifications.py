"""
Notification Service for Snowflake Ops & Intelligence
Handles sending emails and webhooks via Snowflake's system functions.
"""
import streamlit as st
import json

class NotificationService:
    def __init__(self, client):
        self.client = client
        self.email_integration_name = "SNOWFLAKE_OPS_EMAIL_INT" # Default name

    def send_email(self, recipients: list, subject: str, content: str):
        """
        Send an email using Snowflake's SYSTEM$SEND_EMAIL
        Requires a NOTIFICATION INTEGRATION to be configured.
        """
        if not recipients:
            return False, "No recipients provided"

        # Format inputs
        recipient_str = ",".join([f"'{r.strip()}'" for r in recipients])
        
        # Escape single quotes in content
        safe_subject = subject.replace("'", "''")
        safe_content = content.replace("'", "''")
        
        try:
            query = f"""
            CALL SYSTEM$SEND_EMAIL(
                '{self.email_integration_name}',
                '{recipient_str}',
                '{safe_subject}',
                '{safe_content}'
            )
            """
            self.client.execute_query(query)
            return True, "Email sent successfully"
        except Exception as e:
            error_msg = str(e)
            if "integration" in error_msg.lower() and "not found" in error_msg.lower():
                return False, f"Integration '{self.email_integration_name}' not found. Please set it up in Settings."
            return False, error_msg

    def generate_setup_sql(self, allowed_recipients: list) -> str:
        """Generate the SQL needed to set up the integration"""
        recipients_str = ", ".join([f"'{r.strip()}'" for r in allowed_recipients])
        return f"""
-- 1. Create Email Notification Integration (Run as ACCOUNTADMIN)
CREATE OR REPLACE NOTIFICATION INTEGRATION {self.email_integration_name}
    TYPE = EMAIL
    ENABLED = TRUE
    ALLOWED_RECIPIENTS = ({recipients_str});

-- 2. Grant usage to the app/role (if running as a specific role)
-- GRANT USAGE ON INTEGRATION {self.email_integration_name} TO ROLE SYSADMIN;
"""
