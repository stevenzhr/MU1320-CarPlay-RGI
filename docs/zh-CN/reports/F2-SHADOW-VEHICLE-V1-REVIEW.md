# F2 影子试验实车审计（v1）

日期：2026-09-25。原始数据：`resource/private/vehicle-dump/f2-shadow-v1/`。
审计脚本：`scripts/audit_f2_vehicle.py`，从原始文件重新计算 22 项判定，不复制道路名或目的地。
结果：`reports/f2-shadow-vehicle-v1.json`，状态 `F2_SHADOW_STATE_AND_ROLLBACK_VERIFIED`，
22/22 通过。

## 结论

**F2 通过，附限制。** 实车数据在工作站回放，182 个输入逐行一致（0 差异）；三次路线结束都
完整清除；新路线不带旧距离；行驶中距离递减、转向推进和到达都正确。回滚后已恢复基线，
并做过完整重启。

## 实车时间线（Java 启动后秒数；hook 与 Java 时钟对齐误差 < 0.1 s）

| t (s) | 事件 | 说明 |
| --- | --- | --- |
| 164 | SESSION，2 个 DISCONNECT 帧 | hook 连接，发 `new_identify`/`init` 清除帧；DIO 4948105 消费 token，并且是 bus owner |
| 259.5 | ACTIVATE | 路线 1（Apple Maps）：`dd=-1`，随后首个距离 6027 m |
| 401.5 | ROUTE_END+DEACTIVATE | App 内结束路线；hook 扣住 0 帧约 1.5 s 后才发给 Java；`act=0 dm=-1 dd=-1` |
| 415.4 | ACTIVATE | 路线 2：`dd=-1`，随后为新距离 31997 m（不是 6027） |
| 499.6 | ROUTE_END+DEACTIVATE | 清除 |
| 594.4 | ACTIVATE | 路线 3（近距离，行驶）：首个距离 639 m |
| 594–721 | PRIMARY ×5 | 首转向槽位/版本 0/2→1/3→3/5→4/6→5/7；到转向距离递减 89 步 |
| 721.8 | ARRIVED | `route_state=2`，符号 `MANEUVER:3/0`（ARRIVED） |
| 742.9 | ROUTE_END+DEACTIVATE | 到达后 iOS 结束路线，清除 |
| 746.1 | LINK_LOST | USB 意外拔出：活动 DIO 直接退出，**hook 没有发 disconnect 帧**，只能靠 socket 断开发现 |

重新插回后，替代 DIO 8654985 按设计为 PASSIVE（一次性 token 已消耗），F2 之后没有新输入。
`collect armed`/`snapshot` 两份 F2 文件逐字节相同。

## 判定明细

- 事务：install/arm/rollback 均 `FILES_PASSED`；7 组终端 footer 都是 `OUTER_EXIT: 0` 和
  `SD_MOUNT_RESTORED`；全局 receipt 中只有 bus owner 为 ACTIVE。
- F2 状态：182 行，0 个 REJECT，3 次激活，3 次结束清除，1 次到达，1 次 LINK_LOST（`act=0`）。
- 符号统计：MANEUVER 136（TURN 直行 32、TURN 右 86、ARRIVED 18）、HOLD 36、INACTIVE 10。
  HOLD 全部出现在激活后 1 s 内（列表到达前），行驶中没有 HOLD。
- 隐私：capture 中所有自由文本都已换成编号；`source_name` 为 "Apple Maps"。
- **车道首次在实车经 Java 校验**：hook 收到 0x5204（多组 2–7 条车道）；10 个 lg 槽位带数据，
  出现一次 `lane_guidance_showing=1`，全部通过校验。
- 回滚：双 SI 为 BASELINE，F2 JAR 不存在，NavActiveIgnore 哈希未变；新 DIO 2351241 无 marker、
  preload、hook 映射；开机计时 00:01:30，SI PID 938069→925778。

## 对 F3 的影响

1. **断线信号**：本车拔 USB 时 DIO 直接退出，不走 `rgd_clear_state("disconnect")`。上游只依赖
   `disconnect_reason` 和模块 stop，会让 BAP 残留旧状态；F3 必须保留 LINK_LOST 清除。
2. **START_ROUTE**（前往路线起点）映射为 TURN+直行，起步时 32 个样本显示这个符号，与
   BAPBridge 注释（FOLLOW_STREET）不符。F3 需要决定 HUD 显示哪一个。
3. **车道选择**：本次首转向都没有关联车道槽位（`linked_lane_guidance_*`），当前投影的
   `lanes` 一直是 -1。iOS 用顶层 `lane_guidance_showing/slot` 表示当前车道；F3 需要移植上游
   的车道选择逻辑再验证。
4. 起步 HOLD 约 0.1–0.3 s：此时 BAP 还没发过符号，影响很小。

## 实车未覆盖（离线或 E2E 已覆盖，或留给后续阶段）

- 路线进行中断线：这次 LINK_LOST 发生在路线结束 3 s 后，当时状态已为空。活动状态下的断链
  清除由主机 E2E 覆盖；F3 上车时可顺带验证。
- Google Maps：USB 意外重插后 DIO 为被动，没有采集到。多应用矩阵留给 F6。
- 重连后重放重建（一次性 token 限制），改道（state 5），`source_supports_rg=0`：仅离线覆盖。
