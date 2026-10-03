# F6 v3（车道、到达距离条、触摸板灵敏度）：离线审阅（2026-09-27）

结论：**SD 文件夹 `mu1320-f6-accept-v3/` 可以上车，尚未上车。** 只需一次行驶复测（场次 D）。车上当前为基线（v2 已回滚）。

## 范围

修正 F6 v2 实车（[ANALYSIS-BC](../../resource/private/vehicle-dump/f6-accept-v2/ANALYSIS-BC.txt)）发现的问题：

| 项 | 修改 | 层 |
| --- | --- | --- |
| B8 车道只在第一个车道路口显示 | hook 不再按机动编号删车道缓存；Java 按车道编号记住本路线车道 | native + Java |
| B9 Apple 到达前距离条不走 | 到达机动无到转向距离时用到目的地距离 | Java |
| B7 触摸板略灵敏 | 阈值 ×1.25（快/慢 188/250，死区 38） | Java |

## native：navhook v1.3（`scripts/build_navhook_v13.py`）

- 先在同一 Docker 镜像里把 navhook v1.2 源码树**逐位复现**（`ad87795a…5e1d`，与 F5 v5/F6 v2 车上的 hook 相同），再只改
  `rgd_prune_stale_lane_cache()` 为不删除任何条目（补丁 `patches/0004-navhook-lane-cache-no-maneuver-prune.patch`，一个 hunk）。
- 产物 `0e2e82ea…5c95`（240342 字节）。build_hook.sh 的 ABI 检查通过（emutls 0、.init_array 仅编译器、无 eager 构造）。
  符号尺寸只有 `write_bus_snapshot_from_cache` 变化（内联的清理逻辑去掉，−48 字节），其余为编译器内部编号。
- 车道条目改为存活到路线重置（`rgd_maneuver_map_reset`，不变）；缓存 32 个满时淘汰最久未用且非当前的条目（不变）。
  上游代码注释本身写明 iOS 会提前批量发送整条路线的 0x5204，按机动编号删除与此矛盾。
- 快照每帧本来就为 32 个车道槽都写键（有数据或清除标记），缓冲上限 64 KB，保留车道不会溢出。
- 主机测试 `tests/test_navhook_v13.py`：真实 `rgd_hook.c` + 总线桩，按 v2 Apple 实车顺序喂数据。
  v1.2 丢失第 4、7 组车道（与实车一致），v1.3 全部保留；路线重置仍清空；满缓存仍按 LRU 淘汰并保护当前条目。

## Java（`scripts/build_f6_v3.py`，JAR `60fa6835…50fb`，85 类）

以 F6 v2 JAR 为基线，只重编 7 个类，其余逐字节相同；javap 方法级核对：

- `TripPlanner`：`lanes(core)` 变为委托；新增 `lanes(core, memory)`、`build`、`LaneMemory`（容量 64，路线结束/非活动/进入重算/
  换应用/hook 清空时清除）；`Lanes.describe` 用 `slot=mem` 标出来自记忆的车道。
- `F5BapOutput`：每个输入先 `laneMemory.observe`，`onClear` 清除，`start/update` 用带记忆的 lanes。
- `BapPlanner.plan`：B9 回退；新增 `isArrival`（与 RouteStateCore 相同的到达类型）。
- `TouchpadGesture` 阈值；`TouchpadBridge`/`CarPlayApp` BUILD_ID；`StockDisplay` helper 路径（`mu1320-rgi-f6-v3`）。

## 离线验证

| 项目 | 结果 |
| --- | --- |
| F1 v2 lifecycle 等价 | 899,757 项通过 |
| 触摸板 harness（新阈值） | 7,633 项通过 |
| F5 harness | 通过；F2 采集中与 F3 决策唯一的差别是 B9 新增的 14 行递减 DIST_TURN（82→28 m），由修改后的检查明确要求 |
| 实车采集回放 F6V3Replay（F5 v5 ×2、F6 v1、F6 v2 B/C） | 除车道/到转向距离/机动状态/renderer 行外与车上逐行一致；Google 车道路口 5/5（4 个来自记忆）；Apple 6/7，第 7 组在 v2 采集里已被 v1.2 hook 删掉，由 hook v1.3 修复；Apple 到达 91→28 m 递减 |
| 主机测试（F6 v2 事务套件以 v3 重跑 + 包内容 + hook v1.3 + 打点） | 64 项 OK |

## 附带

- `scripts/f6_matrix.py` 增加“车道路口 发出/总数（无车道数据）”和 `PARTIAL` 状态：v2 B/C 为 Apple 1/7、Google 1/5。
  F5 v2 的 Google 采集也是 1/8，其中 7 段 iOS **没有给 lane_guidance_index**，与 B8 的删除不同，hook v1.3 也补不了，记为待观察。
- 被测的 F5 导航日志里版本号仍为 `MU1320-F5-VCHUD-V5`（写在导航 Java 里）。

## 未验证 / 上车要看的

- hook v1.3 在车上加载、一次性 token 与被动模式（与 v1.2 相同的机制，代码未改）。
- 第 2 个及以后车道路口 HUD 显示车道（Apple 含中途补发的车道）；Apple 到达前距离条递减；触摸板 8 折手感。
- 结果回传 `resource/private/vehicle-dump/f6-accept-v3/`。
