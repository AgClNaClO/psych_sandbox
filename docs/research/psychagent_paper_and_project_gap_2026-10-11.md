# PsychAgent方法与沙盒能力差距

本文重写既有研究记录；未在本次重跑外部项目或重新测量原论文实验。

## 来源事实（历史核查）

2026-10-11核查arXiv 2604.00931v3。论文由MAPE记忆规划、SEE技能演化、RIE强化内化组成；会谈best-of-N只是RIE的一部分，参数微调不能由选优代码推定已完成。原论文结果及消融数值保留在历史表中，不是本仓库分数。

## 当前实现

沙盒具备公开记忆、会后自评/计划、技能目录、可选整场选优、工作台审核版本及受控SFT/DPO导出。下一计划来自自评和纵向信号；独立督导不驱动规划。具备导出不等于执行了训练或验证论文收益。

## 未实施建议与验证边界

后续分别验证记忆规划、专家审核技能演化和参数训练；先建立基线、数据切分、盲评、安全回退和可比配置，再讨论是否达到论文效果。

## 历史数据与对照表

以下表格保留原核查口径，包括当时的本地实现；与上面的当前实现分开阅读。

| 系统 | Counselor Shared | Counselor Specific | Client Shared | Client Specific |
|---|---:|---:|---:|---:|
| PsychAgent-Qwen3-8B | 7.35 | 7.78 | 5.94 | 8.19 |
| PsychAgent-Qwen3-32B | **7.32** | **7.91** | **5.92** | **8.24** |

| 配置 | Counselor Shared | Counselor Specific | Client Shared | Client Specific |
|---|---:|---:|---:|---:|
| PsychAgent | 7.32 | 7.91 | 5.92 | 8.24 |
| 去掉 MAPE | 7.07 | 7.66 | 5.86 | 8.03 |
| 去掉 SEE | 7.02 | 7.52 | 5.61 | 7.90 |
| 去掉 RIE | 7.05 | 7.67 | 5.67 | 7.89 |

## 原记录来源链接

- [来源 1](https://arxiv.org/abs/2604.00931v3)
- [来源 2](https://arxiv.org/html/2604.00931v3)
- [来源 3](https://github.com/ECNU-ICALK/PsychAgent)
- [来源 4](https://github.com/ECNU-ICALK/PsychAgent/commit/469f45ef468b968b3fccd1936d7e6a0a574e4c5c)
