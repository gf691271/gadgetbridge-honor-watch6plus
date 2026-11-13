# 复现：怎样确认你装出来的和我们是同一套

本文解决两个问题：

1. 哪些值**必须换成你自己的**（换成别人的反而不通）
2. 哪些值**必须和我们一致**（不一致则协议行为不同，本篇结论不适用）

---

## 1. 必须换成你自己的

| 项 | 说明 |
|---|---|
| **MAC 地址** | 每块表都不同。文档里写作 `00:11:22:33:44:55` 只是占位符，**不要照抄** |
| **蓝牙名称后缀** | 形如 `HONOR Watch 6 Plus-B1E`，后缀由 MAC 末字节派生 |
| **prefs 文件名** | `devicesettings_<mac>.xml`，冒号换下划线、字母小写 |
| **本机路径** | 构建/工具脚本里的路径按你自己的目录改 |

这些换成你自己的**不影响任何结论**——协议行为与 MAC 无关。

---

## 2. 必须与我们一致

只有这几项不同才会导致协议行为差异：

| 项 | 我们的值 | 为什么重要 |
|---|---|---|
| **手表型号** | `Rome-B19C`（HONOR Watch 6 Plus） | 不同型号的服务/命令集不同 |
| **手表固件** | `20.1.0.114` | 固件决定能力表和文件类型字节 |
| **手机系统** | Android 17 / SDK 37（MagicOS） | 权限与后台策略影响同步稳定性 |
| **Gadgetbridge** | 0.95.1（versionCode 255）+ 本仓补丁 | 上游不同版本下载路径不同 |

**固件不一致时**：`docs/protocol-findings.md` 的结论（类型字节、文件大小、TruSleep 行为）
**可能不成立**，需要用同样的方法重新探测一遍（方法见该文档）。

---

## 3. 五步验收

装好之后，按顺序确认这五项。**全过 = 和我们的环境等价**。

### ① 能认证

```powershell
adb pull /sdcard/Android/data/nodomain.freeyourgadget.gadgetbridge/files/gadgetbridge.log
Select-String gadgetbridge.log -Pattern 'mutual auth OK'
```

期望：出现 `STS reconnect complete - mutual auth OK`

### ② 能力表已生成

```powershell
adb shell "run-as nodomain.freeyourgadget.gadgetbridge ls shared_prefs/ | grep capabilities"
```

期望：存在 `huawei_coordinator_capabilities_<mac>.xml`。
里面有形如 `<string name="1">040708090D...</string>` 的服务→命令映射。

**这张表是判断"型号/固件是否一致"的最快方式**：服务数量和命令列表不同，说明固件不同。

### ③ 同步能结束

```powershell
Select-String gadgetbridge.log -Pattern 'sync complete|正在获取活动数据'
```

期望：出现 `Workout sync complete!`，且**没有**卡住的「正在获取活动数据」。

### ④ 睡眠文件非空

```powershell
Select-String gadgetbridge.log -Pattern 'FILEDL_INIT name=sleep'
```

期望：

```
name=sleep_state.bin id=14 size=32
name=sleep_data.bin  id=15 size=105716     ← 关键，不能是 0
```

**如果是 0**：检查 `trusleep` 是否为 `false`（这是最常见原因，见 `pitfalls.md` A1）。

### ⑤ 能解码出逐拍

```powershell
adb pull /sdcard/Android/data/nodomain.freeyourgadget.gadgetbridge/files/dump/sleep_data_<ts>.bin
python decoders/decode_sleep_beats.py sleep_data_<ts>.bin
```

期望输出：

```
ACC=<n>  beats=<n>          ← beats 在 2 万上下
span HH:MM -> HH:MM  (x.xx h)
mean HR ≈ xx bpm
```

如果 `beats=0`，说明文件拿到了但格式不同 —— 固件可能变了。

---

## 4. 快速对照表

| 现象 | 说明 |
|---|---|
| 认证都过不去 | 先重启手表（`pitfalls.md` A3） |
| 能力表里的服务数和我们差很多 | 固件不同，协议结论要重测 |
| `sleep_state=96` 而不是 32 | 可能是有多晚数据或固件差异，不影响 |
| `sleep_data` 恒为 0 | `trusleep` 被打开了 |
| `sleep_data` 大小不是 105716 | 正常，取决于当晚睡眠时长；**只要 > 60000 就算成功** |

---

## 5. 数据量的合理预期

以我们一晚（约 6.4 小时睡眠）为参考：

| 数据 | 量级 |
|---|---|
| 活动样本 | 3000 条左右 |
| 心率 | 1200 条左右 |
| 血氧 | 100～200 条 |
| 睡眠分期样本 | 10～30 条 |
| 逐拍（sleep_data） | 2 万～3 万拍 / 6 万～11 万字节 |

差异在 ±50% 都属于正常（取决于睡眠时长和佩戴情况）。
**数量级差一个数量级才说明配置有问题。**
