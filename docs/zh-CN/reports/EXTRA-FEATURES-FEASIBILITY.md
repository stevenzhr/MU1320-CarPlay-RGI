# MU1320：封面、触摸板与方向盘 OK 的整合可行性

分析日期：2026-09-26。范围：代码与既有证据审阅；本轮没有修改运行代码、生成安装包或执行实车测试。

## 基线与结论

- 本地上游：`f36790d450392516ed9cbfab9cc06aa13a08bf31`（2026-09-08）。本轮检查的功能源码没有本地修改。
- MU1320：F5 v5 的实现及 F6 v1 的相同载荷。F5 已结项；本报告不替代 F6 验收，也不依据旧 README 顶部的早期状态判断项目进度。
- 在线上游 main 已继续演进，例如 OK 的摘要模式有 20 秒自动返回；本报告的具体移植判断以本地固定源码为准，未审计在线最新代码的全部变更。
- 三项都有明确的实现路径，未发现必须更换 MU1320 固件的证据；均不等于已在本车验证。

| 功能 | 可行性判断 | 整体复杂度 | 主要新增面 |
| --- | --- | --- | --- |
| MMI touchpad → DPAD | 高；现有 lifecycle 接入点可复用 | 中，三项最小 | Java 输入转换、生命周期、输入回归 |
| 方向盘滚动保留缩放 | 沿用原厂路径即可，需回归确认 | 低 | 不新增缩放实现 |
| 方向盘 OK → 路线摘要 | 较高；显示写入竞争是主要未知 | 中高 | 原始按键识别、重复 Select 抑制、FctID 19 文本及其所有权 |
| Album cover art | 较高；需确认本车实际图片流与图片服务 | 中高，跨层工作最多 | native 图片处理、总线事件、Java 图片提供者与会话管理 |

既有 `java-mu1320-build.json` 记录包含三项相关源码的 Java 1.4 编译成功；`java-linkage.json` 记录 93 类、2425 引用、0 缺失，检查范围只是静态符号存在，不包含 J9 加载、访问控制和运行行为。本轮又对本车 `MU1320-base.jar` 做了只读 javap 核对：

- `CombiBAPServiceNavi.updateCurrentPositionInfo(String)` 存在。
- `DSIKeyPanel.ATTR_KEY2` 和 `DSICarplaySafe.postButtonEvent(int,int)` 存在。
- `IPictureManager.registerPictureProvider`、`responseCoverArt(long,int,ResourceLocator,boolean)` 存在。
- `AbstractPictureManager.pictureProviders` 字段存在；这支持上游 mux 的结构假设，但不证明本车运行时使用该实现或允许反射访问。

## 1. Album cover art

上游链路：`NmeTransport::Recv` → iAP2 分片 JPEG 重组 → 独立 worker 解码并缩放为 256×256 PNG → tmpfs 文件 + `EVT_COVERART` → `CoverArt` → `TerminalModeBapCombi` 曲目信息合并 → `AppConnectorTerminalMode` / picture manager → VC 媒体页面。

这是原厂媒体图片通道，不经过 maneuver renderer、displayable 98 或 context 80。与导航渲染在功能上可分开，但共用 DIO 进程和 Java 总线。

当前缺口：

1. `build_navhook_trial.py` 明确记录 `coverart_compiled=False`；当前导航 hook 不含封面模块。导航 TLV 接收已验证不代表 JPEG stream 已验证。
2. Stage2 删掉了 CoverArt、AppConnectorTerminalMode、CoverArtProvider 和 mux；F5 延续导航范围，需要重新整合这些部分。
3. `f5-src/CarPlayApp.java` 的 `isActive()` 故意恒为 false；上游封面发送以它为门控。直接复制类会被挡住，不能为此简单改全局返回值，必须建立真实的媒体/CarPlay 会话状态。
4. 核实 `/var/app/icab/tmp/37` 在本车的可写性、读图服务访问、文件更新与重请求行为。不能仅凭目录编号推断 BAP source type：上游发送用了 21，而 mux 注释区分了 Bluetooth 21 和 Apple Link 37，需要结合本车路径实测。

主要复杂性：旧封面不能串到新曲目/新手机；图片晚于曲目信息到达时要刷新；切回 SD/蓝牙媒体后原厂图片 provider 必须仍正常；解码不能阻塞导航数据线程。上游已有单 worker、latest-wins 队列、CRC 去重和原子文件替换，可复用；需保留 QNX `STBI_NO_THREAD_LOCALS`，并复核新增依赖、缓冲区及线程退出边界。

建议验证：先只做 native 接收/生成文件和事件统计，再接 VC 图片发送；最后测连续切歌、无封面曲目、同专辑、暂停、拔线重连、媒体源切换及导航同时运行。无需重做 renderer 图形验证，但必须检查 DIO 负载和导航连续性。

## 2. MMI touchpad → DPAD

上游将触摸板单指位移累积成方向键按下/释放；不是自由光标、直接点击或双指地图操作。`CursorController` 内部方向码 1–4 在 lifecycle 中映射为 DSI 5–8。快/慢移动阈值 150/200 是上游调参，不能视为本车已合适。

