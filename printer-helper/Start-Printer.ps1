$ErrorActionPreference='Stop'
$helper=Join-Path $env:LOCALAPPDATA 'DigitXBDPrint\Run-Printer.ps1'
if(!(Test-Path -LiteralPath $helper)){throw 'Run Setup-Printer.ps1 first.'}
$runtime='powershell.exe'
$modern=Get-Command pwsh.exe -ErrorAction SilentlyContinue
if($modern){$runtime=$modern.Source}
Start-Process -FilePath $runtime -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"'+$helper+'"')) -WindowStyle Hidden
Write-Host 'Printer helper started in the background. Check Print queue in DigitXBD for connection status.'

