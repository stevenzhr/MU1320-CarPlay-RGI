# F1 v2 离线审阅（2026-09-25）

状态：**试验包就绪，未上车**。包 `MU1320-RGI-f1-navi-v2.zip`，SD 目录 `mu1320-f1-navi-v2/`，身份见
[f1-v2-package.json](f1-v2-package.json)。

## 为什么有 v2

F1 v1 在车上完整重启后，Audi smartphone 卡在初始化（项目记忆 §53）。v1 用 jar 覆盖了一个 jxe2jar 转换出的原厂
嵌套类，外层类仍来自 JXE。转换出的 class 之前从未在 J9 上加载过；此前上车的 Java 全部由源码编译。
v1 没抓到 J9 错误日志，根因未定位。

## v2 内容

新 JAR `CarPlayRGI-MU1320-F1NaviV2.jar` 只含 13 个 `CarplayDSILifecycleController` 族类，逐字节取自
`MU1320-RGI-stage2-java-passive-v2.zip` 里的 Stage2 JAR（SHA `f128a948…f852`）。该 JAR 于 2026-09-23 在本车运行，
当时旧 JAR 同样被隔离，CarPlay 进入、电话、Siri 均正常（[stage2-vehicle-v2.json](stage2-vehicle-v2.json)）。
v2 不含新写的字节码，也没有 F1 专用日志。

构建（`scripts/build_f1_v2.py`）断言：

- 从 Stage2 源码重新编译的 13 个类与 Stage2 JAR 里的逐字节相同（出处可复现）；
- 用 `scripts/bytecode_compare.py` 与原厂逐方法做归一化比对：66 个方法相同，其余差异必须落在下面已审阅的清单中，
  否则构建失败（完整 diff：[f1-v2-bytecode.diff](f1-v2-bytecode.diff)）。

| 差异 | 结论 |
| --- | --- |
| `DSICarplayListenerImpl.convertAppState` | 预期：ID 2 → `CarPlayAppState(0,0,0)`，其余走原厂 |
| `updateTouchEvents` | Stage2 已上车的版本：空/空数组直接返回，去掉两条 debug 日志，坐标计算不变 |
| `mapButtonId`、`convert(int)`、`getDSITouchInputId`、`calcSecondCorr` | switch/算术排布不同，等价测试穷举比对一致 |
| `startService`（`byte` 局部量 `i2b`，值 ≤ 15）、多个 `update*`/`updateKey`/`notifyPlayPosition`（early return ↔ goto return） | 等价 |
| 外层与内层构造器、匿名类构造器 | Stage2 源码显式声明 `this$0`/`val$` 字段，javac 另加同名合成字段并在构造器中复制；`run()` 与原厂相同 |
| 原厂匿名触控比较器 → 具名 `TouchXComparator` | 同一比较逻辑，结构性差异 |

HotSpot 1.8 `-Xverify:all` 等价测试（`f1-src/F1V2Harness.java`，[f1-v2-harness.txt](f1-v2-harness.txt)）：
13 个类全部链接并初始化；`convertAppState` 600 组随机输入，非 NAVI 元素与原厂逐项相同；PHONE/SPEECH 语义、null 的 NPE
行为保留；旧 AppState 残留时与“仅旧 JAR”一致；上表 switch 类方法在 −3..300 全输入范围、`calcSecondCorr` 网格、
`getKeyId`/`getKeyState` 全部常量上与原厂一致。共 899757 项检查。

## 脚本

install/rollback 模板与 v1 共用（参数化后 v1 渲染结果逐字节不变，有测试保证），工作目录 `/mnt/app/root/mu1320-rgi-f1-v2`，
不触碰车上 v1 的工作目录。采集器新增：完整 `sloginfo` 存 SD、Java/terminalmode 相关行摘要（最多 150 行）、javacore/Snap
转储查找、j9/SI/DIO PID。事务测试 22 项（v1 与 v2 各跑一遍，含 v2 采集器）、v2 产物复现 3 项，全项目 139 项通过。

## 限制

- 验收靠行为：完整重启后 smartphone 正常初始化且 CarPlay 可用，同时 CarPlay 导航不接管原车导航（旧 JAR 已不在加载路径，
  若替代未生效，原厂逻辑会让 CarPlay 接管）。没有逐帧日志。
- Stage2 上车时 JAR 里还有其他覆盖类；族类单独加载属于首次，但与 Stage2 同样是整族从 jar 加载，不混用 JXE 外层类。
- v1 的失败根因仍未定位；若 v2 仍卡住，本次采集的 sloginfo/javacore 用于定位。
- Android Auto 未测（用户不使用）。
