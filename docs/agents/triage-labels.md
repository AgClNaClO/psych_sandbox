# 分流状态与远端标签兼容

以下映射来自既有远端核查记录，本次没有刷新GitHub标签。执行写入前须重新列出实际标签，不能把此表当成当前远端保证。

| 工作流状态 | 兼容标签 | 评论需说明 |
|---|---|---|
| needs-triage | question | 尚待分类 |
| needs-info | question | 缺失信息与等待对象 |
| ready-for-agent | help wanted | 已可实施的规格 |
| ready-for-human | enhancement | 需要维护者或领域专家决定 |
| wontfix | wontfix | 不实施的依据 |

既有标准标签记录还包括bug、documentation、duplicate、good first issue、invalid。多个状态共用question时，最近评论表达精确状态；远端新增专用状态标签后先更新映射。操作边界见 [Issue约定](issue-tracker.md)。
