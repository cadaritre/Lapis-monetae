param(
    [string]$Branch = "",
    [switch]$Follow,
    [int]$SleepSeconds = 15
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found in PATH."
    }
}

function Get-CurrentBranch {
    return (git rev-parse --abbrev-ref HEAD).Trim()
}

function Get-LatestRun([string]$TargetBranch) {
    $json = gh run list --branch $TargetBranch --limit 1 --json databaseId,status,conclusion,workflowName,displayTitle,url,headSha
    if (-not $json) { return $null }
    $runs = $json | ConvertFrom-Json
    if (-not $runs -or $runs.Count -eq 0) { return $null }
    return $runs[0]
}

function Build-FailureSummary([string]$LogFile, [string]$SummaryFile, [string]$RunUrl, [string]$WorkflowName, [string]$HeadSha) {
    $lines = Get-Content -Path $LogFile

    $keyPatterns = @(
        "error(\[[^\]]+\])?:",
        "thread '.*' panicked at",
        "FAILED",
        "Process completed with exit code",
        "attempt to .* overflow",
        "invalid proof-of-work",
        "assertion `left == right` failed"
    )

    $regex = [regex]::new(($keyPatterns -join "|"), [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
    $hits = New-Object System.Collections.Generic.List[string]
    foreach ($line in $lines) {
        if ($regex.IsMatch($line)) {
            $hits.Add($line)
        }
    }

    $unique = $hits | Select-Object -Unique
    $top = $unique | Select-Object -First 120
    $timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")

    $md = @()
    $md += "# CI failure summary"
    $md += ""
    $md += "- Generated: $timestamp"
    $md += "- Workflow: $WorkflowName"
    $md += "- Head SHA: $HeadSha"
    $md += "- Run URL: $RunUrl"
    $md += ""
    $md += "## Key failure lines"
    $md += ""
    if ($top.Count -eq 0) {
        $md += "_No standard error signatures were detected in failed logs. Check the full log file._"
    } else {
        foreach ($line in $top) {
            $md += "- ``$line``"
        }
    }
    $md += ""
    $md += "## Next step prompt"
    $md += ""
    $md += "Use this with Cursor agent:"
    $md += ""
    $md += "```"
    $md += "Revisa el archivo .ci/failed-run.log y arregla solo errores relevantes del CI."
    $md += "```"

    $md -join [Environment]::NewLine | Set-Content -Path $SummaryFile -Encoding UTF8
}

Require-Command "git"
Require-Command "gh"

if ([string]::IsNullOrWhiteSpace($Branch)) {
    $Branch = Get-CurrentBranch
}

$repoRoot = (git rev-parse --show-toplevel).Trim()
Set-Location $repoRoot

$ciDir = Join-Path $repoRoot ".ci"
if (-not (Test-Path $ciDir)) {
    New-Item -ItemType Directory -Path $ciDir | Out-Null
}

$failedLog = Join-Path $ciDir "failed-run.log"
$summaryMd = Join-Path $ciDir "failed-run-summary.md"

Write-Host "Watching CI for branch '$Branch'..."
$lastRunId = 0

while ($true) {
    $run = Get-LatestRun $Branch
    if ($null -eq $run) {
        Write-Host "No workflow runs found yet. Waiting..."
        Start-Sleep -Seconds $SleepSeconds
        continue
    }

    $runId = [int64]$run.databaseId
    if ($runId -eq $lastRunId) {
        if ($Follow) {
            Start-Sleep -Seconds $SleepSeconds
            continue
        }
        break
    }
    $lastRunId = $runId

    Write-Host "Run #$runId - $($run.workflowName)"
    Write-Host $run.url

    gh run watch $runId --exit-status
    $watchExit = $LASTEXITCODE
    if ($watchExit -eq 0) {
        Write-Host "CI passed for run #$runId"
    } else {
        Write-Host "CI failed for run #$runId, downloading failed logs..."
        gh run view $runId --log-failed | Set-Content -Path $failedLog -Encoding UTF8
        Build-FailureSummary -LogFile $failedLog -SummaryFile $summaryMd -RunUrl $run.url -WorkflowName $run.workflowName -HeadSha $run.headSha
        Write-Host "Saved:"
        Write-Host " - $failedLog"
        Write-Host " - $summaryMd"
        if (-not $Follow) {
            exit 1
        }
    }

    if (-not $Follow) {
        break
    }

    Write-Host "Follow mode enabled: waiting for next run..."
    Start-Sleep -Seconds $SleepSeconds
}
