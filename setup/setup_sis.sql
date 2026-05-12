-- =============================================================================================
-- 🚀 SETUP SCRIPT: Standard Streamlit in Snowflake (SiS)
-- =============================================================================================
-- Use this script for Scenarios 1 & 3:
-- 1. Normal Streamlit App
-- 3. App managed on Stages
--
-- RUN AS: ACCOUNTADMIN or a role with CREATE STREAMLIT privileges
-- =============================================================================================

-- 1. Create Infrastructure
CREATE DATABASE IF NOT EXISTS SNOWFLAKE_OPS_APP_DATA;
CREATE SCHEMA IF NOT EXISTS SNOWFLAKE_OPS_APP_DATA.APP_ANALYTICS;
CREATE SCHEMA IF NOT EXISTS SNOWFLAKE_OPS_APP_DATA.APP_CONTEXT;

-- 2. Create Stage for Files
CREATE STAGE IF NOT EXISTS SNOWFLAKE_OPS_APP_DATA.APP_ANALYTICS.APP_STAGE
  DIRECTORY = (ENABLE = TRUE);

-- 3. Required Tables (if not initialized via Settings page)
CREATE TABLE IF NOT EXISTS SNOWFLAKE_OPS_APP_DATA.APP_ANALYTICS.QUERY_BENCHMARK (
    BENCHMARK_ID NUMBER AUTOINCREMENT PRIMARY KEY,
    QUERY_TEXT VARCHAR,
    QUERY_HASH VARCHAR,
    RUN_TYPE VARCHAR,
    PREDICTED_COST_CREDITS FLOAT,
    ACTUAL_COST_CREDITS FLOAT,
    RUN_TIMESTAMP TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- INSTRUCTION: Upload the following to @SNOWFLAKE_OPS_APP_DATA.APP_ANALYTICS.APP_STAGE/
-- - streamlit_app.py
-- - environment.yml
-- - pages/ (folder)
-- - utils/ (folder)
-- - intelligence/ (folder)

-- 4. Create the Streamlit Object
CREATE STREAMLIT IF NOT EXISTS SNOWFLAKE_OPS_APP_DATA.APP_ANALYTICS.SNOWFLAKE_OPS_INTELLIGENCE
  ROOT_LOCATION = '@SNOWFLAKE_OPS_APP_DATA.APP_ANALYTICS.APP_STAGE'
  MAIN_FILE = 'streamlit_app.py'
  QUERY_WAREHOUSE = 'COMPUTE_WH'; -- Change to your preferred warehouse

-- 5. Grant Permissions (for non-accountadmins)
-- GRANT USAGE ON DATABASE SNOWFLAKE_OPS_APP_DATA TO ROLE my_role;
-- GRANT USAGE ON SCHEMA SNOWFLAKE_OPS_APP_DATA.APP_ANALYTICS TO ROLE my_role;
-- GRANT ALL PRIVILEGES ON STREAMLIT SNOWFLAKE_OPS_APP_DATA.APP_ANALYTICS.SNOWFLAKE_OPS_INTELLIGENCE TO ROLE my_role;
