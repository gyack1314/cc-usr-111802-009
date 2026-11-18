# 生态河段指标分析

项目保存生态河段的来源版次，按资料取得时间比较单期指标并给出区域规则判断。
evidence 保存来源，metrics 计算同口径偏离，context 解释当前区域规则，report
保存报告。attribution 把冰川融水、支流实测、取水许可执行、降水年份差异和生态
流量目标对齐到可比期间与河段，分解断流缺口并显式保留无法归因残差；
explanation 登记断流解释版次，已公布解释原样保留，修订版说明归因变化与补水
承诺影响，并拒绝唯一原因表述。样本是合成数据。

Python 3.11 以上，在项目根目录执行（`-I` 隔离模式下需显式指定包路径）：

    python -I -c "import sys; sys.path.insert(0,'.'); import unittest; unittest.main(module=None, argv=['unittest','discover','-s','tests','-v'])"
    python -I -m compileall -q climate_analysis tests
    python -I -c "import sys; sys.path.insert(0,'.'); from climate_analysis.cli import main; sys.argv=['cli','inspect','data/example.json']; main()"
    python -I -c "import sys; sys.path.insert(0,'.'); from climate_analysis.cli import main; sys.argv=['cli','explain','data/scenario.json']; main()"

数据约定见 docs/data-contract.md。

## 归因与解释治理要点

- **可比口径**：metric、region、unit、period 四项一致才进入同河段水量平衡；
  不一致的记录标记“口径不可比”，缺失标记“证据缺失”，均不静默并入。
- **证据状态**：每项组件标注实测支持、模型估计、许可口径或补报实测，并附来源
  sha256；实测变化与已解释变化之差恒等于无法归因残差。
- **版次治理**：已公布解释（含原叙述、依据指纹、结论指纹）不可改写；修订版
  逐条列出取水补报、融水重算等归因变化，评估补水承诺是否受影响，且禁止把
  任何单一变化表述为唯一原因。

Dockerfile 可在 Linux 容器运行：docker build -t climate-analysis-009 .；docker run --rm climate-analysis-009。
