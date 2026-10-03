# MU1320 CarPlay RGI backlog

这里放不属于当前阶段、以后可能要做的功能和已知的小问题。每条写明来源和现状。
排进计划的条目移到 ROADMAP，不在这里删除。

## 功能

### B1. 地图框箭头显示到转向距离（大地图视图）

- **来源**：F5 v3 实车（2026-09-26，`resource/private/vehicle-dump/f5-vchud-v3/`）。
- **现象**：小地图（大表盘）视图里，VC 根据 BAP 在表盘窗口上叠加 "### ft"。大地图视图右上角的弹出框只有
  renderer 画的箭头和进度条，没有距离。
- **现状**：用户确认保持原厂设计，当前不改。
- **可能的做法**：在 `maneuver_render` 中画距离文字（位图字体或字形图集），数据取自现有的 BAP/RCMD 距离；
  需要确认单位、取整规则与 VC 的 BAP 显示一致，并且只在 popup 视图显示（in-tube 由 VC 叠加，避免重复）。
- **涉及**：renderer（C，需要重新走 F4 式的实车验证）、RenderPlanner 的协议字段。

### B4. FIGHT_STOP 上限调高（6 → 约 12）

- **来源**：F5 v5 实车（`resource/private/vehicle-dump/f5-vchud-v5/OBSERVATIONS-f5-v5.txt`）。
- **现象**：kdk 模式下连续按 2~3 次 VIEW 就可能被原厂连续收回 6 次以上，触发 FIGHT_STOP，暂停 3 秒，期间显示占位图。
- **做法**：`ClusterPresenter.FIGHT_TAKES` 改为约 12。按 v5 日志推算，两次暂停都不会触发；原厂真正持续争夺时，
  最多闪约 3 秒才暂停。用户决定 F5 以 v5 结项，暂不调整。

### B5. VIEW 切换时的原厂占位图

- **来源**：F5 v4/v5 实车。每次按 VIEW，原厂都会把仪表切回 74，露出原厂 KDK 占位图（kdk 模式下不到 1 秒；native 约 2~3 秒）。
- **现状**：F5 的已知限制。在不替换原厂类的前提下只能缩短，不能消除；像上游那样覆盖 `DisplayManagerMIB2High`
  可以根治，但属于替换 HMI 核心类的高风险方案，暂不计划。

## 已知问题（观察到，未处理）

### B2. 到达后到达符号不自动消失

- **来源**：F5 v2 实车第 9 步。到达后到达符号（地图框 + BAP）一直显示，要在 iPhone 上手动结束导航才消失。
- **推测**：到达后 iOS 仍保持路线状态；需要用 v2/v3 的 capture 确认到达后的 route_state 序列，再决定是否在到达后
  一段时间自动清除。
- **F6 离线核对（2026-09-26）**：已确认。F5 v2–v5 的 4 条到达路线中，iOS 一直保持 ARRIVED（route_state=2），直到用户结束或拔线，
  分别 19、29、107、170 秒（`reports/F6-SUPPORT-MATRIX-SEED.md`）。F5 只是如实转发。是否在到达 N 秒后自动清除属于产品决定，
  F6 B8/C8 记录实车时长后再定（F7 前）。

### B3. Google Maps 路线没有到达时间

- **来源**：F5 v2 实车第 10 步。箭头、到转向距离、进度条、车道都正常，只有 ETA（FctID 22）没有。
- **推测**：Google Maps 没有通过 iAP2 提供到达时间；需要用 capture 确认 ETA/剩余时间字段是否为空。
- **结论（F6 场次 A 实车，2026-09-26）：关闭，原厂设计。** 原车导航的 ETA 和到目的地距离也不在 VC/HUD 上显示，
  只在 MMI 屏幕右下方。本车 VC/HUD 没有显示这两个字段的位置，Apple 和 Google 都一样。F5 发出的 FctID 21/22 无害，保留。
- **F6 离线核对（2026-09-26）：推测不成立。** F5 v2 采集中 Google Maps 每秒都发 `eta_seconds`（和剩余时间），F5 也发出了
  345 次 FctID 22（`ETA src=eta`）。所以不是应用没数据，而是 VC/HUD 没显示（或显示在别处）；Apple Maps 的 ETA 同样已发出、
  显示未确认。F6 A2/A13 先找 VC/HUD 上 ETA 和到目的地距离的显示位置。

