# F2 导航状态处理：审阅、离线验证与影子试验包（v1）

日期：2026-09-25。状态：**离线验证通过，影子试验包待实车**。F2 尚未整体通过：实车样本回放与
车上清除/重建证据要等本包上车后补齐。

## 1. 审阅结论：上游 RouteGuidance 的状态处理

对照已实车运行的 native hook 源码（`private/stage1-build/src/hook/routeguidance/rgd_hook.c`，与上游
一致）核对 Java 的输入语义：

| 事实（hook 源码） | 位置 |
| --- | --- |
| 每个 `EVT_RGD_UPDATE` 都是 hook 缓存的**完整快照**；0x5201/0x5202/0x5204 都走同一写出函数 | `write_bus_snapshot_from_cache`，`write_bus_*_partial` |
| 只写 `maneuver_list` 中且有 type 的槽位；32 个 lane 槽位每帧都写（数据或 `-1`/空清除值） | 同上，`write_lane_clear_keys` |
| 路线真正结束（state>0→0，非改道）时重置更新缓存和槽位映射，`ver_counter` 归零 | `rgd_message_handler`，`rgd_maneuver_map_reset` |
| 该 0 先被扣住，800 ms 后由 tick 发极简帧 `route_state=0, maneuver_count=0` | `rgd_periodic_tick` |
| 断线、新 Identify 时发 `route_state=0, maneuver_count=0, disconnect_reason` | `rgd_clear_state` |
| 进程被杀、socket 断开时不发任何帧 | — |

上游 Java 按"增量"处理（缺失字段保留旧值），与上述快照语义不符，产生以下问题：

1. **结束后残留旧距离/目的地**：取消路线后 hook 已清空缓存，但 Java 仍保留 `dist_dest_m`、ETA、
   目的地；新路线在 iOS 重发这些字段前会带着上一条路线的数值。
2. **槽位复用时混入旧字段**：hook 重置后槽位版本从头计数，新转向可能与旧转向同槽、同 `ver`，
   Java 不会清槽，新转向缺失的字段（路口角度、车道、出口文字）沿用旧值。
3. **断链无处理**：`RouteGuidance` 只在 `disconnect_reason` 或模块 stop 时清除；DIO 被杀或 socket
   断开时保持激活和旧状态，直到会话层 teardown。
4. `source_supports_rg=0` 只清路线和槽位，保留距离/ETA/目的地。
5. `BAPBridge` 注释称 START_ROUTE 映射为 FOLLOW_STREET，现行 `ManeuverMapper` 实际映射为 TURN。
   留给 F3 核对。
6. 活动路线中没有 `maneuver_list`、或首个转向类型无效时，上游不发送任何描述符，BAP 保持上一个
   符号（本包记为 `HOLD`）。改道期间可能短暂显示旧箭头；实车频率由本包记录，F3 再决定是否改为
   明确的 NO_SYMBOL/FOLLOW。

问题 1 和 2 用"上游增量语义模型"复现（`LEGACY_DIFF`，是模型而不是上游类本身）。

## 2. F2 实现（`f2-src/`）

- `RouteStateCore`：纯状态机，无 BAP/renderer/显示/所有权/I/O 依赖。
  - **快照语义**：每个通过校验的帧完整替换状态；缺失即清除，未列出的槽位为空。
  - 校验复用实车通过的 `RgdIngressProbe.validate`；拒绝的帧不改变状态。
  - 清除边沿：`disconnect_reason`、`source_supports_rg=0`（只保留来源名称）、`LINK_LOST`、
    `SESSION`（新 HELLO）、stop。事件还包括 `ROUTE_END`（state>0→0）、`ARRIVED`、`REPLAY`。
  - 激活规则逐条沿用上游（含 `visible_in_app=0` 不结束路线，上游 #8）。
  - 输出投影沿用 `BAPBridge.update` 的决策：INACTIVE/NO_SYMBOL/FOLLOW/MANEUVER/HOLD、接近区滞回
    （城市 1500 m / 高速 3000 m，步长 >2 km 为高速）、距离 HOLD、`ManeuverMapper.map`
    （上游源码未修改，commit `f36790d4`）以及关联车道数。
