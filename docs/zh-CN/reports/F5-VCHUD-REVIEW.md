# F5 VC/HUD 整体联调试验包审阅（v1，离线通过，未上车）

日期：2026-09-26。SD 文件夹：`mu1320-f5-vchud-v1/`（复制到 SD 根目录，无 ZIP）。
源码：`f5-src/`；脚本：`scripts/build_f5_vchud.py`、`scripts/prepare_f5_trial.py`、`scripts/f5_dm.sh.in`；
主机测试：`tests/test_f5_trial.py`。结果：`reports/f5-vchud-v1-{build,audit,harness,prepare,host-tests,scripts.diff,renderer-server.diff}`。

## 1. 目标与范围

roadmap F5：以真实路线同时驱动 BAP 和 renderer，协调显示就绪、导航接管和释放；并补 F3/F4 遗留项。

| 来源 | 项目 | F5 v1 处理 |
| --- | --- | --- |
| F4 限制 | 98 在仪表原点 (0,0)，被 VC 遮罩裁剪 | Java `ClusterPresenter` 用原厂 Layout 的 KDK 框裁剪/锚点定位 98（第 3 节），停车网格校准 + 实时调整文件 |
| F3 遗留 | 车道 FctID 24 | 移植上游车道选择与映射（`TripPlanner`），按 `lane_guidance_showing` 门控 |
| F3 遗留 | ETA FctID 22 | 上游 type 1 到达时钟（`eta_seconds` 绝对 UTC，否则 now+剩余时间），换算 HU 本地时间 |
| F3 遗留 | 到达符号 | 规则未变（F2 实车已有 ARRIVED 3/0）；本次加 renderer 到达图标，实车补测 |
| F3 遗留 | VC 不显示到目的地距离（21） | 继续发送；与 ETA 一起观察（上游注释：VC 的 DTD 块含 ArrivalTime） |
| F3 发现 1 | 门控解除后等 iOS 下一帧（~50 s） | 应急开关删除、原车引导结束时立即用保留的路线状态 `RESUME` |
| F3 发现 2 | 73 ms 机动列表回退造成 FOLLOW 闪回 | 回退到"上一个主要机动（slot, ver）"的帧先保持；下一帧替换，300 ms 内无新帧才发布 |

不在 v1：侧街（descriptor sideStreets）、底栏文字（19/46）、HUD 以外的 renderer 用途、Google Maps/Waze 专项（F6）。

## 2. 架构

```
hook (navhook v1.2, 不变) --CarplayBus 19810--> F5Probe
  RouteStateCore (F2, 不变) -> BapPlanner (F3 v2, 不变) -> F5BapOutput --BAP--> 原厂 AppConnectorNavi (VC/HUD)
                                                              \-> RenderPlanner -> RenderLink --19800--> maneuver_render (98)
                                                                                   \-> ClusterPresenter --DSI--> 原厂 DisplayManager (ctx 80/74, 98 几何)
```

- **同一决定**：renderer 命令只由 `F5BapOutput` 每次发布的 BAP 帧推导（`RCMD` 行与 BAP 调用同在 `mu1320-f5-bap.log`）。
  BAP 显示直行/START_ROUTE → renderer 直行图标；BAP 清除/让位 → renderer `CLEAR`。
- **context 80 只在需要时**：`want = !render-off && renderer 已画出一帧 && (BAP 正拥有 CarPlay 路线 || 校准)`；
  仪表在原厂地图 context（74 或 72）时才接管，切走前记住原 context，结束时切回并恢复背板透明度。
  非地图视图（用户切到其他 VC 页）不切换；stock 30 s 内收回超过 4 次则 `FIGHT_STOP`（本次路线不再接管）。
- **不替换任何原厂类**：几何/context 经公开的 `IDisplayManager`（`setCropping/setPosition/setOpacity/switchContext/
  getCurrentContextID`）；stage 读 `Navigation.getViewSizeChangeHandler().isSmallStageActive()`；Layout 从
  `HMIService.getHMITerminal(t)` 的 `HMITerminalImpl.getLayout()` 读取（只读）。
