# F4 Renderer 独立试验实车审阅（v1，run4）

日期：2026-09-25。结果：`F4_RENDERER_LAYER_AND_ROLLBACK_VERIFIED`（附几何限制）。
证据：`resource/private/vehicle-dump/f4-render-v1-run4/`（status、collect before/after/restored、run、13 张照片的观察表）。
审计：`scripts/audit_f4_vehicle.py` → `reports/f4-render-vehicle-v1.json`，21/21 判定通过。
离线审阅与前三次上车经过：[F4-RENDER-REVIEW.md](F4-RENDER-REVIEW.md) 第 8–10 节。

## 1. 结论

| roadmap F4 验收项 | 结果 | 证据 |
| --- | --- | --- |
| 图层成功注册 | **通过** | `gd` 出现 98（Software 328×181）；sloginfo `DisplayManager: new window available 98` ×2 / `window closed: 98` ×2；EGL 1.4、Adreno 320 |
| 图形位置、尺寸、方向与裁剪，以本车测量为准 | **已测量**；位置需 F5 设置 | 方向与颜色正确（grid 白色中心格与 cyan 角格对得上，无翻转、无 R/B 交换，alpha 0.6 透出地图）；尺寸 328×181 未缩放；位置为仪表原点 (0,0) = VC 左上角，被 VC 上边缘和左上圆角遮罩裁掉 |
| 空闲透明、原厂地图正常 | **通过** | 照片 2（闲置）、9（断链）与基线相同，无黑块、无闪烁 |
| renderer 退出后恢复；独立回滚 | **通过** | 正常退出（rc 0）与 SIGKILL（rc 137）后 98 均从 `gd` 消失、VC 干净；在 80 上重启 renderer 可重新注册并显示；切回 74 与照片 1 相同；重启后 `F4_RESTORED_BASELINE: PASS`（无 98、无 context 80，gc 86/86） |

同时回答了离线审阅的两个未知项：

1. **98 能到达 VC**：只用 `dmdt sc 4 80`，没有 Java 的 `setUpdateRate`，也没有经 72 弹跳。
2. **原厂 HMI 在 7 分钟 run 中没有把仪表切走**（`STOCK_CONTEXT_REVERSIONS: 0`，停车、无原厂路线）。试验结束后用户操作原厂视图，
   仪表正常切到 72 `[33]`，说明原厂切换未受影响。

## 2. 几何测量（照片 3，grid 8×6，行从下往上）

| 行 | 可见格 |
| --- | --- |
| 6 | 无（在 VC 上边缘之外） |
| 5 | 6–8（5 仅一条） |
| 4 | 4/5–8 |
| 3 | 3–8 |
| 2 | 2–8 |
| 1 | 1（部分）–8 |

下边缘和右边缘完整、平直；左上方被圆角遮罩斜向裁掉。结果：右转（照片 4、11）完整可读；左转箭头头部、环岛的环、
掉头的弧、到达标记都落在被裁区域，车上看起来像"直行"或两条平行线（照片 5–8）。进度条等级 8/16 正确。

## 3. 对 F5 的输入

- 98 的位置/裁剪必须由 HMI 通过 DSI `setPosition(IIII)` / `setCropping(10×I)` 设置（MU1320 `DisplayManager` 字节码中都有，
  上游由 `ClusterLayerController` 调用）。dmdt 没有对应命令，所以 F5 必然包含 Java 部分。
- 目标位置以原厂 KDK 框为参照：原厂 74 的 20 为 328×181，101/102 为 210×153 底板。F5 首测建议先用 grid 找到合适的
  坐标，再复测左转、环岛、掉头、到达。
- dmdt 使用 displaymanager 内部显示号：主屏 0，仪表 4（`getInternalDisplayID`）。**不要用 `dmdt ts`**（run2 使 MMI 重启）。
- dmdt 重定向输出需要 `f4_unbuf.so`（`_Exit` 不刷新 stdio）。

## 4. 限制

- F4 不驱动 HUD；试验后原厂导航箭头只是"认为正常"，没有在有原厂路线时专门验证。
- 只测了停车状态和地图全屏视图；其他 VC 视图下的位置未测。
- 所用 renderer 为上游原样，未针对本车做任何几何修改。
