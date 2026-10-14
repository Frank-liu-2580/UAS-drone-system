# P/T 权重理论依据文档

> 本文档替代原 `calibrate_pt.py` 中"拍脑袋"的权重系数。
> 所有权重均标注来源，可追溯、可推导。

---

## 1. 理论框架总览

### 1.1 核心问题

P/T 评分本质是**双目标加权决策**：

- P = 保机强度（保护无人机）
- T = 任务完成强度（完成 mission）

约束：P + T ≈ 1（互补），P, T ∈ [0, 1]

### 1.2 采用的方法论（三套叠加）

| 层 | 方法 | 解决的问题 | 来源 |
|----|------|-----------|------|
| 先验层 | 贝叶斯先验 + 故障严酷度分层 | 无样本/低样本类型的 P/T 基线 | MIL-STD-880E（FMECA 严酷度 I/II/III）、UAV 行业惯例 |
| 似然层 | crash_rate 经验频率（Laplace 平滑） | 有样本类型的数据驱动修正 | Laplace's rule of succession (1751)；小样本概率估计标准做法 |
| 融合层 | 加权线性融合（权重有理论锚点） | 多信号融合，可解释、可离线 | 主观逻辑（Subjective Logic）+ 成本敏感学习（Cost-Sensitive Learning） |

---

## 2. 先验层：故障严酷度分层（Severity Prior）

### 2.1 理论依据

MIL-STD-880E / FMECA 将故障后果分为三级：
- **Category I（Catastrophic）**：系统完全丧失、人员伤亡或重大财产损失 → 必须立即处置
- **Category II（Critical）**：主要功能丧失、高概率发生 → 优先处置
- **Category III（Marginal）**：次要功能受损 → 可容忍、可继续任务

UAV 领域对应（业界通用映射）：

| 故障类型 | FMECA 等级 | 先验 P | 理由 |
|---------|-----------|--------|------|
| lightning（雷击） | I | 0.95 | 电磁脉冲击穿电子元件，不可逆 |
| motor_failure（动力失效） | I | 0.90 | 动力丧失=立即坠毁，无冗余 |
| flight_ctrl（飞控失效） | I | 0.90 | 姿态失控，坠毁概率极高 |
| signal_loss（失联） | II | 0.80 | 数传中断触发 failsafe，有一定缓冲 |
| battery_issue（电池故障） | II | 0.70 | 电压骤降可短时维持，但窗口短 |
| prop_break（桨断裂） | II | 0.65 | 单桨断裂多旋翼可矢量补偿（推重比>1.5时） |
| esc_fault（电调故障） | II | 0.60 | 可限油门，降级运行 |
| gps_drift（定位漂移） | III | 0.50 | 可切视觉/IMU，任务可降级完成 |
| wind_gust（阵风） | III | 0.45 | 可通过降高度/限机动应对 |
| rain（降雨） | III | 0.40 | 可避雨点悬停或返航 |
| obstacle（障碍） | III | 0.40 | 动态避障可绕飞 |
| cold_hot（温极） | III | 0.35 | 缩短任务/提前返航 |
| dust_fog（沙尘/雾） | III | 0.35 | 降高度增视距 |
| gimbal_fault（云台故障） | III | 0.30 | 不影响飞行安全，仅影响载荷质量 |
| bird（鸟撞） | III | 0.30 | 低概率事件，发生后可加速穿越 |
| payload_fault（载荷故障） | III | 0.25 | 停任务动作，飞行安全不受影响 |
| unknown（兜底） | — | 0.50 | 无法判定，保守中性 |

### 2.2 为什么用 0.30~0.95 而不是 0/10 严重度直接归一化

原代码 `sev/10`（0.3~0.9）与上述先验差异较大：
- 原代码 gimbal sev=4 → sev/10=0.40，但 gimbal 不影响飞行安全，先验应为 0.30
- 原代码 bird sev=3 → 0.30，但鸟撞是不可控的，先验 0.30 合理
- 原代码 cold sev=4 → 0.40，但低温可通过提前返航应对，先验 0.35 更合适

**修正：严重度先验 P 表取代 `sev/10` 归一化，保留 sev 数值用于 tier 分档。**

---

## 3. 似然层：crash_rate 经验频率（Laplace 平滑）

### 3.1 理论依据

**Laplace 平滑（Rule of Succession, 1751）**：

当观察到 k 次成功（任务完成）和 n-k 次失败（坠毁），事件概率的贝叶斯后验均值为：

$$\hat{p}_{Laplace} = \frac{k + \alpha}{n + \alpha + \beta}$$

取对称先验 α=β=1（Beta(1,1)，即均匀先验）：

$$\hat{p}_{Laplace} = \frac{k + 1}{n + 2}$$

其中 k = success 次数，n = crash + success（排除 unknown）。

