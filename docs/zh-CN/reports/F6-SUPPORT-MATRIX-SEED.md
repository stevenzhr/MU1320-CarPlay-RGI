# F6 support matrix (logs only)

由 `scripts/f6_matrix.py` 生成。只反映日志：应用是否提供、F5 是否发给 BAP/renderer。VC/HUD 是否**显示**要看观察表和照片，这里不能判定。

状态：SENT = 应用提供且已发出；APP_NOT_PROVIDED = 路线够长但应用没提供；NOT_EXERCISED = 没遇到该情况；NOT_SENT = 应用提供了但没发出（缺陷）；SEEN/SHOWN = 出现过/地图框接管过；NOT_SEEN = 路线够长但没观察到。

## 来源

| 采集 | build | 输入 | 路线 | FAULT | REJECT | capture 截断 | 打点 |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: |
| f5-vchud-v1/restored-10760330 | MU1320-F5-VCHUD-V1 | 93 | 3 | 0 | 0 | 否 | 0 |
| f5-vchud-v2/snapshot-18210953 | MU1320-F5-VCHUD-V2 | 1099 | 8 | 0 | 0 | 否 | 0 |
| f5-vchud-v3/armed-10346641 | MU1320-F5-VCHUD-V3 | 297 | 4 | 0 | 0 | 否 | 0 |
| f5-vchud-v4/armed-9781392 | MU1320-F5-VCHUD-V4 | 293 | 4 | 0 | 0 | 否 | 0 |
| f5-vchud-v5/armed-9138299 | MU1320-F5-VCHUD-V5 | 201 | 1 | 0 | 0 | 否 | 0 |

## 按应用

| 项目 | Apple Maps | Google Maps |
| --- | --- | --- |
| 路线数 / 秒 | 17 / 2357 | 3 / 345 |
| 到转向距离 | SENT | SENT |
| 距离递减 | SENT | SENT |
| 到目的地距离 | SENT | SENT |
| ETA/剩余时间 | SENT | SENT |
| 车道 | SENT | SENT |
| 重算 | SEEN | SEEN |
| 到达 | SEEN | NOT_EXERCISED |
| 地图框箭头 | SHOWN | SHOWN |
| 机动类别 | arrive, roundabout, turn | turn |
| 距离单位 | ft, m, mi | ft, mi |
| 应用切换进入 | 0 | 0 |
| 重算时清除 | 0 | 0 |
| 地图框异常 TAKE_FAILED/FIGHT_STOP/UNSTICK_73 | 6 | 1 |

## 每条路线

