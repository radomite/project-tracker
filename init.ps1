<#
.SYNOPSIS
Downloads a public GitHub release and starts it on the existing Docker server over SSH.
.EXAMPLE
.\init.ps1 -Repository YOURNAME/project-tracker -Server deploy@curticapean.net
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidatePattern('^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')][string]$Repository,
    [ValidatePattern('^[A-Za-z_][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9.-]*$')][string]$Server = 'deploy@curticapean.net',
    [ValidatePattern('^[A-Za-z0-9_./-]+$')][string]$Ref = 'main',
    [ValidatePattern('^(/[A-Za-z0-9_./-]+|-)$')][string]$InstallDirectory = '-',
    [ValidatePattern('^[a-z0-9][a-z0-9.-]+[a-z0-9]$')][string]$Domain = 'project.counthom.org',
    [ValidateRange(1024,65535)][int]$AppPort = 18765
)
$ErrorActionPreference = 'Stop'
foreach ($command in 'ssh','scp') { Get-Command $command -ErrorAction Stop | Out-Null }
$headers = @{Accept='application/vnd.github+json'; 'User-Agent'='project-tracker-bootstrap'}
$escapedRef = [Uri]::EscapeDataString($Ref)
$commit = (Invoke-RestMethod -Uri "https://api.github.com/repos/$Repository/commits/$escapedRef" -Headers $headers).sha
if ($commit -notmatch '^[a-f0-9]{40}$') { throw 'GitHub did not return a valid commit.' }
Write-Host "Deploying $Repository at commit $commit to $Server"
$tempFile = Join-Path ([IO.Path]::GetTempPath()) ("project-tracker-"+[Guid]::NewGuid().ToString('N')+'.sh')
$remoteFile = "project-tracker-install-$commit.sh"
try {
    # Download the installer from the exact same commit as the application images.
    Invoke-WebRequest -UseBasicParsing -Uri "https://raw.githubusercontent.com/$Repository/$commit/deploy/install.sh" -OutFile $tempFile
    & scp $tempFile "${Server}:$remoteFile"
    if ($LASTEXITCODE -ne 0) { throw 'Copying the installer over SSH failed.' }
    # Validated arguments contain no shell metacharacters. Interactive SSH permits sudo.
    $remoteCommand = "bash '$remoteFile' '$Repository' '$commit' '$InstallDirectory' '$Domain' '$AppPort'"
    & ssh -t $Server $remoteCommand
    if ($LASTEXITCODE -ne 0) { throw 'Remote installation failed; inspect the output above.' }
} finally {
    Remove-Item -LiteralPath $tempFile -ErrorAction SilentlyContinue
}
Write-Host 'Container startup complete. Install the generated Caddy site fragment as described in deploy/README.md.'
