# F7 v1（日常运行候选包：自动启停，去掉 arm）：离线审阅（2026-09-27）

结论：**SD 文件夹 `mu1320-f7-daily-v1/` 离线验证通过，尚未上车。** 上车前提：F6 v2 的 B/C 场次完成并回滚、完整重启。
如果 B/C 发现问题，先改 F7 v1 再上车。部署仍然用 SSH；Toolbox 绿色菜单入口放在 F7 v2（ROADMAP F7「部署方式」）。

## 目标与范围

ROADMAP F7 的前四项：

| 验收项 | F7 v1 的做法 |
| --- | --- |
| 自动启停，不依赖手工 arm | native 闸门对每个 DIO 默认启用；renderer 和 context 80 由 Java keeper 在 CarPlay 会话开始时自动建立 |
| 替代 DIO、存活 DIO 守卫、日志上限、资源 | 拔插后的新 DIO 也启用；旧 DIO 还在时让出总线；崩溃保护；三个无上限的日志加了上限 |
| native / Java / renderer 各自的禁用 | `off|on native|render|bap|touchpad`（持久）+ `/tmp` 运行时开关 + `stop`（到重启为止）；Java 替换层整体禁用 = `rollback` + 重启 |
| 安装中断、续装、完整卸载、重装 | 沿用 F1–F6 的安装事务（主机测试覆盖）；新增 `purge`，在回滚并重启后删除工作目录 |

「固定候选版本」这一项在 F7 v1 实车通过后再定（可能是 v1，也可能是加了 GEM 入口的 v2）。

运行逻辑与 F6 v2 相同：导航状态、BAP、仪表 context 切换（kdk 默认）、触摸板手势都没有改。BACKLOG B2/B4/B7 等 F6 B/C 结果出来后再定。

## native（`scripts/build_f7_native.py`，hook `3c545ced…412f`，242772 字节）

1. 先把产生车上 hook（F2–F6 一直用的 `ad87795a…5e1d`）的 navhook 源码原样重建，**逐字节复现**，证明构建链没有漂移。
2. 只换 `framework/trial_gate.{c,h}`（入口函数不变，所以 `hook_framework.c` 不改），并在 `bus.c` 的连接循环里加一个判断。差异见 `reports/f7-v1-native.diff`。
3. 所有未定义的动态符号都能在本车的 `libc.so.3` / `libsocket.so.3`（`resource/native-libs`，从动态段读取）中找到；emutls=0，`.init_array`=4，没有新增构造函数。

F7 闸门（`f7-src/trial_gate.c`），每个进程在第一个真实 Cinemo/NME 边界决定一次：

- 不是 `dio_manager` → 被动，什么也不写（继承 LD_PRELOAD 的辅助进程不再产生回执）。
- 以下情况被动并写回执：`/mnt/app/root/mu1320-rgi-f7-v1/off-native` → `OFF_PERSIST`；`/tmp/mu1320-f7-native-off` → `OFF_RUNTIME`；
  崩溃保护已触发 → `CRASH_GUARD`。
- 否则启用，并把 `pid 启动毫秒` 写入 `/tmp/mu1320-f7-gate.last`。
- **崩溃保护**：上一代启用的 DIO 已退出，并且本代在它启动后不到 15 秒就启动 → strikes+1，否则清零；strikes 达到 3 时本次开机余下时间都被动
  （删除 `/tmp/mu1320-f7-gate.strikes` 即可恢复）。SI 自己的重试节奏是 restartDelay 2 s、3 次后停 30 s，所以 hook 如果在启动时出错，第三代就会被动。
  副作用：连续 3 次间隔很短的人为拔插也会触发，结果是本次开机失去导航显示，属于安全方向，场次 P4 会记录。
- **存活 DIO 守卫**：Java 总线只接受一个连接，新连接会挤掉旧连接；hook 断线后每秒重连一次。如果旧 DIO 还没退出，两代会互相抢连接，
  每次重连的 HELLO 都会重置 Java 路线状态。现在 `bus.c` 连接前先调用 `trial_gate_is_current()`：`gate.last` 里记的不是自己，
  就不连接（每 2 秒再查一次）。上一代仍然存活时，本代的回执 reason 为 `PREV_ALIVE`，strikes 清零。

主机测试 `tests/test_f7_gate.py`（9 项，宿主 cc 编译同一份源码）：默认启用且 fork 出的子进程被动、替代 DIO 启用、非 DIO 不写文件、两种开关、
3 次短代触发保护并保持、长代清零、存活上一代、`is_current` 跟随记录、记录文件损坏时仍安全启用。

