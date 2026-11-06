# 科研工作台前端

React、TypeScript与Vite构建本地实验界面。主要流程为自动仿真、人工疗程、技能审核、实验比较与导出；API和Worker说明见 [工作台文档](../docs/workbench/README.md)。

```powershell
npm --prefix frontend ci
npm --prefix frontend run dev
npm --prefix frontend test
npm --prefix frontend run lint
npm --prefix frontend run build
```

开发服务代理到本地后端；生产静态包输出位置由vite.config.ts定义，由FastAPI托管。修改界面后必须通过测试、lint和含TypeScript检查的build。

请求携带服务端会谈版本和稳定操作ID；409冲突先同步权威版本，不为重试换一个ID。SSE使用真实任务通道和seq重放；切换案例或会谈时丢弃迟到请求。分数缺失显示未知，0显示0；勿用界面摘要推断临床结论。密钥只留后端环境，不写入前端资源。

自动实验台将配置、会谈回放和分析督导分栏展示；同一轮按咨询师发言、来访者回答的轨迹顺序回放，咨询师在左、来访者在右。会谈导航可横向滚动，日志、计划和评估摘要可折叠；窄屏通过「实验配置」「分析与督导」打开侧栏，按 Esc 可关闭。配置与历史列表分别滚动，启动按钮保持可见。回放顺序及缺失回答由前端回归测试覆盖。

数值框保留编辑中的空值和 0，提交时由表单检查必填、整数与范围。失败或已停止的历史运行显示「从会谈边界续跑」及恢复位置；续跑使用原运行总会谈数和配置，与左侧新实验草稿独立。
