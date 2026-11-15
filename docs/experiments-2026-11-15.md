# 实验 A + 逐拍 blob 校验：结果（2026-11-15）

对 issue #2 的回复（Mac 侧 Claude 的评论）里第一批能离线做的实验，我在 PC 侧跑完了。
两个结论都推翻了仓库原来的说法。

---

## 1. 实验 A：「固件只认 5 种文件」是客户端 bug，不是固件行为

**做法**：重跑 11-09 的类型扫描日志 `gb_probe_all.log`（12.8 MB），改用
`decoders/decode_filedl.py`（已按回复里的三处修改重写：不再跳过短回包、
把 `02` 认成 file_type、新增 `03` = transfer_id），把每个 0x2C/0x01 回包按类型列成一张表。

**结果（92 个回包，26 种类型 0x00–0x19）**：

| 类型 | 回包形态 | size | `7F` 状态码 |
|---|---|---|---|
| 0x00–0x0D, 0x10–0x19 | **full**（name + type + transfer_id + size 齐全） | 全部 0 | `0x00023281` |
| 0x0E `sleep_state.bin` | full | 16 / 96 / 144 | `0x000186A0` |
| 0x0F `sleep_data.bin` | full | **0 或 78052** | `0x00023281` / `0x000186A0` |
| — | **error-only（只有 `7F`）** | — | **一个都没有** |

三个读数：

1. **没有任何一个类型被设备拒绝。** 26 种全部回了完整 answer。原来「只认 14/15/16/22/24
   五种」完全是我方 `convertFileTypeFrom2C()` 只映射 7 种造成的假象
   （`GetFileDownloadInitRequest.java:59`，已修）。
2. **`transfer_id` 与 `file_type` 完全相同**（92/92）。至少在一次干净的会话里，设备把句柄
   编号成和类型一样。这解释了为什么「按 id 直接问」看起来像能用 —— 但句柄仍然必须由
   `0x2C/0x01` 建立，不能凭空构造。
3. **`0x00023281`（= 144001）配 size=0，`0x000186A0`（= 100000）配 size>0。**
   所以 `0x23281` 是「这个类型我收，但这个窗口没有数据」，不是错误。这一点以前没有区分过。

**还剩的问题**：0x02–0x09（`atrial` / `rri_data` / `once_rri` / `osa_rri` / `osa_spo2` /
`rri_draw` / `ecg` / `once_ppg`）全部 size=0。可能是对应的健康功能没开（房颤筛查、
睡眠呼吸暂停、心电），也可能是这些表在本固件上不产生数据。这需要实验 B 在
「功能确实开着、而且戴过表」的白天再跑一次才能分辨。

---

## 2. 逐拍 blob 的内部校验：全部通过，「无符号差分」是对的

**做法**：新增 `decoders/check_trusleep_framing.py`（按回复给的 C1–C6 判据），
跑 11-09 夜那份 78052 字节真实 blob。

```
bytes 78052  ACC 387  PPG 596  beats 20513
C1 non-zero bytes between records : 0
C2 PPG records consumed exactly   : 596 of 596 (100.0%)
C2b of those ending in one 0x00   : 596
C3 peaks rising, delta unsigned   : 596 of 596 (100.0%)
C3 peaks rising, delta signed     : 563 of 596 (94.5%)
C4 ACC timestamps rising          : 386 of 386 (100.0%)   median step 64 s
C5 PPG record starts before previous ended: 0
C6 beat intervals in 300-2000 ms  : 19917 of 19917 (100.0%)
```

**第一次跑 C2 是 0%（596 条全部 "short"）**，每条记录都多出一个字节。逐条统计后发现：
**596 条记录，每条的尾部都正好是 1 个 `0x00`**，无一例外。把「长度字段多算了一个字节、
最后那个 0 是终止符」写进判据之后，C2 变成 100%。这是纯靠数据自证出来的，不需要第二个数据源。

其余结论：

| 判据 | 结果 | 含义 |
|---|---|---|
| C1 = 0 | 记录之间没有非零字节 | 没有把数据当填充跳过去，也没有漏掉的记录类型 |
| C3 无符号 100% / 有符号 94.5% | **无符号差分正确** | 上游 Java 的 `working += c`（c 是有符号 byte）在心率 < 47 bpm 时会把峰值算错；Python 解码器原来的无符号实现是对的 |
| C4 100%、步长中位 64 s | 时间戳字段位置与字节序正确 | ACC 记录 64 秒一条 |
| C5 = 0 | 记录之间不重叠 | 拍不会重复计数 |
| C6 100% | 相邻拍间隔全部落在 300–2000 ms | 生理上自洽 |

**对之前结论的修正**：这份 blob 解出来是 6.02 小时（02:32 → 08:33）、20513 拍、
**平均 56.8 bpm**。仓库里以前写的「约 2–3 万拍 / 平均 72 bpm」是错的
（拍数对得上，心率不对）。睡眠期 57 bpm 合理。

**这条为什么重要**：呼吸暂停分析要拿逐拍序列算 HRV（RMSSD、pNN50），而
RMSSD 只依赖相邻拍的差值。C2 + C3 + C6 同时成立，说明**这份 blob 的拍时间轴可以信**，
不用等 RRI 实时流对齐也能先做信号级分析。

---

## 3. 顺带修掉的三处代码问题

| 问题 | 位置 | 修法 |
|---|---|---|
| 类型映射不对称 | `GetFileDownloadInitRequest.convertFileTypeFrom2C` | 改成按字节映射，与 `convertFileTypeTo2C` 一致 |
| init 解析失败不 `reset()`，`isBusy` 永远 true | `HuaweiFileDownloadManager` 的两处 `handleException` | 补 `reset()` |
| 同一个 blob 每次同步下 3 次 | `downloadTruSleepData` / `enqueueFullSleepDump` | 去掉上游那条没人用的 `sleep_data` 请求（`SleepFileDownloadCallback` 新增 status-only 构造），归档请求 10 分钟内不重复 |

外加：探针改成**默认关 + 设备偏好开 + 每进程只跑一次**，并且拿到的内容会写到
`files/probe/`（以前拿到了也直接丢）。`FILEDL_RAW` 钩子扩到 `0x2C/0x02`，
为 hash 预检做准备。

---

## 4. 还没做的（等手机连上）

| 项 | 为什么没做 |
|---|---|
| 实验 B（修好映射后白天跑一次 17 文件探针） | 手机当前没连（`adb devices` 空）。代码已编译通过，装机即跑 |
| 6a 的窗口实验 | 同上 |
| 6c 的实时心率实验 | 同上 |
| hash 预检阶段一（只记录） | 按回复建议放到下一轮，先看第一步的实测结果 |

`check_trusleep_framing.py` 已经可以直接跑新 blob —— 下次拿到 105716 字节那份时，
第一件事就是它。
