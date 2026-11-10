# GitHub Issue操作约定

需求与规格使用本仓库GitHub Issues；在当前检出目录执行gh，使origin选择正确仓库。PR用于代码审查，不自动替代需求记录。

2026-11-10 文档同步仅维护本地约定，未读取或修改远端 Issue、PR 或标签。执行任务时应从当前检出目录核对 `git remote -v`，不能沿用历史仓库地址或把本地分支名当作远端状态。

## 读取

`gh issue view <编号> --comments`查看上下文，`gh issue list --state open --json number,title,body,labels,assignees`列出需求。编号含义不明时先尝试gh pr view，再检查issue。添加标签前读取gh label list --limit 100。

## 写入

只有用户任务授权相关写操作时才执行。多行正文写入本次产物目录中的文件，通过--body-file传给gh issue create/comment，避免shell转义改变内容。编辑标签使用gh issue edit --add-label，关闭须记录理由。此约定不授权主动发送消息或自动新建issue。

正文草稿放在 `runs/runtime/<本次调用目录>/`，保留实际换行；可本地准备和核对后再按已授权范围执行。单纯更新 Markdown 不包含发布、评论、关闭或新建 Issue 的授权；凭据和私有运行内容不得因引用日志而进入正文。

工作流状态标签先读 [兼容映射](triage-labels.md)；以实际远端标签为准，精细状态由issue评论补充。当前文档重写未执行GitHub操作。
