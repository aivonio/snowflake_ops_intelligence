"""
Notification Service for Snowflake Ops & Intelligence
Handles sending emails, webhooks, and Slack/Teams messages via Snowflake's
native NOTIFICATION INTEGRATION and SYSTEM$SEND_EMAIL.
"""
import json
import time
import logging
from typing import Optional, Dict, List, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self, client):
        self.client = client
        self.email_integration_name = "SNOWFLAKE_OPS_EMAIL_INT"

    # ── Email ──

    def send_email(self, recipients: list, subject: str, content: str) -> Tuple[bool, str]:
        """Send email via Snowflake SYSTEM$SEND_EMAIL."""
        if not recipients:
            return False, "No recipients provided"
        safe_subject = subject.replace("'", "''")
        safe_content = content.replace("'", "''")
        recipient_str = ",".join(r.strip() for r in recipients)
        try:
            self.client.execute_query(f"""
                CALL SYSTEM$SEND_EMAIL(
                    '{self.email_integration_name}',
                    '{recipient_str}',
                    '{safe_subject}',
                    '{safe_content}'
                )
            """)
            return True, "Email sent"
        except Exception as e:
            return False, str(e)

    # ── Universal dispatcher with retry ──

    def send_with_retry(self, channel_type: str, config: dict,
                        title: str, message: str,
                        max_retries: int = 3) -> Tuple[bool, str]:
        """Send notification with exponential-backoff retry.

        Args:
            channel_type: EMAIL, SLACK, TEAMS, PAGERDUTY, WEBHOOK
            config: Channel-specific config dict (recipients, integration_name, etc.)
            title: Notification title/subject
            message: Notification body
            max_retries: Retry attempts (default 3)

        Returns:
            (success, status_message)
        """
        last_error = ""
        for attempt in range(max_retries):
            try:
                ok, msg = self._dispatch(channel_type, config, title, message)
                if ok:
                    self._log_delivery(channel_type, title, "DELIVERED")
                    return True, msg
                last_error = msg
            except Exception as e:
                last_error = str(e)

            if attempt < max_retries - 1:
                time.sleep(min(2 ** attempt, 10))

        self._log_delivery(channel_type, title, "FAILED", last_error)
        return False, f"Failed after {max_retries} attempts: {last_error}"

    def _dispatch(self, channel_type: str, config: dict,
                  title: str, message: str) -> Tuple[bool, str]:
        """Route to the correct delivery method."""
        ct = channel_type.upper()

        if ct == 'EMAIL':
            recipients = config.get('recipients', [])
            if isinstance(recipients, str):
                recipients = [r.strip() for r in recipients.split(',')]
            return self.send_email(recipients, title, message)

        if ct in ('SLACK', 'TEAMS', 'PAGERDUTY', 'WEBHOOK'):
            integration = config.get('integration_name', '')
            if not integration:
                return False, f"No integration_name in config for {ct}"
            return self._send_via_integration(integration, title, message, ct)

        if ct == 'DASHBOARD':
            self._log_delivery('DASHBOARD', title, "LOGGED")
            return True, "Logged to dashboard"

        return False, f"Unsupported channel: {ct}"

    def _send_via_integration(self, integration_name: str,
                              title: str, message: str,
                              channel_type: str) -> Tuple[bool, str]:
        """Send via Snowflake NOTIFICATION INTEGRATION (webhook type)."""
        safe_msg = f"{title}: {message}".replace("'", "''")[:4000]
        try:
            self.client.execute_query(f"""
                SELECT SYSTEM$SEND_NOTIFICATION(
                    '{integration_name}',
                    '{safe_msg}'
                )
            """)
            return True, f"Sent via {integration_name}"
        except Exception as e:
            error = str(e).lower()
            if 'does not exist' in error or 'not found' in error:
                return False, f"Integration '{integration_name}' not found. Create it in Settings > Automation."
            return False, str(e)

    # ── Message formatting ──

    @staticmethod
    def format_slack_message(title: str, message: str,
                             severity: str = 'INFO',
                             fields: Optional[Dict] = None) -> str:
        """Format a rich Slack message payload."""
        severity_icons = {
            'CRITICAL': ':rotating_light:',
            'WARNING': ':warning:',
            'ERROR': ':x:',
            'INFO': ':information_source:',
        }
        icon = severity_icons.get(severity.upper(), ':bell:')
        ts = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')

        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": f"{icon} {title}"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": message}},
        ]

        if fields:
            field_blocks = []
            for k, v in fields.items():
                field_blocks.append({"type": "mrkdwn", "text": f"*{k}:*\n{v}"})
            blocks.append({"type": "section", "fields": field_blocks[:10]})

        blocks.append({"type": "context", "elements": [
            {"type": "mrkdwn", "text": f"Snowflake Ops Intelligence | {ts}"}
        ]})

        return json.dumps({"blocks": blocks})

    @staticmethod
    def format_teams_message(title: str, message: str,
                             severity: str = 'INFO') -> str:
        """Format a Microsoft Teams Adaptive Card payload."""
        colors = {'CRITICAL': 'attention', 'WARNING': 'warning',
                  'ERROR': 'attention', 'INFO': 'default'}
        color = colors.get(severity.upper(), 'default')

        card = {
            "type": "message",
            "attachments": [{
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {"type": "TextBlock", "text": title, "weight": "Bolder",
                         "size": "Medium", "style": color},
                        {"type": "TextBlock", "text": message, "wrap": True},
                        {"type": "TextBlock", "text": datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'),
                         "size": "Small", "isSubtle": True},
                    ]
                }
            }]
        }
        return json.dumps(card)

    # ── Delivery logging ──

    def _log_delivery(self, channel: str, message: str,
                      status: str, error: Optional[str] = None):
        """Log notification attempt to NOTIFICATIONS_LOG."""
        safe_msg = message[:400].replace("'", "''")
        safe_err = (error or '')[:400].replace("'", "''")
        try:
            self.client.execute_query(f"""
                INSERT INTO APP_CONTEXT.NOTIFICATIONS_LOG
                (LEVEL, MESSAGE, CHANNEL)
                VALUES ('{status}', '{safe_msg} | {safe_err}', '{channel}')
            """, log=False)
        except Exception:
            logger.debug("Failed to log notification delivery")

    # ── Setup SQL generation ──

    def generate_setup_sql(self, allowed_recipients: list) -> str:
        """Generate the SQL needed to set up the email integration."""
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
