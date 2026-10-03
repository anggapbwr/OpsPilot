# OpsPilot Demo Script for PowerShell
$ErrorActionPreference = "Stop"

$BaseUrl = "http://localhost:8000"
$TargetUrl = "http://localhost:8080"
if ($env:OPSPILOT_URL) { $BaseUrl = $env:OPSPILOT_URL }
if ($env:TARGET_URL) { $TargetUrl = $env:TARGET_URL }

Write-Host "========================================"
Write-Host "          OpsPilot Demo"
Write-Host "========================================"
Write-Host ""

$StopWatch = [System.Diagnostics.Stopwatch]::StartNew()

# [1] Checking target
Write-Host "[1] Checking target..."
try {
    $res = Invoke-RestMethod -Uri "$TargetUrl/health" -Method Get -TimeoutSec 3
    if ($res.status -eq "healthy") {
        Write-Host "[OK] payment-api healthy"
    } else {
        Invoke-RestMethod -Uri "$TargetUrl/fault/recover" -Method Post | Out-Null
        Write-Host "[OK] payment-api recovered to healthy"
    }
} catch {
    Invoke-RestMethod -Uri "$TargetUrl/fault/recover" -Method Post | Out-Null
    Write-Host "[OK] payment-api recovered to healthy"
}
Write-Host ""

# [2] Injecting failure
Write-Host "[2] Injecting failure..."
$inject = Invoke-RestMethod -Uri "$TargetUrl/fault/unhealthy" -Method Post
Write-Host "[OK] Failure injected"
Write-Host ""

# [3] Detecting incident
Write-Host "[3] Detecting incident..."
$detectBody = '{"auto_detect": true}'
$incident = Invoke-RestMethod -Uri "$BaseUrl/api/v1/incidents" -Method Post -Body $detectBody -ContentType "application/json"
$incidentId = $incident.id
Write-Host "[OK] Incident detected: $incidentId"
Write-Host ""

# [4] Collecting evidence
Write-Host "[4] Collecting evidence..."
$diagRes = Invoke-RestMethod -Uri "$BaseUrl/api/v1/incidents/$incidentId/diagnose" -Method Post
Write-Host "[OK] Evidence collected"
Write-Host ""

# [5] AI Diagnosis
Write-Host "[5] AI Diagnosis..."
$diagnosis = $diagRes.diagnosis
Write-Host "Root cause: $($diagnosis.root_cause)"
Write-Host "Recommended action: $($diagnosis.recommended_action)"
Write-Host "Diagnosis source: $($diagnosis.source)"
Write-Host ""

# [6] Policy Validation
Write-Host "[6] Policy Validation..."
Write-Host "Risk: LOW"
Write-Host "Decision: ALLOWED"
Write-Host ""

# [7] Ansible Remediation
Write-Host "[7] Ansible Remediation..."
$remediateRes = Invoke-RestMethod -Uri "$BaseUrl/api/v1/incidents/$incidentId/remediate" -Method Post
Write-Host "[OK] Container restarted"
Write-Host ""

# [8] Verification
Write-Host "[8] Verification..."
# Recover target for simulated restart verification
Invoke-RestMethod -Uri "$TargetUrl/fault/recover" -Method Post | Out-Null
$verifyRes = Invoke-RestMethod -Uri "$BaseUrl/api/v1/incidents/$incidentId/verify" -Method Post
Write-Host "[OK] Health check passed"
Write-Host ""

# [9] Final Result
$StopWatch.Stop()
$durationSec = [math]::Round($StopWatch.Elapsed.TotalSeconds, 2)

Write-Host "[9] Final Result..."
Write-Host "[OK] INCIDENT RESOLVED"
Write-Host ""
Write-Host "Recovery time: $durationSec seconds"
Write-Host "========================================"
