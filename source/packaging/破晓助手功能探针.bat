@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
set "RLH_PROBE_SELF=%~f0"
set "RLH_PROBE_PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if defined PROCESSOR_ARCHITEW6432 set "RLH_PROBE_PS=%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
"%RLH_PROBE_PS%" -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$s=[IO.File]::ReadAllText($env:RLH_PROBE_SELF,[Text.Encoding]::UTF8); $m='# === RUINS_FEATURE_PROBE ==='; & ([ScriptBlock]::Create($s.Substring($s.LastIndexOf($m)+$m.Length)))"
set "RLH_PROBE_EXIT=%ERRORLEVEL%"
if not "%RLH_PROBE_EXIT%"=="0" echo Probe failed. Please send the error shown above.
if not "%RLH_PROBE_NO_PAUSE%"=="1" pause
exit /b %RLH_PROBE_EXIT%
# === RUINS_FEATURE_PROBE ===
$ErrorActionPreference = 'Stop'
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8
$logPath = $null
$samples = New-Object 'System.Collections.Generic.List[object]'
$findings = New-Object 'System.Collections.Generic.List[string]'
$notes = New-Object 'System.Collections.Generic.List[string]'
$games = @()
$helpers = @()
$nativeRoot = $null

function Protect-Text([string]$Text) {
    foreach ($pair in @(@($env:LOCALAPPDATA, '[LOCALAPPDATA]'), @($env:USERPROFILE, '[USERPROFILE]'))) {
        if ([string]::IsNullOrWhiteSpace($pair[0])) { continue }
        foreach ($source in @($pair[0].Replace('\','\\'), $pair[0].Replace('\','/'), $pair[0])) {
            $Text = [regex]::Replace($Text, [regex]::Escape($source), $pair[1], 'IgnoreCase')
        }
    }
    return $Text
}
function Log([string]$Text) {
    [IO.File]::AppendAllText($logPath, (Protect-Text $Text) + [Environment]::NewLine, $utf8)
}
function Log-Json([string]$Title, $Value) {
    Log ('--- ' + $Title + ' ---')
    Log (ConvertTo-Json -InputObject $Value -Depth 15)
}
function Finding([string]$Text) {
    if (-not $findings.Contains($Text)) { $findings.Add($Text) }
}
function Select-Fields($Value, [string[]]$Names) {
    $result = [ordered]@{}
    foreach ($name in $Names) {
        if ($null -ne $Value -and $null -ne $Value.PSObject.Properties[$name]) { $result[$name] = $Value.$name }
    }
    return [pscustomobject]$result
}
function Count-Items($Value) {
    return @($Value | Where-Object { $null -ne $_ }).Count
}
function Age($Value, [switch]$Unix) {
    if ($null -eq $Value) { return $null }
    try {
        $stamp = if ($Unix) { [DateTimeOffset]::FromUnixTimeMilliseconds([long]([double]$Value * 1000)) }
                 else { [DateTimeOffset]::Parse([string]$Value) }
        return [math]::Round(([DateTimeOffset]::UtcNow - $stamp).TotalSeconds, 3)
    } catch { return $null }
}
function Fresh($Value, [double]$Limit) {
    return $null -ne $Value -and $Value -ge 0 -and $Value -lt $Limit
}
function Read-State([string]$Name) {
    $path = Join-Path $dataDirectory $Name
    $result = [ordered]@{name=$Name; found=$false; ok=$false; modified_utc=$null; value=$null; error=$null}
    try {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return [pscustomobject]$result }
        $result.found = $true
        $item = Get-Item -LiteralPath $path
        $result.modified_utc = $item.LastWriteTimeUtc.ToString('o')
        if ($item.Length -gt 2MB) { throw '超过 2 MB，未读取' }
        for ($attempt=0; $attempt -lt 3; $attempt++) {
            try {
                $result.value = ConvertFrom-Json -InputObject ([IO.File]::ReadAllText($path, [Text.Encoding]::UTF8))
                if ($null -eq $result.value) { throw 'JSON 内容为空' }
                $result.ok = $true
                break
            } catch {
                if ($attempt -eq 2) { throw }
                Start-Sleep -Milliseconds 60
            }
        }
    } catch { $result.error = $_.Exception.Message }
    return [pscustomobject]$result
}
function Inspect-Process($Process) {
    $row = [ordered]@{pid=$Process.Id; name=$Process.ProcessName; path=$null; started_utc=$null; elevated=$null; error=$null}
    try {
        $detail = [RuinsProbeReadOnly]::Inspect($Process.Id)
        $row.path = $detail.Path
        $row.elevated = $detail.Elevated
        $row.error = $detail.Error
        $row.started_utc = $Process.StartTime.ToUniversalTime().ToString('o')
    } catch { $row.error = $_.Exception.Message }
    return [pscustomobject]$row
}
function Snapshot {
    $files = @{}
    foreach ($name in @('continuous-status.json','feature-status.json','overlay-status.json','native-status.json',
        'native-request.json','native-schema.json','loot-overlay-settings.json','loot-filter-rules.json',
        'current-loot.json','matches-current.json')) { $files[$name] = Read-State $name }
    $c=$files['continuous-status.json'].value; $f=$files['feature-status.json'].value
    $o=$files['overlay-status.json'].value; $n=$files['native-status.json'].value
    $r=$files['native-request.json'].value; $s=$files['loot-overlay-settings.json'].value
    $inventory=$files['current-loot.json'].value; $m=$files['matches-current.json'].value
    $schema=$files['native-schema.json'].value
    $selected = @($files['loot-filter-rules.json'].value | Where-Object { $null -ne $_ -and $_.enabled -ne $false } |
        ForEach-Object { Select-Fields $_ @('key','label','group','field','min','unit','enabled') })
    $ageReader=Age $c.heartbeat_utc; $ageNative=Age $n.utc -Unix
    $requestAge=Age $r.expires -Unix
    $requestFresh=$null -ne $requestAge -and $requestAge -gt -2 -and $requestAge -lt 0
    $foreground = $null
    if ($env:RLH_PROBE_SKIP_SYSTEM -ne '1') {
        try { $foreground = [RuinsProbeReadOnly]::ForegroundPid() } catch {}
    }
    $checks=[ordered]@{
        reader_fresh=(Fresh $ageReader 3); native_fresh=(Fresh $ageNative 2)
        request_not_expired=$requestFresh
        protocol_matches=($null -ne $r.protocol -and $r.protocol -eq $n.protocol)
        session_matches=($null -ne $r.session -and $r.session -eq $n.session)
        game_pid_matches=($r.game_pid -gt 0 -and $r.game_pid -eq $n.game_pid)
        player_matches=($r.player_address -gt 0 -and $r.player_address -eq $n.player_address)
        schema_pid_matches=($c.game_pid -gt 0 -and $c.game_pid -eq $schema.pid)
        game_is_foreground=($null -ne $foreground -and $c.game_pid -gt 0 -and $c.game_pid -eq $foreground)
    }
    $row=[pscustomobject][ordered]@{
        sampled_utc=[DateTimeOffset]::UtcNow.ToString('o')
        ages_seconds=@{reader=$ageReader; native=$ageNative; request_expired_for=$requestAge}
        checks=$checks
        saved_native_settings=$s.native
        selected_rules=$selected
        reader=(Select-Fields $c @('status','game_pid','worker_pid','heartbeat_utc','error','detail'))
        ui=(Select-Fields $f.ui @('valid','backpack_open','blocked','blocked_by'))
        ui_reader=(Select-Fields $f @('status','heartbeat_utc','error'))
        overlay=(Select-Fields $o @('status','pid','live','numeric_matches','legendary_matches','lower_matches',
            'marker_status','marker_slots','include_locked','last_error','error','heartbeat_utc'))
        request=(Select-Fields $r @('protocol','game_pid','active','pickup','auto_lock','auto_recycle',
            'pickup_radius','pickup_interval','pickup_batch','recycle_wait'))
        requested_locks=(Count-Items $r.locks)
        native=(Select-Fields $n @('protocol','game_pid','state','ready','pickup_state','recycle_state',
            'free_slots','backpack_open','error','grid_error','auto_recycle_supported'))
        acknowledgements=@($n.acks | Where-Object {$null -ne $_} | Select-Object -Last 8 |
            ForEach-Object { $_.result })
        inventory=@{status=$inventory.status; sampled_utc=$inventory.sampled_utc;
            equipment_count=(Count-Items $inventory.items); free_slots=$inventory.backpack_free_slots}
        matches=@{live=$m.live; numeric=(Count-Items $m.numeric); legendary=(Count-Items $m.legendary);
            lower=(Count-Items $m.lower)}
        stop_flags=@{reader=(Test-Path -LiteralPath (Join-Path $dataDirectory 'stop.flag'));
            overlay=(Test-Path -LiteralPath (Join-Path $dataDirectory 'overlay-stop.flag'))}
        files=@($files.Values | Sort-Object name | ForEach-Object { Select-Fields $_ @('name','found','ok','modified_utc','error') })
    }
    return $row
}
function Summarize($Rows) {
    $last = $Rows[$Rows.Count-1]
    $ready = @($Rows | Where-Object { $_.checks.native_fresh -and $_.checks.request_not_expired -and
        $_.checks.session_matches -and $_.checks.protocol_matches -and $_.checks.game_pid_matches -and
        $_.checks.player_matches -and $_.native.ready })
    if ($ready.Count) { Finding '观察期间，助手与当前游戏组件的通信链路曾正常接通。' }
    else { Finding '观察期间没有捕获到完整、有效的组件连接；查看下方具体状态。' }
    if ($last.saved_native_settings.pickup -ne $true) { Finding '已保存配置中，自动拾取未开启或配置未读到；界面勾选后需点“应用”。' }
    if ($last.saved_native_settings.lock -ne $true) { Finding '已保存配置中，自动锁定未开启或配置未读到；界面勾选后需点“应用”。' }
    if ($last.stop_flags.reader -or $last.stop_flags.overlay) {Finding '发现助手停止标记文件，可能使读取或显示模块退出；探针只记录，没有删除。'}
    if ($last.saved_native_settings.lock -eq $true -and $null -ne $last.saved_native_settings.lock_sections -and
        -not @($last.saved_native_settings.lock_sections.PSObject.Properties | Where-Object {$_.Value -eq $true}).Count) {
        Finding '自动锁定总开关已开，但锁定栏目没有勾选任何一项。'
    }
    if (-not @($Rows | Where-Object {$_.checks.reader_fresh -and $_.reader.status -eq 'watching'}).Count) {
        Finding '装备读取模块没有持续就绪：这会使已勾选的拾取、锁定无法下发。'
    }
    if (-not @($Rows | Where-Object {$_.checks.native_fresh}).Count) {
        Finding '没有收到新鲜的游戏组件心跳：可能未加载、装到了其他游戏目录，或组件已异常。磁盘文件存在不等于已加载。'
    }
    if (-not @($Rows | Where-Object {$_.checks.request_not_expired}).Count) {
        Finding '没有捕获到未过期的助手指令：检查助手是否运行、是否卡住及读取状态。'
    }
    if (-not @($Rows | Where-Object {$_.checks.reader_fresh -and $_.checks.schema_pid_matches -and $_.ui.valid}).Count) {
        Finding '未捕获到角色读取与字段表同时就绪；即使设置已勾选，助手也可能尚不能启用指令。'
    }
    foreach ($x in $Rows) {
        foreach ($file in $x.files) {
            if ($file.found -and -not $file.ok) { Finding ('状态文件读取失败：' + $file.name + '；' + $file.error) }
        }
        if ($x.checks.native_fresh -and $x.checks.request_not_expired -and -not $x.checks.protocol_matches) {
            Finding '助手与游戏组件协议版本不同，需要核对组件版本并在更新后重启游戏。'
        }
        if ($x.checks.native_fresh -and $x.native.state -eq 'adapter_error') {
            Finding ('游戏组件执行异常：' + $x.native.error)
        }
        if ($x.checks.native_fresh -and $x.native.state -eq 'waiting_for_current_player') {
            Finding '组件未找到当前角色，或角色/界面数据未就绪。'
        }
    }
    $states=@($Rows | Where-Object {$_.checks.native_fresh} | ForEach-Object {$_.native.pickup_state} |
        Where-Object {$_} | Select-Object -Unique)
    foreach ($state in $states) {
        switch ($state) {
            'inactive' { Finding '曾因游戏不在前台/助手未就绪而暂停拾取。探针刚打开时短暂出现属于预期，请看切回游戏后的记录。' }
            'menu' { Finding '曾因背包、菜单或其他游戏面板打开而暂停拾取。' }
            'full' { Finding '曾因背包已满而暂停拾取。' }
            'off' { Finding '组件曾收到“拾取关闭”的指令；与保存设置及读取就绪状态对照。' }
            'waiting_for_loot' { Finding '拾取流程已运行，但该次扫描没有找到附近掉落。' }
            'waiting_for_result' { Finding '拾取流程已运行并等待结果；地面可见物品也可能受距离、排除库或游戏规则影响。' }
            'requested' { Finding '已观察到拾取请求发出；请求发出不等于物品已经进入背包。' }
            'recycling' { Finding '拾取曾等待回收流程完成。' }
        }
    }
    if ($last.saved_native_settings.lock -eq $true -and $ready.Count -and
        -not @($Rows | Where-Object {$_.matches.numeric -gt 0 -or $_.matches.legendary -gt 0 -or $_.matches.lower -gt 0}).Count) {
        Finding '自动锁定已开启，但记录中没有显示匹配装备；需结合锁定栏目、筛选门槛以及装备是否已锁定判断。'
    }
    if (@($ready | Where-Object {$_.acknowledgements -contains 'locked'}).Count) {
        Finding '有效状态记录中包含锁定成功回执；回执可能属于稍早的请求，不能当作本次新锁定数量。'
    }
}

try {
    $outputRoots = if ($env:RLH_PROBE_OUTPUT_DIR) { @($env:RLH_PROBE_OUTPUT_DIR) }
        else { @([Environment]::GetFolderPath('Desktop'), (Split-Path -LiteralPath $env:RLH_PROBE_SELF), $env:TEMP) }
    $name = '破晓助手功能诊断-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' +
        [guid]::NewGuid().ToString('N').Substring(0,6) + '.log'
    foreach ($root in $outputRoots) {
        if ([string]::IsNullOrWhiteSpace($root)) { continue }
        try {
            $null=[IO.Directory]::CreateDirectory($root)
            $candidate=Join-Path $root $name
            [IO.File]::WriteAllText($candidate, '破晓助手功能探针 v1.0' + [Environment]::NewLine, $utf8)
            $logPath=$candidate
            break
        } catch { Write-Host ('无法在此保存，尝试下一个位置：' + $root) }
    }
    if (-not $logPath) { throw '无法保存日志，请检查桌面或临时目录是否可写。' }
    $dataDirectory=if ($env:RLH_PROBE_DATA_DIR) {$env:RLH_PROBE_DATA_DIR} else {Join-Path $env:LOCALAPPDATA 'RuinsLootHelper'}
    $seconds=20
    if ($env:RLH_PROBE_SECONDS -match '^\d+$') {$seconds=[math]::Min(60,[int]$env:RLH_PROBE_SECONDS)}
    Write-Host '破晓助手 · 拾取 / 锁定功能探针' -ForegroundColor Cyan
    Write-Host '请保持助手与游戏运行，并进入角色场景。'
    Write-Host ('现在切回游戏、关闭背包和设置，正常停留约 ' + $seconds + ' 秒。') -ForegroundColor Yellow
    Write-Host '只读检查，不修改设置，不触发拾取、锁定或回收，不联网、不读取机器码或游戏存档。'
    Write-Host ('日志将自动保存：' + $logPath)
    Log ('生成时间 UTC：' + [DateTimeOffset]::UtcNow.ToString('o'))
    Log '说明：本探针只读观察。未采集机器码、游戏存档、完整装备列表或其他应用内容。用户目录路径已脱敏。'
    Log '每次状态文件依次读取，可能相差几十毫秒；瞬时会话不一致需结合后续采样，不单独判定故障。'
    Log ('数据目录：' + $dataDirectory)
    $app=Read-State 'app-settings.json'
    $receipt=Read-State 'native-install.json'
    Log-Json '助手版本及定位' (Select-Fields $app.value @('version','game_exe'))
    if ($env:RLH_PROBE_SKIP_SYSTEM -ne '1') {
        Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public sealed class RuinsProbeProcess {
    public string Path;
    public bool? Elevated;
    public string Error;
}
public static class RuinsProbeReadOnly {
    [DllImport("kernel32.dll", SetLastError=true)] static extern IntPtr OpenProcess(uint access, bool inherit, int pid);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool CloseHandle(IntPtr handle);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern bool QueryFullProcessImageName(IntPtr process, uint flags, StringBuilder text, ref int size);
    [DllImport("advapi32.dll", SetLastError=true)] static extern bool OpenProcessToken(IntPtr process, uint access, out IntPtr token);
    [DllImport("advapi32.dll", SetLastError=true)] static extern bool GetTokenInformation(IntPtr token, int kind, out int value, int size, out int returned);
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window, out int pid);
    public static int ForegroundPid() { int pid; GetWindowThreadProcessId(GetForegroundWindow(), out pid); return pid; }
    public static RuinsProbeProcess Inspect(int pid) {
        var result=new RuinsProbeProcess();
        IntPtr process=OpenProcess(0x1000,false,pid), token=IntPtr.Zero;
        if(process==IntPtr.Zero) {result.Error="query access: "+Marshal.GetLastWin32Error(); return result;}
        try {
            var text=new StringBuilder(32768); int size=text.Capacity;
            if(QueryFullProcessImageName(process,0,text,ref size)) result.Path=text.ToString();
            else result.Error="image query: "+Marshal.GetLastWin32Error();
            if(OpenProcessToken(process,8,out token)) {
                int value, returned;
                if(GetTokenInformation(token,20,out value,4,out returned)) result.Elevated=value!=0;
            }
        } finally { if(token!=IntPtr.Zero) CloseHandle(token); CloseHandle(process); }
        return result;
    }
}
'@
        $games=@(Get-Process -Name 'RuinsOfDawn-Win64-Shipping' -ErrorAction SilentlyContinue | ForEach-Object { Inspect-Process $_ })
        $helpers=@(Get-Process -Name '破晓装备助手','RuinsLootHelper' -ErrorAction SilentlyContinue | ForEach-Object { Inspect-Process $_ })
        Log-Json '进程与权限' @{probe=[RuinsProbeReadOnly]::Inspect($PID); games=$games; helpers=$helpers;
            os_build=[Environment]::OSVersion.Version.ToString(); powershell=$PSVersionTable.PSVersion.ToString();
            process_64bit=[Environment]::Is64BitProcess}
        if (-not $games.Count) { Finding '采集开始时没有检测到游戏进程。' }
        if ($games.Count -gt 1) { Finding '采集开始时检测到多个游戏进程；助手可能无法确定目标。' }
        if (-not $helpers.Count) { Finding '未检测到标准名称的助手 EXE；源码启动或改名版本需要结合读取模块心跳判断。' }
        if (@($games | Where-Object {$_.elevated -eq $true}).Count -and
            @($helpers | Where-Object {$_.elevated -eq $false}).Count) {
            Finding '游戏为管理员权限而助手不是：可能导致游戏读取被拒绝，需结合读取错误判断。'
        }
        $actual=@($games | Where-Object {$_.path})
        $gamePath=if ($actual.Count -eq 1) {$actual[0].path} elseif (-not $actual.Count) {$app.value.game_exe} else {$null}
        if ($gamePath -and (Split-Path -Leaf $gamePath) -eq 'RuinsOfDawn-Win64-Shipping.exe') {
            $nativeRoot=[IO.Path]::GetFullPath((Split-Path -LiteralPath $gamePath))
            if ($actual.Count -eq 1 -and $app.value.game_exe -and $actual[0].path -ine $app.value.game_exe) {
                Finding '正在运行的游戏路径与助手保存的路径不同。'
            }
            $checks=@()
            $required=@('dwmapi.dll','ue4ss\UE4SS.dll','ue4ss\UE4SS-settings.ini','ue4ss\Mods\mods.txt',
                'ue4ss\Mods\RuinsHelper\Scripts\main.lua','ue4ss\Mods\RuinsHelper\Scripts\game.lua',
                'ue4ss\Mods\RuinsHelper\Scripts\core.lua','ue4ss\Mods\RuinsHelper\Scripts\json.lua',
                'ue4ss\Mods\RuinsHelper\Scripts\drop_filter.lua','ue4ss\Mods\RuinsHelper\Scripts\bag_geometry.lua')
            foreach ($relative in $required) {
                $path=Join-Path $nativeRoot $relative
                $row=[ordered]@{file=$relative; exists=(Test-Path -LiteralPath $path -PathType Leaf)}
                if ($row.exists) {
                    $file=Get-Item -LiteralPath $path
                    $row.bytes=$file.Length; $row.modified_utc=$file.LastWriteTimeUtc.ToString('o')
                    $row.sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
                    $key=$relative.Replace('\','/')
                    $expected=$receipt.value.files.$key
                    if ($expected) {$row.receipt_hash_matches=$row.sha256 -eq $expected}
                    if ($actual.Count -eq 1 -and $actual[0].started_utc) {
                        $row.newer_than_game_start=$file.LastWriteTimeUtc -gt [DateTime]::Parse($actual[0].started_utc).ToUniversalTime()
                    }
                }
                $checks += [pscustomobject]$row
            }
            Log-Json '组件文件检查（存在不代表已加载）' @{game=$gamePath; receipt_found=$receipt.found;
                recorded_directory=$receipt.value.directory; files=$checks}
            if (@($checks | Where-Object {-not $_.exists}).Count) {Finding '所检查的游戏目录缺少必要组件文件；参看组件文件检查。'}
            if (@($checks | Where-Object {$_.receipt_hash_matches -eq $false}).Count) {
                Finding '部分组件与安装记录中的校验值不一致；需核对是否混用了组件版本或文件被改动。'
            }
            if (@($checks | Where-Object {$_.newer_than_game_start -eq $true}).Count) {
                Finding '部分组件文件的修改时间晚于本次游戏启动，当前游戏可能尚未加载这些更新。'
            }
            if ($receipt.value.directory -and [IO.Path]::GetFullPath($receipt.value.directory).TrimEnd('\') -ine $nativeRoot.TrimEnd('\')) {
                Finding '组件安装记录指向另一个游戏目录。'
            }
            $modsPath=Join-Path $nativeRoot 'ue4ss\Mods\mods.txt'
            if (Test-Path -LiteralPath $modsPath -PathType Leaf) {
                $enabled=[IO.File]::ReadAllText($modsPath) -match '(?m)^\s*RuinsHelper\s*:\s*1\s*(?:;.*)?$'
                Log-Json '常规组件启用配置' @{RuinsHelper_enabled=$enabled}
                if (-not $enabled) {Finding '常规 mods.txt 中没有启用 RuinsHelper，请核对组件加载配置。'}
            }
        } else { Log '未能确定游戏安装路径，跳过组件文件检查；不会扫描其他目录。' }
    } else { Log '测试模式：已跳过系统、进程和游戏目录检查。' }
    $timer=[Diagnostics.Stopwatch]::StartNew()
    do {
        $sample=Snapshot
        $samples.Add($sample)
        Log-Json ('状态采样 ' + $samples.Count) $sample
        if ($timer.Elapsed.TotalSeconds -ge $seconds) {break}
        Start-Sleep -Milliseconds ([int][math]::Min(4000,[math]::Max(1,($seconds-$timer.Elapsed.TotalSeconds)*1000)))
    } while ($true)
    Summarize $samples.ToArray()
    foreach ($name in @('startup-error.txt','worker-error.txt','ui-error.json')) {
        $path=Join-Path $dataDirectory $name
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            try {
                Log ('--- 错误日志尾部：' + $name + ' ---')
                $text=(Get-Content -LiteralPath $path -Encoding UTF8 -Tail 60) -join [Environment]::NewLine
                Log ($text.Substring([math]::Max(0,$text.Length-16000)))
            } catch { $notes.Add($name + '：' + $_.Exception.Message) }
        }
    }
    if ($nativeRoot) {
        $path=Join-Path $nativeRoot 'ue4ss\UE4SS.log'
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            try {
                Log ('--- UE4SS 日志尾部，文件修改时间 UTC：' + (Get-Item -LiteralPath $path).LastWriteTimeUtc.ToString('o') + ' ---')
                Log ((Get-Content -LiteralPath $path -Encoding UTF8 -Tail 100) -join [Environment]::NewLine)
            } catch {$notes.Add('UE4SS 日志：' + $_.Exception.Message)}
        } else { Log 'UE4SS.log 不存在。' }
    }
    Log '========== 诊断结论（以实际采样为依据） =========='
    foreach ($finding in $findings) {Log ('- ' + $finding)}
    foreach ($note in $notes) {Log ('补充：' + $note)}
    Log '若全程停留在探针/助手窗口，inactive 不能作为故障结论；切回游戏后再采集。'
    Log '请把本 .log 文件发给助手维护者。'
    Write-Host ''
    Write-Host '检测完成，日志已保存：' -ForegroundColor Green
    Write-Host $logPath -ForegroundColor Cyan
    Write-Host '把这个 .log 文件发回来即可，不需要截图或打包。'
    exit 0
} catch {
    $message=$_.Exception.Message
    if ($logPath) {
        try {Log ('探针异常：' + $message); Log $_.ScriptStackTrace} catch {}
    }
    Write-Host ('检测未完整完成：' + $message) -ForegroundColor Red
    if ($logPath) {Write-Host ('已保存的日志仍可发送：' + $logPath)}
    exit 1
}