### B6. 停车时切换公英制，距离单位要等下一次距离变化才更新

- **来源**：F6 场次 A 第 A5 步（2026-09-26，`resource/private/vehicle-dump/f6-accept-v1/ANALYSIS-A.txt`）。
- **现象**：路线进行中在 MMI 里把单位改成公制，停车 30 秒 VC/HUD 仍显示 ft；重新开始路线后变为 m。
- **原因**：F5 在发送距离时按当前系统单位格式化，只在距离变化时发送。停车时距离不变，所以不会重发；行驶中约 1 秒内就会更新。
- **可能的做法**：单位变化时（轮询 `Distance.getSystemUnit()`）重发 DIST_TURN/DIST_DEST。影响小，暂不改。

### B7. 触摸板方向键略微灵敏

- **来源**：F6 v2 场次 T（2026-09-26，`resource/private/vehicle-dump/f6-accept-v2/ANALYSIS-T.txt`）。功能通过，手感“略微灵敏”，
  用户希望约打 8 折。短滑常见 6–7 个采样出 2–3 格。
- **做法**：`TouchpadGesture` 阈值 ×1.25（快/慢 150/200 → 188/250），死区 30 → 38；harness 按比例更新。只改 Java 常量。
- **时间**：现阶段不改（F6 v2 保持被测版本不变），B/C 行驶中再感受一下，F7 前定。
- **状态（2026-09-27）**：用户决定随 F6 v3 一起改，已实现（188/250/38）。**关闭**：场次 D 用户反馈手感很好。
- **附带发现**：本车触摸板对双指只上报一个点（MULTI=0），双指等同单指滑动，不需要处理。

### B8. 车道只在每条路线的第一个车道路口显示（HUD）

- **来源**：F6 v2 场次 B/C（2026-09-27，`resource/private/vehicle-dump/f6-accept-v2/ANALYSIS-BC.txt`）。用户在 C3 看到 CarPlay 有车道和高亮、HUD 没有；只有路线刚开始时 HUD 显示过车道。
- **原因**：Apple/Google 都在路线开始时一次性发齐全部车道信息（0x5204），车道索引自成一套编号。hook 的 `rgd_prune_stale_lane_cache()`（上游）按“车道索引 < 当前最小机动索引”删除车道缓存，机动推进后未用到的车道被删；iOS 之后引用该车道时 Java 查不到，只能发 off。Apple 7 组只显示第 1 组，Google 5 组只显示第 1 组。
- **做法（建议）**：Java `TripPlanner` 按车道索引保存本路线收到的车道数据，路线结束/重算/硬清除/换应用时清空。只改 Java，native 不动。`f6_matrix` 同时增加“showing=1 但无车道数据”的检查。
- **影响**：F6 的“车道”项记 F（显示只覆盖第一个路口）。
- **补充**：Apple 在路线中途补发的车道（v2 B 的第 7 组）到达时就被 hook 删掉，从未进入 Java，所以只改 Java 不够。
- **状态（2026-09-27）**：F6 v3 实现：navhook v1.3 不再按机动编号删车道（v1.2 逐位复现后单点修改，`reports/navhook-v13-*`）+ Java `LaneMemory`。回放 Google 5/5、Apple 6/7（第 7 组需 hook v1.3 上车验证）。待场次 D。
- **待观察（已关闭）**：“无 lane_guidance_index”的片段全部只有 1 帧，是重算/切换时的闪烁，不是车道路口（F5 v2 7 段、F6 v3 D 14 段）。
- **实车（F6 v3 场次 D，2026-09-27）**：Apple 2/2、Google 2/2；Apple 第 2 组按 v1.2 规则会被删、v1.3 下由 hook 直接发出。用户确认 HUD 车道与高亮与 iPhone 一致。**关闭。**

### B9. Apple 到达前最后一段距离条不递减

