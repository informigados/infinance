param(
    [string]$InnoCompilerPath = ""
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

Write-Host "==> Build do instalador INFinance (Inno Setup)"

$distExe = "dist\INFinance\INFinance.exe"
if (-not (Test-Path -LiteralPath $distExe)) {
    throw "Executavel nao encontrado em $distExe. Rode scripts/build_executable.ps1 antes."
}

if ([string]::IsNullOrWhiteSpace($InnoCompilerPath)) {
    $candidates = @(
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe"
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            $InnoCompilerPath = $candidate
            break
        }
    }
}

if ([string]::IsNullOrWhiteSpace($InnoCompilerPath) -or -not (Test-Path -LiteralPath $InnoCompilerPath)) {
    throw "Inno Setup (ISCC.exe) nao encontrado. Informe com -InnoCompilerPath."
}

Invoke-Checked -FilePath $InnoCompilerPath -Arguments @("installer\INFinance.iss")

if (-not (Test-Path -LiteralPath "dist\installer\INFinance-Setup.exe")) {
    throw "Instalador nao encontrado em dist\installer\INFinance-Setup.exe"
}

Write-Host ""
Write-Host "Instalador pronto em dist\installer\INFinance-Setup.exe"
