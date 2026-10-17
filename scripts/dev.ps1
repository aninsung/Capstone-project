param(
[ValidateSet('test', 'serve', 'collect', 'import', 'export-contract', 'probe-llm', 'prepare-week1', 'validate-labels', 'build-index', 'search')]
    [string]$Command = 'test',
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$ExtraArgs
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $projectRoot
$bundledPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if ((Test-Path -LiteralPath $bundledPython) -and (Test-Path -LiteralPath (Join-Path $projectRoot '.runtime/fastapi'))) {
    $pythonExecutable = $bundledPython
    $env:PYTHONPATH = (Join-Path $projectRoot '.runtime')
} else {
    $pythonExecutable = 'python'
}
$env:PYTHONIOENCODING = 'utf-8'
switch ($Command) {
    'test' {
        $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
        & $pythonExecutable -m pytest -q @ExtraArgs
    }
    'serve' { & $pythonExecutable -m uvicorn policy_ai.api:app --host 127.0.0.1 --port 8000 @ExtraArgs }
    default { & $pythonExecutable -m policy_ai.cli $Command @ExtraArgs }
}
exit $LASTEXITCODE
