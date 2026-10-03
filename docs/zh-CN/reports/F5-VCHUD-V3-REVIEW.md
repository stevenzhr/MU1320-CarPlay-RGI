# F5 v3 审阅：native 切换延迟与 FIGHT_STOP 修正（离线通过，未上车，2026-09-26）

## 1. v2 实车结果（`resource/private/vehicle-dump/f5-vchud-v2/`）

基本通过：第 2–12 步用 kdk 模式跑完（到达、车道、Google Maps、拔线都正常），回滚后恢复证据为基线。
v1 的 73 问题已解决：TAKE 33 次，0 次 TAKE_FAILED，0 次 UNSTICK_73。Java 知道 dmdt 的切换（`java_ctx=80`）。

| 现象 | 根因 | v3 |
| --- | --- | --- |
| native 模式 rm 后背板要 3~5 秒才消失 | helper 由 HMI JVM 启动，继承了被忽略的 SIGTERM。`dm()` 的 `kill "$dm_wd"` 关不掉看门狗子 shell，`wait` 要等 `sleep 10` 结束，所以每次 native 切换约 20 秒（实测 20084–20089 ms）。rm 时 presenter 线程还卡在 VIEW 引起的那次重新接管里。本机 sh/ksh 复现：dm() 在 SIGTERM 被忽略时 10.0 秒，正常时约 0 秒 | 看门狗改用 `kill -9`（sh 和 ksh 下均约 0 秒）；新增主机回归测试（SIGTERM 被忽略时 helper 在 5 秒内完成）；去掉本车不支持的 `date +%s` |
| 小地图视图下校准网格被时速表挡住 | in-tube 坐标 (1055,207) 在时速表圈内；路线进行中两个视图的箭头都完整（第 3 步）。推断：VC 只有在收到路线引导后才打开表盘内的 KDK 窗口 | 不改代码；README 改为在路线中检查 in-tube 位置 |
| （用户未察觉）2 次 FIGHT_STOP，之后这条路线不再显示地图框箭头，分别持续约 80 秒和 290 秒 | 一次 VIEW 原厂会连续收回 3~4 次（每 0.25 秒一次，最后一次约 1.25 秒后）；路线开始约 0.5 秒后原厂也会收回一次。v2 的规则（30 秒内超过 4 次）在按两次 VIEW 后就会触发 | 只把持续不到 2 秒的接管算作争夺，连续超过 6 次才 FIGHT_STOP；持续超过 2 秒的接管会把计数清零。harness 按实车节奏构造了 VIEW 连续收回用例（native 和 kdk 各一组） |

## 2. 离线验证

- JAR `carplay_mu1320_f5_vchud_v3.jar.DISABLED`，78 类，SHA `709664c5…3cf6`；符号审计 PASS。
- harness 1,502,889 项，0 失败（PRESENTER 88 项）。
- 主机事务测试 116 项通过。
- SD 文件夹 `mu1320-rgi/mu1320-f5-vchud-v3/`，工作目录 `/mnt/app/root/mu1320-rgi-f5-v3`。

## 3. v3 上车重点

- native：GRID on→TAKE、GRID off→RELEASE 的间隔应在约 1000 ms 以内；rm 后网格和背板应同时消失。
- 路线中连续按 VIEW 4~5 次，箭头每次都应回来，不能出现 FIGHT_STOP。
- 两种模式的闪烁对比（native 预计只闪 74；kdk 会经过 73/72）。

## 4. v2 其他观察（未改，留作后续）

- 到达后到达符号一直不消失，要手动结束导航才消失（iOS 在到达后仍保持路线）。
- Google Maps 路线没有到达时间（ETA）。
- 原车导航开始后，CarPlay 上的导航会被强制结束（iOS/原厂行为，让位规则按预期工作）。
