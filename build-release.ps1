param([string]$Version='0.5.1-alpha')
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $MyInvocation.MyCommand.Path
$release=Join-Path $root 'release'
$stage=Join-Path $release ('.stage-'+[guid]::NewGuid().ToString('N'))
$package=Join-Path $release ("manga-workspace-$Version.zip")
New-Item -ItemType Directory -Force -Path $release,$stage | Out-Null
try {
    Copy-Item -LiteralPath (Join-Path $root 'manga_workspace.desktop') -Destination $stage
    Copy-Item -LiteralPath (Join-Path $root 'manga_workspace') -Destination $stage -Recurse
    Get-ChildItem -LiteralPath (Join-Path $stage 'manga_workspace') -Directory -Recurse |
        Where-Object Name -eq '__pycache__' | Remove-Item -Recurse -Force
    Get-ChildItem -LiteralPath (Join-Path $stage 'manga_workspace') -File -Recurse |
        Where-Object Extension -eq '.pyc' | Remove-Item -Force
    foreach($name in 'README.md','LICENSE','THIRD_PARTY_NOTICES.md','CHANGELOG.md') {
        Copy-Item -LiteralPath (Join-Path $root $name) -Destination $stage
    }
    if(Test-Path -LiteralPath $package){Remove-Item -LiteralPath $package -Force}
    Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $package -CompressionLevel Optimal
    $hash=(Get-FileHash -LiteralPath $package -Algorithm SHA256).Hash.ToLower()
    Set-Content -LiteralPath (Join-Path $release 'SHA256SUMS.txt') -Encoding ascii -Value "$hash  $(Split-Path $package -Leaf)"
    Write-Output $package
    Write-Output $hash
} finally {
    if(Test-Path -LiteralPath $stage){Remove-Item -LiteralPath $stage -Recurse -Force}
}
