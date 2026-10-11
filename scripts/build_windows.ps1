<#
.SYNOPSIS
    Construit dist\LeStitcheurFouCars.exe puis vérifie qu'il démarre.

.DESCRIPTION
    A lancer depuis la racine du dépôt, dans un environnement Python 3.12+ :
        .\scripts\build_windows.ps1
    Options :
        -SkipInstall   ne réinstalle pas les dépendances
        -SkipSmokeTest ne lance pas l'exécutable après le build
        -SoftwareGL    test de démarrage avec le rendu OpenGL logiciel (machines sans GPU)
#>
[CmdletBinding()]
param(
    [switch]$SkipInstall,
    [switch]$SkipSmokeTest,
    [switch]$SoftwareGL
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if ($env:VIRTUAL_ENV) {
    $Python = "python"
} elseif (Test-Path ".venv\Scripts\python.exe") {
    $Python = ".venv\Scripts\python.exe"
} else {
    $Python = "python"
}
Write-Host "Python : $(& $Python --version)"

if (-not $SkipInstall) {
    & $Python -m pip install --upgrade pip
    & $Python -m pip install -e ".[dev]"
    if ($LASTEXITCODE -ne 0) { throw "Installation des dépendances échouée" }
}

# Addon de démonstration embarqué (contenu synthétique, régénéré à chaque build)
& $Python scripts\generate_demo_addon.py
if ($LASTEXITCODE -ne 0) { throw "Génération de l'addon de démonstration échouée" }

if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
& $Python -m PyInstaller --noconfirm --clean packaging\LeStitcheurFouCars.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller a échoué" }

$Exe = Join-Path $Root "dist\LeStitcheurFouCars.exe"
if (-not (Test-Path $Exe)) { throw "Exécutable introuvable : $Exe" }
$SizeMb = [math]::Round((Get-Item $Exe).Length / 1MB, 1)
Write-Host "Exécutable : $Exe ($SizeMb Mo)"

if (-not $SkipSmokeTest) {
    # Dossier de données jetable : le test ne touche pas aux données de l'utilisateur.
    $SmokeHome = Join-Path $env:TEMP "lsfcars-smoke-$(Get-Random)"
    $env:LSFCARS_HOME = $SmokeHome
    $Arguments = @("--smoke-test", "2500")
    if ($SoftwareGL) { $Arguments += "--software-gl" }
    $Process = Start-Process -FilePath $Exe -ArgumentList $Arguments -PassThru -Wait
    Remove-Item Env:\LSFCARS_HOME
    $Log = Join-Path $SmokeHome "logs\lsfcars.log"
    if (Test-Path $Log) {
        Get-Content $Log -Encoding UTF8 | Select-String "Test de démarrage|OpenGL :|import FiveM|ERROR|CRITICAL"
    }
    if ($Process.ExitCode -ne 0) { throw "Test de démarrage échoué (code $($Process.ExitCode))" }
    Write-Host "Test de démarrage réussi."
}
