# 工作原理

补丁不替换 CarPlay（`libairplay.so` 保持逐字节不变）。它旁听 iPhone 与原厂 `dio_manager` 之间的 iAP2 对话，用听到的路线数据驱动仪表。三个进程配合：

| 组件 | 语言 | 运行位置 | 作用 |
| --- | --- | --- | --- |
| `libcarplay_hook.so` | C，ARM32 QNX | 仅 `LD_PRELOAD` 进 `dio_manager` | 拦截 iAP2 路线引导消息（TLV `0x5200`–`0x5204`） |
| Java 补丁（JAR） | Java 1.4 | HMI 虚拟机（`j9`，开机常驻） | 把路线数据映射为 BAP 功能输出到 VC/HUD，驱动 renderer，桥接触摸板输入 |
| `maneuver_render` | C，EGL/GLES2 | 独立进程，由 keeper 启动 | 在原生仪表地图上叠加转向图（displayable 98，空闲时透明） |

```text
iPhone ──iAP2──► dio_manager（原厂 libairplay 210.81 + hook）
                     │  TCP 127.0.0.1:19810   （hook → Java 总线）
                     ▼
               HMI Java 补丁 ──► BAP FctID ──► 虚拟座舱 / HUD
                     │  TCP 127.0.0.1:19800   （CMD_MANEUVER）
                     ▼
               maneuver_render ──► 叠加在原生仪表地图上
```

## 启动与激活顺序

1. HMI 开机即运行，Java 补丁已在总线端口 `accept()`。
2. 手机连接时，`smartphone_integrator`（SI）拉起 `dio_manager`。改过的 SI 配置里 `dio_manager` 那一项带有 hook 的 `LD_PRELOAD`（和试验标记），
   只对这个进程生效，所以 hook 的构造函数在连接时才触发。
3. hook 连上 Java 总线。每次开机第一次 CarPlay 会话时，Java 端通过 `f7_spawn` 启动 **renderer keeper**，由它启动 `maneuver_render`，F8 起还启动**监测**。
4. 路线数据沿 hook → Java → BAP + renderer 流动，直到路线结束或手机断开。

## 安全机制

- **按需生命周期。** `f7.sh install` 备份所有原文件后，把文件写到 `/mnt/app/root/mu1320-rgi-f7-v2` 和 SI/DIO 配置；`rollback` 恢复；`purge` 删除工作目录。
  当前状态与预期不符时脚本拒绝执行（`STOP: ...`）。
- **崩溃保护。** 每一代 hook 都会记录；DIO 在短时间内连续出现三代（快速拔插 USB）后，下一代保持被动直到重启。
  闸门文件是直接写入的，因为车上 `/tmp` 是共享内存，不支持 `rename`（车上发现，B11 修复）。
- **紧急停止。** 先通过运行时开关关 BAP，等 Java 释放仪表 context 并还原原厂显示，再停 renderer。无需拔 USB，几秒内恢复原厂行为；重启后补丁恢复（B12 修复）。
- **运行时开关**（`/tmp/mu1320-f5-bap-off`、`-render-off`、`-f6-touchpad-off`、`-f7-native-off`、`/tmp/mu1320-f8-mon-off`）只在本次开机关闭某个组件；`f7.sh off|on` 为永久开关。
- **环境清理。** 菜单动作先 `cd /`、`umask 022`，去掉 `LD_LIBRARY_PATH` 里的相对路径，因为 Toolbox 菜单启动脚本时 PATH 以 `.` 开头且 umask 为 000。
- **处处校验。** 脚本启动二进制之前先校验其 cksum。

## 监测（F8）

`f8_mon.sh` 每 60 秒采样：空闲内存，以及 `dio_manager`、`smartphone_integrator`、`j9`、`displaymanager`、`maneuver_render`、`screen`、`io-usb` 的 CPU 时间、线程数、数据段和句柄数，
外加 `/tmp` 各日志的大小。每 2 分钟追加到 SD 的 `out/f8/boot-<序号>-<pid>/samples.txt`，并复制有变化的 F7 日志；每 10 分钟另存 `sloginfo` 和 `/mnt/ota` 转储目录清单。
它会把 SD 临时改成可写几秒再改回只读；不写 `/mnt/app`、`/mnt/system`，也不调用 `dmdt`。共享锁 `/tmp/mu1320-f8-sd.lock` 保证菜单动作和监测写入不会互相改 SD 状态。

## 仪表显示 context（选读）

空闲时叠加层合成在原厂仪表 context 之上；引导期间补丁接管一组自定义图层（叠加层 98 加 101、102 和原生地图 33）。
首次实车试验中，原厂代码把补丁的切换请求改写成 context 73，因此后续版本采用“KDK 默认”模式（F5 v5）。
在车上按 VIEW 键可能短暂露出原厂 KDK 占位图（已知限制 B5）。逆向记录见上游项目的 `docs/` 和 [`reports/`](reports/)（`F5-*`）。