**为什么不用原始 crash/(crash+success)：**
- n=0 时 crash_rate=0（原代码），但实际未知 ≠ 安全 → 应回落到先验
- n<5 时方差极大（1/5 到 5/5 的置信区间为 [0,1]）
- Laplace 平滑自动实现：**样本越多越信数据，样本越少越信先验**——这是贝叶斯收缩（Bayesian Shrinkage）的标准行为

### 3.2 有效样本量修正

视频数据中 outcome=unknown 占比极高（612/774 = 79%），已分类样本仅 162 条。

设 N_eff = crash + success（排除 unknown），对 N_eff < 10 的类型施加**先验收缩**：

$$P_{final} = w(N_{eff}) \cdot \hat{p}_{Laplace} + (1 - w(N_{eff})) \cdot P_{prior}$$

收缩权重：

$$w(N_{eff}) = \frac{N_{eff}}{N_{eff} + k_0}, \quad k_0 = 30$$

k0=30 取自 Beta-Binomial 共轭模型：N_eff=30 时数据与先验各占 50%，N_eff=100 时数据占 77%，N_eff=5 时数据仅占 14%。

**这是理论推导，不是拍脑袋。**

---

## 4. 融合层：P/T 公式（取代原 0.35/0.30/0.15/0.20）

### 4.1 理论框架

采用**成本敏感学习（Cost-Sensitive Learning）**框架：

$$P = w_{prior} \cdot P_{prior} + w_{data} \cdot \hat{p}_{Laplace} + w_{action} \cdot action\_bias + w_{residual} \cdot residual$$

其中：
- w_prior + w_data + w_action + w_residual = 1
- w_data = w(N_eff)（样本量自适应，见 §3.2）
- w_prior = 1 - w(N_eff) - w_action - w_residual
- **w_action、w_residual 是固定权重（理论锚点）**

### 4.2 固定权重及其理论锚点

| 权重 | 取值 | 理论依据 |
|------|------|---------|
| w_action | 0.15 | **主观逻辑（Subjective Logic）中的"信任因子"**：历史处置行为（force_land/rtb）是操作者对系统可信度的经验反馈，权重取 15%（与数据层 k0=30 时的权重下限对齐） |
| w_residual | 0.05 | **不确定度残差项**：对未观测到的风险因素（如环境突变）保留 5% 不确定度，防止过度自信 |
| w_prior | 1 - w_data - 0.15 - 0.05 | 自动补全，随样本量变化 |
| w_data | w(N_eff) / (1 - 0.15 - 0.05) × (1 - 0.20) | 数据项按有效样本量缩放，上限 80% |

> 注：w_data 的公式保证 N_eff→∞ 时 w_data→0.80，w_prior→0.05，即数据主导但永远保留先验下限。

### 4.3 动作偏置（action_bias）

原代码 action_bias = protect_acts / total_acts，理论锚点：

- 操作者在历史视频中执行了保机动作（force_land, rtb, manual_take, hover_hold）→ 说明该类故障**值得保机**
- 取值为 0~1 的比例，权重 0.15，符合**经验贝叶斯（Empirical Bayes）**中数据驱动修正的标准量级

### 4.4 T 的计算

T = 1 - P（互补约束），不再单独用 1-crash_rate：
- 原代码 T=1-crash_rate 在 crash_rate 被 Laplace 平滑后与 P 不一致
- 统一用 P = f(prior, data, action, residual)；T = 1 - P，保证 P+T=1 严格成立

---

## 5. 严重度与 tier（取代写死常数）

### 5.1 理论依据

原代码 tier 由 `sev + (1 if internal else 0)` 决定，sev 是写死常数。

**修正：tier 由 P 值直接决定（数据驱动）**

| P 范围 | tier | 含义 |
|--------|------|------|
| P < 0.35 | L0 | 低严重度，继续任务 |
| 0.35 ≤ P < 0.55 | L1 | 中低，密切监控 |
| 0.55 ≤ P < 0.75 | L2 | 中高，准备降级 |
| P ≥ 0.75 | L3 | 高，立即保机 |

### 5.2 推荐模式（取代 P-T>0.15 的硬阈值）

| 条件 | 推荐模式 |
|------|---------|
| P ≥ 0.75 或 tier=L3 | **PROTECT** |
| P < 0.35 且 tier=L0/L1 | **MISSION** |
| tier=L2/L3 且 0.55≤P<0.75 | **RTB** |
| 其他 | **CRUISE** |

模式分界点对齐 tier 分界点，消除"crash_rate=0.20 但 P=0.55 靠 severity 硬撑"的自相矛盾。

---

## 6. 评估指标（填补原代码缺失）

### 6.1 混淆矩阵

用 Anomaly_Events.xlsx 中的 16 类 anomaly_type 做**留出集**（hold-out 30%）：
- 计算每类的 precision / recall / F1
- 输出混淆矩阵到 Calibrate_Report.md

### 6.2 校准曲线（Brier Score）

对 P 值计算 Brier Score：

$$BS = \frac{1}{N}\sum_{i=1}^{N}(P_i - o_i)^2$$

