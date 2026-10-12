# Installation du moteur local TripoSR (licence MIT) pour LeStitcheurFou Cars.
#
# Rien n'est installé dans l'application ni dans le dépôt : tout va dans <EnginesDir>\triposr.
# Téléchargements (environ 5 à 6 Go au total) :
#   - uv (gestionnaire Python, via pip) et Python 3.12 (python-build-standalone) ;
#   - PyTorch (download.pytorch.org : CUDA 12.8 si un GPU NVIDIA est détecté, sinon CPU) ;
#   - dépendances (omegaconf, einops, transformers, huggingface-hub, trimesh, PyMCubes, Pillow) ;
#   - code TripoSR (archive GitHub VAST-AI-Research/TripoSR, MIT) ;
#   - poids stabilityai/TripoSR (config.yaml, model.ckpt ~1,7 Go) et configuration DINO ;
#   - détourage : onnxruntime (PyPI) et modèle U²-Net u2net.onnx (~176 Mo, GitHub
#     danielgatis/rembg, Apache-2.0), contrôlé par empreinte MD5.
#
# Le script est relançable : les étapes déjà faites sont sautées (ajout du détourage à une
# installation existante, par exemple).
#
# Usage : powershell -ExecutionPolicy Bypass -File scripts\install_triposr.ps1 [-EnginesDir <dossier>] [-Cpu]

param(
    [string]$EnginesDir = $(if ($env:LSFCARS_ENGINES) { $env:LSFCARS_ENGINES } else { Join-Path $env:USERPROFILE ".lestitcheurfoucars\engines" }),
    [switch]$Cpu
)

$ErrorActionPreference = "Stop"
$Root = Join-Path $EnginesDir "triposr"
$Tools = Join-Path $EnginesDir "tools"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $EnginesDir "python"
$env:UV_CACHE_DIR = Join-Path $EnginesDir "uv-cache"

function Step($index, $text) { Write-Output "LSF_STEP $index/8 $text" }

New-Item -ItemType Directory -Force $Root | Out-Null

Step 1 "Préparation de uv"
if (-not (Test-Path (Join-Path $Tools "Scripts\uv.exe"))) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if (-not $launcher) { throw "Python (lanceur « py ») introuvable : installez Python 3.12+ depuis python.org." }
    & py -3 -m venv $Tools
    & (Join-Path $Tools "Scripts\python.exe") -m pip install --quiet uv
}
$Uv = Join-Path $Tools "Scripts\uv.exe"

Step 2 "Python 3.12 et environnement du moteur"
& $Uv python install 3.12
if (-not (Test-Path (Join-Path $Root "env\Scripts\python.exe"))) {
    & $Uv venv --python 3.12 --managed-python (Join-Path $Root "env")
}
$Python = Join-Path $Root "env\Scripts\python.exe"

Step 3 "PyTorch"
$gpu = (Get-Command nvidia-smi -ErrorAction SilentlyContinue) -and -not $Cpu
$index = if ($gpu) { "https://download.pytorch.org/whl/cu128" } else { "https://download.pytorch.org/whl/cpu" }
& $Uv pip install --python $Python torch --index-url $index

Step 4 "Dépendances"
& $Uv pip install --python $Python "omegaconf==2.3.0" "einops==0.7.0" "transformers==4.46.3" "huggingface-hub<1.0" trimesh PyMCubes imageio Pillow "numpy<2.4"

Step 5 "Code TripoSR"
if (-not (Test-Path (Join-Path $Root "src\tsr\system.py"))) {
    $zip = Join-Path $Root "triposr.zip"
    Invoke-WebRequest "https://github.com/VAST-AI-Research/TripoSR/archive/refs/heads/main.zip" -OutFile $zip
    Expand-Archive $zip -DestinationPath $Root -Force
    Move-Item (Join-Path $Root "TripoSR-main") (Join-Path $Root "src")
    Remove-Item $zip
}

Step 6 "Poids du modèle"
$env:HF_HOME = Join-Path $Root "hf"
$weights = Join-Path $Root "weights"
& $Python -c "from huggingface_hub import hf_hub_download as d; [d('stabilityai/TripoSR', f, local_dir=r'$weights') for f in ('config.yaml', 'model.ckpt')]; d('facebook/dino-vitb16', 'config.json')"

Step 7 "Détourage neuronal (U²-Net)"
& $Uv pip install --python $Python onnxruntime
$models = Join-Path $Root "models"
$u2net = Join-Path $models "u2net.onnx"
$expected = "60024c5c889badc19c04ad937298a77b"  # empreinte publiée par le projet rembg
if (-not (Test-Path $u2net) -or (Get-FileHash $u2net -Algorithm MD5).Hash.ToLower() -ne $expected) {
    New-Item -ItemType Directory -Force $models | Out-Null
    Invoke-WebRequest "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx" -OutFile $u2net
    if ((Get-FileHash $u2net -Algorithm MD5).Hash.ToLower() -ne $expected) {
        Remove-Item $u2net
        throw "Modèle U²-Net corrompu (empreinte MD5 inattendue) : téléchargement supprimé."
    }
}

Step 8 "Vérification"
& $Python -c "import torch, mcubes, omegaconf, einops, transformers, onnxruntime; print('torch', torch.__version__, 'cuda', torch.cuda.is_available(), 'onnxruntime', onnxruntime.__version__)"
Write-Output "LSF_DONE $Root"
