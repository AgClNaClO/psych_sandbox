param([string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot))

$ErrorActionPreference = 'Stop'
$projectPath = (Resolve-Path -LiteralPath $ProjectRoot).Path
$runsPath = Join-Path $projectPath 'runs'
$runtimePath = Join-Path $runsPath 'runtime'
$testsPath = Join-Path $runsPath 'tests'
$pythonPath = Join-Path $projectPath '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Install the project .venv first.' }
New-Item -ItemType Directory -Force -Path $runtimePath, $testsPath | Out-Null
$moves = [System.Collections.Generic.List[object]]::new()

function Move-Artifact([string]$Source, [string]$Destination) {
    if (-not (Test-Path -LiteralPath $Source)) { return }
    $sourcePath = (Resolve-Path -LiteralPath $Source).Path
    $destinationPath = [IO.Path]::GetFullPath($Destination)
    if (-not $sourcePath.StartsWith($projectPath + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Source outside project: $sourcePath"
    }
    if (-not $destinationPath.StartsWith($runsPath + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Destination outside runs: $destinationPath"
    }
    if ((Get-Item -LiteralPath $sourcePath).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Refusing to move a linked path: $sourcePath"
    }
    if (Test-Path -LiteralPath $destinationPath) { throw "Destination already exists: $destinationPath" }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destinationPath) | Out-Null
    $hash = if (Test-Path -LiteralPath $sourcePath -PathType Leaf) {
        (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash
    } else { $null }
    Move-Item -LiteralPath $sourcePath -Destination $destinationPath
    if ($hash -and (Get-FileHash -LiteralPath $destinationPath -Algorithm SHA256).Hash -ne $hash) {
        throw "Hash mismatch after moving $sourcePath"
    }
    $moves.Add(@{ source = $sourcePath; destination = $destinationPath; sha256 = $hash })
}

$oldDatabase = Join-Path $runsPath 'psychsandbox.sqlite3'
$database = Join-Path $runtimePath 'psychsandbox.sqlite3'
Move-Artifact $oldDatabase $database
foreach ($suffix in @('-wal', '-shm', '-journal')) {
    Move-Artifact ($oldDatabase + $suffix) ($database + $suffix)
}

if (Test-Path -LiteralPath $database) {
    $query = @'
import json, sqlite3, sys
from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).as_uri() + '?mode=ro', uri=True) as c:
    c.row_factory = sqlite3.Row
    print(json.dumps([dict(r) for r in c.execute('select run_id,case_id,therapy,seed,provider,status,created_at,completed_at from experiment_runs')]))
'@
    $records = & $pythonPath -B -c $query $database | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the run database.' }
    foreach ($record in $records) {
        if ($record.run_id -notmatch '^[\w-]+$' -or $record.case_id -notmatch '^[\w-]+$') {
            throw 'Unsafe run or case identifier in the legacy database.'
        }
        $existing = @(Get-ChildItem -LiteralPath $runtimePath -Directory | Where-Object Name -Like "*__$($record.run_id)")
        if ($existing.Count -gt 1) { throw "Duplicate directories for $($record.run_id)" }
        if ($existing.Count -eq 1) {
            $destination = $existing[0].FullName
        } else {
            $stamp = ([DateTimeOffset]::Parse($record.created_at)).ToLocalTime().ToString('yyyyMMdd-HHmmss-ffffff')
            $destination = Join-Path $runtimePath ($stamp + '__' + $record.case_id + '__' + $record.run_id)
            New-Item -ItemType Directory -Path $destination | Out-Null
            $record | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $destination 'run.json') -Encoding utf8
        }
        foreach ($entry in @(@('jsonl', 'trajectory.jsonl'), @('html', 'report.html'), @('result.json', 'result.json'))) {
            Move-Artifact (Join-Path $runsPath ($record.run_id + '.' + $entry[0])) (Join-Path $destination $entry[1])
        }
        # Attribute old diagnostics only when exactly one stored run spans their UTC timestamp.
        $diagnostics = Join-Path $runsPath 'diagnostics'
        if (Test-Path -LiteralPath $diagnostics) {
            foreach ($file in Get-ChildItem -LiteralPath $diagnostics -File) {
                if ($file.Name -match '^(\d{8}T\d{6}\.\d{6}Z)-') {
                    $time = [DateTimeOffset]::ParseExact($Matches[1], "yyyyMMdd'T'HHmmss.ffffff'Z'", [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::AssumeUniversal)
                    $owners = @($records | Where-Object {
                        $_.completed_at -and $time -ge [DateTimeOffset]::Parse($_.created_at) -and $time -le [DateTimeOffset]::Parse($_.completed_at)
                    })
                    if ($owners.Count -eq 1 -and $owners[0].run_id -eq $record.run_id) {
                        Move-Artifact $file.FullName (Join-Path $destination ('diagnostics/' + $file.Name))
                    }
                }
            }
        }
    }
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-ffffff'
$archive = Join-Path $runtimePath ($stamp + '__legacy-unassigned__' + [guid]::NewGuid().ToString('N').Substring(0,12))
# Preserve remaining legacy artifacts without guessing their original run.
foreach ($item in Get-ChildItem -LiteralPath $runsPath -Force) {
    if ($item.Name -notin @('runtime', 'tests', 'README.md')) {
        if ($item.PSIsContainer -and @(Get-ChildItem -LiteralPath $item.FullName -Force).Count -eq 0) {
            Remove-Item -LiteralPath $item.FullName
            continue
        }
        Move-Artifact $item.FullName (Join-Path $archive $item.Name)
    }
}
foreach ($name in @('outputs', 'checkpoints', 'data/external', 'data/processed')) {
    Move-Artifact (Join-Path $projectPath $name) (Join-Path $archive $name)
}
foreach ($kind in @('external', 'processed')) {
    $dataPath = Join-Path $archive ('data/' + $kind + '/psycheval')
    $pointerPath = Join-Path $runtimePath ($kind + '-latest.json')
    if ((Test-Path -LiteralPath $dataPath) -and -not (Test-Path -LiteralPath $pointerPath)) {
        @{ path = $dataPath.Substring($runtimePath.Length + 1).Replace('\', '/') } |
            ConvertTo-Json | Set-Content -LiteralPath $pointerPath -Encoding utf8
    }
}
foreach ($item in Get-ChildItem -LiteralPath $projectPath -Force | Where-Object { $_.Name -like '.pytest_tmp-*' -or $_.Name -eq '.pytest_cache' }) {
    $testArchive = Join-Path $testsPath ($stamp + '__legacy-pytest__' + [guid]::NewGuid().ToString('N').Substring(0,12))
    Move-Artifact $item.FullName (Join-Path $testArchive $item.Name)
}

if ($moves.Count) {
    $manifest = Join-Path $runtimePath ($stamp + '__migration.json')
    ConvertTo-Json -InputObject @($moves.ToArray()) -Depth 8 | Set-Content -LiteralPath $manifest -Encoding utf8
    Write-Output "Moved $($moves.Count) items; manifest: $manifest"
} else {
    Write-Output 'No legacy artifacts to migrate.'
}
