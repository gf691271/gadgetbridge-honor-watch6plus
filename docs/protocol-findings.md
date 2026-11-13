# 手表文件类型探针：实测结果

> 时间：2026-11-08 00:45
> 设备：HONOR Watch 6 Plus（Rome-B19C，固件 20.1.0.114），刚恢复出厂
> 客户端：Gadgetbridge（自编译，加了无条件探针）
> 通道：BR/EDR RFCOMM（service 0x2C / command 0x01）

---

## 1. 方法

Gadgetbridge 原本只在"设备支持 TruSleep"时才请求文件，而这块表的能力位它不认识（日志里 `Capability is not supported`），所以原生流程下**一个文件都不会请求**。

为此打了两处补丁：

| 补丁 | 作用 |
|---|---|
| `HuaweiFileDownloadManager` 增加 `customFileRequest()` | 允许按"任意文件名 + 任意类型字节"发起下载 |
| `HuaweiSupportProvider.onFetchRecordedData()` 增加无条件探针 | 每次同步时把 17 种文件全部请求一遍 |
| `FILEDL_INIT / DONE / FAIL` 日志 | 打印设备实际返回的 `fileId` 与 `size` |

关键日志点：

```java
LOG.info("FILEDL_INIT name={} id={} size={}", filename, r.fileId, r.fileSize);
```

---

## 2. 结果：设备只接受 5 种文件

### 2.1 接受（设备返回有效 init，含 fileId 与 size）

| 类型 ID | 文件名 | size |
|---|---|---|
| 14 | `sleep_state.bin` | 0 |
| 15 | `sleep_data.bin` | 0 |
| 16 | `rrisqi_data.bin` | 0 |
| 22 | `hrv_heart_rate_data.bin` | 0 |
| 24 | `bp_med_measure_data.bin` | 0 |

### 2.2 拒绝（设备回的类型字节为 `UNKNOWN`）

| 类型 ID | 文件名 |
|---|---|
| 2 | `atrial_data.bin` |
| 3 | `rri_data.bin` |
| 4 | `once_rri_data.bin` |
| **5** | **`osa_rri_data.bin`** |
| **6** | **`osa_spo2_data.bin`** |
| 7 | `rri_draw_data.bin` |
| 8 | `ecg_data.bin` |
| 9 | `once_ppg_data.bin` |
| 19 | `food_data.bin` |
| 20 | `health_arrhy_data.bin` |
| 23 | `bp_measure_result.bin` |
| 25 | `workout_data.bin` |

原始错误：

```
FILEDL_FAIL name=osa_rri_data.bin
  error=Data for wrong file received. Expected type OSA_RRI, got type UNKNOWN
```

**语义**：设备在 init 响应里回什么类型字节，客户端就必须匹配；回 `UNKNOWN` 表示该类型不被支持。这与"文件为空"（size=0）是**两种不同的情况**：

| 现象 | 含义 |
|---|---|
| `size=0` | 类型被支持，但当前时间段没有数据 |
| `Expected X, got UNKNOWN` | 该类型**根本不被这个固件支持** |

---

## 3. 结论

1. **固件只认 14/15/16/22/24 五种文件类型。**
   官方 App 的 APK 里那 18 个文件 ID 表，是从其他版本/地区沿用来的，**不是本固件的真实支持集**。

2. **`osa_rri` / `osa_spo2` 不被支持** → 睡眠呼吸暂停的原始逐拍数据在这块表上取不到（至少 20.1.0.114 这个固件）。
   这与"没开 OSA 功能"是两回事：即使开了，协议层也不认这两个类型。

3. **心率相关的是 16（rrisqi）和 22（hrv）**，两者都被接受，只是当前 `size=0`。

4. 所有 `size=0` 的原因是**手表刚恢复出厂，尚无数据**。

---

## 4. 下一步验证

手表已佩戴，等数据积累后（睡一晚，或完成一次 ≥5 分钟的运动）再同步一次，观察：

