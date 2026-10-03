# Health check utility in PowerShell
$BaseUrl = if ($env:OPSPILOT_URL) { $env:OPSPILOT_URL } else { "http://localhost:8000" }
$TargetUrl = if ($env:TARGET_URL) { $env:TARGET_URL } else { "http://localhost:8080" }

Write-Host "=== OpsPilot Platform Health ===" -ForegroundColor Cyan
try {
    $h = Invoke-RestMethod -Uri "$BaseUrl/health" -Method Get
    $h | ConvertTo-Json
} catch {
    Write-Host "Failed to reach OpsPilot at $BaseUrl" -ForegroundColor Red
}

Write-Host ""
Write-Host "=== Component Details ===" -ForegroundColor Cyan
try {
    $comp = Invoke-RestMethod -Uri "$BaseUrl/api/v1/health" -Method Get
    $comp | ConvertTo-Json -Depth 4
} catch {
    Write-Host "Failed to reach OpsPilot component health" -ForegroundColor Red
}

Write-Host ""
Write-Host "=== Target payment-api Health ===" -ForegroundColor Cyan
try {
    $t = Invoke-RestMethod -Uri "$TargetUrl/health" -Method Get
    $t | ConvertTo-Json
} catch {
    Write-Host "Target payment-api is unhealthy or unreachable ($($_.Exception.Message))" -ForegroundColor Red
}
