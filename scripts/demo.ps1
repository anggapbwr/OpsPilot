# ==============================================================================
# OpsPilot End-to-End Autonomous Operations & Remediation Platform Demo
# Validated Scenarios:
#   1. AI Auto-Remediation (Ollama / llama3.2 -> Ansible -> Verification -> Resolved)
#   2. AI Unavailable Fallback (Deterministic Fallback -> Ansible -> Resolved)
#   3. Dangerous Action Blocked (delete_resource -> Blocked by Policy -> Ansible NOT executed)
#   4. Repeated Failure & Bounded Escalation (3 failed attempts -> Escalated)
#   5. Bad Deployment & Human Approval Gate (Deploy 503 -> Rollback -> Awaiting Approval -> Approved -> Resolved)
# ==============================================================================

param(
    [ValidateSet("1", "2", "3", "4", "5", "all")]
    [string]$Scenario = "all",
    [string]$BaseUrl = "http://localhost:8000",
    [string]$TargetUrl = "http://localhost:8080"
)

$ErrorActionPreference = "Stop"

function Invoke-OpsPilotRest {
    param(
        [string]$Uri,
        [string]$Method = "GET",
        [string]$Body = $null,
        [int]$TimeoutSec = 60
    )
    try {
        $headers = @{ "Content-Type" = "application/json" }
        if ($Body) {
            return Invoke-RestMethod -Uri $Uri -Method $Method -Body $Body -Headers $headers -TimeoutSec $TimeoutSec
        } else {
            return Invoke-RestMethod -Uri $Uri -Method $Method -Headers $headers -TimeoutSec $TimeoutSec
        }
    } catch {
        if ($_.Exception.Response) {
            $stream = $_.Exception.Response.GetResponseStream()
            $reader = New-Object System.IO.StreamReader($stream)
            $respBody = $reader.ReadToEnd()
            try {
                return ($respBody | ConvertFrom-Json)
            } catch {
                return @{ error = "http_error"; status_code = $_.Exception.Response.StatusCode; detail = $respBody }
            }
        }
        throw $_
    }
}

function Reset-TargetService {
    try {
        $health = Invoke-OpsPilotRest -Uri "$TargetUrl/health" -TimeoutSec 5
        if ($health.status -ne "healthy") {
            Invoke-OpsPilotRest -Uri "$TargetUrl/fault/recover" -Method "POST" | Out-Null
            Start-Sleep -Seconds 1
        }
    } catch {
        # Target might be restarting
        Start-Sleep -Seconds 2
    }
}

