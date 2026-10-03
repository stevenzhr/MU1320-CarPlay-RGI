# F7 v1.1（日常运行候选包对齐 F6 v3）：离线审阅（2026-09-27）

结论：**SD 文件夹 `mu1320-f7-daily-v1.1/` 离线验证通过，尚未上车。** 它替代 F7 v1 成为 F7 的上车版本；F7 v1
（`mu1320-f7-daily-v1/`）是在 F6 v2 上做的，从未上车，原样保留、不再上车。车上当前为原厂基线（F6 v3 已回滚）。

## 命名：为什么是 v1.1

ROADMAP F7「部署方式」里 **F7 v2 已预留给 Toolbox 绿色菜单入口**（运行代码与上车通过的版本逐字节相同，只加 GEM 入口）。
这次是运行代码的修订、不是菜单，所以不能占用 v2，按项目已有的小版本写法（navhook v1.2/v1.3）叫 **v1.1**。
路径和文件名里点号保留（`v1.1`），Java/SI 标识符里用下划线（`v1_1`）：

| 项 | F7 v1 | F7 v1.1 |
| --- | --- | --- |
| SD 文件夹 | `mu1320-f7-daily-v1` | `mu1320-f7-daily-v1.1` |
| 工作目录 | `/mnt/app/root/mu1320-rgi-f7-v1` | `/mnt/app/root/mu1320-rgi-f7-v1.1` |
| BUILD_ID | `MU1320-F7-DAILY-V1` | `MU1320-F7-DAILY-V1.1` |
| SI marker | `MU1320_F7_TRIAL=mu1320_f7_v1_b71babd1` | `MU1320_F7_TRIAL=mu1320_f7_v1_1_30175784`（后缀为 sha256(BUILD_ID) 前 8 位，与 v1 规则相同） |
| JAR（SD / 装好后） | `carplay_mu1320_f7_daily_v1.jar.DISABLED` / `CarPlayRGI-MU1320-F7DailyV1.jar` | `carplay_mu1320_f7_daily_v1_1.jar.DISABLED` / `CarPlayRGI-MU1320-F7DailyV1_1.jar` |
| StockDisplay helper | `…/mu1320-rgi-f7-v1/render/f5_sc.sh` | `…/mu1320-rgi-f7-v1.1/render/f5_sc.sh` |

`/tmp/mu1320-f7-*` 运行时文件是阶段名，与 v1 相同。F7 v1 的 status 只认 `MU1320-F7-DAILY-V1 LISTENER_READY`，
v1.1 只认 `MU1320-F7-DAILY-V1.1 LISTENER_READY`，两者互不误认（主机测试 `test_f7_v1_listener_is_not_v11`）。

## 与 F7 v1 的差异

| 层 | 改动 | 来源 |
| --- | --- | --- |
| native hook | 补丁 0004（`rgd_prune_stale_lane_cache()` 直接 `return false`）；闸门持久开关路径随工作目录改名（1 行） | F6 v3 / navhook v1.3（B8） |
| Java | `TripPlanner.LaneMemory` + `F5BapOutput` 接线（B8）、`BapPlanner` 到达距离回退（B9）、`TouchpadGesture` 188/250/38（B7） | F6 v3 |
| Java | `F5Probe`、`StockDisplay`、`CarPlayApp`、`TouchpadBridge`、`RendererKeeper`、`F7Switches`：只有版本号/工作目录字符串 | 改名 |
| 脚本 | F7 v1 脚本改名并重新锁定校验值，逻辑不变；新增 `f7_mark.sh` | 改名 / F6 v3 `f6_mark.sh` |

## 与 F6 v3 的差异

就是 F7 v1 相对 F6 v2 的全部改动（见 [F7-DAILY-V1-REVIEW.md](F7-DAILY-V1-REVIEW.md)），没有别的：去掉 arm、每个 DIO 默认启用的闸门
（开关、崩溃保护、存活 DIO 守卫）、Java `RendererKeeper` 经 `f7_spawn` 自动启动 renderer 并声明 context 80、`stop`/`off|on`/`purge`、日志上限。
导航状态、BAP、仪表切换（kdk 默认）、车道记忆、到达距离、触摸板手势与 F6 v3 相同（源码差异 `reports/f7-v1.1-vs-f6-v3-source.diff`）。

