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
