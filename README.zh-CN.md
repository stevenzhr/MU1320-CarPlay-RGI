# MU1320 CarPlay RGI

[English](README.md) · **简体中文**

为搭载 **MU1320** 固件（QNX 6.5、ARMv7）的奥迪 MHI2Q 主机实现 **CarPlay 路线引导在虚拟座舱（VC）和 HUD 上的逐向显示**，
通过绿色菜单 **MIB2 Toolbox** 交付：在 MMI 上就能安装、卸载、采集日志和紧急停止。

本项目是在 [`luka-dev/mib2q-carplay-rgi`](https://github.com/luka-dev/mib2q-carplay-rgi)（MU1316）基础上做的 MU1320 移植与验证。
原厂 `libairplay.so` 始终不被替换，补丁只在它外围拦截。

> **警告，风险自负。** 本项目会修改主机上的系统文件和配置，只在**一台**车（`MHI2Q_US_AUG22_P4246`，MU1320）上由一个人验证过。
> 操作失误可能让 MMI 无法使用，也可能影响保修。动手前请完整备份、确保 SSH 可用，并阅读
> [docs/zh-CN/status.md](docs/zh-CN/status.md) 了解哪些已验证、哪些没有。**HMI 故障时的恢复（屏幕起不来怎么办）没有验证。**
> 不提供任何担保，见 [LICENSE](LICENSE)。

## 功能

- 有线 CarPlay 下，Apple Maps / Google Maps 的转向箭头、距离条、车道，显示在 VC 地图框，并通过 BAP 输出到 VC 和 HUD。
- MMI 触摸板拖动映射为仪表导航输入。
- 绿色菜单五个按钮：Status、Install、Uninstall、Collect、Emergency Stop，另有 SSH 等价命令。
- 长期监测（F8）：把内存、CPU、线程、句柄记录写到 SD 卡，用于稳定性验证。

已知缺口：ETA 和剩余距离不显示在 VC/HUD（本车原厂行为也如此）；无线 CarPlay 适配器不发路线数据；极快的 USB 拔插未处理。
完整列表见 [docs/zh-CN/status.md](docs/zh-CN/status.md)。

## 目录

| 路径 | 内容 |
| --- | --- |
| [`docs/en/`](docs/en/)、[`docs/zh-CN/`](docs/zh-CN/) | 原理、安装与回滚、构建、验证状态；`docs/zh-CN/reports/` 是各阶段实车验证报告（中文原文） |
| [`f8/`](f8/) | F8 候选包 `mu1320-f7-daily-v2.1`：生命周期脚本、监测、C 辅助程序及其 ARM 构建 |
| [`toolbox/`](toolbox/) | Toolbox v1 叠加层（绿色菜单页和调度脚本） |
| [`patches/`](patches/) | 对上游源码的补丁 |
| [`tools/`](tools/) | `assemble_toolbox_v1.py`、`assemble_f8.py`；`provenance/` 是各阶段构建脚本 |
| [`release/v0.9.0-rc.1/`](release/v0.9.0-rc.1/) | 版本说明和校验和 |
| [`NOTICE.md`](NOTICE.md) | 许可说明，以及**刻意不放**在仓库里的内容 |

## 快速开始（概要）

1. 按 [docs/zh-CN/building.md](docs/zh-CN/building.md) 准备输入（hook、renderer、Java 补丁、改过的 SI/DIO 配置）。
   这些不在本仓库分发，原因见 [NOTICE.md](NOTICE.md)。
2. 运行 `python3 tools/assemble_toolbox_v1.py --output build/mu1320-toolbox-v1` 和
   `python3 tools/assemble_f8.py --inputs <目录> --output build/mu1320-f7-daily-v2.1`
   （两者都会校验 SHA-256，和车上验证过的包不一致就拒绝生成）。
3. 拷到 SD 卡，用原厂更新菜单安装 Toolbox v1，然后使用 `Customization > MU1320 RGI`。详见 [docs/zh-CN/install.md](docs/zh-CN/install.md)。

## 致谢

[luka-dev](https://github.com/luka-dev) 的 MU1316 CarPlay RGI 研究与实现；[jilleb](https://github.com/jilleb/mib2-toolbox) 及贡献者的 MIB2 Toolbox。