```
FILEDL_INIT name=rrisqi_data.bin          id=16 size=?
FILEDL_INIT name=hrv_heart_rate_data.bin  id=22 size=?
FILEDL_INIT name=sleep_state.bin          id=14 size=?
```

判读：

| 结果 | 含义 | 下一步 |
|---|---|---|
| size > 0 | 数据通道打通 | 解析文件格式，接入下游程序 |
| 仍为 0 | 该功能未启用或本机不产该数据 | 排查睡眠/心率开关 |
| 变 UNKNOWN | 设备重启后能力变化 | 重新探针 |

---

## 5. 复现方法

```powershell
# 1. 同步（触发探针）
adb -s <serial> shell input tap 390 587

# 2. 拉日志
adb pull /sdcard/Android/data/nodomain.freeyourgadget.gadgetbridge/files/gadgetbridge.log probe.log

# 3. 过滤
Select-String -Path probe.log -Pattern 'FILEDL_INIT|FILEDL_DONE|FILEDL_FAIL'
```

前置条件：

- Gadgetbridge 需开启「调试 → 写入日志文件」
- 设备通过「添加测试设备」绑定为 `Honor Watch 6`
- 荣耀运动健康与 iConnect 需临时禁用，否则会抢连接

---

## 6. 与官方 App 的对照意义

官方 App 能拿到这些数据，说明它走的是**同样的 0x2C 通道**，只是它知道正确的类型字节集合。本次探针的结论修正了此前的一个假设：

> ~~文件类型表 = APK 里那 18 个~~
> **文件类型表 = 设备在 init 响应里认可的那几个**（本机为 5 个）

这也解释了为什么社区里不同机型的"可用文件"差异很大——**同一份 APK，不同固件支持的子集不同**。

---

## 7. 2026-11-08：睡眠文件通道打通（实测更新）

### 7.1 关键发现：能力位判断是错的

Gadgetbridge 因为 `supportsTruSleep()` 返回 `false`，**完全跳过了睡眠文件下载**。但设备其实serves `sleep_state.bin`。

补丁（`HuaweiSupportProvider.downloadTruSleepData`）：

```java
// 原本：if (!getDeviceState().supportsTruSleep()) return false;
if (!getDeviceState().supportsTruSleep())
    LOG.info("TRUSLEEP_PATCH capability missing, continuing anyway");
```

同样的处理也加到了 `downloadStressData`（`supportsAutoStress`）。

**教训**：对于通过"添加测试设备"绑定的机型，GB 的能力位往往读不准，**不能因为能力位为 false 就放弃整条数据路径**。

### 7.2 实测结果

佩戴一晚后同步：

| 文件 | size | 结果 |
|---|---|---|
| `sleep_state.bin` (14) | **48** | ✅ 下载成功并解析 |
| `sleep_data.bin` (15) | 0 | 空 |
| `rrisqi_data.bin` (16) | 0 | 空 |
| `hrv_heart_rate_data.bin` (22) | 0 | 空 |
| `bp_med_measure_data.bin` (24) | 0 | 空 |

解析后数据库：

```
HUAWEI_ACTIVITY_SAMPLE 共 2064 条
  kind=-1 (无数据)  1984
  kind=1  (活动)      66
  kind=8  (REM)        6
  kind=6  (浅睡)       6
  kind=3               2
```

睡眠样本共 12 条，跨 358 分钟：

```
08:58 浅睡   10:44 浅睡   10:44 REM   10:45 REM
11:27 浅睡   12:13 浅睡   12:15 REM   12:16 REM
14:10 浅睡   14:40 浅睡   14:55 REM   14:56 REM
```

**48 字节 = 12 条 × 4 字节**，与记录数吻合。

### 7.3 链路验证结论

```
设备 --(0x2C 文件下载, 48B)--> GB --(TruSleep 解析)--> 数据库(12 条样本)
```

✅ 整条链路已验证可用。这是本项目第一次从手表拿到**结构化的睡眠分期数据**。

### 7.4 仍未解决

