# F3 BAP 输出试验审阅（v1，离线）

日期：2026-09-25。状态：`F3_BAP_TRIAL_READY`（离线通过，**未上车**）。
SD 文件夹：`mu1320-rgi/mu1320-f3-bap-v1/`。源码：`f3-src/`。脚本：`scripts/build_f3_bap.py`、
`scripts/prepare_f3_trial.py`。测试：`tests/test_f3_trial.py`。

## 1. 用户决定（2026-09-25）

| 问题 | 选择 |
| --- | --- |
| 与原车导航冲突 | **让位模式**：原车无路线时才输出；不取消原车路线、不装拦截层、不替换原厂 ClusterService |
| 显示端 | VC + HUD |
| START_ROUTE（前往路线起点） | **FOLLOW_STREET**（沿路直行）+ 距离 |

上游的 REPLACE 模式需要改原厂 `ClusterService`（上游是整类覆盖）并在 `CombiBAPListener.combiservice`
上装 `GatedCombiService`，属于 F1 v1 在车上失败的那类改动，本版不采用。

## 2. 原厂 API 核对（MU1320 lsd.jxe 转换 JAR）

- `CombiBAPServiceNavi` 接口与上游使用的方法签名一致；实现为 `AppConnectorNavi`。
- `AppConnectorNavi` 的同步模型与上游文档一致：`updateRGStatus` 值变化时 `startSync(0)`；
  `updateManeuverDescriptor` 调 `startSync(1)`；各 FctID 经 `sendStatusIfChanged` 去重。所以沿用上游
  顺序：descriptor 之后发 ExitView（变体交替，保证 49 真的发送）和距离，以关闭 sync(1)。
- `Navigation.getInstance().getRouteManager().getRoute()` 存在，用于判断原车是否有路线。
  MU1320 原厂 `ClusterService` 没有上游覆盖类里的 `getDSIResponseContainer`，F3 不伪造 `rgActive`，
  也不调用 `updateRGIString`。
- `BAPDistanceFormatter` 存在；`BAPDistance` 的内部类属性在转换 JAR 中缺失，按上游用反射读取。
  主机上：500 m→`5000/0`，2.5 km→`25/1`，英制 500 m→`5000/2`，英制 30 km→`190/4`（原厂格式，
  实际单位显示以车上为准）。

## 3. 设计

```
hook → CarplayBus → RouteStateCore (F2，逐字节相同) → BapPlanner (纯函数) → F3BapOutput → NaviBapSink → AppConnectorNavi
```

- **BapPlanner**：把 F2 决定映射为 descriptor/距离/进度条/ManeuverState/目的地距离。与上游
  BAPBridge 的差异：START_ROUTE→FOLLOW_STREET；没有 600 ms 闪烁线程（进度条线性）；只发
  17/39/23/18/49/55/21。`ManeuverMapper` 保持上游原样，覆盖只在 planner 中。
- **F3BapOutput**（发布状态机）：
  - 开始：`RG_STATUS 1, RG_TYPE 0, DESCRIPTOR, EXIT_VIEW, DIST_TURN, MANEUVER_STATE, DIST_DEST`。
  - 更新：只发变化项；descriptor 变化时必带 ExitView + 距离。
  - 释放（路线结束、到达后结束、LINK_LOST、SESSION、disconnect 帧、STOP、应急开关）：上游 teardown
    的 7 个调用——**仅当原车没有路线**。原车有路线或无法判断时静默释放（`RELEASE_SILENT`），
    不发任何调用，避免抹掉原车引导；之后 `HOLD_OFF`，直到原车没有路线才重新开始。
  - 看门狗每秒检查原车路线和应急开关（`/tmp/mu1320-f3-bap-off`）。
  - 原厂服务抛异常：记录 `FAULT`，尽力 teardown（同样遵守原车路线规则），本进程内不再输出。
- **NaviBapSink**：通过 TerminalMode `IServiceManager` 取 `CombiBAPServiceNavi`，首个路线激活时绑定；
  formatter 首次使用时才创建；绑定失败只记录原因（`BIND fail=`）。
- **F3BapProbe**：F2 管线 + 输出。state/capture 与 F2 格式相同（F2Replay 可直接回放），另写
  `/tmp/mu1320-f3-bap.log`（每个决定/调用一行，只有数字）。
- 入口 `CarPlayApp.startTransport` 在原有 `try/catch Throwable` 内，且只有看到
  `MU1320-F3-BAP-V1 LISTENER_READY` 才允许 arm。

## 4. JAR 组成（52 类，SHA `aa692cfb…b886`，87693 字节）

