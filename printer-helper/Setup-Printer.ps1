param([switch]$NoStart)
$ErrorActionPreference='Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Run this helper on Windows.' }
$folder=Join-Path $env:LOCALAPPDATA 'DigitXBDPrint'
New-Item -ItemType Directory -Force -Path $folder | Out-Null
# Only this Windows account and SYSTEM can read helper credentials and temporary PDFs.
$identity=[Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls.exe $folder /inheritance:r /grant:r "${identity}:(OI)(CI)F" 'SYSTEM:(OI)(CI)F' | Out-Null
if($LASTEXITCODE -ne 0){throw 'Could not secure the helper folder.'}
$server=(Read-Host 'App address (example: http://localhost:8091 or https://your-domain.com)').Trim().TrimEnd('/')
$uri=[Uri]$server
if(!$uri.IsAbsoluteUri -or $uri.Scheme -notin @('http','https') -or ($uri.Scheme -eq 'http' -and !$uri.IsLoopback) -or $uri.UserInfo -or $uri.Query -or $uri.Fragment -or $uri.AbsolutePath -ne '/') {throw 'Use HTTPS for remote servers, or HTTP localhost for the same computer. Enter the app address without a page path.'}
$defaultPath=@((Join-Path $env:LOCALAPPDATA 'SumatraPDF\SumatraPDF.exe'),(Join-Path $env:ProgramFiles 'SumatraPDF\SumatraPDF.exe')) | Where-Object {Test-Path -LiteralPath $_} | Select-Object -First 1
$exe=(Read-Host "SumatraPDF.exe full path (Enter for $defaultPath)").Trim().Trim('"')
if(!$exe){$exe=$defaultPath}
if(!$exe -or !(Test-Path -LiteralPath $exe -PathType Leaf) -or [IO.Path]::GetFileName($exe) -ne 'SumatraPDF.exe'){throw 'Install SumatraPDF from sumatrapdfreader.org, then run setup again.'}
$printers=@(Get-Printer | Select-Object -ExpandProperty Name)
if(!$printers.Count){throw 'Install the Canon Windows printer driver first.'}
Write-Host 'Installed printers:'
$printers | ForEach-Object {Write-Host "  $_"}
$defaultPrinter=$printers | Where-Object {$_ -eq 'Canon G3010 series'} | Select-Object -First 1
if(!$defaultPrinter){$defaultPrinter=$printers | Where-Object {$_ -match 'G3010'} | Select-Object -First 1}
$printer=(Read-Host "Printer name (Enter for $defaultPrinter)").Trim()
if(!$printer){$printer=$defaultPrinter}
if($printer -notin $printers -or $printer -match '["\r\n]'){throw 'Enter the exact installed printer name.'}
$token=Read-Host 'Paste the helper key from Print queue' -AsSecureString
if($token.Length -lt 30){throw 'Helper key is incomplete.'}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Run-Printer.ps1') -Destination (Join-Path $folder 'Run-Printer.ps1') -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Start-Printer.ps1') -Destination (Join-Path $folder 'Start-Printer.ps1') -Force
$helperId=[Guid]::NewGuid().ToString()
if(Test-Path -LiteralPath (Join-Path $folder 'config.json')){
    $old=Get-Content -LiteralPath (Join-Path $folder 'config.json') -Raw | ConvertFrom-Json
    if($old.helper_id){$helperId=$old.helper_id}
}
$config=@{server=$server;printer=$printer;sumatra=(Resolve-Path -LiteralPath $exe).Path;token=($token | ConvertFrom-SecureString);helper_id=$helperId}
$config | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $folder 'config.json') -Encoding UTF8
Write-Host "Saved privately in $folder. Your key is encrypted for this Windows account."
Write-Host 'Checking connection (no document will be printed)...'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $folder 'Run-Printer.ps1') -Check
if($LASTEXITCODE -ne 0){throw 'Connection failed. Check app address and helper key, then run setup again.'}
if(!$NoStart){& (Join-Path $PSScriptRoot 'Install-AutoStart.ps1')}
Write-Host 'Ready. Keep the computer awake and printer connected. The connector now starts and reconnects automatically.'