| 项 | 现象 | 推测原因 |
|---|---|---|
| 心率 | 所有样本 `HEART_RATE = -1` | `0x07/0x17`（自动心率）命令已下发并有异步响应，但设备未在活动流中回心率；可能需要开启"实时自动心率"模式，或等设备累积 |
| `rrisqi_data.bin` (16) | size=0 | 可能依赖压力/HRV 测量事件 |
| `hrv_heart_rate_data.bin` (22) | size=0 | 可能依赖睡眠 HRV，需 TruSleep 完整运行一整晚 |
| `sleep_data.bin` (15) | size=0 | 该固件可能只产出 `sleep_state` |

### 7.5 下一步

1. **开启"实时自动心率测量模式"**（GB：设备特殊设置 → 健康 → 该开关），观察活动流是否出现真实心率值；
2. 让 TruSleep 完整跑一整晚（今天只戴到下午），次日再同步，观察 `hrv`/`rrisqi` 是否非 0；
3. 如需分析原始字节，开启「调试 → 保存原始文件」，把 `raw/SLEEP_STATE/*.bin` 拉下来逆向格式。

---

## 8. 逐拍心率（RRI）通道：已打通并解出格式

### 8.1 通道

| 项 | 值 |
|---|---|
| 服务 | `0x19`（HrRriTest） |
| 命令 | `0x01` = 开关（type 3 开 / 4 关）、`0x05` = 数据推送 |
| 触发 | 发送 `0x19/0x01`，`type=3` |
| 推送频率 | 约 **每 4 秒一批**，每批 **14 条**记录 |
| 结束 | 设备会在约 20 秒后自行关闭流（回 `0x7F`） |

### 8.2 报文字段（实测）

```
01 04 6AF05104   tag 0x01, len 4  → 时间戳（epoch 秒，大端）
06 01 00         tag 0x06, len 1  → 标志
07 01 00         tag 0x07
08 01 00         tag 0x08
82 7E            tag 0x82, len 126 → 容器
  83 07          tag 0x83, len 7  → 单条记录
    04 02 026C   tag 0x04, len 2  → RRI，单位 ms（大端），0x026C = 620
    05 01 64     tag 0x05, len 1  → SQI，0x64 = 100（信号质量，满分 100）
  ...重复 N 次
```

结束/错误：`7F 04 00 01`。

### 8.3 换算

```
心率(bpm) = 60000 / RRI(ms)
```

实测值：

```
RRI 620ms → 97 bpm      RRI 687ms → 87 bpm
RRI 583ms → 103 bpm     RRI 652ms → 92 bpm
```

5 批共 70 个逐拍样本，SQI 全部 100。

### 8.4 关键认知修正

| 之前 | 实际 |
|---|---|
| 心率要靠 `hrv_heart_rate_data.bin` 文件 | ❌ 该文件恒为 0 |
| 心率拿不到 | ❌ **通过 `0x19/0x05` 实时流可以拿到逐拍数据** |
| 需要官方 App | ❌ 不需要 |

**这也解释了为什么活动流里 `HEART_RATE` 全是 -1**：活动采样不携带心率，心率走独立通道。

### 8.5 工具

`tools/decode_rri.py`：把日志里的 `HRRRI_RAW` 行解析成 RRI/SQI/心率。

```powershell
python tools\decode_rri.py data\gb_hex.log
```

### 8.6 尚未解决

设备约 20 秒后自行关闭 RRI 流。要拿到**整晚的逐拍心率**，需要：

1. 周期性重新发送 `0x19/0x01 type=3`（例如每 15 秒一次）；
2. 或找出让设备持续推送的附加参数（待试探）。

当前实现（`HuaweiSupportProvider` 里的 `RRI_STREAM_OPEN`）只在每次同步时开一次。

---

## 9. 重大修正：手表一直缓存在整晚的逐拍数据（11-09 实测）

### 9.1 结论先行

**手表会在本地缓存整晚的 PPG（逐拍脉搏波），通过 48 小时窗口一次同步即可完整取回。**

这意味着**不需要整夜挂机采集**——早晨同步一次就够。此前"RRI 只有实时流"的判断是错的。

### 9.2 关键机制：时间窗口决定数据量

