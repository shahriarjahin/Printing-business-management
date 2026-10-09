# Runs the real helper loop with a fake printer and HTTP responses. No physical printing.
$ErrorActionPreference='Stop'
$root=Join-Path $PSScriptRoot '.runs\helper-test'
New-Item -ItemType Directory -Force -Path $root | Out-Null
$previousLocal=$env:LOCALAPPDATA
$previousOS=$env:OS
$env:LOCALAPPDATA=$root
$env:OS='Windows_NT'
$folder=Join-Path $root 'DigitXBDPrint'
New-Item -ItemType Directory -Force -Path $folder | Out-Null
$exe=Join-Path $folder 'SumatraPDF.exe'
Set-Content -LiteralPath $exe -Value 'Mock executable - never run'
$secret=ConvertTo-SecureString 'fictional-test-only-helper-token-never-real' -AsPlainText -Force
@{server='http://localhost:8091';printer='Canon G3010 series';sumatra=$exe;token=($secret | ConvertFrom-SecureString);helper_id=[Guid]::NewGuid().ToString()} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $folder 'config.json')
$global:DigitXBDMock_printed=0
$global:DigitXBDMock_ack=0
$global:DigitXBDMock_failAck=$true
$global:DigitXBDMock_expected='submitted'
$global:DigitXBDMock_heartbeatFailures=1
$global:DigitXBDMock_job=@{id=123;claim_key=('a'*43);options=@{printer='Canon G3010 series';copies=2;pages='1-2';mode='monochrome';paper='A4';scale='fit'}}
function Get-Printer { [pscustomobject]@{Name='Canon G3010 series'} }
function Invoke-RestMethod {
    param($Uri,$Method,$Headers,$ContentType,$Body,$TimeoutSec,$MaximumRedirection)
    if($Headers.Authorization -ne 'Bearer fictional-test-only-helper-token-never-real'){throw 'Wrong mock credential.'}
    if($Uri.EndsWith('/heartbeat')){
        if($global:DigitXBDMock_heartbeatFailures -gt 0){$global:DigitXBDMock_heartbeatFailures--;throw 'Mock Docker app is still starting'}
        return @{ok=$true}
    }
    if($Uri.EndsWith('/next')){
        if($global:DigitXBDMock_ack){return @{job=$null}}
        return @{job=$global:DigitXBDMock_job}
    }
    if($Uri.EndsWith('/result')){
        $data=$Body | ConvertFrom-Json
        if($data.status -ne $global:DigitXBDMock_expected){throw 'Unexpected result status.'}
        if($global:DigitXBDMock_failAck){$global:DigitXBDMock_failAck=$false;throw 'Mock acknowledgement network failure'}
        $global:DigitXBDMock_ack++;return @{ok=$true}
    }
    throw 'Unexpected mock request.'
}
function Invoke-WebRequest {
    param([switch]$UseBasicParsing,$Uri,$Headers,$OutFile,$TimeoutSec,$MaximumRedirection)
    Set-Content -LiteralPath $OutFile -Value '%PDF-1.4 mock' -Encoding ASCII
}
function Start-Process {
    param($FilePath,$ArgumentList,$WindowStyle,[switch]$PassThru)
    $global:DigitXBDMock_printed++
    if(($ArgumentList -join ' ') -notmatch 'monochrome,paper=A4,fit,simplex,collate,ignore-pdf-print-settings,2x,1-2'){throw 'Print arguments changed.'}
    $fake=[pscustomobject]@{ExitCode=0;Id=99999}
    $fake | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value {param($milliseconds);return $true}
    $fake | Add-Member -MemberType ScriptMethod -Name Refresh -Value {}
    return $fake
}
function Start-Sleep {
    param($Seconds)
    if($global:DigitXBDMock_ack){throw 'MOCK-DONE'}
}
try {
    try{& (Join-Path $PSScriptRoot '..\printer-helper\Run-Printer.ps1')}catch{if($_.Exception.Message -ne 'MOCK-DONE'){throw}}
    if($global:DigitXBDMock_printed -ne 1 -or $global:DigitXBDMock_ack -ne 1){throw 'A failed acknowledgement duplicated a physical submission.'}
    if(Get-ChildItem (Join-Path $folder 'temporary') -Filter '*.pdf'){throw 'Temporary PDF was not deleted.'}
    Write-Output 'Helper mock integration passed: one submission, failed acknowledgement retried, PDF deleted.'
    if($global:DigitXBDMock_heartbeatFailures -ne 0){throw 'Offline startup recovery was not exercised.'}
    Write-Output 'Automatic reconnect passed: app initially offline, helper waited and connected without restarting.'
    $global:DigitXBDMock_printed=0
    $global:DigitXBDMock_ack=0
    $global:DigitXBDMock_expected='uncertain'
    $global:DigitXBDMock_job=@{id=124;claim_key=('b'*43);options=@{}}
    @{id=124;claim=('b'*43);status='started';detail='';acknowledged=$false} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $folder ('journal\124-'+('b'*43)+'.json'))
    try{& (Join-Path $PSScriptRoot '..\printer-helper\Run-Printer.ps1')}catch{if($_.Exception.Message -ne 'MOCK-DONE'){throw}}
    if($global:DigitXBDMock_printed -ne 0 -or $global:DigitXBDMock_ack -ne 1){throw 'A restarted helper repeated an interrupted print.'}
    Write-Output 'Helper restart recovery passed: interrupted job marked for review, no duplicate print.'
}finally{
    $env:LOCALAPPDATA=$previousLocal
    $env:OS=$previousOS
    # Delete only the verified test fixture directory.
    $target=(Resolve-Path -LiteralPath $root).Path
    if(!$target.StartsWith((Join-Path $PSScriptRoot '.runs')+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Unsafe test cleanup path.'}
    Remove-Item -LiteralPath $target -Recurse -Force
}
