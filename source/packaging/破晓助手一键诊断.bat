@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
set "RLH_DIAG_SELF=%~f0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$s=[IO.File]::ReadAllText($env:RLH_DIAG_SELF,[Text.Encoding]::UTF8); $m='# === LOOT_HELPER_DIAGNOSTIC_POWERSHELL ==='; & ([ScriptBlock]::Create($s.Substring($s.LastIndexOf($m)+$m.Length)))"
set "RLH_DIAG_EXIT=%ERRORLEVEL%"
if not "%RLH_DIAG_EXIT%"=="0" echo Diagnostic did not finish. Please send a screenshot of this window.
if not "%RLH_DIAG_NO_PAUSE%"=="1" pause
exit /b %RLH_DIAG_EXIT%
# === LOOT_HELPER_DIAGNOSTIC_POWERSHELL ===
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$utf8 = New-Object System.Text.UTF8Encoding($false)
$appName = '破晓装备助手'
$notes = New-Object 'System.Collections.Generic.List[string]'
$missing = New-Object 'System.Collections.Generic.List[string]'
$collected = New-Object 'System.Collections.Generic.List[object]'
$work = $null

function Protect-Text([string]$Text) {
    foreach ($pair in @(@($env:LOCALAPPDATA, '[LOCALAPPDATA]'), @($env:USERPROFILE, '[USERPROFILE]'))) {
        if (-not [string]::IsNullOrWhiteSpace($pair[0])) {
            foreach ($value in @($pair[0].Replace('\', '\\'), $pair[0].Replace('\', '/'), $pair[0])) {
                $Text = [regex]::Replace($Text, [regex]::Escape($value), $pair[1], 'IgnoreCase')
            }
        }
    }
    return $Text
}

function Save-Text([string]$Name, [string]$Text) {
    [IO.File]::WriteAllText((Join-Path $work $Name), (Protect-Text $Text), $utf8)
}

function Get-AppProcesses([string]$Name) {
    foreach ($process in @(Get-Process -Name $Name -ErrorAction SilentlyContinue)) {
        $info = [ordered]@{pid=$process.Id; name=$process.ProcessName; path=$null; started=$null;
            main_window_handle=$null; main_window_title=$null; responding=$null}
        try {
            $info.path = $process.Path
            $info.started = $process.StartTime.ToString('o')
            $info.main_window_handle = $process.MainWindowHandle.ToInt64()
            $info.main_window_title = $process.MainWindowTitle
            $info.responding = $process.Responding
        } catch { $notes.Add('进程详情部分不可读：' + $_.Exception.Message) }
        [pscustomobject]$info
        $process.Dispose()
    }
}

function Get-RelatedEvents([string]$Log, [int[]]$Ids, [int]$Limit) {
    if ($env:RLH_DIAG_SKIP_EVENTS -eq '1') {
        return [ordered]@{status='skipped_for_test'; events=@()}
    }
    try {
        $events = @(Get-WinEvent -FilterHashtable @{LogName=$Log; Id=$Ids; StartTime=(Get-Date).AddDays(-7)} -MaxEvents $Limit -ErrorAction Stop)
        $matched = @($events | Where-Object {
            $_.Message -match '破晓装备助手|RuinsLootHelper|loot_app\.py'
        } | Select-Object -First 30 | ForEach-Object {
            [ordered]@{time=$_.TimeCreated.ToString('o'); id=$_.Id; provider=$_.ProviderName; message=$_.Message}
        })
        return [ordered]@{status='read'; days=7; scanned=$events.Count; scan_limit=$Limit; limit_reached=($events.Count -eq $Limit); events=$matched}
    } catch {
        if ($_.FullyQualifiedErrorId -like 'NoMatchingEventsFound*') {
            return [ordered]@{status='no_events_in_query'; days=7; events=@()}
        }
        $notes.Add('部分 Windows 记录无法读取（不会要求提权）：' + $Log + '；' + $_.Exception.Message)
        return [ordered]@{status='unavailable'; error=$_.Exception.Message; events=@()}
    }
}

try {
    Write-Host '破晓装备助手 · 一键诊断' -ForegroundColor Cyan
    Write-Host '正在收集状态和错误记录，请保持这个窗口打开。'
    Write-Host '只读取助手相关信息，生成本地 ZIP；不会启动、关闭或修改游戏和助手。'
    Write-Host ''
    $batDirectory = Split-Path -LiteralPath $env:RLH_DIAG_SELF
    $data = if ($env:RLH_DIAG_DATA_DIR) { $env:RLH_DIAG_DATA_DIR } else { Join-Path $env:LOCALAPPDATA 'RuinsLootHelper' }
    $desktop = [Environment]::GetFolderPath('Desktop')
    $outputRoots = if ($env:RLH_DIAG_OUTPUT_DIR) { @($env:RLH_DIAG_OUTPUT_DIR) } else { @($desktop, $batDirectory, $env:TEMP) }
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $zipName = '破晓助手诊断-' + $stamp + '-' + [guid]::NewGuid().ToString('N').Substring(0,6) + '.zip'
    $work = Join-Path ([IO.Path]::GetTempPath()) ('RuinsLootDiagnostic-' + [guid]::NewGuid().ToString('N'))
    $null = New-Item -ItemType Directory -Path $work
    $helpers = @(Get-AppProcesses $appName)
    $games = @(Get-AppProcesses 'RuinsOfDawn-Win64-Shipping')
    Write-Host '[1/4] 收集助手日志和运行状态……'
    # Explicit allowlist: never include equipment inventories, saves or arbitrary files.
    $allowed = @('startup-error.txt', 'overlay-status.json', 'continuous-status.json',
        'feature-status.json', 'app-settings.json', 'loot-overlay-settings.json',
        'ui-error.json', 'worker-error.txt', 'native-status.json')
    foreach ($name in $allowed) {
        $path = Join-Path $data $name
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { $missing.Add($name); continue }
        try {
            $item = Get-Item -LiteralPath $path
            if ($item.Length -gt 2MB) { $notes.Add($name + ' 超过 2 MB，已跳过。'); continue }
            $content = $null
            for ($attempt=0; $attempt -lt 3; $attempt++) {
                try { $content = [IO.File]::ReadAllText($path, [Text.Encoding]::UTF8); break }
                catch { if ($attempt -eq 2) { throw }; Start-Sleep -Milliseconds 50 }
            }
            Save-Text $name $content
            $collected.Add([ordered]@{name=$name; source_modified=$item.LastWriteTime.ToString('o'); bytes=$item.Length})
        } catch { $notes.Add($name + ' 读取失败：' + $_.Exception.Message) }
    }

    Write-Host '[2/4] 检查系统、显示器和助手文件……'
    $system = [ordered]@{os_build=[Environment]::OSVersion.Version.ToString(); os_64bit=[Environment]::Is64BitOperatingSystem;
        powershell=$PSVersionTable.PSVersion.ToString(); process_64bit=[Environment]::Is64BitProcess; displays=@()}
    try {
        $windows = Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
        $system.windows_release = $windows.DisplayVersion
        $system.windows_build = $windows.CurrentBuild
        $system.windows_revision = $windows.UBR
        Add-Type -AssemblyName System.Windows.Forms
        $system.displays = @([Windows.Forms.Screen]::AllScreens | ForEach-Object {
            [ordered]@{primary=$_.Primary; bounds=@($_.Bounds.X,$_.Bounds.Y,$_.Bounds.Width,$_.Bounds.Height);
                working_area=@($_.WorkingArea.X,$_.WorkingArea.Y,$_.WorkingArea.Width,$_.WorkingArea.Height)}
        })
    } catch { $notes.Add('系统或显示器信息部分不可读：' + $_.Exception.Message) }

    $exe = Join-Path $batDirectory ($appName + '.exe')
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
        $exe = $helpers | Where-Object { $_.path } | Select-Object -First 1 -ExpandProperty path
    }
    $package = [ordered]@{exe_found=$false; checked_files=@()}
    if ($exe -and (Test-Path -LiteralPath $exe -PathType Leaf)) {
        try {
            $package.exe_found = $true
            $package.exe_path = $exe
            $package.exe_sha256 = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash
            $package.exe_version = [Diagnostics.FileVersionInfo]::GetVersionInfo($exe).FileVersion
            $packageRoot = Split-Path -LiteralPath $exe
            $package.checked_files = @('python311.dll', '_tkinter.pyd', 'tcl86t.dll', 'tk86t.dll',
                'base_library.zip', 'catalog\filter-catalog.json', 'catalog\skill-names.json') | ForEach-Object {
                $candidate = Join-Path (Join-Path $packageRoot '_internal') $_
                [ordered]@{file=('_internal\' + $_); present=(Test-Path -LiteralPath $candidate -PathType Leaf)}
            }
        } catch { $notes.Add('助手文件检查部分失败：' + $_.Exception.Message) }
    } else { $notes.Add('未找到助手 EXE；如需核对安装文件，请把 BAT 放在 EXE 旁再运行。') }

    Write-Host '[3/4] 查询最近 7 天与助手有关的 Windows 记录……'
    $application = Get-RelatedEvents 'Application' @(1000,1001,1002,1026) 500
    $defender = Get-RelatedEvents 'Microsoft-Windows-Windows Defender/Operational' @(1116,1117) 200
    $observation = if ($helpers.Count -gt 0) {
        '采集时助手进程仍在运行。如果看不到窗口，应优先检查窗口显示；这不代表读取功能一定正常。'
    } else {
        '采集时没有发现助手进程。需要结合错误记录判断是否崩溃；尚未启动和正常关闭也会出现这个状态。'
    }
    $report = [ordered]@{
        tool_version='1.0'; generated_local=(Get-Date).ToString('o'); generated_utc=[DateTime]::UtcNow.ToString('o');
        observation=$observation; data_directory=$data; system=$system; helper_processes=$helpers; game_processes=$games;
        package=$package; collected_files=@($collected.ToArray()); missing_files=@($missing.ToArray());
        application_events=$application; defender_events=$defender; notes=@($notes.ToArray())
    }
    Save-Text 'report.json' (ConvertTo-Json -InputObject $report -Depth 12)
    $readme = @(
        '破晓装备助手诊断包', ('采集时间：' + (Get-Date).ToString('yyyy-MM-dd HH:mm:ss zzz')), '',
        $observation, ('助手进程数：' + $helpers.Count), ('游戏进程数：' + $games.Count),
        ('相关 Windows 应用事件数：' + @($application.events).Count),
        ('相关 Windows Defender 事件数：' + @($defender.events).Count), '',
        ('已收集：' + (($collected | ForEach-Object { $_.name }) -join '、')),
        ('未找到的日志：' + ($missing.ToArray() -join '、')), '',
        '请将整个 ZIP 发给装备助手维护者，无需逐个打开文件。',
        '未找到日志并不等于没有发生崩溃；底层崩溃可能只在 Windows 事件中留痕。',
        '事件查询范围为最近 7 天，应用事件最多检查 500 条，Defender 事件最多检查 200 条，仅保留与助手名称匹配的记录。',
        '没有收集装备列表、游戏存档或其他应用日志；当前 Windows 用户目录路径已替换为占位符。', '',
        '采集说明：', ($notes.ToArray() -join [Environment]::NewLine)
    ) -join [Environment]::NewLine
    Save-Text '诊断说明.txt' $readme

    Write-Host '[4/4] 生成 ZIP……'
    $zipPath = $null
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    foreach ($output in $outputRoots) {
        if ([string]::IsNullOrWhiteSpace($output)) { continue }
        try {
            $null = [IO.Directory]::CreateDirectory($output)
            $candidate = Join-Path $output $zipName
            [IO.Compression.ZipFile]::CreateFromDirectory($work, $candidate, [IO.Compression.CompressionLevel]::Optimal, $false, [Text.Encoding]::UTF8)
            $check = [IO.Compression.ZipFile]::OpenRead($candidate)
            try {
                if (-not ($check.Entries | Where-Object { $_.FullName -eq 'report.json' })) { throw '诊断包缺少报告。' }
            } finally { $check.Dispose() }
            $zipPath = $candidate
            break
        } catch { Write-Host ('这个保存位置不可用，尝试下一个：' + $_.Exception.Message) -ForegroundColor Yellow }
    }
    if (-not $zipPath) { throw ('无法生成 ZIP，已采集的文件仍在：' + $work) }

    # Remove only our uniquely-created temporary report directory after ZIP verification.
    try {
        $resolved = [IO.Path]::GetFullPath($work).TrimEnd('\')
        $expectedParent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
        if ([IO.Directory]::GetParent($resolved).FullName.TrimEnd('\') -eq $expectedParent -and
            [IO.Path]::GetFileName($resolved) -match '^RuinsLootDiagnostic-[a-f0-9]{32}$') {
            Remove-Item -LiteralPath $resolved -Recurse -Force
        }
    } catch { Write-Host 'ZIP 已生成；临时文件暂未清理。' -ForegroundColor Yellow }
    Write-Host ''
    Write-Host '诊断包已生成。把下面这个 ZIP 发回来即可：' -ForegroundColor Green
    Write-Host $zipPath -ForegroundColor Cyan
    if ($env:RLH_DIAG_NO_UI -ne '1') {
        try { Start-Process -FilePath explorer.exe -ArgumentList ('/select,"' + $zipPath + '"') }
        catch { Write-Host '无法自动打开文件夹，请按上面的路径找到 ZIP。' }
    }
    exit 0
} catch {
    Write-Host ''
    Write-Host ('诊断未完成：' + $_.Exception.Message) -ForegroundColor Red
    Write-Host $_.ScriptStackTrace
    Write-Host '请把这个窗口的错误截图发回来。窗口会保留，不会自动关闭。'
    exit 1
}
