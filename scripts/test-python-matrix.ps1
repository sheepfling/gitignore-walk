param(
    [string[]]$PythonVersions = @("3.10", "3.11", "3.12", "3.13", "3.14", "3.15")
)

$ErrorActionPreference = "Stop"
$arguments = @("matrix", "--backend", "vanilla", "--versions") + $PythonVersions
& python -m scripts.ci @arguments
exit $LASTEXITCODE
