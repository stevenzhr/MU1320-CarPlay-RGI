# F3 BAP v2 实车审计（2026-09-25）

原始数据：`resource/private/vehicle-dump/f3-bap-v2/`。审计脚本：`scripts/audit_f3_vehicle.py`（从原始文件重算，
不复制道路名/目的地）。结果：`reports/f3-bap-vehicle-v2.json`，状态 **`F3_BAP_OUTPUT_AND_ROLLBACK_VERIFIED`**，24/24。

## 结论

**F3 通过（附限制）。** CarPlay 路线第一次经原厂 BAP 显示在 VC 和 HUD 上：箭头、到转向距离（英制，
HUD 显示 100 ft）、接近路口的进度条都正常；结束路线约 1 s 清除，拔线约 2 s 清除；让位模式下原车引导
没有被清掉；回滚后恢复基线。

## 逐帧核对

- `F3Replay`：state 回放 370/370 一致；新增的 **gated 回放**（按车上日志里的 `GATE`/`STOCK` 行顺序重放
  应急开关和原车状态）使整个会话的 BAP 日志 440/440 行逐行一致，0 差异。车上每一次 BAP 调用都由同一份
  字节码可复现。
- 调用计数：RG_STATUS 10、RG_TYPE 10、DESCRIPTOR 16、EXIT_VIEW 16、DIST_TURN 182、MANEUVER_STATE 17、
  DIST_DEST 175；0 FAULT、0 REJECT；`BIND ok … AppConnectorNavi`；sloginfo 无 Java 链接错误。

## 各步骤

| 步骤 | 日志 | 观察 |
| --- | --- | --- |
| 1 开始路线 | i=5 START（FOLLOW_STREET，START_ROUTE 30 m） | VC/HUD 箭头 + 100 ft |
| 2 结束 | i=23 TEARDOWN ROUTE_END | ~1 s 消失，VC 恢复 |
| 3 新路线 | i=25 START，无旧距离 | 同为去往起点的 100 ft |
| 4 驾驶 | 右转（13/192）→左转（13/64）→右转→右转；4 段进度条 220→1、223→2、102→7、91→30 m，bar 97→0 等，1 Hz 递减 | 箭头正确、距离递减、有进度条 |
| 5 应急开关 | GATE kill=1 → 同毫秒 TEARDOWN；kill=0 后 49 s 下一帧才 START | ~1 s 消失；约 3 分钟后移车才回来 |
| 6 行驶中开原车路线 | i=333 CarPlay ROUTE_END → TEARDOWN，**1.19 s 后** `rg_active=1` | CarPlay 被中断，原车箭头正常保留 |
| 7 原车优先 | i=335 `HOLD_OFF reason=STOCK_ROUTE`；原车结束后 i=351 START（50 s 后下一帧） | 显示原车；结束原车后 CarPlay 箭头未及时出现 |
| 9 路线进行中拔线 | i=370 TEARDOWN LINK_LOST | ~2 s 消失（补上 F2 的缺口） |

让位硬性检查：原车 `rg_active` 非 0 期间 **0 次 BAP 调用**。`STOCK rg_active=0 persistent_route=1`
在车上出现，直接证实 v1 的根因。AirPlay `turns` 在步骤 6 由 controller 变 accessory，与观察一致。

回滚：install/arm/rollback/所有 collect 均 CONTROL_EXIT=0；NavActiveIgnore 移回且 cksum 为基线；F3 JAR 与隔离件
不存在；重启后新 DIO 无 marker/preload，receipt 0。

## 发现（进入后续版本）

1. **门控解除后不立即恢复**：应急开关关闭、原车路线结束后，要等 iOS 下一帧（停车时约 50 s）才重新 START。
   应在看门狗解除门控时用已有路线状态立即开始。
2. **瞬时回跳**：i=261 hook 快照中的机动列表回到上一版 `[2,3]` 且距离 0，仅 73 ms 后恢复 `[4]`；F3 如实发出
   FOLLOW_STREET 再发右转。可加约 300 ms 去抖（主要机动回退到旧版本时）。
3. **VC 不显示到目的地距离**：FctID 21 已发送（175 次）但 VC 未显示；可能需要 ETA（22）或特定视图，与 ETA 一起研究。
4. 步骤 6 中 F3 的清除比原车开始引导早约 1.2 s，本次无可见问题；若顺序反过来则静默释放，两种情况都已覆盖。
5. 未测：到达符号、车道、ETA、环岛/出口、改道、Google Maps/Waze；终端输出未随文件归档（footer 仅由 action log 的
   CONTROL_EXIT 佐证）。
