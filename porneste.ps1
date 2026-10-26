<#
  Pornește PMS Popas Căprioara.
  Exemple:
    .\porneste.ps1                       # doar pe acest PC (http://127.0.0.1:5000)
    .\porneste.ps1 -Retea                # și de pe telefoane din rețeaua locală
    .\porneste.ps1 -Retea -Cert C:\PMS\192.168.1.50.pem -Cheie C:\PMS\192.168.1.50-key.pem   # cu HTTPS
    .\porneste.ps1 -CeasTest "2026-10-27 23:00"   # ceas de test (NU cu date reale)
#>
param(
    [switch]$Retea,
    [string]$Cert = "",
    [string]$Cheie = "",
    [int]$Port = 5000,
    [string]$CeasTest = ""
)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "Mediul Python lipsește. Rulați întâi instalarea (vezi ghidul)." -ForegroundColor Red
    exit 1
}
$env:MOTEL_PORT = "$Port"
$env:MOTEL_HOST = if ($Retea) { "0.0.0.0" } else { "127.0.0.1" }
if ($Cert -and $Cheie) { $env:MOTEL_SSL_CERT = $Cert; $env:MOTEL_SSL_KEY = $Cheie } else { Remove-Item Env:MOTEL_SSL_CERT, Env:MOTEL_SSL_KEY -ErrorAction SilentlyContinue }
if ($CeasTest) { $env:MOTEL_TEST_NOW = $CeasTest } else { Remove-Item Env:MOTEL_TEST_NOW -ErrorAction SilentlyContinue }
if ($Retea) {
    $ip = Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } | Select-Object -First 1 -ExpandProperty IPAddress
    $schema = if ($Cert) { "https" } else { "http" }
    Write-Host "Pe telefon deschideți: $schema`://$ip`:$Port" -ForegroundColor Green
}
& ".\.venv\Scripts\python.exe" app.py