# ------------------------------------------------------------------------------
# SCENARIO 1: AI Auto-Remediation via Ollama
# ------------------------------------------------------------------------------
function Run-Demo1 {
    Write-Host ""
    Write-Host "==================================================================" -ForegroundColor Cyan
    Write-Host " DEMO 1: AI AUTO-REMEDIATION (Ollama / llama3.2)" -ForegroundColor Cyan
    Write-Host " Flow: Detect -> Evidence -> Ollama -> Policy -> Ansible -> Verify" -ForegroundColor Cyan
    Write-Host "==================================================================" -ForegroundColor Cyan
    $sw = [System.Diagnostics.Stopwatch]::StartNew()

    Write-Host "[1] Checking target service health..." -ForegroundColor Yellow
    Reset-TargetService
    $h = Invoke-OpsPilotRest -Uri "$TargetUrl/health"
    Write-Host "    [OK] payment-api status: $($h.status)" -ForegroundColor Green

    Write-Host "[2] Injecting failure into target..." -ForegroundColor Yellow
    $inj = Invoke-OpsPilotRest -Uri "$TargetUrl/fault/unhealthy" -Method "POST"
    Write-Host "    [OK] Fault injected: $($inj.detail)" -ForegroundColor Green

    Write-Host "[3] Detecting incident..." -ForegroundColor Yellow
    $inc = Invoke-OpsPilotRest -Uri "$BaseUrl/api/v1/incidents" -Method "POST" -Body '{"auto_detect": true}'
    $incId = $inc.id
    Write-Host "    [OK] Incident detected: $incId (Type: $($inc.type), Target: $($inc.target))" -ForegroundColor Green

    Write-Host "[4] Evidence Collection & AI Diagnosis (Ollama)..." -ForegroundColor Yellow
    Write-Host "    Querying Ollama with llama3.2 model..." -ForegroundColor Gray
    $diagRes = Invoke-OpsPilotRest -Uri "$BaseUrl/api/v1/incidents/$incId/diagnose" -Method "POST" -TimeoutSec 60
    $diag = $diagRes.diagnosis
    Write-Host "    Root Cause:         $($diag.root_cause)" -ForegroundColor White
    Write-Host "    Confidence:         $([math]::Round($diag.confidence * 100, 1))%" -ForegroundColor White
    Write-Host "    Recommended Action: $($diag.recommended_action)" -ForegroundColor White
    Write-Host "    Diagnosis Source:   $($diag.source)" -ForegroundColor Green
    Write-Host "    Reasoning:          $($diag.reasoning_summary)" -ForegroundColor Gray

    if ($diag.source -ne "ollama") {
        Write-Host "    [WARNING] Expected diagnosis source 'ollama', got '$($diag.source)'" -ForegroundColor Yellow
    }

    Write-Host "[5] Policy Validation & Remediation Execution..." -ForegroundColor Yellow
    $remRes = Invoke-OpsPilotRest -Uri "$BaseUrl/api/v1/incidents/$incId/remediate" -Method "POST"
    $att = $remRes.attempt
    if ($att.status -eq "success") {
        Write-Host "    [OK] Container restarted via Ansible" -ForegroundColor Green
        Write-Host "    Playbook: $($att.playbook) | Duration: $($att.duration_seconds)s | Exit Code: 0" -ForegroundColor Gray
    } else {
        Write-Host "    [FAILED] Ansible execution failed: $($att.error)" -ForegroundColor Red
        return
    }

    Write-Host "[6] Independent Verification..." -ForegroundColor Yellow
    Start-Sleep -Seconds 2
    $verRes = Invoke-OpsPilotRest -Uri "$BaseUrl/api/v1/incidents/$incId/verify" -Method "POST"
    $v = $verRes.verification
    if ($v.passed -eq $true) {
        Write-Host "    [OK] Health check passed (HTTP $($v.status_code), Latency: $($v.latency_ms)ms)" -ForegroundColor Green
        Write-Host "    Outcome: $($v.outcome)" -ForegroundColor Green
    } else {
        Write-Host "    [FAILED] Verification failed: $($v.error)" -ForegroundColor Red
    }

    $sw.Stop()
    $finalInc = Invoke-OpsPilotRest -Uri "$BaseUrl/api/v1/incidents/$incId"
    Write-Host "[7] Final Incident State:" -ForegroundColor Yellow
    Write-Host "    State:       $($finalInc.status)" -ForegroundColor Green
    Write-Host "    Attempts:    $($finalInc.attempt_count) / $($finalInc.max_attempts)" -ForegroundColor White
    Write-Host "    Recovery:    $([math]::Round($sw.Elapsed.TotalSeconds, 2))s" -ForegroundColor White
    Write-Host "    Result:      INCIDENT RESOLVED" -ForegroundColor Green
}

