# Reset demo target service in PowerShell
$TargetUrl = if ($env:TARGET_URL) { $env:TARGET_URL } else { "http://localhost:8080" }

Write-Host "[*] Resetting target payment-api state to healthy..." -ForegroundColor Yellow
try {
    $res = Invoke-RestMethod -Uri "$TargetUrl/fault/recover" -Method Post
    Write-Host "[+] Reset complete: $($res.detail)" -ForegroundColor Green
} catch {
    Write-Host "[-] Warning: Could not reach $TargetUrl ($_.Exception.Message)" -ForegroundColor Red
}