当前 F1 v2 / F5 已携带同一组 13 个 `CarplayDSILifecycleController` 类，但构建时移除了 touch sink，并恢复 MU1320 的原厂 touch 语义。因此接入点和类加载基础已经存在，新增范围集中在 CursorController 与 lifecycle 的输入/启停部分，不需要 native hook 或 renderer 改动。

移植要点：

- 基于当前 MU1320 适配后的源码改动，保留资源 API 修正和 CarPlay NAVI 的窄替代。
- 同一触摸板手势只走一种 CarPlay 输入路径，避免原始 touch 与 DPAD 双重响应；真实 touchscreen 分支继续按其设备类型处理。
- 按下和释放成对；抬手、异常多指、切出 CarPlay、断开和重新初始化时清空累积量和 sink。
- 全部 lifecycle 内部类作为同一构建产物更新，不能只替换某个反编译 class。

主要实车未知是触摸板事件是否按预期到达、坐标范围/方向/采样率以及焦点移动手感。验收以四方向、轻触抖动、长划、斜划、反向划、重连及中控旋钮/返回键/原厂手写回归为主。

## 3. 方向盘滚轮与 OK

滚动通过 Navigation-BAP `MapScale.steps` 进入原厂地图缩放；中控旋钮的 `updateRotary` 是另一条 CarPlay 菜单输入。MU1320 应继续保持两者分离，不引入新的缩放处理。

OK 的工作有两层：

1. 输入：监听 `DSIKeyPanel.ATTR_KEY2`，区分方向盘 raw key 40 和中控 raw key 16。原厂会将两者折叠成 `DDS_SELECT`；需要抑制方向盘派生的那份 CarPlay Select，并保留中控选择。上游以 600 ms 标记窗口关联，需验证 MU1320 的事件顺序、按下/释放、快速交替操作。仪表页面识别也必须适配；上游把 `IMMICombiScreenChangeManager` 当作可选服务，不能假定本车一定提供。
2. 显示：在 F5 状态机上新增路线文本/摘要模式，将路名与 ETA/剩余时间作为 FctID 19 的文字发布。现有 F5 有 ETA 状态与 FctID 22 数值发送，但没有 `updateCurrentPositionInfo` 调用。数据解析层已保留 current road / maneuver after-road 等字符串，可以复用。

最主要的架构难点是文本所有权。原厂即使没有活动导航，也可能继续发布当前位置路名；上游通过 `ScreenNavStatusGate`、`GatedCombiService` 和修改后的 `ClusterService` 阻止其覆盖 CarPlay 文本。F5 的让位机制与此不同，不能直接把整个 ScreenModule/BAPBridge 搬进来并同时运行两套显示控制。

建议先验证 FctID 19 文本能否在两种 VIEW 中持续显示，再确定最窄的原厂写入门控；其后接 OK。只靠周期性重发文字不能视为解决竞争。所有权必须在原车导航接管、CarPlay 结束、断线和功能禁用时归还；关闭时不得清除原车刚写入的信息。若确需替换 ClusterService，则扩大导航回归范围。

当前 BACKLOG B3 已确认 Google Maps 提供 ETA，且 F5 已发出 FctID 22；不能再归因为 Google 缺数据。补充 FctID 19 是获得可见摘要的一条合理路径，但尚不能宣布它修复了本车全部 ETA 显示问题，更不能推导 HUD 会同步出现该文本。

## 建议拆分与顺序

以实现和定位效率排序：触摸板 → FctID 19 显示/方向盘 OK → 封面。若优先解决用户看不到 ETA 的问题，可把第二项的“文本显示探针”提前。

三项各自设置开关与验证结果，基于同一套 MU1320 源码和构建流程合并。触摸板与方向盘都改 lifecycle，封面与现有入口都改 TerminalModeBapCombi；不应制作多个包含重复原厂类的 JAR 叠加安装。

工作量为相对判断：触摸板是一次集中的 Java 功能移植；方向盘需要“文本显示所有权 + 输入路由”两个验证步骤；封面需要“native 图片链路 + Java/VC 图片链路 + 共存稳定性”三个步骤。实际工程时长取决于上车反馈，当前证据不足以给固定交付日期。

保留 F5 v5/F6 v1 为可比较基线；附加功能使用新版本，避免混入仍按旧载荷定义的 F6 结果。

## 证据入口

- 本地：`scripts/build_stage2_java.py`、`scripts/build_f5_vchud.py`、`scripts/build_navhook_trial.py`。
- 本地：`f5-src/CarPlayApp.java`、`f5-src/NaviBapSink.java`、`f5-src/F5BapOutput.java`、`f2-src/RouteStateCore.java`。
- 本地：`reports/java-mu1320-build.json`、`reports/java-linkage.json`、`reports/stage2-java-scope.diff`、`BACKLOG.md`。
- [上游封面说明](https://github.com/luka-dev/mib2q-carplay-rgi/blob/main/docs/hook/cover-art.md)
- [上游触摸板说明](https://github.com/luka-dev/mib2q-carplay-rgi/blob/main/docs/input/touchpad-dpad.md)
- [上游方向盘说明](https://github.com/luka-dev/mib2q-carplay-rgi/blob/main/docs/input/steering-wheel.md)

