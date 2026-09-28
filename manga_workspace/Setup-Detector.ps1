param([Parameter(Mandatory=$true)][string]$RuntimeRoot,[string]$DownloadCache='')
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$root=[IO.Path]::GetFullPath($RuntimeRoot)
if(Test-Path -LiteralPath $root){throw 'Destination exists. Choose a new empty runtime folder; existing files are never overwritten.'}
$parent=Split-Path $root
New-Item -ItemType Directory -Force -Path $parent | Out-Null
$stage=Join-Path $parent ('.detector-install-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage | Out-Null
function Fetch($url,$file,$sha){
    $cached=if($DownloadCache){Join-Path $DownloadCache (Split-Path $file -Leaf)}else{''}
    if($cached -and (Test-Path -LiteralPath $cached)) {
        Copy-Item -LiteralPath $cached -Destination $file
    } elseif(Get-Command curl.exe -ErrorAction SilentlyContinue) {
        & curl.exe -L --fail --max-time 300 $url -o $file
        if($LASTEXITCODE -ne 0){throw 'Download failed'}
    } else {
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $file -TimeoutSec 300
    }
    if((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLower() -ne $sha){throw "Checksum mismatch: $file"}
}
try {
    Write-Output 'Downloading isolated Python...'
    Fetch 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip' (Join-Path $stage 'python.zip') '4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3'
    $runtime=Join-Path $stage 'python'
    Expand-Archive -LiteralPath (Join-Path $stage 'python.zip') -DestinationPath $runtime
    [IO.File]::WriteAllText((Join-Path $runtime 'python312._pth'), "python312.zip`n.`nLib/site-packages`nimport site`n")
    Fetch 'https://bootstrap.pypa.io/get-pip.py' (Join-Path $stage 'get-pip.py') 'fb24e693bab954209a063d90953621412ccad4a500905a726286e038f508ddf6'
    $python=Join-Path $runtime 'python.exe'
    & $python -I (Join-Path $stage 'get-pip.py') --no-warn-script-location
    if($LASTEXITCODE -ne 0){throw 'pip setup failed'}
    & $python -I -m pip --isolated install --index-url https://pypi.org/simple --only-binary=:all: --no-warn-script-location 'onnxruntime==1.22.1' 'numpy==2.2.6' 'Pillow==11.3.0'
    if($LASTEXITCODE -ne 0){throw 'Detector dependency setup failed'}
    Write-Output 'Downloading detection model (250 MB)...'
    Fetch 'https://huggingface.co/tori29umai/rtdetrv4-x-manga109s/resolve/717acd6efd5362e830c7d2d8be5f74a7a5f56282/model.onnx' (Join-Path $stage 'model.onnx') 'fba50583bfaaba3eed33f3eac6ca37be09b8c4882bac05da93f96697010a45b1'
    & $python -I -c 'import onnxruntime,numpy,PIL'
    if($LASTEXITCODE -ne 0){throw 'Runtime validation failed'}
    [IO.File]::WriteAllText((Join-Path $stage 'runtime.json'), '{"version":1,"python":"3.12.10","detector":"rtdetrv4-x-manga109s"}')
    # Both paths are explicit siblings under the chosen parent. Rename only this unique stage.
    Move-Item -LiteralPath $stage -Destination $root
    Write-Output 'Detector installation completed. Existing Python environments were not modified.'
} catch {
    Write-Error "Installation failed. Existing installations are untouched. Partial files remain at $stage. $_"
    exit 1
}