## native（`scripts/build_f7_v11_native.py`，hook `fc749d3a…c792`，242234 字节）

1. 用 `build_f7_native.py` 的做法（navhook v1.2 源码树 + `f7-src/trial_gate.{c,h}` + `bus.c` 存活 DIO 守卫）重建，
   **逐字节复现 F7 v1 hook `3c545ced…412f`**（`reports/f7-v1-native-build.json`）。
2. 在复现的树上只加补丁 0004：`rgd_hook.c` 与 navhook v1.3 的 `rgd_hook.c` 逐字节相同，差异与 `reports/navhook-v13-rgd.diff` 完全一致（一个 hunk）。
   这一步单独构建为中间产物 `785baa21…cf23`（“只加 0004”）。
3. 发出的 hook 与中间产物只差 `f7-v1.1-src/trial_gate.c` 一行：`F7_OFF_PERSIST` 改为 `/mnt/app/root/mu1320-rgi-f7-v1.1/off-native`。
   二进制上两者长度相同，只有 13 个字节不同，全部落在这个路径字符串里。
   **说明**：任务要求“只加 0004”，但工作目录必须改名，而这个路径编译在 hook 里；不改的话 `f7.sh off native` 会写到 v1.1 工作目录，
   hook 却去看 v1 的路径，持久关闭 native 就会失效。所以这一行是改名的必然结果，单独列出、单独验证。
4. `build_hook.sh` 的 ABI 检查通过（emutls=0、`.init_array` 仅编译器 000004、无 eager `rgd_module_init/fini`）；
   未定义动态符号都在本车 `libc.so.3` / `libsocket.so.3` 里，并且是 F7 v1 导入符号的子集。
   相对 F7 v1 的符号尺寸变化只有 `write_bus_snapshot_from_cache`（8364→8316，内联的清理逻辑去掉）和编译器内部编号；相对中间产物无变化。
5. `f7_spawn` 与 F7 v1 逐字节相同（不重编）。

主机测试 `tests/test_f7_v11_native.py`：
- 车道缓存：用 `navhook-src/host-test/lane_cache_test.c` + `stubs.c` 编译发出树的真实 `rgd_hook.c`，按 F6 v2 Apple 实车顺序喂数据：
  开头发的车道 3、途中补发的车道 6 都保留；路线重置后清空；40 个事件满缓存时按 LRU 淘汰 1..8、保护活动条目 0 ——**全部通过**；
  “只加 0004”的树同样通过；复现的 F7 v1 树重现车上的丢失（车道 3、6 FAIL）。
- F7 闸门：`test_f7_gate.py` 的 9 项以 `f7-v1.1-src` 重跑（`F7GateTests` 的源码目录改为类属性，v1 行为不变），并确认 `trial_gate.c` 与 v1 只差这一行。
- 产物哈希、符号尺寸、13 字节范围、差异文件两段 hunk。

## Java（`scripts/build_f7_v11_java.py`，JAR `2813457c…88d4`，94 类）

以 F7 v1 JAR 为基线。步骤：

1. **先复现**：F7 v1 的 6 个源码类编译后与 F7 v1 JAR 逐字节相同；F6 v3 的 7 个源码类与 F6 v3 JAR 逐字节相同。
   并确认 F7 v1 没动过 F6 v3 改的四个类（与 F6 v2 相同），F6 v3 没动过 F5Probe/RendererKeeper/F7Switches。
