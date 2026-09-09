# 开发与构建

程序、测试、运行资源和构建脚本已整体归入仓库的 `source/` 目录，内部相对路径保持不变。先进入该目录，再执行下文命令：

```powershell
cd source
```

本次源码与 `0.3.5` 发行版同步。

## 环境

Windows 10/11 x64，Python 3.11 x64，安装 Python 时包含 Tcl/Tk。程序通过 Win32 API 和 Steam 安装记录工作，不支持在 Linux/macOS 上运行桌面功能。

源码启动前需安装 `requirements.txt` 中的图像定位依赖：

```powershell
py -3.11 -m pip install -r requirements.txt
py -3.11 -B loot_app.py
```

测试 Lua 和打包时，在 `source/` 内创建虚拟环境：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -B -m unittest discover -q
```

测试使用临时配置、模拟游戏对象和 Tk 窗口，不应要求启动游戏。Lupa 仅用于 Lua 模拟测试，不随程序发行。

## 构建 Windows 便携包

```powershell
.\.venv\Scripts\python.exe -B packaging/build_release.py
```

构建使用 PyInstaller 的 onedir 模式。此源码快照的完整产物在 `source/releases/<版本>/`；包含 EXE、`_internal`、说明、诊断 BAT 以及第三方许可。构建前需将已校验的 `UE4SS-2bfa839f.zip` 放入 `source/runtime/`；下载 URL 与 SHA-256 在 `native_support.py`。二进制包内置该组件，支持离线安装。

版本字段位于 `loot_app.py`、`packaging/build_release.py` 和 `packaging/version.txt`；发布前同步更新。不要把当前最新源码自动等同于同号旧发行包。

脚本会验证归档完整性和打包内容，阻止个人快照与一次性装备修改工具混入发行包。新版拾取库属于正常应用依赖。

## 源码结构

| 文件或目录 | 用途 |
| --- | --- |
| `loot_app.py`、`startup_window.py` | 启动、版本、安装位置和连接状态 |
| `release_runtime.py`、`probe.py`、`worker_process.py` | 当前游戏会话读取和后台进程 |
| `loot_overlay.py`、`overlay_*.py` | 悬浮窗、设置、分区、标记和数据刷新 |
| `gear_view.py`、`loot_current.py`、`catalog/` | 词条及技能映射、当前背包筛选 |
| `native_*.py`、`native/` | 可选原生桥接与策略 |
| `pickup_library.py` | 装备和图鉴排除选择 |
| `test_*.py` | 本地回归测试 |
| `packaging/` | 构建、使用说明与诊断工具 |

`catalog/` 仅包含运行所需的名称、属性和兼容性映射。游戏二进制资源、存档、个人背包快照、日志、虚拟环境与一次性修改脚本不在仓库中。

## 发布

先完成测试和游戏实测，再创建对应版本的 Release。对最终 ZIP 计算 SHA-256，并把完全相同的文件上传至 GitHub Releases 和蓝奏云；更新[下载页](downloads.md)及[更新记录](../CHANGELOG.md)。本仓库不自动上传或发布 EXE。
