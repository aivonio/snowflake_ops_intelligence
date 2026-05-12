-- ==============================================================================
-- POSTHOG ANALYTICS — EXTERNAL ACCESS INTEGRATION
-- ==============================================================================
-- Run as ACCOUNTADMIN to allow the Streamlit app to send analytics events
-- to PostHog (https://us.i.posthog.com).
--
-- This is OPTIONAL. The app will work without it — analytics simply won't fire.
-- ==============================================================================

USE ROLE ACCOUNTADMIN;

-- 1. Network Rule — Allow outbound HTTPS to PostHog servers
CREATE OR REPLACE NETWORK RULE SNOWFLAKE_OPS_INTELLIGENCE.APP_CONTEXT.POSTHOG_NETWORK_RULE
  TYPE = HOST_PORT
  MODE = EGRESS
  VALUE_LIST = (
    'us.i.posthog.com:443',
    'us-assets.i.posthog.com:443',
    'app.posthog.com:443'
  );

-- 2. External Access Integration — Link the network rule
CREATE OR REPLACE EXTERNAL ACCESS INTEGRATION POSTHOG_ACCESS_INTEGRATION
  ALLOWED_NETWORK_RULES = (SNOWFLAKE_OPS_INTELLIGENCE.APP_CONTEXT.POSTHOG_NETWORK_RULE)
  ENABLED = TRUE
  COMMENT = 'Allow SnowOps Intelligence to send analytics to PostHog';

-- 3. Store PostHog API Key in platform settings (so the app can read it)
INSERT INTO SNOWFLAKE_OPS_INTELLIGENCE.APP_CONTEXT.PLATFORM_SETTINGS 
  (SETTING_KEY, SETTING_VALUE, DESCRIPTION)
SELECT 'POSTHOG_API_KEY', 'phc_W89NRd31nyEXwMDNHgvW1kxycaKPLq2SqKjm9RuKpzH', 'PostHog project API key for analytics tracking'
WHERE NOT EXISTS (
  SELECT 1 FROM SNOWFLAKE_OPS_INTELLIGENCE.APP_CONTEXT.PLATFORM_SETTINGS 
  WHERE SETTING_KEY = 'POSTHOG_API_KEY'
);

INSERT INTO SNOWFLAKE_OPS_INTELLIGENCE.APP_CONTEXT.PLATFORM_SETTINGS 
  (SETTING_KEY, SETTING_VALUE, DESCRIPTION)
SELECT 'POSTHOG_HOST', 'https://us.i.posthog.com', 'PostHog API host endpoint'
WHERE NOT EXISTS (
  SELECT 1 FROM SNOWFLAKE_OPS_INTELLIGENCE.APP_CONTEXT.PLATFORM_SETTINGS 
  WHERE SETTING_KEY = 'POSTHOG_HOST'
);

-- 4. Enable Telemetry Toggle
INSERT INTO SNOWFLAKE_OPS_INTELLIGENCE.APP_CONTEXT.PLATFORM_SETTINGS 
  (SETTING_KEY, SETTING_VALUE, DESCRIPTION)
SELECT 'TELEMETRY_ENABLED', 'TRUE', 'Enable anonymous usage telemetry. Disable anytime in Settings.'
WHERE NOT EXISTS (
  SELECT 1 FROM SNOWFLAKE_OPS_INTELLIGENCE.APP_CONTEXT.PLATFORM_SETTINGS 
  WHERE SETTING_KEY = 'TELEMETRY_ENABLED'
);

-- 5. When deploying the Streamlit app, attach the external access integration:
-- ALTER STREAMLIT SNOWFLAKE_OPS_INTELLIGENCE.APP_ANALYTICS.SNOWFLAKE_OPS_INTELLIGENCE
--   SET EXTERNAL_ACCESS_INTEGRATIONS = (POSTHOG_ACCESS_INTEGRATION);

-- ==============================================================================
-- SETUP COMPLETE
-- ==============================================================================
SELECT '✅ PostHog analytics integration configured!' AS STATUS;
