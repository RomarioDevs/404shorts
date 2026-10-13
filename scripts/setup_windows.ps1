$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path "$PSScriptRoot\.."
$PythonLauncher = Get-Command py -ErrorAction SilentlyContinue
$Python311 = $null
if ($PythonLauncher) {
    $Python311 = (& $PythonLauncher.Source -3.11 -c "import sys; print(sys.executable)" 2>$null)
}
if (-not $Python311) {
    $KnownPython = "$env:LocalAppData\Programs\Python\Python311\python.exe"
    if (Test-Path -LiteralPath $KnownPython) { $Python311 = $KnownPython }
}
if (-not $Python311 -or -not (Test-Path -LiteralPath $Python311)) {
    throw "Python 3.11 x64 não encontrado. Execute instalar.bat ou instale Python 3.11 x64."
}
$PythonInfo = & $Python311 -c "import struct,sys; print(f'{sys.version_info.major}.{sys.version_info.minor} {struct.calcsize(chr(80))*8}-bit')"
if ($LASTEXITCODE -ne 0 -or $PythonInfo -ne "3.11 64-bit") {
    throw "É necessário CPython 3.11 de 64 bits. Encontrado: $PythonInfo"
}

if (-not (Test-Path -LiteralPath "$ProjectRoot\.venv")) {
    & $Python311 -m venv "$ProjectRoot\.venv"
}

& "$ProjectRoot\.venv\Scripts\python.exe" -m pip install --use-feature=truststore "setuptools>=75"
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar setuptools." }
& "$ProjectRoot\.venv\Scripts\python.exe" -m pip install --use-feature=truststore --no-build-isolation -e "${ProjectRoot}[dev]"
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar o CortaFlow ou suas dependências." }
