# PsychEval固定版本源码核查

本文重写既有研究记录；未在本次重跑外部项目或重新测量原论文实验。

## 来源事实（历史核查）

核查版本为e04df535749e5bca76fcc45d9a85f3f46a082d91。该快照公开病例、对话、评测与资源，不能仅靠数据结构还原完整生成器或训练流程。案例包括client_info、global_plan、sessions及纵向档案；评测管理器规范角色并移除咨询师think块后交各量表。

## 当前实现

本仓库编写独立API模拟运行时，病例保留来源，咨询师与来访者生成不同于上游离线评测。模型角色、权限和整体督导时序见 [领域边界](../agents/domain.md)。

## 未实施建议与验证边界

来源快照与现行上游可能不同。未来比较需固定提交与资源指纹，分开“数据形态”“公开可运行代码”“论文实验”；不能把eval客户端当成生成器。

## 原记录来源链接

- [来源 1](https://github.com/ECNU-ICALK/PsychEval/blob/e04df535749e5bca76fcc45d9a85f3f46a082d91/README.md#L44-L71)
- [来源 2](https://github.com/ECNU-ICALK/PsychEval/blob/e04df535749e5bca76fcc45d9a85f3f46a082d91/README.md#L8-L18)
- [来源 3](https://github.com/ECNU-ICALK/PsychEval/blob/e04df535749e5bca76fcc45d9a85f3f46a082d91/README.md#L8-L19)
- [来源 4](https://github.com/ECNU-ICALK/PsychEval/blob/e04df535749e5bca76fcc45d9a85f3f46a082d91/data/cbt/1.json)
- [来源 5](https://github.com/ECNU-ICALK/PsychEval/blob/e04df535749e5bca76fcc45d9a85f3f46a082d91/eval/manager/evaluation_multi.py#L458-L486)
- [来源 6](https://github.com/ECNU-ICALK/PsychEval/blob/e04df535749e5bca76fcc45d9a85f3f46a082d91/eval/manager/evaluation_multi.py#L488-L518)
- [来源 7](https://github.com/ECNU-ICALK/PsychEval/blob/e04df535749e5bca76fcc45d9a85f3f46a082d91/eval/manager/evaluation_multi.py#L620-L670)
- [来源 8](https://github.com/ECNU-ICALK/PsychEval/blob/e04df535749e5bca76fcc45d9a85f3f46a082d91/eval/methods/client/scl_90.py#L24-L64)
- [来源 9](https://github.com/ECNU-ICALK/PsychEval/blob/e04df535749e5bca76fcc45d9a85f3f46a082d91/eval/methods/counselor/wai.py#L26-L68)
- [来源 10](https://github.com/ECNU-ICALK/PsychEval/blob/e04df535749e5bca76fcc45d9a85f3f46a082d91/eval/prompts_cn/wai/wai.txt#L1-L14)
- [来源 11](https://github.com/ECNU-ICALK/PsychEval/blob/e04df535749e5bca76fcc45d9a85f3f46a082d91/eval/utils/gpt5_chat_client.py#L29-L75)
- [来源 12](https://github.com/ECNU-ICALK/PsychEval/blob/e04df535749e5bca76fcc45d9a85f3f46a082d91/eval/utils/gpt5_chat_client.py#L92-L142)
- [来源 13](https://github.com/ECNU-ICALK/PsychEval/commit/e04df535749e5bca76fcc45d9a85f3f46a082d91)
