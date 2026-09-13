# Windows 分发构建

0.3.6 使用 Python 3.11、Tk、Win32 和 PyInstaller。入口为 `loot_app.py`；设置面板与鼠标穿透标记层分开，读取工作在独立后台进程中进行。

游戏路径优先使用已保存的有效路径，失效后通过 Steam 注册表、`libraryfolders.vdf` 和 AppID 4364910 的安装记录重新发现。内存中的角色和背包地址仍随游戏会话重新定位，不复用旧进程地址。

## 构建

在 `source` 目录准备构建环境：

```powershell
python -m pip install -r requirements-dev.txt
python -X utf8 -B packaging/build_release.py
```

需事先放入固定的 `runtime/UE4SS-2bfa839f.zip`，下载地址及散列见 `native/README.md`。构建器会核对运行库、包内模块、私有数据排除、ZIP 完整性与 SHA-256。

产物为 `releases/0.3.6/RuinsLootHelper-0.3.6-Windows-x64.zip`，可运行目录为 `release-staging-0.3.6/破晓装备助手/`。

必须分发完整目录或 ZIP，不能只复制 EXE。Windows 10/11 x64 无需另装 Python；one-folder 模式不在运行时临时解包。EXE 通过管理员清单请求与游戏匹配的读取权限。

发行包包括助手、离线游戏组件、组件源码、默认规则和第三方许可，不包括个人快照、存档、窗口位置、校准坐标或一次性装备修改工具。

## 验证

```powershell
python -X utf8 -B -m unittest discover -q
```

EXE 提供以下自检参数：

- `--self-test <输出文件>`：检查冻结程序、Tk、目录数据和安装发现。
- `--smoke-test <输出文件> --data-dir <独立测试目录> --seconds 60`：只读连接正在运行的游戏，读取当前背包后退出。

两个参数可同时使用。只读测试报告可能包含本地背包样本，不加入发行包。游戏组件的新动作需要另外安装、重启并在游戏内验证；构建清单不会将自检成功写成原生功能实测成功。
