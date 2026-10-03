# F6 support matrix (logs only)

由 `scripts/f6_matrix.py` 生成。只反映日志：应用是否提供、F5 是否发给 BAP/renderer。VC/HUD 是否**显示**要看观察表和照片，这里不能判定。

状态：SENT = 应用提供且已发出；APP_NOT_PROVIDED = 路线够长但应用没提供；NOT_EXERCISED = 没遇到该情况；NOT_SENT = 应用提供了但没发出（缺陷）；SEEN/SHOWN = 出现过/地图框接管过；NOT_SEEN = 路线够长但没观察到。

## 来源

| 采集 | build | 输入 | 路线 | FAULT | REJECT | capture 截断 | 打点 |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: |
| f6-accept-v1/snapshot-16707722 | MU1320-F5-VCHUD-V5 | 694 | 11 | 0 | 0 | 否 | 14 |

## 按应用

| 项目 | Apple Maps | Google Maps |
| --- | --- | --- |
| 路线数 / 秒 | 8 / 680 | 3 / 360 |
| 到转向距离 | SENT | APP_NOT_PROVIDED |
| 距离递减 | SENT | NOT_SEEN |
| 到目的地距离 | SENT | SENT |
| ETA/剩余时间 | SENT | SENT |
| 车道 | NOT_EXERCISED | NOT_SENT |
| 重算 | NOT_EXERCISED | SEEN |
| 到达 | NOT_EXERCISED | NOT_EXERCISED |
| 地图框箭头 | SHOWN | SHOWN |
| 机动类别 | - | - |
| 距离单位 | ft, m, mi | ft, mi |
| 应用切换进入 | 1 | 2 |
| 重算时清除 | 0 | 0 |
| 地图框异常 TAKE_FAILED/FIGHT_STOP/UNSTICK_73 | 0 | 0 |

## 每条路线

| 采集 | 应用 | i | 秒 | 结束 | 状态 | 重算 | 到达后秒 | 机动 | ETA 来源 | TAKE/RELEASE | 打点 |
| --- | --- | --- | ---: | --- | --- | ---: | ---: | --- | --- | --- | --- |
| snapshot-16707722 | Apple Maps | 5–19 | 17 | ROUTE_END | LOADING:11,PROCEED_TO_ROUTE:4 | 0 | - | - | eta:2,none:2 | 2/1 | - |
| snapshot-16707722 | Apple Maps | 22–38 | 32 | ROUTE_END | LOADING:14,PROCEED_TO_ROUTE:3 | 0 | - | - | eta:1,none:2 | 2/1 | A4 |
| snapshot-16707722 | Apple Maps | 41–56 | 62 | ROUTE_END | LOADING:11,PROCEED_TO_ROUTE:5 | 0 | - | - | eta:3,none:2 | 2/1 | A45 |
| snapshot-16707722 | Apple Maps | 59–74 | 64 | ROUTE_END | LOADING:11,PROCEED_TO_ROUTE:5 | 0 | - | - | eta:3,none:2 | 2/1 | A45 |
| snapshot-16707722 | Apple Maps | 77–109 | 422 | APP_SWITCH | LOADING:11,PROCEED_TO_ROUTE:22 | 0 | - | - | eta:12,none:1 | 7/0 | A6,A7,A8,A9,A10,A11 |
| snapshot-16707722 | Google Maps (从 Apple Maps 切换) | 110–296 | 126 | ROUTE_END | ROUTE_SET:152,LOADING:34,REROUTING:1 | 1 | - | - | eta:130,none:4 | 0/1 | A12 |
| snapshot-16707722 | Apple Maps | 299–311 | 1 | APP_SWITCH | LOADING:11,PROCEED_TO_ROUTE:2 | 0 | - | - | eta:1,none:1 | 2/0 | - |
| snapshot-16707722 | Google Maps (从 Apple Maps 切换) | 312–449 | 97 | APP_SWITCH | ROUTE_SET:116,LOADING:22 | 0 | - | - | eta:100,none:2 | 0/0 | - |
| snapshot-16707722 | Apple Maps (从 Google Maps 切换) | 450–461 | 17 | ROUTE_END | LOADING:10,PROCEED_TO_ROUTE:2 | 0 | - | - | eta:1,none:2 | 0/1 | - |
| snapshot-16707722 | Google Maps | 464–678 | 136 | ROUTE_END | ROUTE_SET:167,LOADING:46,REROUTING:2 | 2 | - | - | eta:140,none:5 | 2/1 | A1213,A13 |
| snapshot-16707722 | Apple Maps | 681–693 | 66 | LINK_LOST | LOADING:8,PROCEED_TO_ROUTE:5 | 0 | - | - | eta:3,none:2 | 2/1 | A15,A16 |