| 采集 | 应用 | i | 秒 | 结束 | 状态 | 重算 | 到达后秒 | 机动 | ETA 来源 | TAKE/RELEASE | 打点 |
| --- | --- | --- | ---: | --- | --- | ---: | ---: | --- | --- | --- | --- |
| restored-10760330 | Apple Maps | 5–21 | 114 | ROUTE_END | LOADING:11,PROCEED_TO_ROUTE:6 | 0 | - | - | eta:3,none:2 | 5/0 | - |
| restored-10760330 | Apple Maps | 24–46 | 267 | ROUTE_END | LOADING:14,PROCEED_TO_ROUTE:9 | 0 | - | - | eta:4,none:3 | 3/0 | - |
| restored-10760330 | Google Maps | 49–91 | 5 | ROUTE_END | ROUTE_SET:24,LOADING:19 | 0 | - | - | eta:8,none:3 | 0/0 | - |
| snapshot-18210953 | Apple Maps | 5–19 | 55 | ROUTE_END | LOADING:11,PROCEED_TO_ROUTE:4 | 0 | - | - | eta:2,none:2 | 5/0 | - |
| snapshot-18210953 | Apple Maps | 22–40 | 126 | ROUTE_END | LOADING:14,PROCEED_TO_ROUTE:5 | 0 | - | - | eta:2,none:3 | 6/3 | - |
| snapshot-18210953 | Apple Maps | 43–58 | 1 | ROUTE_END | LOADING:14,PROCEED_TO_ROUTE:2 | 0 | - | - | eta:1,none:2 | 2/1 | - |
| snapshot-18210953 | Apple Maps | 61–400 | 328 | ROUTE_END | ROUTE_SET:253,ARRIVED:5,LOADING:26,REROUTING:3,PROCEED_TO_ROUTE:53 | 2 | 19 | turn=LEFT/RIGHT; roundabout=ROUNDABOUT_EXIT_1; arrive=ARRIVE_RIGHT | eta:5,none:4 | 2/1 | - |
| snapshot-18210953 | Google Maps | 403–966 | 334 | ROUTE_END | ROUTE_SET:504,LOADING:53,REROUTING:7 | 7 | - | turn=LEFT/RIGHT | eta:337,none:10 | 6/0 | - |
| snapshot-18210953 | Google Maps | 969–998 | 5 | ROUTE_END | ROUTE_SET:17,LOADING:13 | 0 | - | - | eta:8,none:3 | 2/1 | - |
| snapshot-18210953 | Apple Maps | 1001–1080 | 82 | ROUTE_END | ROUTE_SET:53,ARRIVED:13,LOADING:8,PROCEED_TO_ROUTE:6 | 0 | 29 | turn=LEFT/RIGHT; arrive=ARRIVE_LEFT | eta:2,none:2 | 2/1 | - |
| snapshot-18210953 | Apple Maps | 1083–1098 | 98 | LINK_LOST | LOADING:11,PROCEED_TO_ROUTE:5 | 0 | - | - | eta:3,none:2 | 2/1 | - |
| armed-10346641 | Apple Maps | 5–18 | 10 | ROUTE_END | LOADING:11,PROCEED_TO_ROUTE:3 | 0 | - | - | eta:1,none:2 | 0/0 | - |
| armed-10346641 | Apple Maps | 21–36 | 1 | ROUTE_END | LOADING:14,PROCEED_TO_ROUTE:2 | 0 | - | - | eta:1,none:2 | 2/1 | - |
| armed-10346641 | Apple Maps | 39–57 | 136 | ROUTE_END | LOADING:14,PROCEED_TO_ROUTE:5 | 0 | - | - | eta:2,none:3 | 6/3 | - |
| armed-10346641 | Apple Maps | 60–297 | 269 | OPEN | ROUTE_SET:170,LOADING:16,REROUTING:1,PROCEED_TO_ROUTE:51 | 1 | - | turn=LEFT/RIGHT; roundabout=ROUNDABOUT_EXIT_1 | eta:4,none:2 | 3/0 | - |
| armed-9781392 | Apple Maps | 5–121 | 142 | ROUTE_END | ROUTE_SET:87,LOADING:17,REROUTING:6,PROCEED_TO_ROUTE:7 | 1 | - | turn=RIGHT | eta:6,none:3 | 7/1 | - |
| armed-9781392 | Apple Maps | 124–140 | 84 | ROUTE_END | LOADING:8,PROCEED_TO_ROUTE:9 | 0 | - | - | eta:2,none:2 | 8/0 | - |
| armed-9781392 | Apple Maps | 143–174 | 77 | ROUTE_END | LOADING:8,PROCEED_TO_ROUTE:24 | 0 | - | - | eta:2,none:2 | 9/1 | - |
| armed-9781392 | Apple Maps | 177–293 | 259 | OPEN | ROUTE_SET:73,ARRIVED:10,LOADING:8,PROCEED_TO_ROUTE:26 | 0 | 107 | turn=LEFT/RIGHT; arrive=ARRIVE_LEFT | eta:9,none:1 | 4/0 | - |
| armed-9138299 | Apple Maps | 5–200 | 307 | LINK_LOST | ROUTE_SET:138,ARRIVED:41,LOADING:8,PROCEED_TO_ROUTE:9 | 0 | 170 | turn=RIGHT; arrive=ARRIVE_LEFT | eta:6,none:2 | 17/1 | - |
