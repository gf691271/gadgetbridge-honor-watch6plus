# 未完成事项

按优先级排序。每条都写清「为什么值得做」和「怎么判断做完了」。

---

## ~~P0 — manifest 改成真正机器可读~~ ✅ 已完成（schema 4 → 5）

**现状问题**

```json
"unique_keys": ["HUAWEI_ACTIVITY_SAMPLE: (TIMESTAMP, OTHER_TIMESTAMP) — plain TIMESTAMP is NOT unique"]
```

这是**自然语言**，下游要写正则去解析。

`row_time_base` 是全局声明 `"epoch_s (UTC seconds)"`，但 `workout-base` 表用的是**毫秒**，
消费者会算错时间。

**要做成什么样**

```json
"unique_keys": [
  {"table": "HUAWEI_ACTIVITY_SAMPLE", "columns": ["TIMESTAMP", "OTHER_TIMESTAMP"]},
  {"table": "BATTERY_LEVEL", "columns": ["TIMESTAMP", "BATTERY_INDEX"]}
],
"files": [
  {
    "name": "activity-20261113-120000.csv",
    "timestamp_column": "TIMESTAMP",
    "time_base": "epoch_s",
    "sha256": "…",
    "bytes": 123456
  }
]
```

**完成标志**：manifest 里所有字段都能被程序直接用，无需解析自然语言；
每个文件都有 `sha256`。

---

## ~~P0 — 给下游项目提 issue，钉死文件契约~~ ✅ 已提 PR（mailuo #1）

契约文档在 `gf691271/mailuo` 的 `docs/integrations/gadgetbridge.md`（分支 `docs/gb-data-contract`），
已覆盖到 schema 5，附带真机导出的脱敏 manifest 样例。

下游程序 **不依赖 Gadgetbridge 代码**，只读导出目录。所以契约必须写死：

- 文件名模式：`<table>-<yyyyMMdd-HHmmss>.csv`、`manifest-<stamp>.json`
- `schema` 版本号（现在是 3），变了就 +1
- 每张表的时间列与单位
- 唯一键（用于去重）
- 缺失值：`-1` 和 NULL 都当 null
- 时区：时间戳都是 epoch，本地时区只在 manifest 注明

**完成标志**：下游侧实现一个 <100 行的读取器，能幂等导入，不 import 任何 GB 类。

---

## P1 — 逐拍数据每晚稳定归档

**现状**：2026-11-13 才第一次成功抓到完整的 105716 字节（11-13 夜）。

**要验证**：连续 3 晚，每晚 `files/dump/` 都出现新的 >60KB 文件，且解码出的日期是当晚。

**风险点**
- `trusleep` 被改回 true（会全空）
- 定时同步被「忙碌」跳过（旧版 NPE 的遗留；新版上游已修）
- 手表蓝牙栈卡死（需要重启手表）

**完成标志**：连续 3 晚自动归档成功，无需人工干预。

---

## P1 — 鼾声与手表数据的时间对齐

下游程序负责录音，GB 负责生理数据，两边在**手机本地**按时间戳对齐，不依赖云。

**要注意**
- 录音起始时间 vs 手表 PPG 时间基（两者时钟可能差几秒）
- 用睡眠分期（浅/深/REM）给鼾声事件打标签
- 输出：每个鼾声事件 + 当时的心率/血氧/体动

---

## P2 — 提升数据密度

| 维度 | 现状 | 可以试的 |
|---|---|---|
| 血氧 | 5 分钟一次（115 条/晚） | 打开「自动血氧测量」，看能否到 1 分钟 |
| 心率 | 60 秒一次 | 打开「自动心率测量」 |
| 压力 | 关闭 | `pref_huawei_stress_switch` |

注意：这些都会增加手表耗电。当前整晚耗电约 1%。

---

## P2 — 5 个未实现服务

设备能力表里报告了 5 个 Gadgetbridge 完全没有实现的服务：

```
服务 0x16 (22): 命令 01,03,07
服务 0x1B (27): 命令 01,0F,19
服务 0x2E (46): 无命令
服务 0x30 (48): 命令 01
服务 0x35 (53): 命令 03,04
```

裸请求（空 TLV）被拒，返回错误码 `100003` / `100007`。
要探索得先搞清每个命令需要的参数格式。

**价值未知**，优先级低。0x16 在连接瞬间主动推过 `cmd=0x25` / `cmd=0x26`，
可能是某类状态上报。

---

## P3 — 清理

- 研究脚手架补丁全部删除（见 `patches.md`）
- `ResponseManager` 里的原始包日志降级或删掉（刷屏）
- 确认 `keys/README.md` 里的密钥丢失说明仍然准确


---

## 2026-11-13 收工时的实际状态