- **renderer 生命周期**：`arm` 从 `$ROOT/render` 启动（忽略 SIGHUP，SSH 断开后继续），等待注册 98 并连上 Java
  19800，再 `dmdt dc 80 98 102 101 33`（F4 实车路径）；arm 不切仪表。`disarm`/`rollback` 停止 renderer，若仪表停在
  80 则 `dmdt sc 4 74`。重启清除 context 80 与 renderer。

## 3. 原厂字节码核对（MU1320-base.jar）

- `DisplayManager.switchContext` 不检查 Java 侧 `dc[]`（MIB2High 只声明 0–78），直接转 DSI；最多 `wait(200)`；
  listener 为 null 时跳过回调。`getCurrentContextID(1)` 返回已确认 context（未确认时为请求值）。
- `setCropping/setPosition/setOpacity` 用 `getInternalDisplayID`（外部 1 → 内部 4），数组 `[8][110]` 容纳 98/101/102。
- `CombiMapController.handleKdkDualTerminal`：popup 用 Layout 118–121 裁剪 + 60/61 锚点，hint 8（small stage）用
  122–125 + 58/59；背板 101/102 由 `positionKDKBackgrounds` 定位。F5 对 98 用完全相同的值。
- MU1320 `LayoutMIB2HighB9`/`B9Sport` 与上游表一致：Classic popup (1091,110) 裁剪 (59,27) 210×153，in-tube (1055,207)；
  Sport in-tube (984,139) 裁剪 (0,0) 328×180。找不到活动 Layout 时用 B9 Classic 值（日志 `layout=fallback-B9`）。
- `AppConnectorNavi.updateTimeToDestination(1, fmt, epochSeconds)` 以 GregorianCalendar 格式化（JVM 为 UTC），故先换本地时间；
  `updateLaneGuidance(boolean, CombiBAPNaviLaneGuidanceData[])` 与上游一致。

## 4. 离线验证

| 项目 | 结果 |
| --- | --- |
| JAR | 77 类，SHA `ed1baa5c…9151`（`reports/f5-vchud-v1-build.json`）；F2 实车类 26 个逐字节相同，`BapPlanner` 与 F3 v2 JAR 逐字节相同，F1 v2 生命周期 13 类逐字节复制；`RendererMapper` 为上游原样，`RendererServer` 仅加网格开关（`-renderer-server.diff`） |
| 链接审计 | 1845 引用 0 缺失，与 NavActiveIgnore 无重叠 |
| F5Harness | **1,322,847 项，0 失败**（`-harness.txt`） |
| 主机事务测试 | 109 项通过（含 31 项 F5：真实脚本 + 假 dmdt/renderer；继承全部 F3 v2 事务用例） |

Harness 重点：

- **VEHICLE_F2**：F2 实车 capture（3 条路线、行驶、到达、拔线）→ F5 的 BAP 调用除车道/ETA 外与 F3 v2 字节码（隔离类加载器运行已上车的 F3 v2 类）
  逐条相同；renderer 出现直行、转弯、到达图标和 32 次进度条更新；所有释放都伴随 `RCMD CLEAR`。
- **VEHICLE_F3**：F3 v2 实车 capture + 其 BAP 日志的门控行重放。F5 与 F3 v2 车上发出的 descriptor **仅**差：
  i=261 的 FOLLOW 闪回及 i=262 的恢复（被去抖吸收），i=320/351 的延迟 START 变为 i=319 `RESUME reason=KILL_OFF`、
  i=350 `RESUME reason=STOCK_IDLE`。原车引导期间 0 次 BAP 调用。该 capture 中 24 帧 `lane_guidance_showing=1` 全部得到车道（样例 3 车道）。
  开发中该用例发现一个设计缺陷：iOS 重新规划（route_state 3/5）时主要机动先变为"无"再回到同一机动，初版把它当回退保持；
  已改为历史只记录有效机动。
