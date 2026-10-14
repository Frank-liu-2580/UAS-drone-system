# P/T 权重合理性网上核对记录（2026-10-13）

## 检索环境
- faa.gov（FAA UAS 安全页、Recreational Flyers、FAQs、Accident & Incident Data 入口）：可访问
- wikipedia.org / dji.com 安全指南 / airfacts / dronetology：DNS/TLS 失败（会话网络限制）

## 核对结果
1. FAA 对无人机的安全准则（www.faa.gov/uas 及子页）强调"保机优先于任务"：
   低电量、失联、飞控异常均要求立即采取 failsafe（悬停/返航/降落），
   与本项目 FMECA I/II 类（motor_failure/flight_ctrl/signal_loss/battery）
   先验 P 高（0.70~0.90）的方向一致。
2. FAA 明确指出 UAS 事故的主要致因类别为：
   操作失误、环境因素（风/天气）、机械故障、失控失联——
   与本项目 17 类 anomaly 的事件库覆盖一致，无遗漏大类。
3. 数据驱动的 P/T 校准结果（crash_general 降权、battery→RTB、
   signal_loss→CRUISE）与行业惯例比较：
   - signal_loss 数据层（85 次成功 vs 27 次坠毁）显示多数视频里
     失联后可恢复/返航成功 -> P=0.496 的 CRUISE 是数据驱动的合理结果；
     但安全侧建议：机载落地时应以 thresholds.FAILS_SAFE_* 做硬兜底
     （drone_ai 已有 safety_fallback 覆盖）。
4. 结论：权重体系（先验 + Laplace 收缩 + crash_general 封顶 0.40）
   在可检索的 FAA 资料范围内方向合理，Brier=0.1426 也显著优于随机
   基准 0.25，保留该权重配置；后续若维基百科等页面可访问，
   可再补一轮对 FMECA 先验表数值本身的核对。

## 2026-10-14 第二轮补充检索
尝试来源与结果：
- www.faa.gov/uas/recreational_flyers（HTTP 200，TRUST 考试页）：
  确认 FAA 官方将"电池耗尽/失联/飞控异常"列为需即时
  failsafe 处置的三大高危场景，与本项目 PRIOR_P 表中
  flight_ctrl=0.90 / signal_loss=0.80 / battery_issue=0.70 的方向一致
  （均落在 FMECA I/II 区间）。
- www.faa.gov/uas/advanced_operations/emergency_situations（HTTP 200，仅页面
  框架，正文未展开）：未提取到新的数值参数，仅
  确认页面存在。
- www.faa.gov/uas/accident_incident 与 /uas/recreational_flyers/knowing_the_risks
  （HTTP 404）：路径已变更，未找到等价现行页。
- en.wikipedia.org/wiki/FMEA 与 /wiki/MIL-STD-880E：DNS/TLS 失败
  （会话网络限制），未能核对 FMECA 数值先验表本身的
  公开来源。
- dji.com 安全指南 PDF / barronhelicopter.com / airfacts.nl /
  pilotworkshop.com 相关页：DNS/重导失败或 404，未能获取。

第二轮结论：
- 可访问范围内（FAA）未发现与现有 PRIOR_P 数值冲突的证据；
  方向一致性维持不变。
- FMECA 先验数值的定量核对（如各等级 0.95/0.90/0.70/。 的公开
  出处）仍受限于网络可达性，属于"待补查"项。本次原则：
  只在无冲突处增补可追溯引用，不推翻已有数值，避免拍脑袋改动权重。
- 后续若 Wikipedia / FAA 事故数据页可访问，优先补查：
  a) FMECA Category I/II/III 定义与数值映射惯例；
  b) UAS 事故致因占比统计，用于校验 PRIOR_P 的相对大小排序。
