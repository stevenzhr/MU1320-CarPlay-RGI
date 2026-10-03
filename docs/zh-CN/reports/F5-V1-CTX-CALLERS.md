# F5 v1：仪表 context 写入方与 KDK 改写调用方核对（MU1320-base.jar，2026-09-26）

背景：F5 v1 实车第 1 步失败。Java 调用 `switchContext(80,1,null)` 后，仪表实际停在 73
（`OBSERVATIONS-F5.txt` §1）。本文列出原厂中所有会写仪表（外部终端 1）context 或 KDK 可见性的代码，
作为 v2 方案的依据。方法：对 MU1320-base.jar 全部类做常量池字符串扫描，再用 CFR 0.152 反编译命中的类。
`resource/bundles*` 中没有命中；`resource/jars/diag.jar` 只在诊断菜单控件（`MapWidgetDiagEvoHigh`、
`WidgetsDiagEvoHigh`）中命中，正常使用时不涉及。

## 1. 引用 `switchContext` / `setKDKVisible` 的类（lsd）

| 类 | 作用于仪表？ | 说明 |
| --- | --- | --- |
| `DisplayManager`（基类） | — | 真正的 DSI 调用。确认的 context 需要 `sessionIDs[t]==回调 session` 或 session≤0 才会记录 |
| `DisplayManagerMIB2High`（运行时 `DisplayManagerEvo` 继承，未覆盖） | 是 | ① `switchContext`：`visibleKDKs[t]==20` 时经过 `addKDKToContext` 改写，72→74、74→74、76→77、77→77、75→73，**其余→73**。② `setKDKVisible(n,t)`：值变化时调用 `switchContext(getCurrentContextID(t))`（再次改写），或 `removeKDKFromContext`：74→72、77→76、73→75，其余原样 |
| `CombiMapController`（仪表地图控件，终端 1） | 是 | 见 §2，是主要写入方 |
| `DisplayControllerEvo` / `EALManager.handleContextSwitch` | 是 | 仪表切换画面（VC 标签页）时，切到该画面的目标 context；没有控制器时切到 0 |
| `AnimationMIB2High` | 否 | 调用 `getVisibleKDK(0)`，属于 G24 单屏路径（`kombiType==4`）；本车 dm-gc 为 0–78+80，不是 G24 |

## 2. CombiMapController 的触发链

KDK 控制模型为 `ChoiceModel(1, 168)`：
- **值 = 目标 context**，由 `map.Context.switchDisplayContextKombi` 写入（`MapUtils.contextToHMIServiceID`，
  对应 72/75/76 等地图 context）。
- **hints = KDK 位**（`NaviMoKoKDKConstants`）：1/2 表示帧率，4 表示 KDK 可见，8 表示 in-tube（小舞台），
  16 表示淡入（不透明）。

模型的值或 hints 一发布，就会调用 `processModelUpdateEvent`（`sysConst 541==2`，本车满足）：
1. `handleKDK` → `handleKdkDualTerminal`：重设 20 的裁剪/透明度，**重设背板 101/102 的位置和透明度**，
   调用 `setKDKVisible(hint4 ? 20 : -1, 1)`。
2. `switchToTargetContext()`：若模型值是地图 context（72–77），调用 `switchContext(值,1,this)`，
   然后被 MIB2High 改写成带 KDK 的版本（74/77）。

`ClusterKDKHandlerImpl` 发布 hints 的时机（FPK 版本）：
- `viewSizeChanged`，即 **VIEW 键**：每次都会发布；
- KOMO 视图 enabled/visible 变化（VC 进入或离开地图）；
- 原车 `rgActive` 变化、待机、clamp15；
- 仪表 BAP 请求 `setSupplementaryMap` → `setKDKVisibility`，带回退定时器；
- 另外 `ClusterService.setKOMODataRate` 也会发布（帧率位）。

FPK 版本在地图视图中 `kdkAvailable` 恒为真，所以 **hint 4 在空闲时也是置位的**。因此 `visibleKDKs[1]==20`
几乎一直成立，这就是 v1 在空闲的 74 上切 80 也被改成 73 的原因。hint 16（KDK 不透明）只在原车引导中才置位。

与 v1 日志的对应：每次按 VIEW，原厂都会发布 hints → `switchToTargetContext` → 74（日志中 `CTX actual=74`）。

## 3. 对 v2 方案的含义

| 方案 | 切 80 能否成功 | 原厂事件（VIEW 等）之后 | 风险 |
| --- | --- | --- | --- |
| A：Java 先调 `setKDKVisible(-1,1)`，再调 `switchContext(80)` | 能（先闪一下 72） | `handleKDK` 调 `setKDKVisible(20)` → `switchContext(当前=80)` → **73（瞬间没有地图）** → `switchToTargetContext` → 74；F5 需要再次接管。每次 VIEW 画面会经历 80→73→74→72→80 | 改动了原厂的 `visibleKDKs` 状态；闪烁 |
| B：原生 `dmdt sc 4 80`（F4 已在实车验证） | 能，不经过 Java 改写 | 取决于**未知项**：Java 是否能收到 dmdt 切换的确认（`setActiveContext` 会丢弃 session 不匹配的确认）。若收不到：Java 仍以为是 74，原厂的 `switchContext(74)` 会被当成"已在 74"而跳过，80 能保持住，但 F5 释放时也必须用 dmdt。若能收到：VIEW 会把仪表拉回 74，F5 再用 dmdt 接管，每次 VIEW 闪一下 | Java 如何调用 dmdt：`Runtime.exec`（lsd J9 上未验证），或由 arm 启动一个常驻脚本，读取 FIFO 请求（纯文件 I/O） |
| C：像上游那样覆盖 `DisplayManagerMIB2High`（≥80 不改写，占用期间拦截原厂切换） | 能 | 最稳定，不闪烁 | 替换 HMI 核心类（含内部类 `DisplayManagerProvider`），与 F1 v1 的 ROM/jar 混用挂死同类风险；一旦失败，HMI 启动不了 |

各方案都需要的修正：
- TAKE 后读到 73，按"被改写"处理：立即切回原 context 并停止本次接管，而不是 YIELD 后干等。
- 原厂 `handleKDK` 会覆盖 101/102 的位置和透明度。F5 每个周期核对背板，而不是只在签名变化时写。
- 若采用 B：F5 读取当前 context 不能只依赖 Java 的 `getCurrentContextID`。