| 部分 | 类 | 来源 |
| --- | --- | --- |
| F2 类集 | 26 | 源码重编译，与车上 F2 JAR **逐字节相同**（CarPlayApp 除外） |
| F1 v2 lifecycle 族 | 13 | 直接复制车上 F1 v2 JAR 的字节（NAVI app state→0，替代 NavActiveIgnore） |
| F3 新类 | 13 | BapPlanner、BapSink、F3BapOutput(+接口)、NaviBapSink(+内部类)、F3BapProbe(+内部类)、CarPlayApp |

链接审计（`reports/f3-bap-audit.json`）：1313 个引用全部解析，0 缺失，无形状/访问变化，与
NavActiveIgnore 无类重叠。审计函数新增 `allowed_tokens` 参数（默认不变，navjava 报告重跑逐字节相同）。

## 5. 离线验证

`reports/f3-harness.txt`：340,374 项检查，0 失败（HotSpot `-Xverify:all`，与车载 JAR 同一批字节码）。

- **VEHICLE_REPLAY**（525）：F2 实车 capture（182 输入）先经 F2Replay 核对 0 差异，再驱动 F3：
  3 条路线 → 3 次 START、3 次 TEARDOWN、0 次静默；调用语法（开始/清除序列、descriptor 后
  ExitView+距离、ExitView 变体交替、非所有期无调用）全部成立；32 个 START_ROUTE 输入不再出现
  TURN 直行；右转和到达符号已发；路线 3 发出 95 次距离；拔线 LINK_LOST 时已无需清除。
- **PLANNER**（16）：START_ROUTE、城市/高速阈值、进度条分母、PREPARE_TURN→CHANGE_LANE、
  DIST_HOLD/SYM_HOLD 保留。
- **SYNTH**（31）：原车路线先在→零调用、原车清除后开始；原车后出现→静默；路线结束时原车有路线→静默；
  看门狗轮询；原车状态未知→不输出；应急开关开/关；LINK_LOST/SESSION/STOP/disconnect→清除；
  reject 不变；更新/开始/清除中的异常。
- **PROPERTY**（339,796）：两组 60,000 步随机（帧、路线结束、断链、会话、原车切换、应急开关、
  注入异常）：**原车有路线或未知时 BAP 调用次数为 0**；所有者必然是活动路线且原车空闲；
  无故障的 20,000 步运行满足完整调用语法。
- **FORMAT**（6）：原厂 formatter 在主机可用；未绑定时调用会抛出（发布端记 FAULT，不会静默丢弃）。

事务测试 `tests/test_f3_trial.py`：继承 navjava/F2 的全部事务测试，并覆盖需改变预期的主流程，
新增隔离相关用例（安装后隔离、arm 要求已隔离、隔离槽占用拒装、隔离件丢失从备份恢复、
仅剩隔离时回滚不能判为已基线、未知文件停止、应急开关状态、旧 listener 标记不能 arm）。
两项新测试在去掉对应守卫的脚本上失败（变异检查）。全项目 168 项测试通过。

脚本由 navjava 模板经重命名表 + 隔离补丁生成，与车上 F2 脚本的差异见 `reports/f3-bap-scripts.diff`。
采集器新增 F3 文件复制、BAP 计数、事件行、sloginfo 全文存 SD（含 `Modes changed` 摘录）。

## 6. 风险与未验证

1. **VC 是否接受**：上游在 MU1316 上强制 `rgActive`/`rgiValid` 以便 VC 接受 RGI；F3 不这样做。
   HUD 预期直接显示 BAP 符号；VC 的表现是本次试验要回答的问题（照片 + 观察表）。
2. **原车空闲时的写入**：未装拦截层。若原车在空闲时也刷新 17/23/18 等，会与 F3 交错。离线无法
   验证；看 VC/HUD 是否闪回或箭头消失。
3. `getRoute()==null` 作为"原车无路线"的依据来自上游，MU1320 上未实测；若车上始终返回非 null，
   F3 将一直 `HOLD_OFF`（安全，但本轮无输出）。
4. AppConnectorNavi 由 F3（bus 线程）与原厂（NavigationJobs）并发调用，与上游相同，未加锁。
5. 英制单位显示、HUD 进度条行为、到达符号外观只能实车确认。
6. 未包含：车道（F2 已指出需移植上游车道选择）、ETA、底栏文字、renderer（F4）。

## 7. 上车判定（回传后审计）

通过条件：BIND ok；每条 CarPlay 路线 START 一次并在结束时 TEARDOWN（或第 6 步 RELEASE_SILENT）；
0 FAULT、0 REJECT；F3Replay 回放 bap.log 至第一条门控行 0 差异；观察表/照片显示 HUD（及 VC，若有）
箭头与距离随路线变化、结束/拔线后消失；让位步骤中原车引导未被清除；回滚后基线与完整重启恢复。