- **来源**：F6 v2 场次 B8（2026-09-27）。
- **原因**：切到到达机动后，Apple 的到转向距离一直是 0（只有到目的地距离在减），F5 视为无效不再发 DIST_TURN，距离条停在上一个机动的最后值（本次 94，约 17 秒）。
- **做法（建议）**：到达类机动的到转向距离无效时用到目的地距离代替。只改 Java。
- **状态（2026-09-27）**：F6 v3 实现（BapPlanner），回放 v2 B 为 91→28 m 递减，F2 采集中同样情况 82→28 m。场次 D 未用到（Apple 未到达；Google 到达自带距离），实车待下一次 Apple 到达。
- **F7（2026-09-27）**：F7 v1.1 合入同一份 BapPlanner（与 F6 v3 JAR 逐字节相同），回放照旧 91→28 m。实车确认放进 F7 上车观察项：v1.1 观察表可选项 **A1 Apple 到达**（场次 P 之后开一小段到几百米外的目的地，看距离条递减到到达）；没做就留到 F7 v2 场次 D。
- **实车（F7 v1.1 A1，2026-09-27）**：Apple 到达前距离条 30→1 m 逐秒递减，用户确认递减到到达。**关闭。**


### B10. 运行日志持续镜像到 SD

- **来源**：F7 v2 部署讨论（2026-09-27）。
- **原因**：hook/Java 日志在 `/tmp`，断电即清空。开完车直接锁车，下次上车 MMI 已重启，那次开车的日志就没了。F7 v2 先靠操作说明（停车后、锁车前点一次采集）解决。
- **做法（建议）**：生命周期内加一个低频任务，把 `/tmp` 下本项目日志的增量定期同步到 SD；SD 不在或只读时静默跳过，不写 `/mnt/app` 闪存。要考虑 SD 读写切换频率和写入量上限。
- **影响**：只影响采集便利性，不影响功能；F7 v2 不做。
- **F8（2026-10-02）**：用户决定做进 F8 候选 F7 v2.1（`f8_mon.sh`）：renderer keeper 每次开机第一次连 CarPlay 时启动，每 60 s 采样、每 2 min 把采样和有变化的日志写到 SD `out/f8/boot-<序号>-<pid>/`，SD 只读时只在写入的几秒改为可写，与 f7.sh 共用 `/tmp/mu1320-f8-sd.lock`；每次开机日志最多 256 MB；不写 `/mnt/app`。主机测试通过，待场次 M 实车确认。

### B11. F7 闸门记录写不出来，崩溃保护不生效

- **来源**：F7 v1.1 实车 P4（2026-09-27，`resource/private/vehicle-dump/f7-daily-v1.1/ANALYSIS-P-T.txt`）。
- **原因**：`trial_gate.c` 的 `write_small()` 先写 `<path>.<pid>` 再 `rename()`；本车 `/tmp` → `/dev/shmem`，不支持 rename，失败后临时文件被删，`/tmp/mu1320-f7-gate.last`、`.strikes` 从未出现。每个 DIO 都读不到上一代，strikes 永远 0；存活 DIO 守卫（LAST 读不到时返回 1）同样失效。目前无害：拔 USB 时原厂会杀旧 DIO。
- **做法**：LAST/STRIKES 直接 `open(O_WRONLY|O_CREAT|O_TRUNC)` 写（或 rename 失败时回退直写）；主机测试模拟 rename 失败；实车重测 P4。需要重新编译 hook。
- **状态**：用户决定并入 F7 v2（2026-09-27）。**F7 v2 已修（离线，2026-09-27）**：`write_small()` 直接 `O_TRUNC` 写；主机测试模拟无 rename 的文件系统，v1.1 重现车上失效、v2 第 4 代快速 DIO 被动。待场次 Q2 实车确认。
- **实车（F7 v2 场次 Q，2026-09-27）**：同一次开机 7 代 DIO，strikes 0、0、1、2 后第 4 次快速拔插 `PASSIVE CRASH_GUARD strikes=3`，之后一直被动；两个记录文件都在，重启后归零。**关闭。**（[实车审阅](reports/F7-DAILY-V2-VEHICLE-REVIEW.md)）

### B12. stop 后 VC 地图框不回原厂

