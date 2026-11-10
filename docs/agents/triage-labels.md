# 分流状态与远端标签兼容

以下映射来自既有远端核查记录；2026-11-10 的文档同步没有刷新 GitHub 标签。执行写入前须在本仓库运行 `gh label list --limit 100`，不能把此表当成当前远端保证。

| 工作流状态 | 兼容标签 | 评论需说明 |
|---|---|---|
| needs-triage | question | 尚待分类 |
| needs-info | question | 缺失信息与等待对象 |
| ready-for-agent | help wanted | 已可实施的规格 |
| ready-for-human | enhancement | 需要维护者或领域专家决定 |
| wontfix | wontfix | 不实施的依据 |

既有标准标签记录还包括bug、documentation、duplicate、good first issue、invalid。多个状态共用question时，最近评论表达精确状态；远端新增专用状态标签后先更新映射。操作边界见 [Issue约定](issue-tracker.md)。

表中的工作流状态是本地语义，兼容标签只表示远端存在时可使用的近似映射；本地文档更新不会创建标签或改变 Issue 状态。遇到标签缺失时先保留明确的状态说明，再在用户授权范围内处理，不能自行假定有新增标签权限。
