# v0.9.0-rc.1 — release candidate / 候选版本说明

## English

First public release, marked as a **pre-release**. It becomes v1.0.0 once sessions N and X pass. Two deliverables:

1. **Toolbox v1** — green-menu page `Customization > MU1320 RGI` (5 buttons: Status, Install,
   Uninstall, Collect, Emergency Stop). Fully reproducible and verified byte-for-byte:
   `python3 tools/assemble_toolbox_v1.py --output build/mu1320-toolbox-v1`
   (158 files match `toolbox-v1.SHA256SUMS`). Ships as a Release asset `mu1320-toolbox-v1.zip`.
2. **F8 candidate** (`mu1320-f7-daily-v2.1`) — the scripts, helpers and monitor; the runtime
   binaries are built by you (see `docs/en/building.md`). `f8-SHA256SUMS` are the checksums of
   the package that ran in the car; `tools/assemble_f8.py` refuses to assemble anything that differs.

Status: F8 sessions L (partly), I and M passed in the car on 2026-10-03; the multi-day
soak (>= 10 cold boots, session N) and final uninstall/reinstall (session X) are **still open**.
See `docs/en/status.md`. `f8-SHA256SUMS` differs from the original package in one line:
`README.md` (documentation only; the original checksum was stale).

## 中文

首个公开版本，标记为**预发布**；场次 N、X 通过后转正为 v1.0.0。两个交付物：

1. **Toolbox v1**：绿色菜单页 `Customization > MU1320 RGI`（Status / Install / Uninstall / Collect / Emergency Stop）。
   可完整复现并逐字节校验：`python3 tools/assemble_toolbox_v1.py --output build/mu1320-toolbox-v1`。
2. **F8 候选包** `mu1320-f7-daily-v2.1`：脚本、辅助程序和监测脚本在仓库内；运行时二进制由使用者自己构建（见 `docs/zh-CN/building.md`）。

状态：F8 的场次 I、M 已于 2026-10-03 通过，场次 L 部分完成；多日稳定性（≥10 次冷启动）和最终卸载重装**尚未完成**。
