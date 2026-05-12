-- Run this script as ACCOUNTADMIN to configure OAuth for the Streamlit App

USE ROLE ACCOUNTADMIN;

-- 1. Create the Security Integration
-- Replace "YOUR_STREAMLIT_URL" with your actual app URL (e.g., http://localhost:8501 or https://myapp.streamlit.app)
CREATE OR REPLACE SECURITY INTEGRATION STREAMLIT_OAUTH_INTEGRATION
  TYPE = OAUTH
  ENABLED = TRUE
  OAUTH_CLIENT = CUSTOM
  OAUTH_CLIENT_TYPE = 'PUBLIC' -- Use 'CONFIDENTIAL' if you can store client_secret securely
  OAUTH_REDIRECT_URI = 'http://localhost:8501' -- CHANGE THIS to your deployed URL
  OAUTH_ISSUE_REFRESH_TOKENS = TRUE
  OAUTH_REFRESH_TOKEN_VALIDITY = 86400 -- 24 hours
  BLOCKED_ROLES_LIST = ('ORGADMIN') -- Security best practice
;

-- 2. Get the Client ID (You'll need this for your secrets.toml or environment variables)
SELECT SYSTEM$SHOW_OAUTH_CLIENT_SECRETS('STREAMLIT_OAUTH_INTEGRATION');

-- Instructions:
-- 1. Run this script in a Snowflake Worksheet.
-- 2. Copy the "OAUTH_CLIENT_ID" from the output of the SELECT statement.
-- 3. Add to your .streamlit/secrets.toml:
--    [oauth]
--    client_id = "YOUR_CLIENT_ID"
--    client_secret = "YOUR_CLIENT_SECRET" (Only if PUBLIC is changed to CONFIDENTIAL)
--    redirect_uri = "http://localhost:8501"
