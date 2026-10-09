param([switch]$Check, [switch]$ValidateOnly)
$ErrorActionPreference='Stop'

function Get-PrintArguments($options) {
    # Options are also checked here: never execute arbitrary arguments supplied by a server.
    if($options.printer -notin @(Get-Printer | Select-Object -ExpandProperty Name) -or $options.printer -match '["\r\n]'){throw 'Printer is not installed.'}
    if($options.mode -notin @('color','monochrome') -or $options.paper -notin @('A4','A5','letter','legal') -or $options.scale -notin @('fit','shrink','noscale')){throw 'Unsupported print options.'}
    if([string]$options.copies -notmatch '^\d{1,2}$' -or [int]$options.copies -lt 1 -or [int]$options.copies -gt 50){throw 'Invalid copy count.'}
    if($options.pages -and ([string]$options.pages -notmatch '^\d+(-\d+)?(,\d+(-\d+)?)*$' -or $options.pages.Length -gt 300)){throw 'Invalid page selection.'}
    $parts=@($options.mode,('paper='+$options.paper),$options.scale,'simplex','collate','ignore-pdf-print-settings',([string]$options.copies+'x'))
    if($options.pages){$parts+= [string]$options.pages}
    return ($parts -join ',')
}
if($ValidateOnly){return}
if($env:OS -ne 'Windows_NT'){throw 'Windows is required.'}
# A launcher may pass another PowerShell edition's module paths. Prefer this runtime's built-ins.
$nativeModules=Join-Path $PSHOME 'Modules'
$windowsModules=Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\Modules'
$env:PSModulePath=$nativeModules+[IO.Path]::PathSeparator+$windowsModules+[IO.Path]::PathSeparator+$env:PSModulePath
Import-Module (Join-Path $nativeModules 'Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1') -ErrorAction Stop
$folder=Join-Path $env:LOCALAPPDATA 'DigitXBDPrint'
$config=Get-Content -LiteralPath (Join-Path $folder 'config.json') -Raw | ConvertFrom-Json
$uri=[Uri]$config.server
if(!$uri.IsAbsoluteUri -or $uri.Scheme -notin @('http','https') -or ($uri.Scheme -eq 'http' -and !$uri.IsLoopback) -or $uri.UserInfo -or $uri.Query -or $uri.Fragment -or $uri.AbsolutePath -ne '/'){throw 'Unsafe server address.'}
if(!(Test-Path -LiteralPath $config.sumatra -PathType Leaf) -or [IO.Path]::GetFileName($config.sumatra) -ne 'SumatraPDF.exe'){throw 'SumatraPDF executable is missing.'}
$secure=$config.token | ConvertTo-SecureString
$plain=[Net.NetworkCredential]::new('', $secure).Password
$headers=@{Authorization=('Bearer '+$plain);'X-Print-Helper'=$config.helper_id}
$plain=$null
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$mutex=[Threading.Mutex]::new($false,'Local\DigitXBDPrinterHelper')
if(!$mutex.WaitOne(0)){Write-Host 'A printer helper is already running.'; exit 0}
$tempFolder=Join-Path $folder 'temporary'
$journalFolder=Join-Path $folder 'journal'
New-Item -ItemType Directory -Force -Path $tempFolder,$journalFolder | Out-Null

