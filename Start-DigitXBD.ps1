$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.env')) {
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $secretBytes = New-Object byte[] 32
    $setupBytes = New-Object byte[] 24
    $generator.GetBytes($secretBytes)
    $generator.GetBytes($setupBytes)
    $secret = ([BitConverter]::ToString($secretBytes)).Replace('-', '').ToLowerInvariant()
    $setup = ([BitConverter]::ToString($setupBytes)).Replace('-', '').ToLowerInvariant()
    @("SECRET_KEY=$secret", "SETUP_TOKEN=$setup", 'PUBLIC_URL=http://localhost:8091', 'BIND_ADDRESS=127.0.0.1', 'PORT=8091', 'COOKIE_SECURE=0', 'MIGRATE_TRACKER=0') | Set-Content -LiteralPath '.env' -Encoding ascii
    $generator.Dispose()
}
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { throw 'Docker could not start DigitXBD. Check that Docker Desktop is running.' }
$printerStarter=Join-Path $env:LOCALAPPDATA 'DigitXBDPrint\Start-Printer.ps1'
if(Test-Path -LiteralPath $printerStarter){& $printerStarter}else{Write-Host 'For automatic Canon printing, complete the one-time setup from Print queue in the app.'}
Write-Host 'DigitXBD is running. Open http://localhost:8091'
Write-Host 'For first setup, open .env and copy SETUP_TOKEN. Create your own owner username and password.'
