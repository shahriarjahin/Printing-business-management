$ErrorActionPreference='Stop'
$folder=Join-Path $env:LOCALAPPDATA 'DigitXBDPrint'
if(!(Test-Path -LiteralPath (Join-Path $folder 'config.json'))){throw 'Run Setup-Printer.ps1 once to choose the printer and connect your app.'}
foreach($name in @('Run-Printer.ps1','Start-Printer.ps1')){
    $source=Join-Path $PSScriptRoot $name
    $target=Join-Path $folder $name
    if($source -ne $target){Copy-Item -LiteralPath $source -Destination $target -Force}
}
$helper=Join-Path $folder 'Run-Printer.ps1'
$runtime=Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$modern=Get-Command pwsh.exe -ErrorAction SilentlyContinue
if($modern){$runtime=$modern.Source}
$startup=[Environment]::GetFolderPath('Startup')
$shell=New-Object -ComObject WScript.Shell
$shortcut=$shell.CreateShortcut((Join-Path $startup 'DigitXBD Print Connector.lnk'))
$shortcut.TargetPath=$runtime
$shortcut.Arguments='-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "'+$helper+'"'
$shortcut.WorkingDirectory=$folder
$shortcut.WindowStyle=7
$shortcut.Description='Connects DigitXBD to the Windows printer. Waits for Docker and reconnects after restarts.'
$shortcut.Save()
$previous=Get-ScheduledTask -TaskName 'DigitXBD Print Connector' -ErrorAction SilentlyContinue
if($previous){Unregister-ScheduledTask -TaskName 'DigitXBD Print Connector' -Confirm:$false}
& (Join-Path $folder 'Start-Printer.ps1')
Write-Host 'Startup shortcut installed. The printer connector starts at Windows sign-in and reconnects when Docker starts.'
