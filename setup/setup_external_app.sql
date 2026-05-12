-- EXTERNAL APP SETUP SCRIPT (SaaS / Standalone Deployment)
-- Run this as ACCOUNTADMIN if you want to allow users to login to this app hosted externally.

USE ROLE ACCOUNTADMIN;

-- 1. Create the Security Integration (OAuth)
-- Replace "YOUR_APP_URL" with your actual hosted URL (e.g., https://my-snowflake-ops.onrender.com)
-- If running locally, use http://localhost:8501

CREATE OR REPLACE SECURITY INTEGRATION SNOWFLAKE_OPS_OAUTH
  TYPE = OAUTH
  ENABLED = TRUE
  OAUTH_CLIENT = CUSTOM
  OAUTH_CLIENT_TYPE = 'PUBLIC' -- Use 'CONFIDENTIAL' if you can store client_secret securely (e.g. backend server)
  OAUTH_REDIRECT_URI = 'http://localhost:8501' -- CHANGE THIS to your deployed URL
  OAUTH_ISSUE_REFRESH_TOKENS = TRUE
  OAUTH_REFRESH_TOKEN_VALIDITY = 86400 -- 24 hours
  BLOCKED_ROLES_LIST = ('ORGADMIN') -- Security best practice
;

-- 2. Network Policy (Optional but Recommended)
-- If you want to restrict access to only your App's IP address
-- CREATE NETWORK POLICY APP_ALLOWLIST ALLOWED_IP_LIST = ('YOUR_APP_IP');
-- ALTER SECURITY INTEGRATION SNOWFLAKE_OPS_OAUTH SET NETWORK_POLICY = APP_ALLOWLIST;

-- 3. Get the Client ID & Secret
SELECT SYSTEM$SHOW_OAUTH_CLIENT_SECRETS('SNOWFLAKE_OPS_OAUTH');

-- INSTRUCTIONS FOR CONFIGURATION:
-- 1. Copy 'OAUTH_CLIENT_ID' and 'OAUTH_CLIENT_SECRET' from the output above.
-- 2. Add them to your App's secrets.toml (or Environment Variables):
--
-- [snowflake]
-- account = "your-account-id"
-- warehouse = "compute_wh" (Default warehouse for login checks)
--
-- [oauth]
-- client_id = "..."
-- client_secret = "..."
-- redirect_uri = "http://localhost:8501" 

-- 4. Setup User Roles (Preferred over ACCOUNTADMIN)
-- Create roles that allow users to access the app's full features securely

CREATE ROLE IF NOT EXISTS SNOWFLAKE_OPS_ADMIN;
CREATE ROLE IF NOT EXISTS SNOWFLAKE_OPS_USER;

-- Grant Admin Privileges (View Cost/Usage)
GRANT DATABASE ROLE SNOWFLAKE.GOVERNANCE_VIEWER TO ROLE SNOWFLAKE_OPS_ADMIN;
GRANT DATABASE ROLE SNOWFLAKE.USAGE_VIEWER TO ROLE SNOWFLAKE_OPS_ADMIN;

-- Grant Warehouse Usage (Replace 'COMPUTE_WH' with your actual warehouse)
GRANT USAGE ON WAREHOUSE COMPUTE_WH TO ROLE SNOWFLAKE_OPS_ADMIN;
GRANT USAGE ON WAREHOUSE COMPUTE_WH TO ROLE SNOWFLAKE_OPS_USER;

-- 5. Assign Roles to Users
-- GRANT ROLE SNOWFLAKE_OPS_ADMIN TO USER <user_name>;
-- GRANT ROLE SNOWFLAKE_OPS_USER TO USER <user_name>;
