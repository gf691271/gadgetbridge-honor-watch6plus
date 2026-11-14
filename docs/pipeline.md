# 数据管线说明（历史版本，已被取代）

> **这份文档描述的是 2026-11 上旬的旧管线**：Gadgetbridge 每 3 小时导出整库 `.db`，电脑用 `adb pull`
> 拉取再分析。文中的 `sync.py`、`report.py`、`GBSyncTask` 都不在本仓库里，「已知缺口」一节说的
> 「心率 / 血氧无」也已经过时（见 [`protocol-findings.md`](protocol-findings.md) 第 8 节）。
>
> 现在的管线是：打过补丁的自动导出 Worker 把 manifest + CSV + raw 文件写到 SAF 目录，下游只读这个目录。
> 文件契约见 [`patches.md`](patches.md) 和 mailuo 仓库的 `docs/integrations/gadgetbridge.md`。
> 这里只保留第 4 节「数据结构要点」还有参考价值。

目标：把荣耀手表 6 Plus 的数据**稳定、自动**地落到这台电脑上，并生成结构化结果。

---

## 1. 架构

```
┌─────────┐  BR/EDR   ┌──────────────┐  每 3 小时   ┌──────────────────┐
│ 手表    │ ────────> │ Gadgetbridge │ ──────────> │ 手机 Download/    │
└─────────┘           │  (Android)   │  导出 DB     │ Gadgetbridge.db* │
                      └──────────────┘             └────────┬─────────┘
                                                            │ adb pull
                                       ┌────────────────────▼──────────┐
                                       │ 电脑：计划任务 GBSyncTask    │
                                       │ 每 30 分钟                     │
                                       │ sync.py → 去重 → 分析 → 报告   │
                                       └───────────────────────────────┘
```

两级节奏：

| 环节 | 频率 | 由谁负责 |
|---|---|---|
| 手表 → 手机 | 每 3 小时 | Gadgetbridge「自动导出数据库」 |
| 手机 → 电脑 | 每 30 分钟 | Windows 计划任务 `GBSyncTask` |

## 2. 组件

### Gadgetbridge（手机端）

- 设置 → 自动化 → 自动导出数据库：**开启**，间隔 3 小时，位置 `Download`
- 设备 → 开发者设置：`Save RAW files` 开启（可选，用于排障）
- 注意：**不要**用 zip 导出（SAF 单文件 URI，删文件后失效）

### sync.py（电脑端）

```
python tools\sync.py          # 拉取 + 分析（内容没变则跳过）
python tools\sync.py --force  # 强制重新分析
```

做的事情：

1. `adb devices` 检查设备；无设备则安静退出（退出码 0）
2. 在 `/sdcard/Download` 里找**最新**的 `Gadgetbridge*.db`（含 `(1)` 重名）
3. 拉到 `data/inbox/gb_<时间戳>.db`
4. SHA-256 去重，内容没变就跳过
5. 跑 `report.py` + `export_csv.py`
6. 写 `data/status.json`

### 计划任务

```
任务名：GBSyncTask
命令：  <REPO_ROOT>\sync.bat
频率：  每 30 分钟
状态：  已创建并手动验证通过
```

查看/修改（需要管理员）：

```powershell
schtasks /Query  /TN "GBSyncTask" /FO LIST
schtasks /Run    /TN "GBSyncTask"
schtasks /Delete /TN "GBSyncTask" /F
```

## 3. 目录与产物

```
honor-rec/
├─ data/
│  ├─ inbox/gb_YYYYMMDD_HHMMSS.db   历史快照（不复用文件名）
│  ├─ report/report.json            结构化报告
│  ├─ csv/*.csv                     原始表导出
│  ├─ status.json                   最近一次同步状态
│  ├─ sync_state.json               去重用的状态
│  └─ sync.log                      运行日志
├─ tools/sync.py                    拉取 + 编排
├─ tools/report.py                  日报表（步数/睡眠段/电量/训练）
├─ tools/export_csv.py              CSV 导出
└─ sync.bat / sync-loop.bat         计划任务入口 / 手动循环
```

## 4. 数据结构要点

### HUAWEI_ACTIVITY_SAMPLE

| 列 | 含义 |
|---|---|
| `TIMESTAMP` | **秒**（不是毫秒），本地时区换算要乘 1000 |
| `RAW_KIND` | -1=无数据；1=活动；6=浅睡；7=深睡；8=REM |
| `STEPS` | 步数增量，-1 表示无 |

**坑**：导出里每个时间点有**两行**（一行 STEPS=-1，一行 STEPS=0），分析前必须按时间戳去重，且优先保留 `RAW_KIND != -1` 的那行。

### 睡眠

- 没有独立睡眠表，睡眠分期混在活动采样里（kind 6/7/8）
- 采样很稀疏（中位间隔 14 分钟，最大 59 分钟）
- 分段算法：按 **3 小时间隔**切夜，时长 = 首末样本之差
- 实测 03:49–10:16 = 388 分钟，与手表 6h23m 一致

## 5. 排障

| 现象 | 原因 | 处理 |
|---|---|---|
| `no adb device; skip` | 手机未连/未授权 | 插线、解锁、允许调试 |
| `no Gadgetbridge db found` | 手机端还没导出过 | 检查 GB 自动导出是否开启 |
| `unchanged` | 手机端没新数据 | 正常，等下一轮 |
| 分析结果睡眠为 0 | 去重把睡眠行覆盖了 | 确认 `sync.py` 用的是最新版 `report.py` |
| `error parsing event list` | GB 解析事件列表失败 | **非致命**，同步照常完成 |

## 6. 已知缺口

| 数据 | 状态 | 说明 |
|---|---|---|
| 心率 / 血氧 / 压力 | 无 | GB 无解析实现，需改源码 |
| 训练记录 | 无 | 1 分钟的运动未被手表保存；需 ≥5 分钟实测 |
| 睡眠粒度 | 粗 | 手表固件决定（约 9 分钟一点），软件无法加密 |

## 7. 扩展点

- **接入下游程序**：读 `data/inbox/*.db` → 转 HealthEvent → 下游的 HTTP/MQTT 通道
- **接 Grafana / 网页**：`report.json` 已经是稳定结构，可直接喂图表
- **补心率**：改 Gadgetbridge 源码（见 `protocol.md` 第 6 节）


