# `assets/`

本目录保存两类随仓库分发的静态研究资产，但它们在当前运行时中的地位不同。

| 路径 | 当前用途 | 加载入口 |
|---|---|---|
| `skills/sect/` | 五流派、三阶段的元技能与原子技能树；仿真必需 | `src/psychsandbox/skills/registry.py` |
| `profiles/` | Psych-new 的 sample/rft 人物画像副本；保留作来源对照 | 当前仿真不从此目录索引病例 |

`skills/sect/<bt|cbt|het|pdt|pmt>/<stage1|stage2|stage3>/` 下各有 `meta_skills.json` 和 `micro_skills.json`。运行时按流派、阶段、审核状态硬过滤，再按咨询师模型选择的末级元技能 ID 精确展开原子技能；只有展开数量超过配置阈值时才调用独立 embedding 接口筛选，再由模型核对适用依据。默认阈值 24、保留 12 项，不使用 BM25，也不逐层选择。元技能筛选提示与原子技能完整路径在运行时派生，不修改原始技能树、不读取旧 `.pt` 缓存，不为原子技能新增 120 字原文摘要。详见 [技能选择说明](../docs/SKILL_SELECTION.md)。

当前病例和实际人物画像统一由 `data/<therapy>/*.json` 提供。`assets/profiles` 的具体边界见 [`profiles/README.md`](profiles/README.md)。
