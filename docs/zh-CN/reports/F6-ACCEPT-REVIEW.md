# F6 v1 功能与兼容性验收包：离线审阅（2026-09-26）

结论：**SD 文件夹 `mu1320-f6-accept-v1/` 可以上车，尚未上车。** F6 不改运行代码，验收对象是 F5 v5（实车通过版本）。

## 范围与决定

- F6 是验收阶段。改代码会让被验收的版本不再是 F5 实车通过的版本，所以 F6 v1 只增加证据工具：
  - hook、Java JAR（`27b2fefd…8bfd`）、renderer、SI/DIO 配置、全部 `f5_*`/`control.sh`/`collect_f5.sh` 与
    `mu1320-f5-vchud-v5/` **逐字节相同**（21 个文件，`prepare_f6_accept.py` 按 v5 的 `SHA256SUMS` 核对）。
  - `control.sh` 校验 `collect_f5.sh`，`f5_trial.sh` 校验 `control.sh`，因此打点不能加进 collect。
    新增的 `f6_mark.sh` 只把一段文本追加到 SD 的 `out/f6-marks.txt`（SD 挂载先切 rw，写完恢复原状态，与 `f5_trial.sh` 做法相同）。
- BACKLOG 项（B1 距离文字、B2 到达自动清除、B4 FIGHT_TAKES、B5 占位图）不在 F6 v1 中修改。F6 的结果决定是否在 F7 前处理它们。
- 一次 install 可覆盖多个场次（每场次 = 完整重启 + arm + 一次 USB）。arm 每次开机只能一次（verbose 标记），
  状态日志 6000 行上限约为 Google Maps 1.5 小时，所以每场次 ≤60 分钟。场次间隔较长时先回滚。

## 首版支持矩阵（F5 v1–v5 采集，[F6-SUPPORT-MATRIX-SEED.md](F6-SUPPORT-MATRIX-SEED.md)）

`scripts/f6_matrix.py` 按共同的输入计数 i 把 frames.cap、state、BAP、render 日志对齐，按路线（结束、断线、会话、
应用切换）分段。5 次采集，20 条路线（Apple Maps 17 条/2357 秒，Google Maps 3 条/345 秒），BAP FAULT 0，REJECT 0。

| 项目 | Apple Maps | Google Maps | Waze |
| --- | --- | --- | --- |
| 到转向距离 / 距离递减 | 已发出 | 已发出 | 未测 |
| 到目的地距离 | 已发出（VC 显示未确认） | 已发出（显示未确认） | 未测 |
| ETA | 已发出（显示未确认） | **已发出**（显示未确认） | 未测 |
| 车道 | 已发出 | 已发出 | 未测 |
| 重算 | 出现过，无清除闪断 | 出现过 7 次，无清除闪断 | 未测 |
| 到达 | 出现过 | 未遇到 | 未测 |
| 机动 | 左/右转、环岛出口 1、到达左/右 | 左/右转 | 未测 |
| 单位 | mi/ft（少量 m） | mi/ft | — |

日志层面的新发现：

1. **B3 重新定性**：F5 v2 的 Google Maps 路线 `eta_seconds` 每秒更新（ETA 按秒递增，由“当前时间 + 剩余时间”算出），
   F5 发出了 345 次 FctID 22（`ETA src=eta`）。所以 Google Maps **提供** ETA，F5 也已发出，VC/HUD 上看不到是**显示端**的问题。
   Apple Maps 的 ETA 同样已发出且显示未确认。F6 A2/A13 要先找出 VC/HUD 在哪里（是否）显示 ETA 和到目的地距离。
2. **B2 数据**：iOS 进入 ARRIVED 后一直保持，直到用户结束导航或拔线：4 条到达路线在 ARRIVED 分别停留 19、29、107、170 秒。
   到达符号一直显示是 F5 如实转发 iOS 状态的结果；是否自动清除（例如到达 N 秒后）是 F7 前的产品决定，F6 B8/C8 记录实际时长。
