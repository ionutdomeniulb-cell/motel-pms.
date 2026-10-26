<#
  Pornire automată a PMS la autentificarea în Windows, cu repornire dacă se oprește.
  Rulați în PowerShell ca administrator, din folderul aplicației:
    .\pornire-automata.ps1 -Retea                 # instalează
    .\pornire-automata.ps1 -Dezinstaleaza         # elimină
  Recomandat: un cont Windows dedicat aplicației, cu autentificare automată la pornirea PC-ului.
#>
param([switch]$Retea, [string]$Cert = "", [string]$Cheie = "", [switch]$Dezinstaleaza)
$ErrorActionPreference = "Stop"
$nume = "PMS Popas Caprioara"
if ($Dezinstaleaza) {
    Unregister-ScheduledTask -TaskName $nume -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Pornirea automată a fost eliminată."
    exit 0
}
$script = Join-Path $PSScriptRoot "porneste.ps1"
$argumente = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Minimized -File `"$script`""
if ($Retea) { $argumente += " -Retea" }
if ($Cert -and $Cheie) { $argumente += " -Cert `"$Cert`" -Cheie `"$Cheie`"" }
$actiune = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argumente -WorkingDirectory $PSScriptRoot
$declansator = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$setari = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 0) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $nume -Action $actiune -Trigger $declansator -Settings $setari -Description "Pornește PMS Popas Căprioara" -Force | Out-Null
Write-Host "Gata: PMS pornește automat la autentificarea utilizatorului $env:USERNAME și repornește dacă se oprește." -ForegroundColor Green
