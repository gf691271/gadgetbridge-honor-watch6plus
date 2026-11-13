# 荣耀手表数据文件全表（从官方 App 反编译得出）

来源：`com.hihonor.btdomain.download.oKmO`（classes28.dex，类名被混淆但字符串明文）。
这解释了为什么 Gadgetbridge 只能拿到 3 个文件——它只知道其中 3 个类型 ID。

## 请求方式

调试请求（Gadgetbridge 内置）：

```
44,1,false,false,(1,-<文件名>),(2,B<文件ID>),(5,I<开始时间>),(6,I<结束时间>)
```

- service `44` = `0x2C`（FileDownloadService2C）
- command `1` = 初始化下载
- `(1,-xxx)` 字符串文件名；`(2,B5)` 文件类型 ID；`(5,I…)`/`(6,I…)` 起止时间（秒）

## 文件类型表（实测反编译）

| 文件 ID | 文件名 | 内容 |
|---|---|---|
| 2 | `atrial_data.bin` | 房颤数据 |
| 3 | `rri_data.bin` | R-R 间期 |
| 4 | `once_rri_data.bin` | 单次 RRI 测量 |
| **5** | **`osa_rri_data.bin`** | **呼吸暂停 RRI（逐拍心率）** |
| **6** | **`osa_spo2_data.bin`** | **呼吸暂停血氧** |
| 7 | `rri_draw_data.bin` | RRI 绘图数据 |
| 8 | `ecg_data.bin` | 心电 |
| 9 | `once_ppg_data.bin` | 单次 PPG |
| 14 | `sleep_state.bin` | 睡眠状态（GB 已有，返回 0 字节） |
| 15 | `sleep_data.bin` | 睡眠明细（GB 已有，返回 0 字节） |
| 16 | `rrisqi_data.bin` | RRI+SQI（GB 已有，返回 0 字节） |
| 19 | `food_data.bin` | 饮食记录 |
| 20 | `health_arrhy_data.bin` | 心律异常 |
| 22 | `hrv_heart_rate_data.bin` | **HRV 心率** |
| 23 | `bp_measure_result.bin` | 血压测量结果 |
| 24 | `bp_med_measure_data.bin` | 血压连续监测 |
| 25 | `workout_data.bin` | 运动数据 |
| 27 | `cardiac_arrest_measure_result_details.bin` | 心脏骤停测量 |

## 与 Gadgetbridge 的对照

| GB 认识的 | GB 不知道的 |
|---|---|
| 14 sleep_state / 15 sleep_data / 16 rrisqi | 2,3,4,5,6,7,8,9,19,20,22,23,24,25,27 |

**所以"全量数据"的瓶颈不是协议，是 GB 的文件白名单只有 3 个。**

## 关键结论

1. 只要手表里存在这些文件，用上面的调试请求就能拉下来——**不需要改代码**（调试请求可直接指定任意文件名）。
2. `osa_*` 两个文件只有在**开启睡眠呼吸暂停功能**后才会生成。
3. `rri_data.bin`(3)、`hrv_heart_rate_data.bin`(22) 可能在没有开 OSA 时也有数据，值得优先试。

## 待验证

- [ ] 手表连上后，逐个请求 2/3/4/5/6/8/9/22，看哪些返回非空
- [ ] 确认返回是原始字节流还是经过 TLV 分包
- [ ] 用 Wireshark 对照（若是 pcap 格式的包装）