## renderer 启动（替代 arm 的 `render_arm`）

- `f7_render.sh up`（安装到 `render/`）的步骤：hold / `off-render` / JAR 不在 → 返回 10（HELD）；
  然后核对 renderer、atlas、`f5_dm.sh`、垫片、`f7_spawn` 的校验值（错了返回 17）；renderer 已经在运行 → 跳过启动；
  否则 `dmdt gd` 确认没有别人的 98（有则返回 16），用 `f7_spawn` 启动，等 `ready` 和 19800 连接（与 arm 的时限相同）；等 98 注册；
  `gc` 解析，没声明就 `dc 80 {98,102,101,33}` 并读回，声明内容不同则返回 14。它从不切换仪表。自己的日志超过 256 KB 时清空。
- `f7_spawn.c`（`6a18e2ac…9ad2`，8680 字节，同一工具链、`-Wall -Wextra -Werror`）：fork 后在子进程里 `setsid`，
  所有信号恢复默认（SIGHUP 忽略），清空信号屏蔽，关闭 3 以上的所有描述符，stdin 接 `/dev/null`，输出追加到日志，
  去掉 LD_PRELOAD 等变量并设好库路径和 GRAPHICS_ROOT，然后 exec；父进程写 pid 文件（0600）后退出。
  这样解决了两个从 JVM 启动子进程的问题：一是 F5 v3 实车发现的 SIGTERM 被继承为忽略；二是 JVM 的 19800/19810 监听 socket 会泄漏给 renderer。
- 主机测试 `F7SpawnTests`：在父进程故意忽略 SIGTERM、多开一个描述符的情况下，子进程的 SIGTERM 是默认、SIGHUP 是忽略、没有多余描述符、
  是新会话、工作目录和环境变量正确；exec 失败时启动器已经返回 0，子进程以 127 退出。

## Java（`scripts/build_f7_java.py`，JAR `99053a47…753b`，93 类）

- 以 F6 v2 JAR 为基线。改动前先用未修改的源码编译 F5Probe、StockDisplay、CarPlayApp、TouchpadBridge，**必须复现 F6 v2 的字节**。
  发现一处：F6 v2 没有重编 F5Probe，所以它内联的 `StockDisplay.SC_HELPER` 还是 F5 v5 路径，只影响 render 日志 `START_PROBE` 行里的
  `helper=` 文字（实际调用用的是 StockDisplay 自己的常量，F6 v2 正确）。复现检查因此分两次编译；F7 重编后这一行也正确了。
- 改动（全部在 `reports/f7-v1-source.diff`）：
  - `F5Probe`：用 `F7Switches.bapOff()/renderOff()`（`/tmp` 开关或工作目录里的持久文件）取代两个 `/tmp` 判断；
    HELLO（CarPlay 会话开始）时 `keeper.request("hello")`；看门狗每秒执行 `keeper.tick(renderer 已连接)`，路线进行中 renderer 未就绪时请求一次，
    `setRenderKill(renderOff || !keeper.ready())`，所以 renderer 就绪前仪表保持原厂；每 60 秒调用一次 `capLogs`。
  - `RendererKeeper`（新增）：在守护线程里运行脚本，超时 90 秒；返回 0 表示就绪，10 表示被挡住（30 秒内不重试），
    其他值算失败，按 10 秒、60 秒、300 秒退避，失败 4 次后本次放弃；就绪后 19800 断开超过 15 秒 → `KEEPER_LOST`，再请求一次。
    renderer、sc、keeper 三个日志超过 512 KB 就清空重写（写入方都是追加模式）。
  - `F7Switches`（新增）：运行时开关沿用 F5/F6 的名字；持久开关 `off-bap|off-render|off-touchpad` 最多每 2 秒检查一次。
  - `TouchpadBridge`：原来的运行时文件判断之外，再加持久开关；BUILD_ID 改为 F7。`StockDisplay`：helper 路径改为 F7 工作目录。`CarPlayApp`：BUILD_ID 和 listener 行。
- 其他 80 个类与 F6 v2 逐字节相同。Harness：keeper 32 项、F1 lifecycle 等价 899,757 项、触摸板 8,680 项、F5（车上 F2/F3 日志重放）全部通过；
  链接审计 2089 个引用 0 缺失（`reports/f7-v1-audit.json`）。

## 脚本（`scripts/prepare_f7_daily.py`）

从 F6 v2 实车跑过的脚本推导：先重命名（工作目录 `mu1320-rgi-f7-v1`、JAR、marker `mu1320_f7_v1_b71babd1`、标签 F7），
再重新锁定变化了的校验值，最后逐个应用改动块。完整差异见 `reports/f7-v1-scripts.diff`。