- **PRESENTER**：接管/释放、两种 stage 与 Sport 实时 Layout、调整文件（含无效键警告与删除恢复）、背板透明度恢复、从 72 接管回 72、
  非地图视图不切、stock 高频收回 → FIGHT_STOP、每 20 s 一次 VIEW 切换不触发、render-off、校准、工作线程 stop 释放。
- **PROPERTY**：3×60,000 步随机帧/事件/原车/应急开关/故障注入/去抖/校准；不变量：原车有路线时 0 次 BAP、renderer 所有权跟随 BAP、
  仪表只在 74/80 且"想要⇔在 80"、状态机语法。
- **E2E_RENDER**：真实 `RendererServer` 监听 127.0.0.1:19800 + 假 renderer：48 字节 `CMD_MANEUVER`/`CMD_BARGRAPH`/`CMD_CLEAR`/网格包，
  FRAME_READY 才切 80，断开即切回，重连 READY 后重发当前画面，5 s 无心跳断开。
- **FORMAT**：原厂 `BAPDistanceFormatter`，经代理的原厂 `CombiBAPNaviLaneGuidanceData` 与 `updateTimeToDestination` 参数。

## 5. SD 包与脚本

脚本由 F3 v2 模板（生成车上 F3 v2 脚本的同一套）经改名表 + 显式 hunk 生成，对比车上 F3 v2 脚本的差异见
`reports/f5-vchud-v1-scripts.diff`：新增 renderer/atlas 载荷校验与安装（`$ROOT/render`），`f5_dm.sh`（F4 实车的 dmdt 包装、解析与
renderer 检查，校验和通过后才 source），`arm` 在 token 之前 `render_arm`，`disarm`（rollback 也调用）末尾 `render_disarm`，
`status`/`collect` 增加 renderer 与 displaymanager 只读状态、F5 日志和计数。原生件 hook/loader/mount_state/DIO 配置与 F3 v2 逐字节相同，
`maneuver_render`/`flag_atlas.rgba`/`f4_unbuf.so` 与 F4 run4 SD 文件夹逐字节相同。全部脚本无 `dmdt ts`。

## 6. 上车判定要点（结果回传 `resource/private/vehicle-dump/f5-vchud-v1/` 后）

1. 校准网格在两种 VC 地图视图中是否落在原厂 KDK 框、完整可见（照片 + `GEOM` 行）；如需调整，记录最终 `geom.cfg`。
2. 路线开始：地图框箭头与 BAP/HUD 箭头一致；`TAKE from=74|72` 与 `RELEASE` 成对；左转/环岛/掉头/到达图标完整（F4 被裁的项）。
3. 车道：VC/HUD 是否显示，与 iPhone 一致；ETA 是否在 VC/HUD 显示；到目的地距离是否因 ETA 出现。
4. 让位与恢复：原车引导期间 0 次 BAP 调用、仪表回原厂 context；原车结束、应急开关删除后几秒内 `RESUME`。
5. Google Maps（README 第 10 步，2026-09-26 应用户要求加入）：Google Maps 路线是否经同一 hook/Java 链路到达（state log 有
   ACTIVATE、BAP log 有 START），VC 地图框与 BAP/HUD 是否显示并与 CarPlay 屏幕一致，结束时是否清除。之前各阶段均无
   Google Maps 实车样本；若无任何显示，用 capture 区分"App 未提供 0x5200–0x5204 数据"与"F5 未发布"。
6. 拔线：`LINK_LOST` → TEARDOWN + `RCMD CLEAR` + `RELEASE`；回滚 + 重启后 `F5_RENDERER: ABSENT`、`DM_CONTEXT_80: ABSENT`、基线。
7. 工作站：`F2Replay` 回放 state log 0 差异；`F5Replay` 门控回放 BAP log（含 `RCMD`）0 差异；写 `audit_f5_vehicle.py`。

