@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
echo 正在读取本机微信标识，请稍候…
echo 请先打开并登录要交付的那个微信。不需要做微信读取初始化。
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$out = Join-Path -Path '%~dp0' -ChildPath '本机wxid.txt';" ^
  "$now = Get-Date -Format 'yyyy-MM-dd HH:mm:ss';" ^
  "$skip = @('all_users','Backup','backup','old_backup','WMPF','wmpf','Message','Radium','radium');" ^
  "function Ident-FromFolder([string]$name) {" ^
  "  $lower = $name.Trim().ToLowerInvariant();" ^
  "  if ($lower.StartsWith('wxid_') -and $lower -match '^wxid_[a-z0-9]+_[a-z0-9]{2,6}$') { return ($lower -replace '_[^_]+$','') }" ^
  "  return $lower" ^
  "}" ^
  "$roots = New-Object System.Collections.Generic.List[string];" ^
  "function Add-Root([string]$p) { if ($p -and (Test-Path -LiteralPath $p -PathType Container) -and -not $roots.Contains($p)) { [void]$roots.Add($p) } }" ^
  "Add-Root ([IO.Path]::Combine([Environment]::GetFolderPath('MyDocuments'), 'xwechat_files'));" ^
  "Add-Root ([IO.Path]::Combine($env:USERPROFILE, 'Documents', 'xwechat_files'));" ^
  "Add-Root ([IO.Path]::Combine($env:USERPROFILE, 'xwechat_files'));" ^
  "Add-Root ([IO.Path]::Combine([Environment]::GetFolderPath('MyDocuments'), 'WeChat Files'));" ^
  "Add-Root ([IO.Path]::Combine($env:USERPROFILE, 'Documents', 'WeChat Files'));" ^
  "$accounts = @();" ^
  "foreach ($root in $roots) {" ^
  "  Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue | ForEach-Object {" ^
  "    if ($skip -contains $_.Name) { return }" ^
  "    $accounts += [pscustomobject]@{ Folder=$_.Name; Stamp=$_.LastWriteTimeUtc.Ticks; Id=(Ident-FromFolder $_.Name) }" ^
  "  }" ^
  "}" ^
  "$lines = New-Object System.Collections.Generic.List[string];" ^
  "[void]$lines.Add('Judy · 本机微信标识');" ^
  "[void]$lines.Add('时间：' + $now);" ^
  "[void]$lines.Add('');" ^
  "$current = '';" ^
  "if ($roots.Count -eq 0) {" ^
  "  [void]$lines.Add('未找到微信数据目录。请先打开并登录电脑微信，稍等半分钟后再双击本脚本。');" ^
  "} elseif ($accounts.Count -eq 0) {" ^
  "  [void]$lines.Add('已找到微信数据目录，但没有账号文件夹。请先打开并登录电脑微信后再运行。');" ^
  "} else {" ^
  "  $sorted = $accounts | Sort-Object Stamp -Descending;" ^
  "  $cur = $sorted[0];" ^
  "  $current = $cur.Id;" ^
  "  [void]$lines.Add('当前登录（请把这一行发给实施人员）：');" ^
  "  [void]$lines.Add($current);" ^
  "  [void]$lines.Add('');" ^
  "  [void]$lines.Add('数据目录：' + $cur.Folder);" ^
  "  $others = @($sorted | Select-Object -Skip 1);" ^
  "  if ($others.Count -gt 0) {" ^
  "    [void]$lines.Add('');" ^
  "    [void]$lines.Add('本机还发现这些账号目录（不一定是当前登录）：');" ^
  "    foreach ($item in $others) { [void]$lines.Add('  ' + $item.Id + '  (目录 ' + $item.Folder + ')') }" ^
  "  }" ^
  "}" ^
  "[void]$lines.Add('');" ^
  "[void]$lines.Add('只发给实施人员，不要发到群里。');" ^
  "$text = [string]::Join([Environment]::NewLine, $lines);" ^
  "[IO.File]::WriteAllText($out, $text + [Environment]::NewLine, [Text.UTF8Encoding]::new($false));" ^
  "Write-Output $text;" ^
  "Write-Output '';" ^
  "if ($current) { Set-Clipboard -Value $current; Write-Output ('已复制到剪贴板：' + $current) }" ^
  "Write-Output ('结果已保存：' + $out)"
echo.
pause
endlocal