2. **逐类三方合并**（`git merge-file`，base = F6 v2 源码，ours = F7 v1，theirs = F6 v3），先把版本号和工作目录换成占位符，合并后再填 v1.1 的值。
   10 个类全部无冲突：

   | 类 | F7 v1 改过 | F6 v3 改过 | 结果 |
   | --- | --- | --- | --- |
   | TripPlanner、BapPlanner、F5BapOutput、TouchpadGesture | 否 | 是 | 取 F6 v3，**编译后与 F6 v3 JAR 逐字节相同** |
   | F5Probe、CarPlayApp、TouchpadBridge | 是 | 仅版本号（CarPlayApp、TouchpadBridge） | 保留 F7 v1（keeper、开关、`touchpadPersistentOff`），版本号改 v1.1 |
   | StockDisplay | 仅路径 | 仅路径 | 路径改为 v1.1 工作目录 |
   | RendererKeeper、F7Switches | 新增 | — | F7 v1 源码；`F7Switches.ROOT` 改 v1.1 |

   F5Probe、RendererKeeper 源码不变，但内联了 `SC_HELPER`、`RendererKeeper.SCRIPT`（= `F7Switches.ROOT` + 路径）、`CarPlayApp.BUILD_ID`，所以一起重编
   （F7 v1 构建时发现过 F6 v2 没重编 F5Probe 导致日志里路径过时）。
3. **范围检查**：
   - F7 这一侧的 7 个 class 文件（含 `RendererKeeper$ScriptRunner`）用 `javap -v -p -c` 比较，把 v1.1 字符串换回 v1 后与 F7 v1 **完全相同**（只有常量池字符串变了）；
   - `bytecode_compare` 方法级（相对 F7 v1，`reports/f7-v1.1-method-scope.json`）：TripPlanner/BapPlanner/F5BapOutput 的变化方法与 F6 v3 构建允许的范围一致，
     新增只有 `LaneMemory`、`build`、`lanes(core, memory)`、`isArrival`；TouchpadGesture 只有 `sample`；F7 侧每个变化方法都是装载了 v1.1 字符串的方法
     （`F5Probe.start`、`StockDisplay.helper`、`CarPlayApp.onActivate/startTransport`、`TouchpadBridge.start`、`RendererKeeper$ScriptRunner.run`、`F7Switches.<clinit>`）；
   - 整个 JAR 没有旧版本字符串（`mu1320-rgi-f6-*`、`F6-ACCEPT`、`mu1320-rgi-f7-v1/`、`MU1320-F7-DAILY-V1` 不带 `.1`），只剩导航字节码里本来就有的 `MU1320-F5-VCHUD-V5`、`MU1320-F2-SHADOW-V1`；
   - 其余 80 个类与 F7 v1 逐字节相同；链接审计 2129 个引用 0 缺失（`reports/f7-v1.1-audit.json`）。
4. **Harness**（全部 `-Xverify:all`，在发出的类上运行）：

   | 项目 | 结果 |
   | --- | --- |
   | F7 keeper harness（3 个路径断言改为 v1.1，`reports/f7-v1.1-harness.diff`） | 32 项 0 失败 |
   | F1 v2 lifecycle 等价 | 899,757 项通过 |
   | 触摸板 harness（`f6-v3-src/TouchpadHarness.java`，188/250/38） | 7,633 项通过 |
   | F5 harness（带 `build_f6_v3.py` 的 B9 检查修改） | 通过；F2 采集相对 F3 只多出 14 行递减的 DIST_TURN（82→28 m） |
   | F6V3Replay：`build_f6_v3.py` 的 CAPTURES | 全部 strict_mismatches=0；Google 车道 5/5（4 个来自记忆）；Apple `lanes=all-but:6` 6/7（第 7 组在 v2 采集里已被 v1.2 hook 删掉）；Apple 到达 91→28 m 递减 |
   | F6V3Replay：F6 v3 场次 D `armed-15691920`（`lanes=all`） | 2352 个输入，strict 1783 行 0 不一致；车道路口 4/4（Apple 2/2、Google 2/2），全部由 hook 直接提供 |

## 脚本与 SD 文件夹（`scripts/prepare_f7_v11_daily.py`）

- `control.sh`、`collect_f7.sh`、`f7.sh`、`f7_render.sh`、`f5_sc.sh`、`f5_dm.sh`、`smartphone_integrator.json` 都由 F7 v1 的文件改名（工作目录、JAR、marker、BUILD_ID）
  再重新锁定校验值得到，没有行为改动；`f7_render.sh` 还核对了与模板 `f7-src/f7_render.sh.in` 重新渲染的结果一致。差异见 `reports/f7-v1.1-scripts.diff`。