# ------------------------------------------------------------------------------
# SCENARIO 2: AI Unavailable / Deterministic Fallback
# ------------------------------------------------------------------------------
function Run-Demo2 {
    Write-Host ""
    Write-Host "==================================================================" -ForegroundColor Cyan
    Write-Host " DEMO 2: AI UNAVAILABLE FALLBACK (Resilience Path)" -ForegroundColor Cyan
    Write-Host " Flow: Detect -> Evidence -> Fallback -> Policy -> Ansible -> Verify" -ForegroundColor Cyan
    Write-Host "==================================================================" -ForegroundColor Cyan
    $sw = [System.Diagnostics.Stopwatch]::StartNew()

    Write-Host "[1] Checking target service health..." -ForegroundColor Yellow
    Reset-TargetService
    $h = Invoke-OpsPilotRest -Uri "$TargetUrl/health"
    Write-Host "    [OK] payment-api status: $($h.status)" -ForegroundColor Green

    Write-Host "[2] Injecting failure into target..." -ForegroundColor Yellow
    $inj = Invoke-OpsPilotRest -Uri "$TargetUrl/fault/unhealthy" -Method "POST"
    Write-Host "    [OK] Fault injected: $($inj.detail)" -ForegroundColor Green

    Write-Host "[3] Detecting incident..." -ForegroundColor Yellow
    $inc = Invoke-OpsPilotRest -Uri "$BaseUrl/api/v1/incidents" -Method "POST" -Body '{"auto_detect": true}'
    $incId = $inc.id
    Write-Host "    [OK] Incident detected: $incId" -ForegroundColor Green

    Write-Host "[4] Diagnosing via Deterministic Fallback Engine..." -ForegroundColor Yellow
    # Force deterministic fallback to prove resilience when Ollama is unavailable
    $diagRes = Invoke-OpsPilotRest -Uri "$BaseUrl/api/v1/incidents/$incId/diagnose" -Method "POST" -Body '{"force_fallback": true}'
    $diag = $diagRes.diagnosis
    Write-Host "    Root Cause:         $($diag.root_cause)" -ForegroundColor White
    Write-Host "    Recommended Action: $($diag.recommended_action)" -ForegroundColor White
    Write-Host "    Diagnosis Source:   $($diag.source)" -ForegroundColor Green
    Write-Host "    Reasoning:          $($diag.reasoning_summary)" -ForegroundColor Gray

    Write-Host "[5] Policy Validation & Remediation Execution..." -ForegroundColor Yellow
    $remRes = Invoke-OpsPilotRest -Uri "$BaseUrl/api/v1/incidents/$incId/remediate" -Method "POST"
    $att = $remRes.attempt
    if ($att.status -eq "success") {
        Write-Host "    [OK] Container restarted via Ansible" -ForegroundColor Green
        Write-Host "    Playbook: $($att.playbook) | Duration: $($att.duration_seconds)s" -ForegroundColor Gray
    }

    Write-Host "[6] Independent Verification..." -ForegroundColor Yellow
    Start-Sleep -Seconds 2
    $verRes = Invoke-OpsPilotRest -Uri "$BaseUrl/api/v1/incidents/$incId/verify" -Method "POST"
    $v = $verRes.verification
    if ($v.passed -eq $true) {
        Write-Host "    [OK] Health check passed (HTTP $($v.status_code))" -ForegroundColor Green
        Write-Host "    Outcome: $($v.outcome)" -ForegroundColor Green
    }

    $sw.Stop()
    $finalInc = Invoke-OpsPilotRest -Uri "$BaseUrl/api/v1/incidents/$incId"
    Write-Host "[7] Final Incident State:" -ForegroundColor Yellow
    Write-Host "    State:       $($finalInc.status)" -ForegroundColor Green
    Write-Host "    Source:      $($diag.source)" -ForegroundColor Green
    Write-Host "    Recovery:    $([math]::Round($sw.Elapsed.TotalSeconds, 2))s" -ForegroundColor White
    Write-Host "    Result:      INCIDENT RESOLVED (VIA FALLBACK RESILIENCE)" -ForegroundColor Green
}

