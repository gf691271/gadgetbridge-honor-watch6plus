# 实验 B 结果 + 昨晚（11-14→15）实测（2026-11-15 晚）

## 1. 实验 B：17 个文件类型全部被接受，**全部 size=0**

修好 `convertFileTypeFrom2C` 之后，15:31 和 15:33 各跑了一次探针（连接路径一次、同步路径一次，
`pref_research_file_probes=true`）。日志里第一次出现了这些类型的 `FILEDL_INIT` —— 以前它们
在打印之前就被客户端当成「wrong file received」抛掉了：

```
name=atrial_data.bin      id=2  size=0
name=rri_data.bin         id=3  size=0
name=once_rri_data.bin    id=4  size=0
name=osa_rri_data.bin     id=5  size=0
name=osa_spo2_data.bin    id=6  size=0
name=rri_draw_data.bin    id=7  size=0
name=ecg_data.bin         id=8  size=0
name=once_ppg_data.bin    id=9  size=0
name=sleep_state.bin      id=14 size=0
name=sleep_data.bin       id=15 size=0
name=rrisqi_data.bin      id=16 size=0
name=food_data.bin        id=19 size=0
name=health_arrhy_data.bin id=20 size=0
name=hrv_heart_rate_data.bin id=22 size=0
name=bp_measure_result.bin id=23 size=0
name=bp_med_measure_data.bin id=24 size=0
name=workout_data.bin     id=25 size=0
```

`FILEDL_DONE ... bytes=0` 一条条对上，**没有一条失败**。

**结论：这块固件上不存在逐拍/OSA/心电的文件通道。** 17 个类型都收（不是「只认 5 种」），
但除 `sleep_state` / `sleep_data` 在**有数据的那段时间**之外，全部返回 0 字节。
`osa_rri` / `osa_spo2` 不是被拒，是**没有产物**——对应的健康功能（睡眠呼吸暂停监测、
房颤筛查、心电）要么没开，要么这个固件不产生。

另外：探针跑完后 `sleep_state.bin`（早上还有 16 字节）和 `sleep_data.bin`（早上还有
105716 字节）**都变成 0** 了。

## 2. 6a 结案：blob 不会每晚重新生成，而且会被设备「收走」

| 时间 | 事件 | 证据 |
|---|---|---|
| 11-14 20:24 | 存下 105716 字节 blob | `sleep_data_1794659073311.bin` |
| 11-15 08:00 | 设备又给 105716 字节，**与上面逐字节相同** | `FULLDUMP unchanged since sleep_data_1794659073311.bin` |
| 11-15 14:08 | 再给一次同样内容，随后同一次同步里变成 0 | `FULLDUMP sleep_data bytes=105716` → 下一请求 `size=0` |
| 11-15 15:26 起 | 一直 0 | `FULLDUMP sleep_data empty, nothing saved` |

而 blob 覆盖的时间是 **11-13 00:51 → 08:50**（ACC 时间戳直接读出来的）。
也就是说：**11-13 之后手表再也没有生成过新的 sleep_data**，包括昨晚（戴了表、RRI 收了 8 小时）。
`protocol-findings.md` 11.1 把「换新」归因于探针不再抢数据，这个解释不成立 —— 现在探针关了，
blob 反而既不变也不再出现。

所以现在能拿到的信号级数据只有两份历史 blob（11-09 的 78052、11-13 的 105716），
以及**实时 RRI 流**。呼吸暂停分析的逐拍来源应当以 RRI 流为主。

## 3. 昨晚是第一个完整验证成功的夜（00:00 开流 / 08:00 关流）

`capture_20261115.csv`：

```
epoch_s,event
1794672003,open_requested      → 00:00:03
1794700812,close_requested     → 08:00:12
```

`rri_20261115.csv`：509,986 字节，最后一笔写在 **08:00**，之后不再增长。

| 指标 | 值 |
|---|---|
| 时长 | 8.00 h（00:00:05 → 08:00:03） |
| 包 / 拍 | 5,967 / 26,728 |
| 每包拍数（中位） | 4 |
| 包间隔（中位） | 4 s |
| 相邻包重复拍 | **0**（5,957 对里没有一对重复） |
| `sqi=0` 占比 | 1.7% |
| **拍覆盖率** | **中位 0.77**，最低 0.68，最高 0.89 |

覆盖率 0.77 是这次新加的指标（`check_rri_packets.py` 现在会打出来）：
一拍的时间总和 ÷ 墙上时间。4 秒一包只装 4 拍（≈3.6 秒）→ 0.75 左右。
**即约四分之一的拍没到手**，不是重复，是缺。做 HRV 时要先处理这些缺口
（跨缺口不参与 RMSSD，或按缺口切段）。

## 4. 两份 blob 的差别（顺手校准文档里的「72 bpm」）

| blob | 覆盖 | ACC | PPG | 拍数 | 平均心率 |
|---|---|---|---|---|---|
| 78052 字节 | 11-09 夜 | 387 | 596 | 20,513 | 56.8 bpm |
| 105716 字节 | 11-13 00:51–08:50 | 449 | 716 | 27,406 | 71.8 bpm |

文档里原来写的「约 2–3 万拍 / 平均 72 bpm」用的是 105716 那份，数字没错；
「56.8」是 78052 那份。两份都通过 C1–C6 全部校验（含「每条记录尾部一个 `0x00`」那条）。

## 5. 待做

- **今晚**是第二个完整夜，明早看 `capture_20261116.csv` 的 `open_requested` / `close_requested`，
  以及 `rri_20261116.csv` 的覆盖率
- 手表戴一整晚后，看 `sleep_data` 有没有重新出现（今天的结论是「不会」）
- 探针偏好已改回 `false` 并重启，确认没有新的 sweep
