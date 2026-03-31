param(
    [string]$PythonExe = "",
    [switch]$Clean
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $false)][string[]]$Arguments = @()
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao executar: $FilePath $($Arguments -join ' ')"
    }
}

function Resolve-NpmCmd {
    $candidates = @(
        "npm.cmd",
        "$env:ProgramFiles\nodejs\npm.cmd",
        "$env:ProgramFiles(x86)\nodejs\npm.cmd"
    )
    foreach ($candidate in $candidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate)) {
            if ($candidate -eq "npm.cmd") {
                try {
                    & $candidate --version *> $null
                    if ($LASTEXITCODE -eq 0) {
                        return $candidate
                    }
                } catch {
                    continue
                }
            } elseif (Test-Path -LiteralPath $candidate) {
                return $candidate
            }
        }
    }
    return $null
}

Write-Host "==> Build do executavel INFinance (PyInstaller)"

if ([string]::IsNullOrWhiteSpace($PythonExe)) {
    if (Test-Path -LiteralPath ".\.venv\Scripts\python.exe") {
        $PythonExe = ".\.venv\Scripts\python.exe"
    } else {
        $PythonExe = "python"
    }
}

if ($Clean) {
    Write-Host "==> Limpando artefatos anteriores (build/dist)"
    Remove-Item -LiteralPath "build" -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath "dist" -Recurse -Force -ErrorAction SilentlyContinue
}

$npmCmd = Resolve-NpmCmd
if ([string]::IsNullOrWhiteSpace($npmCmd)) {
    throw "Node.js/npm nao encontrado. Instale Node.js para gerar o CSS compilado."
}

Write-Host "==> Gerando CSS compilado (Tailwind)"
$env:npm_config_cache = Join-Path (Get-Location) ".npm-cache"
Invoke-Checked -FilePath $npmCmd -Arguments @("ci")
Invoke-Checked -FilePath $npmCmd -Arguments @("run", "build:css")

Invoke-Checked -FilePath $PythonExe -Arguments @("-m", "pip", "install", "-r", "requirements.txt", "-r", "requirements-build.txt")
Invoke-Checked -FilePath $PythonExe -Arguments @("-m", "PyInstaller", "--noconfirm", "--clean", "infinance.spec")

if (-not (Test-Path -LiteralPath "dist\INFinance\INFinance.exe")) {
    throw "Build concluido sem gerar dist\INFinance\INFinance.exe"
}

Write-Host ""
Write-Host "Executavel pronto em dist\INFinance\INFinance.exe"
