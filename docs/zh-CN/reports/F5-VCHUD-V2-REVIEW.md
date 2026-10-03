# F5 v2 审阅：仪表 context 切换修正（离线通过，未上车，2026-09-26）

## 1. 起因

F5 v1 实车第 1 步（校准）安全失败，详见 `resource/private/vehicle-dump/f5-vchud-v1/OBSERVATIONS-F5.txt` §1
和 `reports/F5-V1-CTX-CALLERS.md`：
- Java 调用 `switchContext(80)` 后，原厂 `DisplayManagerMIB2High.addKDKToContext` 在 KDK 可见时把它改成 73
  （`{20,102,101}`，没有地图也没有 98）。
- v1 又把 73 当成用户切换了视图，只等待，不把仪表切回来。
- 13 次 TAKE 全部停在 73；第 2–10 步里地图框的结论无效，BAP 的结论有效。

## 2. v2 改动（只改仪表 context 切换，BAP 与 renderer 不变）

| 项 | 内容 |
| --- | --- |
| native 模式（默认） | Java 通过 `Runtime.exec` 运行工作目录中的 `render/f5_sc.sh`（原厂 lsd 也用同样方式执行命令：`CommandLineExecuter`，调用方是 `PowerDSIHandler`）。helper 执行 `dmdt sc 4 <ctx>`（F4 实车路径），再用 `dmdt gs` 读回（最多读 3 次），以读回的 context 作为退出码。读回不是 80 → `TAKE_FAILED`，撤销并切回原 context，本次 ownership 内不再重试 |
| Java 是否知道 dmdt 切换 | 这是未知项（原厂 `setActiveContext` 会丢弃 session 不匹配的确认）。presenter 记下切换后 Java 报告的值：Java 报告的值发生变化，就说明原厂切换过。Java 没报告 80 时，1 秒后用 `gs` 再读回一次（`VERIFY`），用来区分"Java 不知道"和"原厂已在 helper 执行期间收回" |
| kdk 模式（备选） | `/tmp/mu1320-f5-ctx-mode` 内容为 `kdk`：先调原厂公开接口 `setKDKVisible(-1,1)`（74→72），再调 Java `switchContext(80)`，这时不会被改写；释放时先切回原 context，再恢复 KDK。模式在每次接管时锁定，切换模式会重新允许接管 |
| 73 保护 | 失去仪表后出现 73，且 1.5 秒内原厂没有自行切走 → `UNSTICK_73` 切回原来的地图 context。v1 那种"卡在 73、要按 VIEW 才恢复"的情况由此消除 |
| 背板 | 原厂 `handleKdkDualTerminal` 在每次 VIEW 或 KDK hint 变化时重写 101/102。presenter 每个周期核对背板，被改就重新设置（`BACKING_REASSERT`） |
| 释放 | 释放用接管时的同一种方式（native 用 dmdt，kdk 用 Java），不再依赖 Java 报告 80。遗留的 80（`RELEASE_STRAY`）最多每 5 秒重试一次 |
| 安装 / arm | install 把 `f5_sc.sh`、`f5_dm.sh`、`f4_unbuf.so` 放进 `$ROOT/render`（固定 cksum）；status/arm 核对它们的 checksum；arm 在放 token 前用只读的 `f5_sc.sh gs` 验证 helper（`CONTEXT_HELPER_OK: gs=74`）；status 输出 `CTX_MODE`；collect 复制 `mu1320-f5-sc.log` 和模式文件，并统计新的日志标签 |

helper 从 HMI JVM 启动，继承的 PATH 未知，所以显式设置 `PATH`（dm() 的看门狗需要 `sleep`）。
helper 的输出只写 `/tmp/mu1320-f5-sc.log`，Java 不读取任何管道。

## 3. 离线验证

| 项目 | 结果 |
| --- | --- |
| JAR | `carplay_mu1320_f5_vchud_v2.jar.DISABLED`，78 类，SHA `f3472984…aa3b`；F2 实车类、BapPlanner（F3 v2）、F1 v2 生命周期 13 类逐字节相同（build 断言）；符号审计 PASS（1910 引用，0 缺失） |
| harness | 1,502,885 项，0 失败。PRESENTER 的假 DisplayManager 改为按原厂字节码建模：KDK 改写、确认 session（Java 知道 / 不知道 dmdt 两种情况都覆盖）、`handleKDK` + `switchToTargetContext`（VIEW、离开/返回地图）。第一条用例复现了 v1 实车现象（Java `switchContext(80)` → 73）。PROPERTY 按种子交替两种确认行为，并断言从不出现 73 |
| 主机事务测试 | 115 项通过（F3 v2 事务用例 + F5：helper 切换/读回/重读/用法/超时/缺文件、arm 拒绝被篡改的 helper 或缺失的 shim、CTX_MODE、collect 复制） |
| SD 文件夹 | `mu1320-rgi/mu1320-f5-vchud-v2/`，工作目录 `/mnt/app/root/mu1320-rgi-f5-v2`；脚本与 F3 v2 车上版本的差异见 `reports/f5-vchud-v2-scripts.diff` |

## 4. 仍需实车确认

- Java 是否知道 dmdt 的切换（TAKE 行中的 `java_ctx`）；两种情况都已处理，记录下来以供参考。
- native 模式下 VIEW 是否会让原厂把仪表拉回 74（Java 知道时会拉回，F5 随后再接管，画面闪一下；Java 不知道时不会拉回）。
- kdk 模式的闪烁程度（接管时先闪到 72；每次 VIEW 会经过 73→74→72→80）。
- 从 lsd 执行 `Runtime.exec` 的耗时和成功率（`mu1320-f5-sc.log` 带时间戳）。
- 98 的几何位置在 v1 从未上屏，仍是第一次验证。