3. Google Maps 在 334 秒的路线中经历 7 次 `REROUTING→LOADING→ROUTE_SET`，期间没有 BAP TEARDOWN 或仪表 RELEASE
   （`reroute_clears=0`），不会闪断。F6 C7 用照片确认。
4. 仍未覆盖、需要 F6 补测：Waze、应用切换（0 次）、匝道/出口、保持车道、掉头、Google 到达、公制单位、日夜、以及回归项。

## 新增文件

| 文件 | 说明 |
| --- | --- |
| `f6-src/f6_mark.sh` | 车上只读打点：`DATE`/`EPOCH`、F5 state/bap/render 日志最后一行（只有数字）、ctx-mode 与开关文件是否存在。步骤号限定 `[A-Za-z0-9._-]{1,16}`，备注经 `tr -c` 过滤。不读 hook 日志，不调用 dmdt，没有 `&& fail` 写法。 |
| `f6-src/README.md` | 分场次流程：A 停车（应用、ETA 显示位置、公英制、日夜、电话/Siri/音频/倒车影像/输入、应用切换、Waze），B/C 行驶（乘员操作），结束回滚。 |
| `f6-src/OBSERVATIONS-F6.txt` | 支持矩阵观察表（P/F/U/N/NA）+ 各步骤记录。 |
| `scripts/f6_matrix.py` | 矩阵工具：SENT / APP_NOT_PROVIDED / NOT_EXERCISED / NOT_SENT；车道按 F5 的 `lane_guidance_showing=1` 条件判定；ETA 按 `src=eta/rem`；重算闪断、到达停留秒数、打点归属。 |
| `scripts/prepare_f6_accept.py` | 生成 SD 文件夹，核对携带文件与 v5 相同；`out/` 存在时拒绝覆盖。 |
| `tests/test_f6_matrix.py`、`tests/test_f6_mark.py`、`tests/test_f6_accept.py` | 见下。 |

## 验证

- `test_f6_matrix`（12 项）：路线分段（结束、断线、会话、应用切换）、字段判定四种状态、NOT_SENT 在应用行优先、车道门控、
  重算闪断计数、到达停留、打点归属、capture 截断、坏行拒绝；另有一项读取 F5 v2 实车采集（私有数据存在时运行），
  断言 Google ETA/车道为 SENT、FAULT 0、重算清除 0。
- `test_f6_mark`（10 项，/bin/sh 与 /bin/ksh 都运行）：追加格式、SD ro→rw→ro、SD 原本 rw 时不重新挂载、备注过滤、
  非法步骤号不写、非 root/错误平台/helper 被改时拒绝、挂载恢复失败时报 STOP、`date +%s` 不支持时写 NA、
  写出的格式能被 `f6_matrix.parse_marks` 读取、静态规则。
- `test_f6_accept`（41 项，285 秒，全部通过；日志 `f6-accept-v1-host-tests.txt`）：F5 v5 的全部事务测试（install/arm/collect/rollback/disarm、context helper 等）以 F6 文件夹重跑；
  SHA256SUMS 与文件一致；v5 携带文件逐字节不变；README 使用 F6 路径。

## 上车后

结果放到 `resource/private/vehicle-dump/f6-accept-v1/`。然后：

1. 对每个场次的 `armed-*`/`snapshot-*` 运行 `scripts/f6_matrix.py <dirs> --marks out/f6-marks.txt`，并用 `F2Replay`/`F5Replay` 回放。
2. 把观察表的显示列并入矩阵，写 `reports/F6-SUPPORT-MATRIX.md`（日志层 + 显示层，区分通过/失败/未测/应用未提供）。
3. 写 `audit_f6_vehicle.py`（回滚证据、FAULT/REJECT/TAKE_FAILED、每场次 arm/collect 完整性）。