同一文件、同一类型，不同窗口的结果：

| 窗口 | 返回 |
|---|---|
| 1.5 小时（Gadgetbridge 默认的"上次同步至今"） | `size=0` |
| **48 小时** | **78052 字节** |

**"没数据"多数时候是"窗口太窄"。** 这是本项目最重要的排障经验之一。

### 9.3 文件名无关，类型字节决定一切

枚举 16 个文件名 × 48 种类型：任何文件名配 `type=0x0F` 都返回 78052 字节；其它类型返回 0。

**设备不校验文件名，只按类型返回数据。**

### 9.4 数据格式：与上游 TruSleep 兼容

Gadgetbridge 的 `HuaweiTruSleepParser` 格式说明：

```
零填充 + ACC(1) / PPG(2) 交替
ACC: tag(1) + len(1) + [timestamp(4 LE) + flags(2)]
PPG: tag(1) + len(2 LE) + [timestamp(4 LE) + count(1) + peak[] + amp[]]
peak/amp 压缩: tag 0xAA=原始, 0xBB=差分, 0xFF=重启
```

**我们的 78052 字节完全符合该格式**，解析结果：

```
ACC 记录:  387 条   11-09 01:54 → 08:46
PPG 记录:  ≈600 条（示例）
PPG 逐拍:  ≈20000 拍（示例）
```

所以**荣耀仍沿用这套格式**（至少 sleep_data 是），"荣耀独立后换算法"的猜测不成立。

### 9.5 为什么 GB 没解析出来

不是格式不兼容，而是 **Gadgetbridge 的同步窗口太窄**：

```java
// 上游：start/end 来自 syncState 的"上次同步至今"
sleepDataFileRequest(supportsTruSleepNewSync, start, end, callback)
```

窗口只有 1.5 小时 → 设备返回 `size=0` → 解析器拿到空数组 → 0 条样本。

补丁（`0005-support-provider.patch` 已含）：

```java
int wideEnd = (int) (System.currentTimeMillis() / 1000L);
int wideStart = wideEnd - 48 * 3600;
sleepDataFileRequest(..., wideStart, wideEnd, callback);
```

### 9.6 产物与工具

| 文件 | 内容 |
|---|---|
| `data/sleep_data_full.bin` | 78052 字节原始数据 |
| `data/csv/sleep_beats.csv` | ≈20000 个逐拍（epoch_ms, peak, amp） |
| `data/csv/sleep_acc.csv` | 387 条 ACC 记录（flags） |
| `tools/parse_trusleep.py` | TruSleep 格式解析（Python 移植） |
| `tools/decode_sleep_beats.py` | 逐拍解码 + 每 10 分钟心率 |
| `tools/runs_bin.py` | 结构探测 |
| `tools/decode_filedl.py` | 文件下载响应解码（fileId / size / err） |

### 9.7 对架构的影响

| 之前设计 | 现在 |
|---|---|
| 整夜挂 GB 采集 RRI（手表掉电 30-50%） | ❌ **不需要** |
| 每天点同步 | ✅ 早晨同步一次，48h 窗口 |
| RRI 实时流是唯一心率来源 | 仅作实时补充，非必需 |

**手表耗电回到正常水平，采集流程变成"每天同步一次"。**

---

## 10. 逐拍数据卡住不更新（2026-11-11 排查中）

### 10.1 现象

`sleep_data.bin` 每次返回 **78052 字节、SHA256 前 16 位恒为 `8A291C23F3BD1CDD`**，
解码内容固定为 **11-09 02:32–08:33**，此后三天的同步都拿到同一份字节。

同一时间 `sleep_state.bin` 却在变（144 → 96 字节），数据库里的睡眠分期每晚都有新数据。

**结论：采集链路没坏，是 `sleep_data` 这个文件本身没有被设备重新生成。**

### 10.2 排除的假设