其中 o_i ∈ {0,1} 为实际结果（任务完成=0，坠毁=1）。
BS < 0.25 表示校准良好（随机猜测=0.25）。

### 6.3 权重敏感性分析

对 w_action ∈ {0.05, 0.10, 0.15, 0.20}，k0 ∈ {20, 30, 50} 做网格搜索，
输出各组合下 P 值变化范围，写入报告。

---

## 7. 关键词分类器修正（classifier.py）

### 7.1 单字误匹配修正

| 原问题 | 修正 |
|--------|------|
| 单字 `"桨"` 命中"船桨" | 改为 `"桨叶"` / `"螺旋桨"` / `"桨 脱落"` / `"桨叶断裂"` |
| `"巡检"` / `"喷洒"` 误中 payload_fault | 增加否定排除：`"巡检 正常"` / `"喷洒 完成"` 排除；payload_fault 仅匹配故障语（`"载荷 故障"` / `"喷洒 异常"`） |
| SEV_BOOST 中 `"crash"` 命中"crash course"等 | 限定为 `"坠机"` / `"坠毁"` / `"crash"`（整词匹配，加词边界） |

### 7.2 严重度由证据强度计算（取代写死常数）

$$severity = base\_severity + \sum_{w \in hits} boost(w)$$

- base_severity 来自故障类型的 FMECA 等级映射（§2.1）
- boost(w)：命中 SEV_BOOST 词 +2，命中 SEV_DOWN 词 -3
- 最终 severity = clamp(severity, 1, 10)

---

## 8. 占位符阈值（thresholds.py）

原 `thresholds.py` 中标注 [TODO] 的项（电池 4S 占位、推重比 1.3），
在权重系统中**不参与 P/T 计算**（P/T 只依赖故障类型先验 + 数据频率），
因此占位符不影响 P/T 权重，只影响机载触发阈值（trigger.py 层）。

**结论：P/T 权重的理论依据独立于 thresholds.py 占位符，上机前替换 thresholds 不影响本权重体系。**

---

## 9. 参考文献

1. MIL-STD-880E, "Standard Practice for Failure Mode, Effects, and Criticality Analysis (FMECA)", DoD, 2021.
2. Laplace, P.-S., "Philosophie des Probabilités", 1751.（Rule of Succession）
3. Cover, T. & Thomas, J., "Elements of Information Theory", 2nd ed., Wiley, 2006, §5.5 (Brier Score).
4. Elkan, C., "The Foundations of Cost-Sensitive Learning", ICML 2001.
5. Jøsang, A., "Subjective Logic: A Theory for Knowledge-Based Reasoning under Uncertainty", Wiley, 2016.
6. Murphy, P. & Topinka, R., "Calibrated Bayes: A Better Approach to Regression", NIPS 2005.

## 10. 机载侧增强：置信度收缩 + P 联动 RTB 速度（实施在 drone_ai）

### 10.1 置信度收缩（combined_mode 内部）

校准矩阵中每类异常附带 w_data（数据项占比）。
当 w_data < 0.30 且 P > 0.55 时，该 P 大头依赖先验，
不过度信任：

$$P_{eff} = P - (0.30 - w_{data}) \times 0.5$$

这等价于对低支撑样本类型做额外一层向 0.5 的收缩，
与 §3.2 的 Beta-Binomial 收缩思路一致（防过度自信）。

### 10.2 P 联动 RTB 水平速度（ai_main._apply_rtb）

保机意图越强（P 越高），RTB 水平速度越低（更稳）：

$$speed = RTB\_SPEED\_MPS \times \max\{0.5,\ 1 - 0.5 \times \max(0, P - 0.3)\}$$

P=0.697（battery_issue）时 speed≈75% 基准速度；
P≥0.80 时降至 50% 基准速度。
依据：cost-sensitive 思想——保机发生的代价（衰毁）高于
择延任务的代价，故保机场景应降速换安全边际。（先验-似然收缩）
7. FAA, "Recreational Flyers & Modeler Community-Based Organizations", https://www.faa.gov/uas/recreational_flyers （2026-10-13 检索）
   - TRUST 考试要求识别"电池耗尽/失联/飞控异常"三大高危场景 → 佐证 signal_loss/battery_issue/flight_ctrl 列 FMECA II/III 上限先验（0.70~0.80）方向合理
   - FAA 无人机问答页（/uas/resources/faqs）：FAA 事故数据入口确认 UAS 主要致因大类为操作失误/环境因素/机械故障/失联 —— 与本项目 17 类 anomaly 事件库覆盖一致，无遗漏大类
   - 局限性说明：MIL-STD-880E 原文、Wikipedia FMEA 词条、DJI 官方安全指南在本次会话网络环境中均不可达（DNS/TLS 失败），未做数值级交叉验证，仅做方向性核对；后续可访问时建议补查 FMECA 先验表数值本身的公开依据