已完成并验证：

| 项 | 证据 |
|---|---|
| RRI 逐拍抓取 | `rri_20261113.csv`，实时流每包 143 字节 |
| 健康开关每次连接重下发 | `HEALTHSW ... pushed` + 手表 `Service: 2d` 应答 |
| 忙碌看门狗 | 已装，未触发 |
| RRI 进导出清单 | 已装，待 00:00 验证 |
| 每晚上验收脚本 | `tools/nightly-check.ps1`，仅语法验证过 |
| 时钟偏移 | 已实现，但偏移恒为 0（见下） |

### 时钟偏移的已知缺陷

GB 每次连接都推时间，所以测到的是**推送后的残余偏差**，不是真实漂移。
要测真实漂移，需要在 `SetTimeRequest` 发出**之前**采样手机时间，并在响应到达后
计算 —— 改 `SetTimeRequest` 的时序即可，但会改动握手流程，需谨慎。

### 下一轮的第一件事

按 [`0x0a-session-plan.md`](0x0a-session-plan.md) 的 **第 1 步**开始：
纯观测，不改协议逻辑，只把 0x0A/0x05 的实际到达情况打印出来。

关键前提（方案文档里已论证）：之前所有探针都是 `addToResponse=false`，
等于主动不接收 0x0A/0x05；而且 0x0A/0x05 被解析为非 TLV，
`tlv == null` 恰恰说明数据到了，不是失败。

### 一个有用的操作技巧

导出可以手动触发，不必等到 00:00：

```
prefs 里设 intent_api_allow_trigger_export = true
adb shell am broadcast -a nodomain.freeyourgadget.gadgetbridge.TRIGGER_DATABASE_EXPORT
（完成后记得把 pref 恢复）
```

注意广播的 action 是 **`nodomain.freeyourgadget.gadgetbridge.command.TRIGGER_DATABASE_EXPORT`**
（带 `.command.`），旧的不带 `.command.` 的形式已废弃。

---

## 2026-11-14 收工时的实际状态

已完成并**真机验证**（不是"应该能用"）：

| 项 | 证据 |
|---|---|
| 夜间窗口 00:00–08:00（本地时区） | 代码 `RRI_WINDOW_START_HOUR=0` / `END=8`；19:33 之后 `rri_20261114.csv` 不再增长 |
| 出窗口主动关流 | `closeRriStream()` 发 `0x19/0x01 type=4`，靠 `lastRriPacketMs` 判断流是否真的活着 |
| 采集状态时间线 | `files/rri/capture_20261114.csv` 已生成：`1794659057,session_start_outside_window` |
| 归档内容寻址（schema 5） | 导出目录只剩 5 个 `raw-*`，`raw-rri_20261109.csv (1)` 这类重复被自动清掉 |
| 同名不同内容能更新 | `raw-rri_20261113.csv` 从 77945 字节重写成 181079；`raw-sleep_data.bin` 稳定名 105716 |
| `(1)` 重复的根因 | 旧逻辑靠目录列表判断"已归档"，列表偶尔为空就再建一个同名文件 |
| 0x0A 块读实验 | `Send0ABlockSizeProbe` 调用已注释；29 次以上零返回 |
| 发布补丁完整性 | `all-changes.patch` 从 18 个文件补到 27 个（之前漏了 AndroidManifest / GBApplication 的定时同步接线），`git apply --check` 通过 |

### 今晚要验的三件事

1. **00:00 开流**：`capture_<明天>.csv` 应出现 `open_requested`，且 `rri_<明天>.csv` 开始有行
2. **08:00 关流**：应出现 `close_requested`，之后 csv 不再增长
3. **耗电**：整夜应 ≈3%（RRI 全天开是 2.5%/小时）

判定脚本：`tools/nightly-check.ps1`（仍未在真机上跑过，明早第一次跑要顺手修）。

### 已知但没修的

| 项 | 说明 |
|---|---|
| `sleep_data.bin` 每 30 分钟重下一次 | 105716 字节内容常常一模一样，应该先问设备要 hash 再决定下不下（`GetFileHashRequest` 已存在但没接） |
| 时钟偏移恒为 0 | GB 连接时就推时间，测到的是推送后的残余偏差，不是真实漂移 |
| 压力开关 | `setStress()` 需要校准数据，没有就自己复位成 false |
| 日志会在 force-stop 时丢尾巴 | logback appender 是 `lazy` + `immediateFlush=false`；所以采集时间线用独立文件立即落盘，不要只看 log |

### 下一轮的第一件事

先在真机上跑一次 `tools/nightly-check.ps1`，把它的误报修掉 —— 它是唯一能自动判定
"今晚数据到底行不行"的东西，现在是纯手工验证。