function Call-App($path,$body,$claim='') {
    $requestHeaders=@{Authorization=$headers.Authorization;'X-Print-Helper'=$config.helper_id}
    if($claim){$requestHeaders['X-Print-Claim']=$claim}
    Invoke-RestMethod -Uri ($config.server+$path) -Method Post -Headers $requestHeaders -ContentType 'application/json' -Body ($body | ConvertTo-Json -Depth 8 -Compress) -TimeoutSec 30 -MaximumRedirection 0
}
function Save-Journal($path,$value) {
    # Atomic replacement: a restart must not repeat an already-started print.
    $staging=$path+'.new'
    $value | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $staging -Encoding UTF8
    Move-Item -LiteralPath $staging -Destination $path -Force
}
function Write-HelperLog($message) {
    $path=Join-Path $folder 'helper.log'
    if((Test-Path -LiteralPath $path) -and (Get-Item -LiteralPath $path).Length -gt 1000000){Move-Item -LiteralPath $path -Destination ($path+'.previous') -Force}
    # Never log credentials or PDF content.
    Add-Content -LiteralPath $path -Value ((Get-Date -Format s)+' '+$message)
}
function Heartbeat {
    $installed=@(Get-Printer | Select-Object -ExpandProperty Name)
    if($config.printer -notin $installed){throw 'Configured printer is not installed.'}
    Call-App '/api/print-agent/heartbeat' @{printer=$config.printer;printers=$installed} | Out-Null
}
try {
    # Temporary PDFs are retained only for the active print process, never long term.
    Get-ChildItem -LiteralPath $tempFolder -Filter 'job-*.pdf' -File | Remove-Item -Force
    if($Check){Heartbeat;Write-Host 'Printer helper connected. No print was sent.'; exit 0}
    # Windows can start before Docker. Keep waiting rather than exiting on the first failed connection.
    $lastBeat=[DateTime]::MinValue
    while($true){
        try {
            if(((Get-Date)-$lastBeat).TotalSeconds -ge 20){Heartbeat; $lastBeat=Get-Date}
            # Retry only result acknowledgements, never physical printing.
            foreach($entry in @(Get-ChildItem -LiteralPath $journalFolder -Filter '*.json' -File)){
                $saved=Get-Content -LiteralPath $entry.FullName -Raw | ConvertFrom-Json
                if($saved.status -eq 'started'){$saved.status='uncertain';$saved.detail='Helper restarted during printing. Check the printer before sending again.';Save-Journal $entry.FullName $saved}
                if(!$saved.acknowledged){
                    try{Call-App ("/api/print-agent/jobs/$($saved.id)/result") @{status=$saved.status;detail=$saved.detail} $saved.claim | Out-Null;$saved.acknowledged=$true;Save-Journal $entry.FullName $saved}catch{if($_.Exception.Response.StatusCode.value__ -in @(401,409)){$saved.acknowledged=$true;Save-Journal $entry.FullName $saved}}
                }
                # The server keeps completed history; scan only unacknowledged jobs on each poll.
                if($saved.acknowledged){Remove-Item -LiteralPath $entry.FullName -Force}
            }
            $reply=Call-App '/api/print-agent/next' @{}
            $job=$reply.job
            if(!$job){Start-Sleep -Seconds 3;continue}
            if([string]$job.id -notmatch '^\d+$' -or [string]$job.claim_key -notmatch '^[A-Za-z0-9_-]{30,100}$'){throw 'Invalid job response.'}
            # Include claim key in journal filename: restored server IDs cannot collide.
            $journalPath=Join-Path $journalFolder ("$($job.id)-$($job.claim_key).json")
            if(Test-Path -LiteralPath $journalPath){Start-Sleep -Seconds 3;continue}
            $saved=@{id=$job.id;claim=$job.claim_key;status='failed';detail='';acknowledged=$false}
            $pdf=Join-Path $tempFolder ("job-$($job.id).pdf")
            try {
                if($job.options.printer -ne $config.printer){throw 'Job targets a different printer. Review and send it again.'}
                $settings=Get-PrintArguments $job.options
                $downloadHeaders=@{Authorization=$headers.Authorization;'X-Print-Helper'=$config.helper_id;'X-Print-Claim'=$job.claim_key}
                Invoke-WebRequest -UseBasicParsing -Uri ($config.server+"/api/print-agent/jobs/$($job.id)/file") -Headers $downloadHeaders -OutFile $pdf -TimeoutSec 60 -MaximumRedirection 0 | Out-Null
                $stream=[IO.File]::OpenRead($pdf)
                try{$bytes=New-Object byte[] 5;[void]$stream.Read($bytes,0,5);if([Text.Encoding]::ASCII.GetString($bytes) -ne '%PDF-'){throw 'Downloaded document is not a PDF.'}}finally{$stream.Dispose()}
                $saved.status='started';Save-Journal $journalPath $saved
                # Fixed executable, fixed flags, validated values; no shell command evaluation.
                $arguments=@('-print-to',('"'+$config.printer+'"'),'-print-settings',('"'+$settings+'"'),'-silent','-appdata',('"'+$tempFolder+'"'),('"'+$pdf+'"'))
                $process=Start-Process -FilePath $config.sumatra -ArgumentList $arguments -WindowStyle Hidden -PassThru
                if(!$process.WaitForExit(120000)){
                    Stop-Process -Id $process.Id -ErrorAction SilentlyContinue
                    $saved.status='uncertain';$saved.detail='Print submission timed out. Check the Windows queue and printer before sending again.'
                }else{
                    $process.Refresh()
                    if($process.ExitCode -ne 0){$saved.status='uncertain';$saved.detail='Printer returned an error. Check Windows queue before sending again.'}
                    else{$saved.status='submitted';$saved.detail='Accepted by Windows. Physical completion must be checked at the printer.'}
                }
            }catch{
                if($saved.status -eq 'started'){$saved.status='uncertain';$saved.detail='Print process was interrupted. Check the printer before sending again.'}
                else{$saved.status='failed';$saved.detail='Could not download or prepare PDF. Check file availability, printer and helper setup.'}
            }finally{
                Remove-Item -LiteralPath $pdf -Force -ErrorAction SilentlyContinue
            }
            Save-Journal $journalPath $saved
            Write-HelperLog ("Job $($saved.id): $($saved.status)")
            # Next loop sends the journalled acknowledgement, even after a network failure.
        }catch{Write-HelperLog 'Connection or printer check failed; retrying in 10 seconds.';Start-Sleep -Seconds 10}
    }
}finally{$mutex.ReleaseMutex();$mutex.Dispose()}