| 假设 | 实验 | 结果 |
|---|---|---|
| 时间窗口太宽导致返回缓存 | 请求 48h 窗口（起点 11-09 07:51），返回内容大部分在窗口外 | ❌ 设备根本不按窗口过滤 |
| 文件名影响 | 之前已验证文件名被忽略 | ❌ |
| 同步被跳过 | 02:00 确实被"忙碌"跳过一次，但手动同步后仍是旧数据 | ❌ |

### 10.3 找到的真问题（两个）

**① 0x0A 探针会把下载流程搞崩**

我们的文件清单探针回复被 GB 正在进行的下载会话误认领，导致
`GetFileParametersRequest.createRequest` 空指针 → 下载中断 → "正在获取活动数据"
永远不结束。已停用全部 0x0A 探针（list / fileinfo / block / parameters / debugdl）。

**② TruSleep 开关是关着的**

```
trusleep            = false   →  已改为 true 并在连接时成功推送（SetTruSleepRequest）
huawei_sleep_breath = false
heartrate_automatic_enable = false  → 改为 true（尚未推送）
spo_automatic_enable       = false  → 改为 true（尚未推送）
```

推测：TruSleep 关闭时手表只做基础分期（写 sleep_state），不再录制原始 PPG（写 sleep_data）。
验证方式：等一晚，看明天 `sleep_data.bin` 的哈希是否变化。

### 10.4 修改偏好文件的正确方法

文件名含冒号（MAC 地址），`run-as sh -c 'cat > path'` 会因引号失败。可行方式：

```powershell
# 宿主侧把内容通过 stdin 管道进去，路径用单引号包住整个 sh -c 参数
Get-Content local.xml -Raw | adb shell "run-as <pkg> sh -c 'cat > shared_prefs/devicesettings_00:11:22:33:44:55.xml'"
```

先 `am force-stop`，改完再启动，否则 GB 会用内存里的旧值覆盖。

---

## 11. 逐拍数据恢复（2026-11-13 结论）

### 11.1 真正的两个原因

**① TruSleep 开关**

| trusleep | sleep_state | sleep_data |
|---|---|---|
| true | 0 | 0 |
| false | 32 | 105716 |

开启后手表走 GB 不支持的 newSync 协议，两个文件都返回 0。**必须保持关闭。**

**② 探针抢先消费了数据**

`DEBUG_DL_CANDIDATES` 里包含 `sleep_data.bin`、`sleep_state.bin`、`rrisqi_data.bin`，
而 `enqueueProbeDownloads()` 在 `onFetchRecordedData()` 里排在归档路径之前。
结果：探针先下载一次，归档路径再请求时拿到 0。

把这三个真实数据文件从候选列表移除后，归档路径独占 `sleep_data`，
GB 自己只拿 `sleep_state`（算分期），互不干扰 —— 实测连续三次都拿到 105716 字节。

### 11.2 恢复后的数据

```
文件 105716 字节（旧格式 78052）
ACC=449  beats=≈27000（旧 ≈20000）
span 某晚 02:31 – 08:53，6.37 h
mean HR ≈72 bpm
```

分析（11-13 夜）：

| 指标 | 结果 | 11-09 夜对比 |
|---|---|---|
| CVHR 谷（严格） | 3 次，Fcv = 0.5/h | 0/h |
| 心率骤升 ≥6bpm | 70 次 ≈ 11/h | 8/h |

均远低于 OSA 判读阈值（CVHR >10/h 才有提示意义），**只能作为生理负荷参考，不能当 AHI**。

### 11.3 踩坑记录：手表蓝牙栈会卡死

现象：GB 一直显示"认证中"，日志 `read failed, socket might closed or timeout`。
蓝牙绑定和认证密钥都正常，**重启手表后立即恢复**（14:15:56 `mutual auth OK`）。

### 11.4 编译环境

`<WORK>` 下的目录删除一律被 Windows 权限拒绝，但**重命名可行**。
做法：把各模块的 `build` 目录改名，Gradle 就会全新编译。
脚本见 `tools/build-gb.ps1`（支持 -Project / -AndroidHome，自动重试）。
注意 `ANDROID_USER_HOME` 必须指向含 `7885FD5C...` 密钥的 home，否则签名不匹配装不上。



