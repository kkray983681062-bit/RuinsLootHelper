# 破晓装备助手

**完全免费，下载和使用均不收费。**

适用于 Steam 版《破晓之墟》（Ruins of Dawn）的 Windows 助手。筛选装备、定位背包格子，并提供可选的进阶辅助。

## 下载 v0.3.7

### [蓝奏云下载](https://wwaou.lanzoup.com/b01giaqhvg) · 密码 **71my**

大陆用户优先使用蓝奏云。文件由作者同步，请核对文件名中的版本号。

[GitHub 下载 Windows 完整包](https://github.com/kkray983681062-bit/RuinsLootHelper/releases/download/v0.3.7/RuinsLootHelper-0.3.7-Windows-x64.zip) · [本次版本与校验值](https://github.com/kkray983681062-bit/RuinsLootHelper/releases/tag/v0.3.7)

Windows 10/11 · 64 位 · 约 72 MB。游戏组件随包提供，安装组件无需联网。

0.3.7 包含离线游戏组件，首次安装无需联网下载。蓝奏云同步以文件夹内实际版本为准。详情见[验证与限制](docs/validation.md)。

## 开始使用

1. 完整解压 ZIP，保留 `_internal` 文件夹，运行 **破晓装备助手.exe**。
2. 启动游戏并进入角色。助手会记住游戏路径，自动连接当前会话。
3. 在 **装备筛选** 中设置词条、上技能、下技能，点击右下角 **保存设置**。
4. 需要进阶辅助时，再到 **进阶辅助 → 安装 / 更新组件**，安装后重启游戏。

装备筛选可以独立使用。自动锁定与自动回收上下放在同一组，先锁定达标装备，再回收。

## 0.3.7 的变化

- 自动锁定改为完整保留规则：**同一条规则内全部条件同时满足，不同启用规则满足任意一条即可保留**。
- 品质、T 级、指定装备、基础属性门槛和技能条件不再互相绕过。例如“完美＋T6＋霄引＋魔法上限 ≥48”必须全部达标。
- T6 支持套装／非套装范围，以及灭世、星陨、冥墟套装分组；上技能筛选增加 T6。
- 自动锁定成为侧栏独立页面，可添加、停用和删除规则，选择任意或指定上／下技能。
- 装备勾选只限定范围；未设置保留条件时不锁定，全品质保留需明确勾选。
- 首次升级自动备份旧锁定配置并迁移；请检查迁移后的规则，再保存设置。

保留自动拾取、背包标记、自动回收、自动开门和八卦入口提示。游戏组件仍需实机验证，详见[验证与限制](docs/validation.md)。

自动开门条件：等级 ≥50，或额外掉落率与额外极品率均 ≥300%。八卦提示在地图放大时隐藏，加入他人房间时可能读不到入口。

## 界面截图

以下为本地程序界面预览；功能开关与数据为演示配置。

![进阶辅助](docs/images/advanced-0.3.5.png)

![装备筛选](docs/images/filters-0.3.5.png)

[使用说明](docs/getting-started.md) · [常见问题](docs/faq.md) · [更新记录](CHANGELOG.md) · [反馈问题](https://github.com/kkray983681062-bit/RuinsLootHelper/issues/new/choose)

<details>
<summary>源码与项目说明</summary>

本版本的程序、测试和构建文件在 [source](source/) 目录；见[开发说明](docs/development.md)。

[项目与许可说明](NOTICE.md) · [验证与限制](docs/validation.md)

本项目为个人维护的非官方工具，与游戏开发商、发行商及 Steam 无隶属关系。

</details>
