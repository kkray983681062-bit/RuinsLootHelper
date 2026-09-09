# 原生游戏组件（测试中）

适配目标：Ruins of Dawn / 破晓之墟 1.15，Steam AppID 4364910、构建 24933058，Unreal Engine 5.5。当前源码协议为 4。游戏更新后需重新核对接口和实测效果。

原生动作默认关闭，只有主动安装组件并选择功能后才执行。普通装备筛选和手动背包定位不需要安装组件。

## 功能和边界

- 拾取逐件调用游戏现有流程，核对距离、归属、场景、菜单和容量。发送请求不等于实际入包。
- 范围、间隔和批量分别设置；自动批量按耗时让出游戏线程，单次原生调用本身不能中断。
- 图鉴和装备排除匹配接入官方新掉落判断，保留官方屏蔽结果。请求过期、助手关闭或接口异常时不追加屏蔽。
- 已在地上的物品只跳过助手拾取，不删除现有背包物品。
- 自动锁定调用前检查未锁定和完整属性，收到回执并读回状态后才报告成功。手动解锁后的静默期为 30 秒。
- 自动回收是独立选项，默认关闭，并依赖自动锁定及官方回收方式。
- 自动网格从当前角色主界面主背包读取 60 格的坐标；失效时隐藏标记。
- 无边框功能仅在用户启用后调整窗口模式，普通置顶层不能保证覆盖独占全屏。

当前版本的新掉落屏蔽、批量拾取等效果仍需在目标游戏版本实测。策略与模拟 UObject 测试不能替代实际掉落、锁定或回收验证。

## 文件通信

助手和 Lua 通过 `%LOCALAPPDATA%\RuinsLootHelper` 中的请求与状态 JSON 交换有限字段，携带进程、会话和时限。配置文件不会作为任意代码执行。

## 第三方组件

UE4SS 运行库未包含在源码或助手包中。主动安装时从官方仓库下载固定版本并验证 SHA-256：

- [固定运行库](https://github.com/UE4SS-RE/RE-UE4SS/releases/download/experimental-latest/UE4SS_v3.0.1-1127-g2bfa839f.zip)
- SHA-256：`29367ce89f3637a537d507f2c79b9d33df3d145c63fd8bb0179f737a5ce46374`
- [UE4SS 上游源码](https://github.com/UE4SS-RE/RE-UE4SS/tree/2bfa839f)
- [rxi/json.lua](https://github.com/rxi/json.lua)，许可保留在源文件头。

助手桥接脚本许可见 [LICENSE](LICENSE)。完整第三方说明见 [packaging/THIRD-PARTY-NOTICES.txt](../packaging/THIRD-PARTY-NOTICES.txt)。

## 停用

先关闭游戏，按 `%LOCALAPPDATA%\RuinsLootHelper/native-install.json` 中的安装记录确认本助手添加的文件，再停用对应组件。不要覆盖或删除其他插件已有的文件。