- `F2ShadowProbe`：订阅 RGD 和 HELLO，每秒轮询 `CarplayBus.isConnected()` 判断断链。
  每个输入写一行决定到 `/tmp/mu1320-f2-state.log`；净化后的帧差分写到
  `/tmp/mu1320-f2-frames.cap`，自由文本换成会话内编号。两者都有上限。
- `F2Replay`（仅主机）：由 capture 重建帧，用同一份字节码回放，与车上 state log 逐行比较。

## 3. 离线验证

`scripts/build_f2_shadow.py`：Java 1.4 编译，以原厂 bootclasspath，HotSpot `-Xverify:all`，
结果见 `f2-harness.txt`。

| 标签 | 检查数 | 内容 |
| --- | --- | --- |
| VEHICLE_SHAPED | 37 | 按 navjava-ingress 实车 14 帧的键数、状态和槽位摘要重建；字段值为合成（车上只存了摘要） |
| SYNTH | 41 | 增量推进、槽位复用、缺失字段、取消、到达、断线、断链与重放重建、改道、support=0、visible=0、车道、10 类畸形帧 |
| LEGACY_DIFF | 2 | 上游增量模型复现问题 1、2 |
| PROPERTY | 197,989 | 两个种子各 20,000 步随机 hook 序列：状态只取决于最后一帧、保留槽位必在列表中、清除边沿无输出/距离/目的地、激活等于门控规则、MANEUVER 只来自有效首转向、拒绝帧不改状态 |
| E2E_BUS | 13 | 真实 `CarplayBus` 服务端与 `F2ShadowProbe` 走 TCP：HELLO、帧、断 socket（`LINK_LOST`）、重连重放（`REPLAY` 后状态与断前一致）、断线；磁盘无私密文字；主机回放 0 差异 |

合计 198,082 项，0 失败。

- JAR：27 类、46,947 字节，SHA `0fe890e8…65aa`。其中与实车运行过的 navjava JAR 共有的 18 类
  **逐字节相同**（bus、Log、TerminalModeBapCombi、RgdIngressProbe）；新增 9 类。
- 链接审计：665 个引用全部解析，与 `NavActiveIgnore.jar` 无类重叠，class major 48
  （`f2-shadow-audit.json`）。
- 主机事务测试 22 项（navjava 9 项复用 + F2 13 项），全项目 152 项全部通过。

## 4. 影子试验包 `mu1320-f2-shadow-v1/`

直接复制到 SD 卡根目录，不再制作 ZIP。操作见包内 `README.md`。

- hook、loader_check、mount_state、trial_gate、ARM-TOKEN、私有 `dio_manager.json` 与
  navjava-ingress 包逐字节相同。SI 改动只有运行目录和 marker 不同。
- 三个脚本由 navjava 模板经显式替换表生成，差异见 `f2-shadow-scripts.diff`。collector 新增
  F2 文件复制、事件计数和非 UPDATE 行输出，capture 只复制不打印。

## 5. 上车后的判定标准

1. install/arm/collect/rollback 与 navjava 相同：token 被同一稳定 DIO 消费，hook 有 0x52xx，
   回滚后恢复基线。
2. state log 中 `ev=REJECT` 为 0，至少一次 `ACTIVATE`。
3. App 内结束路线时出现 `ROUTE_END+DEACTIVATE`，且该行 `act=0 dm=-1 dd=-1`。新路线在出现新的
   距离前 `dd=-1`（不残留）。
4. 拔 USB 后出现 `DISCONNECT` 或 `LINK_LOST`，且 `act=0`。
5. 工作站 `F2Replay` 回放整份 capture，0 差异。回放后 capture 成为 F2 的实车样本回放用例。

仍需 F6 验收：车道（本车尚无 0x5204 样本）、行驶中改道、多应用矩阵。F3 负责 BAP 实际输出。
