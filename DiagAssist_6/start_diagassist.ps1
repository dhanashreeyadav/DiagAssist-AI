# ==============================
# DiagAssist One-Click Launcher
# Google ADK + Vertex AI
# ==============================

Write-Host ""
Write-Host "🚗 Starting DiagAssist AI..."
Write-Host ""

# Set Vertex AI environment
$env:GOOGLE_CLOUD_PROJECT = "diagassit"
$env:GOOGLE_CLOUD_LOCATION = "us-central1"
$env:GOOGLE_GENAI_USE_VERTEXAI = "TRUE"

# Add Google Cloud SDK to PATH
$env:Path += ";C:\Users\HP\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin"

# Verify ADC
Write-Host "Checking Google ADC..."
gcloud auth application-default print-access-token > $null

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "❌ Google ADC authentication failed!"
    Write-Host "Run: gcloud auth application-default login"
    exit
}

Write-Host "✅ Vertex AI authentication successful"

# Move to project folder
Set-Location $PSScriptRoot


# Check database
if (!(Test-Path ".\database\dtc_database.db")) {
    Write-Host "Database missing. Creating..."
    python database.py
}


Write-Host ""
Write-Host "🚀 Launching DiagAssist Web UI..."
Write-Host ""

# Start Streamlit
streamlit run streamlit_app.py