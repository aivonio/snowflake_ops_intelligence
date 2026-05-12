# Snowflake Ops Intelligence Platform - Deployment Script
# Run this script from the project root directory

param(
    [switch]$Initialize,
    [switch]$Deploy,
    [switch]$RunLocal,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

function Show-Help {
    Write-Host @"
Snowflake Ops Intelligence Platform - Deployment Script

Usage: .\deploy.ps1 [-Initialize] [-Deploy] [-RunLocal] [-Help]

Options:
  -Initialize   Initialize database and run setup.sql
  -Deploy       Deploy as Snowflake Native App
  -RunLocal     Run Streamlit app locally for development
  -Help         Show this help message

Examples:
  .\deploy.ps1 -Initialize    # Set up database first time
  .\deploy.ps1 -RunLocal      # Run locally for development
  .\deploy.ps1 -Deploy        # Deploy to Snowflake
"@
}

function Initialize-Database {
    Write-Host "
=== Initializing Snowflake Database ===" -ForegroundColor Cyan
    
    # Check if snow CLI is installed
    if (!(Get-Command "snow" -ErrorAction SilentlyContinue)) {
        Write-Host "Snowflake CLI not found. Installing..." -ForegroundColor Yellow
        pip install snowflake-cli-labs
    }
    
    # Test connection
    Write-Host "Testing Snowflake connection..." -ForegroundColor Yellow
    snow connection test
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Connection test failed. Please run 'snow connection add' first." -ForegroundColor Red
        exit 1
    }
    
    # Run setup SQL
    Write-Host "Running setup.sql..." -ForegroundColor Yellow
    $setupSql = Get-Content -Path ".\setup.sql" -Raw
    snow sql -q $setupSql
    
    Write-Host "
[SUCCESS] Database initialized successfully!" -ForegroundColor Green
}

function Deploy-NativeApp {
    Write-Host "
=== Deploying Snowflake Native App ===" -ForegroundColor Cyan
    
    # Check if snow CLI is installed
    if (!(Get-Command "snow" -ErrorAction SilentlyContinue)) {
        Write-Host "Snowflake CLI not found. Installing..." -ForegroundColor Yellow
        pip install snowflake-cli-labs
    }
    
    # Deploy the app
    Write-Host "Deploying application..." -ForegroundColor Yellow
    snow app run
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "
[SUCCESS] Application deployed successfully!" -ForegroundColor Green
        Write-Host "Access your app in Snowsight under Apps section." -ForegroundColor Cyan
    } else {
        Write-Host "
[ERROR] Deployment failed." -ForegroundColor Red
        exit 1
    }
}

function Run-Local {
    Write-Host "
=== Running Streamlit Locally ===" -ForegroundColor Cyan
    
    # Check if secrets file exists
    $secretsPath = ".\app\.streamlit\secrets.toml"
    if (!(Test-Path $secretsPath)) {
        Write-Host "Creating secrets.toml from template..." -ForegroundColor Yellow
        
        $templatePath = ".\app\.streamlit\secrets.toml.template"
        if (Test-Path $templatePath) {
            Copy-Item $templatePath $secretsPath
            Write-Host "Created $secretsPath - Please edit with your credentials!" -ForegroundColor Yellow
            Write-Host "Opening secrets file..." -ForegroundColor Yellow
            notepad $secretsPath
            exit 0
        } else {
            Write-Host "Template not found. Please create secrets.toml manually." -ForegroundColor Red
            exit 1
        }
    }
    
    # Install dependencies
    Write-Host "Installing Python dependencies..." -ForegroundColor Yellow
    pip install streamlit snowflake-snowpark-python plotly pandas altair openpyxl xlsxwriter sqlparse
    
    # Run streamlit
    Write-Host "Starting Streamlit..." -ForegroundColor Green
    Set-Location -Path ".\app"
    streamlit run streamlit_app.py
}

# Main execution
if ($Help) {
    Show-Help
} elseif ($Initialize) {
    Initialize-Database
} elseif ($Deploy) {
    Deploy-NativeApp
} elseif ($RunLocal) {
    Run-Local
} else {
    Show-Help
}