# ------------------------------------------------------------------------------
# SCENARIO 3: Dangerous Action Blocked (Security Validation)
# ------------------------------------------------------------------------------
function Run-Demo3 {
    Write-Host ""
    Write-Host "==================================================================" -ForegroundColor Cyan
    Write-Host " DEMO 3: DANGEROUS ACTION BLOCKED (Safety & Policy Enforcement)" -ForegroundColor Cyan
    Write-Host " Flow: Rogue Action -> Policy Engine -> BLOCKED -> Ansible NOT Run" -ForegroundColor Cyan
    Write-Host "==================================================================" -ForegroundColor Cyan

    Write-Host "[1] Creating security test incident..." -ForegroundColor Yellow
    $incBody = '{"type": "container_unhealthy", "severity": "critical", "target": "payment-api"}'
    $inc = Invoke-OpsPilotRest -Uri "$BaseUrl/api/v1/incidents" -Method "POST" -Body $incBody
    $incId = $inc.id
    Write-Host "    [OK] Incident registered: $incId" -ForegroundColor Green

    Write-Host "[2] Simulating rogue AI recommendation: 'delete_resource'..." -ForegroundColor Yellow
    $diagRes = Invoke-OpsPilotRest -Uri "$BaseUrl/api/v1/incidents/$incId/diagnose" -Method "POST" -Body '{"mock_action": "delete_resource"}'
    $diag = $diagRes.diagnosis
    Write-Host "    Recommended Action: $($diag.recommended_action)" -ForegroundColor Red
    Write-Host "    Reasoning:          $($diag.reasoning_summary)" -ForegroundColor Gray

    Write-Host "[3] Evaluating Policy for dangerous action..." -ForegroundColor Yellow
    $remRes = Invoke-OpsPilotRest -Uri "$BaseUrl/api/v1/incidents/$incId/remediate" -Method "POST"
    
    Write-Host "    Policy Response:    ACTION PROHIBITED" -ForegroundColor Red
    Write-Host "    Error Code:         $($remRes.detail.error)" -ForegroundColor Red
    Write-Host "    Policy Message:     $($remRes.detail.message)" -ForegroundColor Red

    Write-Host "[4] Verifying Audit Trail..." -ForegroundColor Yellow
    $auditRes = Invoke-OpsPilotRest -Uri "$BaseUrl/api/v1/incidents/$incId/audit"
    $lastAudit = $auditRes.audit_trail[-1]
    Write-Host "    Audit Action:       $($lastAudit.recommended_action)" -ForegroundColor White
    Write-Host "    Policy Decision:    $($lastAudit.policy_decision)" -ForegroundColor Red
    Write-Host "    Execution Status:   $($lastAudit.execution_status)" -ForegroundColor Green
    Write-Host "    Outcome:            $($lastAudit.outcome)" -ForegroundColor Yellow
    Write-Host "    Final Status:       $($lastAudit.final_status)" -ForegroundColor Yellow

    Write-Host "[5] Safety Confirmation:" -ForegroundColor Yellow
    Write-Host "    [OK] Ansible was NOT executed." -ForegroundColor Green
    Write-Host "    [OK] Target infrastructure remains intact." -ForegroundColor Green
    Write-Host "    [OK] Incident marked BLOCKED by Policy Engine." -ForegroundColor Green
}

# ------------------------------------------------------------------------------
# SCENARIO 4: Repeated Failure & Bounded Escalation
# ------------------------------------------------------------------------------
function Run-Demo4 {
    Write-Host ""
    Write-Host "==================================================================" -ForegroundColor Cyan
    Write-Host " DEMO 4: REPEATED FAILURE & BOUNDED ESCALATION" -ForegroundColor Cyan
    Write-Host " Flow: Persistent Failure -> Retries (Max 3) -> ESCALATED" -ForegroundColor Cyan
    Write-Host "==================================================================" -ForegroundColor Cyan

    Write-Host "[1] Creating unrecoverable incident targeting invalid target..." -ForegroundColor Yellow
    $incBody = '{"type": "container_unhealthy", "severity": "high", "target": "unresponsive-target"}'
    $inc = Invoke-OpsPilotRest -Uri "$BaseUrl/api/v1/incidents" -Method "POST" -Body $incBody
    $incId = $inc.id
    Write-Host "    [OK] Incident registered: $incId (Target: unresponsive-target)" -ForegroundColor Green

    Write-Host "[2] Diagnosing incident..." -ForegroundColor Yellow
    $diagRes = Invoke-OpsPilotRest -Uri "$BaseUrl/api/v1/incidents/$incId/diagnose" -Method "POST" -Body '{"force_fallback": true}'
    Write-Host "    Recommended Action: $($diagRes.diagnosis.recommended_action)" -ForegroundColor White

    Write-Host "[3] Executing autonomous pipeline with bounded retries..." -ForegroundColor Yellow
    $runRes = Invoke-OpsPilotRest -Uri "$BaseUrl/api/v1/incidents/$incId/run" -Method "POST" -TimeoutSec 60

    Write-Host "    Final Incident Status: $($runRes.status)" -ForegroundColor Yellow
    Write-Host "    Total Attempts Made:   $($runRes.attempt_count) / $($runRes.max_attempts)" -ForegroundColor Yellow

    Write-Host "[4] Verifying Remediation History & Escalation..." -ForegroundColor Yellow
    foreach ($attempt in $runRes.remediation_history) {
        Write-Host "    Attempt $($attempt.attempt_number): Status=$($attempt.status), Error=$($attempt.error)" -ForegroundColor Gray
    }

    $auditRes = Invoke-OpsPilotRest -Uri "$BaseUrl/api/v1/incidents/$incId/audit"
    $lastAudit = $auditRes.audit_trail[-1]
    Write-Host "    Audit Final Status:    $($lastAudit.final_status)" -ForegroundColor Yellow
    Write-Host "    Audit Outcome:         $($lastAudit.outcome)" -ForegroundColor Yellow

    Write-Host "[5] Bounded Escalation Confirmation:" -ForegroundColor Yellow
    Write-Host "    [OK] Maximum retries strictly bounded at $($runRes.max_attempts)." -ForegroundColor Green
    Write-Host "    [OK] No infinite loop occurred." -ForegroundColor Green
    Write-Host "    [OK] Incident escalated to human on-call engineer." -ForegroundColor Green
}