- 从 F7 v1 逐字节带过来：`loader_check(.c)`、`mount_state(.c)`、`dio_manager.json`、`maneuver_render`、`flag_atlas.rgba`、`f4_unbuf.so`、`geom-example.cfg`、`f7_spawn(.c)`、`trial_gate.h`。
- 新增 `f7_mark.sh`：F6 v3 实车用过的 `f6_mark.sh`（含 tr 不用范围的修正）改为 F7 标签（`F7MARK`、`F7_MARK_SAVED`、`out/f7-marks.txt`），
  开关列表去掉 arm 文件、加 `/tmp/mu1320-f7-native-off`、`/tmp/mu1320-f7-render-hold`，并记录 keeper 日志最后一行和 `GATE_STRIKES`。`scripts/f6_matrix.py` 能解析 F7MARK。
- 所有车上脚本 `sh -n`、`ksh -n` 通过；没有 `exists … && fail`、没有 `dmdt ts`、没有 tr 字符范围；所有 `/mnt/app/root/mu1320*` 路径只有 v1.1 工作目录。
- **仍叫 F5/F6 的名字**：`/tmp/mu1320-f5-*`、`/tmp/mu1320-f6-touchpad-*`、`render/f5_sc.sh`、`render/f5_dm.sh`、日志里的 `MU1320-F5-VCHUD-V5`，写在导航/触摸板字节码里，README 已说明。
- README 和观察表为中文；观察表支持矩阵应用列在前（`Apple  Google  项目`），无时间/照片列，靠 `f7_mark.sh` 打点。
  B9 放进观察表的可选项 **A1 Apple 到达**（场次 P 之后开一小段到几百米外的目的地）；没做就留到 F7 v2 场次 D。

## 主机测试

`reports/f7-v1.1-host-tests.txt`：**134 项全部通过，0 跳过**（626 秒）。

- F7 v1 的 54 项原样通过：`test_f7_gate` 9、`test_f7_trial` 45（3 处 `STAGE_DIR` 改为 `BASE / self.STAGE`，对 v1 等价）；
- `test_f7_v11_native` 15：v1.1 闸门 9 + 源码只差一行 1 + 车道缓存/产物 5；
- `test_f7_v11_trial` 48：F7 v1 事务套件以 v1.1 名字整套重跑 39 项（含安装中断续装、keeper、stop、开关、purge），
  v1 与 F5/F6 工作目录不受影响（覆盖）、v1 listener 不被误认 1 项，文件夹检查 8 项（F7 v1 文件夹未被改动、载荷来源、脚本只差版本名和校验值、hook/Java/脚本同一工作目录、README/观察表）；
- `test_f7_mark` 17：F6 v1/v2 打点套件以 F7 标签重跑（sh + ksh），外加 F7 行。
- 另：`test_f6_mark`、`test_f6_v2_mark`、`test_f6_matrix` 在 `f6_matrix.parse_marks` 支持 F7MARK 之后照常通过。

## 风险与未验证项

1. 与 F7 v1 相同：这是 F7 第一次上车，替代 DIO 启用、Java 启动 renderer、崩溃保护、开关、stop 只在主机上验证过，场次 P 验证它们。
2. 车道修复与 F6 v3 场次 D 上车通过的代码相同（hook 只多了 F7 闸门、Java 车道类逐字节相同），停车时没有车道路口，场次 P 不复测车道。
3. **B9 仍未在车上遇到 Apple 到达**：观察表 A1（可选）；没做就留到 F7 v2 场次 D。
4. 安装中断续装、purge、完整卸载重装只有主机测试；车上放在 F7 v2 场次 R。

## 上车顺序

车上为原厂基线 → 复制 `mu1320-f7-daily-v1.1/` 到 SD → `status` → `install` → 重启 → 场次 P（P1–P8）→（可选 A1）→ `rollback` → 重启 → `collect restored`。
结果回传 `resource/private/vehicle-dump/f7-daily-v1.1/`，之后写 `scripts/audit_f7_vehicle.py`。