- `control.sh`：删除 arm/disarm/token/verbose；新增 `stop`（写 hold 和 native-off，然后执行 F4/F5 的 `render_disarm`）、
  `off|on <部件>`（重新挂载 /mnt/app，写或删 `off-*` 文件，恢复只读）、`purge`（要求：阶段为 `INSTALLATION_BASELINE_RESTORED`、两处 SI 都已是基线（说明已经重启）、
  NavActiveIgnore 在位、F7 JAR 已移走、renderer 没在运行、原厂文件与工作目录里的备份完全一致，全部满足才删除工作目录）；
  rollback 在停止 renderer 之前先写 hold，这样还在运行的 F7 Java 不会把 renderer 再拉起来。
  install 增加 `f7_spawn` 和 `f7_render.sh` 两个载荷；status 增加开关、hold、闸门记录、listener、keeper 最后一行。
- `collect_f7.sh`：阶段改为 `live|restored|snapshot`，采集 F7 闸门回执、`gate.last`/`strikes`、开关、keeper 日志和计数、render 日志里的 KEEPER 计数。
- `f7.sh`：新的命令集合，`arm`、`disarm`、`collect armed` 会被拒绝。
- `f5_dm.sh` / `f5_sc.sh`：与 F6 v2 相同，只改了路径和标签（Java 仍然调用 `render/f5_sc.sh`）。

主机测试 `tests/test_f7_trial.py`：沿用 navjava → F3 → F5 的假车环境跑真实脚本。凡是不涉及 arm 的事务测试都原样继承，
包括安装中断后续装、`/mnt/system` 重挂载失败、未知归档、隔离区被占、NavActiveIgnore 缺失时从备份恢复、hook inode 不变、SD 只读时直接回滚、context helper 等。
arm 专用的 16 项撤掉，换成 keeper、stop、开关、purge、启动器和文件夹检查。宿主结果：**`test_f7_gate` + `test_f7_trial` 共 54 项通过**（`reports/f7-v1-host-tests.txt`）。
所有脚本都通过了 `ksh -n` 语法检查。把入口 shell 换成 ksh93 再跑一遍，只有继承来的 `f5_sc.sh` 超时用例失败；
F6 v2 在同样条件下也失败，F5 v3–v5 实车上 helper 工作正常，判定为宿主 ksh93 的差异，不是 F7 回退。

## 风险与未验证项

1. **最大的新行为是替代 DIO 启用。** F1–F6 在车上只跑过每次开机的第一代启用 DIO；F2 看到拔线时没有 disconnect 帧，Java 靠 LINK_LOST 处理，
   重连后的重放只有主机端到端测试。场次 P3 直接验证这一点。
2. Java 从 HMI 进程启动 renderer 是新路径。helper（f5_sc.sh）已经证明 Runtime.exec 在车上可用，renderer 的启动方式在主机上验证过，但 J9 在 QNX 上的描述符和信号行为要看车上的结果。
   观察点：`KEEP READY ... started=1`、`F7_RENDERER: RUNNING`、`stop` 后 renderer 日志里有 `caught SIGTERM`（或者 5 秒后被 SIGKILL）。
3. keeper 在 CarPlay 第一次连上时启动 renderer，与 DIO 初始化同时进行（上游 MU1316 的时机相同；F5/F6 的 arm 是在连接之前）。仪表在 READY 之前保持原厂，所以最坏情况是第一条路线开头几秒地图框里没有箭头。
4. HMI 单独重启（不整机重启）时，renderer 保留下来，由新的 Java 重新连接；keeper 看到 `ALIVE` 和已存在的 context 80 就直接就绪。这条路径只在代码审阅里核对过。
5. 崩溃保护可能因人为连续快速拔插而误触发（安全方向）；阈值要按场次 P4 的结果调整。
6. 导航的 LineLog 在达到行数上限后就不再写（F5 起如此），长时间运行后的诊断需要重启；轮转留给 F8 视情况再做。

## 上车顺序

F6 v2 B/C 场次 → F6 v2 rollback → 重启 → F7 v1 install → 重启 → 场次 P → rollback → 重启。
场次 D（日常行驶）和场次 R（卸载、purge、重装）改到 F7 v2，用绿色菜单做，不带电脑（2026-09-27 用户决定）。
结果回传到 `resource/private/vehicle-dump/f7-daily-v1/`，然后写 `scripts/audit_f7_vehicle.py`。
