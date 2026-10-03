# F6 v2（F5 v5 导航 + 触摸板 DPAD）：离线审阅（2026-09-26）

结论：**SD 文件夹 `mu1320-f6-accept-v2/` 可以上车，尚未上车。** 上车前需先用 v1 文件夹回滚 F6 v1 并重启。

## 范围

- 依据 [EXTRA-FEATURES-FEASIBILITY.md](EXTRA-FEATURES-FEASIBILITY.md) 的顺序，三项附加功能中先做最小的触摸板 → DPAD。
  方向盘 OK（FctID 19 文本所有权）和封面（native 图片链路）不在 v2 中。
- 场次 A 已由 v1 完成，v2 删去 A，新增停车的 **T 场次**（安装、重启、**不 arm**、连 CarPlay 测触摸板），通过后重启进入 B/C。
- 导航载荷不变：native hook、renderer、dmdt 垫片、DIO 配置与 F5 v5 逐字节相同；导航 Java 字节码只改了 StockDisplay 的
  helper 路径（新工作目录）和 CarPlayApp 的 BUILD_ID（arm 检查的 listener 标记）。

## Java 改动（`scripts/build_f6_v2.py`，JAR `da92287c…c294`，84 类）

| 位置 | 改动 |
| --- | --- |
| `CarplayDSILifecycleController` 构造 / `init` / `deinit` | 建立、启动、停止 `TouchpadBridge` |
| `$CarplayDSIController.startService` | 每次 CarPlay 连接调用 `TouchpadBridge.newSession()`，丢弃上一次连接遗留的手势 |
| `$TerminalModeDSIKeyEventsController.updateTouchEvents` | 先交给桥接；桥接不接管（开关、故障、停止）时走原来的 MU1320 路径 |
| 新增 `com.luka.carplay.input.*` | `TouchpadGesture`（上游 CursorController f36790d 的 150/200 阈值、30 死区，单次采样最多 8 格）、`TouchpadBridge`、`TouchpadLog`（≤2000 行，只有数字） |

`reports/f6-v2-method-scope.json`：与 F5 v5 相比 87 个方法 javap 相同，只有上表 5 个方法和一个 `access$` 变化；
中控旋钮 `updateRotary`、`updateKey`（选择/返回/推拨）不变，harness 也在真实 lifecycle 上重放确认。

**修正 codex 草稿的一处接线**：草稿用 `CarPlayApp.onActivate/onDeactivate` 打开触摸板会话，但 F5 系列的 `TerminalModeBapCombi`
只调用 `startTransport` 和 `onDeactivateAndWait`（javap 核对），会话永远不会打开，桥接在车上不会生效；主机 harness 手动设了会话所以没发现。
v2 改为不设会话门控（HMI 只在 CarPlay 有输入焦点时把触摸批次交给这个 lifecycle），由 `startService` 负责每次连接的重置，CarPlayApp 不再改动调用逻辑。

## 触摸板行为要点

- 只处理非触摸屏（触摸板）单指；抬手、双指、空批次都会清掉累积量。按下/释放成对发送，即使 DSI 在按下后抛异常也尝试释放。
- 运行时开关 `/tmp/mu1320-f6-touchpad-off`：每个触摸批次检查；手势进行中切换时，这一下按原方式做完或丢弃，抬手后才切换，不会把 DPAD 手势的尾巴当成原厂触摸发出。
- 故障（DSI 异常）后本次开机停用桥接并回到原厂路径（日志 `FAULT`）。
- 本车 A4 B9 无触摸屏；触摸屏分支保持原厂的坐标偏移和按 X 排序，仅为兼容。

## 脚本（`scripts/prepare_f6_v2.py`）

与 F5 v5 同一模板链（F3 v2 模板 → F5 重命名/renderer hunks）生成，再做 F6 v2 重命名：工作目录 `/mnt/app/root/mu1320-rgi-f6-v2`、
JAR `CarPlayRGI-MU1320-F6AcceptV2.jar`、SI marker `mu1320_f6_v2_cb925ff9`、listener `MU1320-F6-ACCEPT-V2`。
之后所有脚本层面的 F5 名字改为 F6：入口 `f6_trial.sh`、采集 `collect_f6.sh`、终端标签 `F6_*`、SI marker 键 `MU1320_F6_TRIAL`、pending 文件名。
只有导航 Java 用到的名字保留 F5：`/tmp/mu1320-f5-*`（为统一，脚本自用的 renderer.log/pid、dm-* 临时文件也留在这个前缀下）、`render/f5_sc.sh` / `f5_dm.sh`，以及导航日志里的 `MU1320-F5-VCHUD-V5`。
测试沿用 F5 套件，对期望标签做 F5_→F6_ 翻译，另有一项检查 status/arm/collect/rollback 输出里不再出现 F5 标签。
新增：`status` 的 `TOUCHPAD_OFF_SWITCH` / `TOUCHPAD_LOG`；`collect` 复制 `/tmp/mu1320-f6-touchpad.log` 并输出 `F6_TOUCH_COUNT[...]`
（逐格 `DPAD` 行只复制不打印）。`f5_dm.sh`、`f5_sc.sh` 除工作目录外与 v5 相同。与 v5 的完整差异见 `f6-v2-scripts.diff`。
`f6_mark.sh` v2 另记触摸板日志最后一行和开关（与 v1 的差别只在这两处）。

## 离线验证

| 项目 | 结果 |
| --- | --- |
| Java 1.4 编译 + 链接审计 | PASS（84 类，1999 引用，缺失 0） |
| F1 v2 等价 harness（电话/语音/资源/按键在新 lifecycle 上） | 899,757 项通过 |
| 触摸板 harness（手势 + 真实 lifecycle 的 touch/key/rotary） | 8,680 项通过 |
| F5 harness（导航状态/BAP/renderer，v2 类） | 1,502,905 项 0 失败 |
| 主机测试 `test_f6_v2_trial`（F5 v5 事务套件在 v2 包上全部重跑 + T 场次无 arm 的 snapshot + 包内容）、`test_f6_v2_mark`（sh + ksh） | 60 项 OK（`f6-v2-host-tests.txt`） |

codex 草稿中 F5 harness 的 `listen on 19800` 失败是其运行环境不允许本地监听，本机重跑通过。

## 未验证 / 上车要看的

- J9 上的加载与触摸板事件是否按预期到达、坐标方向与采样率、手感（阈值为上游 MU1316 的调参）。
- `startService` 在本车每次连接都被调用（`SESSION g=` 行数应等于连接次数）；若不是，手势仍会在抬手时重置，只影响重连瞬间。
- 原厂触摸板在 CarPlay 里的行为（手写等）在开启桥接后被方向键取代；T9 用开关对比记录。
- 结果回传 `resource/private/vehicle-dump/f6-accept-v2/`。
