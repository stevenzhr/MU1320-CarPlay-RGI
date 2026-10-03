# F3 BAP v1 实车结果（2026-09-25）

原始数据：`resource/private/vehicle-dump/f3-bap-v1/`。结论：**未通过，但原因已定位，且未向 BAP 写入任何内容**。

## 现象

完整重启后 arm 成功，一次 USB 连接，Apple Maps 开始路线（>2 km）并等待 60 秒，VC/HUD 均无箭头或距离。
第 2–7 步跳过；collect armed → 路线进行中拔 USB → collect snapshot → rollback → 完整重启 → collect restored。

## 证据

- 管线正常：DIO 4489284 消费 token（receipt ACTIVE_TOKEN_CONSUMED，全局 1 个）；Java `LISTENER_READY`；
  state log 43 输入、0 REJECT，F2Replay 回放 43/43 一致；两次 ACTIVATE（i=5、i=26），首转向为
  START_ROUTE（到起点 28 m），i=24 路线结束、i=43 LINK_LOST。
- 服务绑定成功：`BIND ok service=de.audi.app.combi.bap.app.navi.AppConnectorNavi refs=1`。
- **两次激活均为 `HOLD_OFF reason=STOCK_ROUTE`，全程没有 START、没有任何 CALL**。原车当时无路线（观察表）。
- AirPlay `Modes changed` 显示 `turns controller`（CarPlay 持有导航，F1 v2 类族生效）。
- 回滚：NavActiveIgnore 回到原位且 cksum 为基线值，F3 JAR 与隔离件不存在；重启后新 DIO 1781884
  无 marker/preload。

## 根因

`RouteManager.getRoute()` 只返回字段 `route`，其唯一写入者是 `updateRmPersistentRoute`——原车的
**持久化路线**（用于恢复引导），没有引导时也不为空。上游在 MU1316 上用它判断"原车无路线"，在本车
不成立。审阅第 6 节风险 3 即此情况（安全失败：不输出）。

## 修正（v2）

改用导航核心 DSI `rgActive`：`Navigation.getInstance().getDsiResponseContainer().isRgActive()`。
全部导航代码中 `DSIResponseContainer.setRgActive` 只有一个写入者
`AbstractDSINavigationHandler.updateRgActive`（DSI 回调），原厂停止引导命令、`ClusterService.refreshRGIValid`、
`RouteGuidanceInterAppService.getRgActiveStatus` 等都读它。v2 在 BAP log 中每次变化记录
`STOCK rg_active=… persistent_route=…`，可在车上同时验证两个信号。

用本次实车 capture 按"原车空闲"回放 v2：i=5、i=26 各 START 一次（FOLLOW_STREET，到起点 28 m，
目的地 6027 m），i=24 路线结束 TEARDOWN，i=43 拔线 TEARDOWN。

## 仍未验证

VC/HUD 是否接受 F3 的 BAP 输出（v1 没有发出任何调用，这一问题完全未测）。