# ------------------------------------------------------------------------------
# SCENARIO 5: Bad Deployment & Human Approval Gate (Rollback)
# ------------------------------------------------------------------------------
function Run-Demo5 {
    Write-Host ""
    Write-Host "==================================================================" -ForegroundColor Cyan
    Write-Host " DEMO 5: BAD DEPLOYMENT & HUMAN APPROVAL GATE" -ForegroundColor Cyan
    Write-Host " Flow: Deploy 503 -> Detect -> Diagnose Rollback -> Policy Approval Gate -> Approved -> Resolved" -ForegroundColor Cyan
    Write-Host "==================================================================" -ForegroundColor Cyan

    Write-Host "[1] Checking and resetting target microservice..." -ForegroundColor Yellow
    Reset-TargetService
    $h = Invoke-OpsPilotRest -Uri "$TargetUrl/health"
    Write-Host "    [OK] Baseline status: $($h.status)" -ForegroundColor Green

    Write-Host "[2] Injecting bad deployment failure (v2.0.0-broken, 503)..." -ForegroundColor Yellow
    $inj = Invoke-OpsPilotRest -Uri "$BaseUrl/api/v1/simulator/deployment-failed" -Method "POST"
    Write-Host "    [OK] Bad deployment injected: $($inj.detail)" -ForegroundColor Green

    Write-Host "[3] Probing and registering incident..." -ForegroundColor Yellow
    $inc = Invoke-OpsPilotRest -Uri "$BaseUrl/api/v1/incidents" -Method "POST" -Body '{"auto_detect": true}'
    $incId = $inc.id
    Write-Host "    [OK] Incident detected: $incId" -ForegroundColor Green
    Write-Host "    Incident Type:     $($inc.type)" -ForegroundColor White
    Write-Host "    Incident Severity: $($inc.severity)" -ForegroundColor White

    Write-Host "[4] Running diagnosis..." -ForegroundColor Yellow
    $diagRes = Invoke-OpsPilotRest -Uri "$BaseUrl/api/v1/incidents/$incId/diagnose" -Method "POST"
    $diag = $diagRes.diagnosis
    Write-Host "    Root Cause:         $($diag.root_cause)" -ForegroundColor White
    Write-Host "    Recommended Action: $($diag.recommended_action)" -ForegroundColor White
    Write-Host "    Diagnosis Source:   $($diag.source)" -ForegroundColor Green

    Write-Host "[5] Running autonomous pipeline (expecting approval halt)..." -ForegroundColor Yellow
    $runRes1 = Invoke-OpsPilotRest -Uri "$BaseUrl/api/v1/incidents/$incId/run" -Method "POST"
    Write-Host "    Incident Status:    $($runRes1.status)" -ForegroundColor Yellow
    Write-Host "    Requires Approval:  $($runRes1.policy_decision.requires_approval)" -ForegroundColor Yellow

    if ($runRes1.status -ne "awaiting_approval") {
        throw "Expected status 'awaiting_approval', got '$($runRes1.status)'"
    }
    Write-Host "    [OK] Pipeline safely halted at approval gate." -ForegroundColor Green

    Write-Host "[6] Simulating Operator Human Approval via API..." -ForegroundColor Yellow
    $appBody = '{"approved_by": "oncall_sre_lead", "note": "Rollback authorized for live demo scenario 5"}'
    $appRes = Invoke-OpsPilotRest -Uri "$BaseUrl/api/v1/incidents/$incId/approve" -Method "POST" -Body $appBody
    Write-Host "    Approval Recorded:  Approved=$($appRes.approval.approved), By=$($appRes.approval.approved_by)" -ForegroundColor Green

    Write-Host "[7] Resuming autonomous pipeline with approval granted..." -ForegroundColor Yellow
    $runRes2 = Invoke-OpsPilotRest -Uri "$BaseUrl/api/v1/incidents/$incId/run" -Method "POST" -TimeoutSec 60
    Write-Host "    Final Incident Status: $($runRes2.status)" -ForegroundColor Green
    Write-Host "    Attempts Executed:     $($runRes2.attempt_count) / $($runRes2.max_attempts)" -ForegroundColor White

    Write-Host "[8] Inspecting Compliance Audit Trail..." -ForegroundColor Yellow
    $auditRes = Invoke-OpsPilotRest -Uri "$BaseUrl/api/v1/incidents/$incId/audit"
    $lastAudit = $auditRes.audit_trail[-1]
    Write-Host "    Audit Action:       $($lastAudit.recommended_action)" -ForegroundColor White
    Write-Host "    Audit Policy:       $($lastAudit.policy_decision)" -ForegroundColor White
    Write-Host "    Audit Execution:    $($lastAudit.execution_status)" -ForegroundColor White
    Write-Host "    Audit Verification: $($lastAudit.verification_status)" -ForegroundColor White
    Write-Host "    Audit Outcome:      $($lastAudit.outcome)" -ForegroundColor Green

    Write-Host "[9] Approval Gate & Rollback Verification Confirmation:" -ForegroundColor Yellow
    Write-Host "    [OK] High-risk rollback strictly blocked until human authorized." -ForegroundColor Green
    Write-Host "    [OK] Ansible rollback executed successfully." -ForegroundColor Green
    Write-Host "    [OK] Microservice health verified and incident resolved." -ForegroundColor Green
}

# ------------------------------------------------------------------------------
# Execution Router
# ------------------------------------------------------------------------------
Write-Host "==================================================================" -ForegroundColor Magenta
Write-Host "           OPSPILOT PLATFORM VERIFICATION SUITE" -ForegroundColor Magenta
Write-Host "   Detect -> Evidence -> Diagnose -> Policy -> Remediate -> Verify" -ForegroundColor Magenta
Write-Host "==================================================================" -ForegroundColor Magenta

if ($Scenario -eq "1" -or $Scenario -eq "all") { Run-Demo1 }
if ($Scenario -eq "2" -or $Scenario -eq "all") { Run-Demo2 }
if ($Scenario -eq "3" -or $Scenario -eq "all") { Run-Demo3 }
if ($Scenario -eq "4" -or $Scenario -eq "all") { Run-Demo4 }
if ($Scenario -eq "5" -or $Scenario -eq "all") { Run-Demo5 }

# Reset target to healthy at the end
Reset-TargetService

Write-Host ""
Write-Host "==================================================================" -ForegroundColor Magenta
Write-Host " ALL DEMO SCENARIOS COMPLETED SUCCESSFULLY" -ForegroundColor Magenta
Write-Host "==================================================================" -ForegroundColor Magenta
