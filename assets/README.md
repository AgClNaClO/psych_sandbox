# `assets/`

本目录保存两类随仓库分发的静态研究资产，但它们在当前运行时中的地位不同。

| 路径 | 当前用途 | 加载入口 |
|---|---|---|
| `skills/sect/` | 五流派、三阶段的元技能与原子技能树；仿真必需 | `src/psychsandbox/skills/registry.py` |
| `profiles/` | Psych-new 的 sample/rft 人物画像副本；保留作来源对照 | 当前仿真不从此目录索引病例 |

`skills/sect/<bt|cbt|het|pdt|pmt>/<stage1|stage2|stage3>/` 下各有
`meta_skills.json` 和 `micro_skills.json`。运行时按流派、阶段、审核状态硬过滤，再按咨询师模型
选择的元技能 ID 返回全部原子技能；不进行 BM25、向量检索或相关性排序。

当前病例和实际人物画像统一由 `data/<therapy>/*.json` 提供。`assets/profiles` 的具体边界见
[`profiles/README.md`](profiles/README.md)。