## 7. 未知与风险

- **VC 是否在 KDK 框位置遮挡 98**：F4 只验证了 (0,0)；原厂 KDK 显示时 VC 会"开洞"（由原厂 KDK 可见性驱动），F5 不伪造 KDK 可见性。
  若框内被 VC 自己的图形盖住，校准网格会直接显示出来；对策（v2）是调整位置或研究 KDK 可见性信号。
- **stock 与 F5 争夺仪表 context**：F4 七分钟停车 0 次收回；F5 行驶中、切换视图时未知。有限次收回会被记录（`STOCK_RECLAIMED`/`FIGHT_STOP`）。
- 仪表显示是否需要 `setUpdateRate`：F4 证明 `sc 4 80` 即可到达 VC；Java 路径（`switchContext(80,1,null)`）等价但首次上车验证。
- 在 small stage 下 Classic 的 in-tube 裁剪继承自 Q7（210×153），与 101 背板（328×180）尺寸不同，是原厂同样的组合；实车看效果。
- renderer 网格状态保存在 renderer 进程中；校准中若 renderer 重连（同一进程）网格状态可能与 Java 记录不一致——校准结束时若仍见网格，`disarm` 即可。
- 车道/ETA 在 VC/HUD 上的实际呈现取决于 VC 固件；只有"调用成功"不能算显示通过。

## 8. 上车前外部审阅（Codex，2026-09-26）与处理

5 项发现逐条核对属实，全部在 v1 原地修正（尚未上车；JAR 与脚本重建，SD 文件夹名不变）：

| 级别 | 发现 | 处理 | 新增测试 |
| --- | --- | --- | --- |
| P1 | 去抖 `fireDebounce()` 不查原车导航，300 ms 内原车开始引导时会写 BAP | fire 前重查 `routePresent()`，非 0 则静默释放（`DEBOUNCE_STOCK_ROUTE_*`）；watchdog 在 fire 前先读应急开关 | SYNTH：fire 时 stock=1 → 0 次 BAP 调用 + renderer CLEAR，之后原车结束 RESUME |
| P1 | 无路线校准只发网格，renderer 须收到机动指令才报 FRAME_READY（`main.c` `g_cleared`），Java 永远不切 80 | 校准时网格 + 直行箭头（F4 网格场景同样带箭头），结束时网格关 + CLEAR；README 同步 | E2E_RENDER：网格包 + `CMD_MANEUVER` 直行、FRAME_READY 后切 80、结束 CLEAR 后回 74 |
| P2 | `out/` 存在即把 dmdt 输出写 SD；SD 只读时直接 `control.sh rollback` 在 `render_disarm` 处退出 | control 的查询输出一律写 `/tmp` 平面文件；解析函数容忍文件缺失；超时记录不因写失败退出 | 主机：`out/` 只读时直接 rollback 完整恢复 |
| P2 | 释放时无条件恢复背板透明度，可能覆盖原厂刚设置的值；未恢复背板位置 | 只有 F5 自己切回时才恢复透明度，且仅当当前值仍是 F5 写入的值；原厂已收回 context 时不动（`op=stock_owns`）；位置仍是 F5 写入的值时恢复原位置 | PRESENTER：原厂改写的值保留、F5 的值恢复、覆盖文件移动的背板位置恢复、原厂收回时不动 |
| P2 | 仪表切回失败或查询超时 `disarm` 仍报成功 | `render_disarm` 核验"renderer 已停且 context 已知且≠80"；`disarm` 否则 `STOP`；rollback 继续恢复文件并打印 WARNING（回滚后的重启清除 80） | 主机：sc 无效 → disarm 失败；dm 无响应 → disarm 失败、rollback 成功并警告 |

同日应用户要求 README/观察表加入 Google Maps 路线步骤（第 10 步），判定见第 6 节第 5 项。
