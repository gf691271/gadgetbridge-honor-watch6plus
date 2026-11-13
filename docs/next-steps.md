# 未完成事项

按优先级排序。每条都写清「为什么值得做」和「怎么判断做完了」。

---

## P0 — manifest 改成真正机器可读

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

## P0 — 给下游项目提 issue，钉死文件契约

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