- **来源**：F7 v1.1 实车 P7（2026-09-27）。
- **现象**：`stop` 报 `DISARM_CLUSTER_CONTEXT: 74 restored=1`，但 VC 地图框仍是 CarPlay 状态，拔 USB 后才回原厂。`render.log` 在 `KEEPER_HELD` 后没有任何 RELEASE（包括随后的 LINK_LOST，正常情况会立即 RELEASE）。
- **推测**：kdk 模式下 KDK 可见性和 101/102 背板由 Java 管，原生 stop 绕过 Java。那次开机没有 collect，原因未确认。
- **做法**：stop 先写标记让 Java 执行 RELEASE，确认后再停 renderer；重测时 stop 后、重启前先 collect live。
- **状态**：用户决定并入 F7 v2（2026-09-27）。**F7 v2 已修（离线，2026-09-27）**：复查后推测主因是 stop 没停 BAP（当前 DIO 仍启用，VC 在原厂 KDK 位置画 BAP 箭头，HUD 同理；stop 输出无 `CLUSTER_ON_80` 说明 80 已被 Java 放回）。v2 的 stop/rollback 先写车上验证过的运行时开关 `/tmp/mu1320-f5-bap-off`，等 Java 的 `GATE kill=1` 和 displaymanager 离开 80，再停 renderer；Java 字节码不变。待场次 Q3 实车确认（Q4 重启前采集）。
- **实车（F7 v2 场次 Q，2026-09-27）**：stop 顺序 `JAVA_RELEASE: BAP_OFF` → ctx 74 → `RENDERER_STOP`，没走 native 兜底，Q4 采集为原厂仪表。但按 stop 时 BAP 已空闲约 127 秒，日志没覆盖“导航显示中 stop”；用户在支持矩阵里 Apple/Google 都填了 P。用户确认（2026-10-02）：支持矩阵的 P 就是导航显示中按 stop 得到的，VC/HUD 几秒内回原厂。**关闭。**

### B13. 无线 CarPlay 适配器不显示导航箭头

- **来源**：F7 v1.1 临时场次 T（2026-09-27）。
- **现象**：USB 插无线 CarPlay 适配器，CarPlay 与触摸板正常，VC/HUD 无箭头。
- **原因**：适配器在 USB 上冒充 iPhone（`05ac:12a8`），DIO、hook、闸门和 Identify 改写都正常，但整段导航没有任何 RouteGuidance 帧；AirPlay 通道正常（`turns controller`，HID 触摸板）。适配器不转发 iAP2 路线引导（0x5200/0x5201/0x5202），RGI 无数据可用。
- **现状**：不是本项目缺陷，我方无法修；只有适配器固件支持转发路线引导时才可能工作。可选确认：`/tmp/carplay_verbose` 下接适配器，看 hook 是否反复 `Sent 0x5200` 而无回应。

### B14. 快速插拔时原厂 SI 超时强杀 DIO

- **来源**：F7 v2 场次 Q（2026-09-27，`resource/private/vehicle-dump/f7-daily-v2/snapshot-7446670/sloginfo.txt`）。
- **现象**：1 秒内插拔时，DIO 刚启动、还在“sleeping on condition”就断开，SI 等关闭超时后 `TIMEOUT_SHUTDOWN` 转储（`/mnt/ota/system/logs/smartphone_integrator_error_17–19`）并强杀。7 代里有 3 代被杀，其中一代是闸门被动的；三次故障地址都在 `dio_manager` 本体同一偏移，不在 hook 里。功能上无影响，下一次插上照常。
- **现状**：更可能是原厂行为，但没有原厂基线的同样测试。要确认就在基线下做同样的快速插拔，再看 sloginfo。另外每次转储都会占用 `/mnt/ota` 的空间。
- **附带建议**：F7 v2 的 purge 没有检查是否已经重启过（车上 purge 和卸载在同一次开机）。可以在 Java 监听器在线或有加载了 hook 的 DIO 时拒绝 purge。
- **purge 保护（F7 v2.1，2026-10-02）**：已加：本次开机 F7 Java 运行过（`carplay_java.log`/`.1` 有 LISTENER_READY）、监测或 renderer 在运行、或有带 F7 标记的 DIO 时拒绝 purge。B14 本身（原厂对照）不在 F8 范围。
