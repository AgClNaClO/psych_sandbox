# 人格与情绪动力学的研究设计

本文重写既有研究记录；未在本次重跑外部项目或重新测量原论文实验。

## 来源事实（历史核查）

2026-10-01提出将事实、模拟参数、时变状态和表达分离，参考EMA事件评价、情绪基线/惯性/恢复及BFI-2测量结构。工程基线x_next=project(mu+R(dt,theta)*(x-mu)+B(theta)*appraisal+noise)是建议，不是论文原式或临床定律。

## 当前实现

现已有私有ClientSimulationConfig、有来源互动先验、反应/行为规划和独立情绪评价；旧personality字段仍不自动进入模型。配置不确定度可令调节为零，发言器不接收完整私有状态解释。详见 [来访者模拟](../CLIENT_SIMULATION.md)。

## 未实施建议与验证边界

完整时间尺度动力学、显式会谈间隔和人格干预泛化仍需设计。优先人格开关×动力学开关的2×2消融、固定刺激配对、分层五流派及专家盲评；不把悲伤减少、合作或披露增加等同治疗进展。

## 原记录来源链接

- [来源 1](https://escholarship.org/uc/item/16x6n05t)
- [来源 2](https://www.ppw.kuleuven.be/okp/_pdf/Kuppens2010FCAFI.pdf)
