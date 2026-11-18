# 生态河段数据约定

## 记录类型

observation、reference、rule 三种记录分别表示观测、参照和区域规则，沿用单期
指标流程（metric、region、unit 同口径比较）。跨期跨河段归因新增四种记录：

| kind | 含义 | 关键 payload 字段 | 证据状态 |
| --- | --- | --- | --- |
| glacier_melt | 冰川融水（可附质量平衡） | value、method、mass_balance_metres_we | 模型估计/实测支持 |
| tributary_flow | 支流控制站实测来水 | value、gauge | 实测支持 |
| abstraction | 取水许可与实际取水 | permitted、actual、compliance | 实测支持/补报实测/许可口径（actual 缺报时降级） |
| precipitation_runoff | 降水年份对应径流 | value、year_type、anomaly_ratio | 实测支持 |

另有 glacier_mass_balance 记录（单位“米水当量”），只作冰川退缩的背景佐证，
不进入以“万立方米”为单位的水量平衡。

## 可比口径

metric、region、unit、period 四项共同定义可比口径。参照记录固定使用
`period="REF"`。期间或单位不一致的记录不会被静默并入平衡，而是在归因结果中
标记为“口径不可比”，对应组件贡献为空、来源为空，计入无法归因部分；缺少任何
同口径记录时标记“证据缺失”。

## 版次与补报

同一 record_id 的新 revision 表示补报或重算（如取水实际值迟报、融水模型重算），
旧 revision 不可变保留。known_at 决定某一时点可见的最新版次，因此已公布解释
的依据可按公布时点复现。explanations 表单独保存断流解释版次：原叙述、依据
来源指纹、结论指纹原样留存，修订版通过 supersedes 链接前版，并记录逐条归因
变化与补水承诺评估；唯一原因类叙述在登记处直接拒绝。
