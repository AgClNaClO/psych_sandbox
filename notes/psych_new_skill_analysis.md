# Psych-new 技能树、检索与提示词源码调查

调查日期：2026-08-27。调查范围仅为 D:\a华东师范\2项目\1实践\Psych-new；读取时 HEAD 为 469f45ef468b968b3fccd1936d7e6a0a574e4c5c，结论依据当前磁盘源码及资源，而非仅依据提交内容。未调查 psych_sandbox 实现，未进行两项目比较。

**验证边界：**未启动 backend/sample，未调用任何模型或 embedding API，未导入项目入口，未修改生产代码。进行了源码调用链追踪、15 组 JSON/.pt 数据只读核查，以及抽取原始方法的离线控制流验证。本文所说“实际生效”指当前入口有可达、明确的调用与数据传递，不等于已经观察到线上某次会话成功检索或模型遵守了指令。唯一写入文件为本报告。

## 一、先给主要结论

1. **资源是真正多级的 meta 树，不是固定“meta→micro”两层。**meta 文件中的 parent_ids 是“从根到自身”的完整路径；leaf 是“meta 文件内部不再有 meta 后代的节点”，并不是 micro 技能。micro 自己另存一份，其路径在 leaf 路径后追加自身 ID。当前 15 组库的 meta 深度最高 7，micro 路径长度最高 8。[src/sample/skill_manager.py:387](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:387) [src/sample/skill_manager.py:346](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:346) [assets/skills/sect/cbt/stage1/meta_skills.json:2](D:/a华东师范/2项目/1实践/Psych-new/assets/skills/sect/cbt/stage1/meta_skills.json:2) [assets/skills/sect/cbt/stage1/micro_skills.json:2](D:/a华东师范/2项目/1实践/Psych-new/assets/skills/sect/cbt/stage1/micro_skills.json:2)
2. **运行时真的按流派、阶段分库，再用 leaf 选 micro；但没有从根逐层进行 LLM 决策。**粗筛把全部 meta leaf 扁平化，并移除 parent_ids 后交给 LLM。父层路径仍用于程序的精确归属匹配；父层名称虽然会拼为 meta_skill，两个入口随后只展开 micro_skills，未将该祖先文本交给咨询师。[src/sample/skill_manager.py:127](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:127) [src/sample/skill_manager.py:199](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:199) [src/sample/skill_manager.py:362](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:362) [src/web/backend/psychagent_engine.py:309](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/psychagent_engine.py:309) [src/sample/runner.py:492](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:492)
3. **主链路是“LLM 粗筛→LLM query rewrite→embedding 余弦排序→把 micro 文本放入咨询师 system prompt”。**Web 每次回复都重新粗筛；sample 每次会谈粗筛一次，在开场和每次来访者回应后重做精筛。[src/web/backend/psychagent_engine.py:110](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/psychagent_engine.py:110) [src/sample/runner.py:221](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:221) [src/sample/runner.py:344](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:344) [src/sample/runner.py:385](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:385)
4. **当前主入口不是 ReAct 工具检索。**检索在咨询师生成之前由 Python 固定调用；咨询师没有先发工具请求、接收 Observation 再继续生成的循环。底层 chat 请求不传 tools/tool_choice，输出也没有工具调用执行器。提示词中的 assessment、skill、strategy 是文本输出约定，不是工具协议。[src/sample/backends/openai_api.py:96](D:/a华东师范/2项目/1实践/Psych-new/src/sample/backends/openai_api.py:96) [src/web/backend/psychagent_engine.py:115](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/psychagent_engine.py:115) [src/sample/runner.py:385](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:385) [prompts/psychagent/cbt/counsel/system.jinja2:133](D:/a华东师范/2项目/1实践/Psych-new/prompts/psychagent/cbt/counsel/system.jinja2:133)
5. **默认粗筛 20 个 leaf、精筛 top_k=5、threshold=None。**20 不是经过校验的硬限制；默认不设相似度门槛。7 组库的 leaf 少于 20，而粗筛提示词仍要求恰好 20 个互不重复 ID，存在可直接确认的约束矛盾。[src/sample/skill_manager.py:172](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:172) [src/sample/skill_manager.py:233](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:233) [prompts/psychagent/skill/select_skill/system.txt:8](D:/a华东师范/2项目/1实践/Psych-new/prompts/psychagent/skill/select_skill/system.txt:8) [prompts/psychagent/skill/select_skill/system.txt:37](D:/a华东师范/2项目/1实践/Psych-new/prompts/psychagent/skill/select_skill/system.txt:37)
6. **提示词确实被读取、渲染并发送，但“只能选列表内技能”只在提示词中约束。**代码不校验最终 skill 标签的名称、数量或归属，也不检验自然语言实际是否落实所选技能。无 response 标签时，还会把原始文本当作回复接受。[src/sample/prompt_manager.py:25](D:/a华东师范/2项目/1实践/Psych-new/src/sample/prompt_manager.py:25) [src/web/backend/psychagent_engine.py:126](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/psychagent_engine.py:126) [src/sample/runner.py:326](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:326) [prompts/psychagent/cbt/counsel/system.jinja2:158](D:/a华东师范/2项目/1实践/Psych-new/prompts/psychagent/cbt/counsel/system.jinja2:158) [src/sample/utils.py:13](D:/a华东师范/2项目/1实践/Psych-new/src/sample/utils.py:13) [src/sample/runner.py:575](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:575)

## 二、真实入口与执行顺序

### 2.1 Web 后端

根启动脚本进入 src/web 并执行 uvicorn main:app；默认配置路径来自 PSYCHAGENT_WEB_BASELINE_CONFIG 和 PSYCHAGENT_WEB_RUNTIME_CONFIG，未覆盖时分别指向下述 baseline/runtime YAML。Web main 在 startup 调用 PsychAgentWebBackend.startup，再进入 SkillManager.load_library。这里并不是先由咨询师决定是否加载技能库。[run_backend.sh:22](D:/a华东师范/2项目/1实践/Psych-new/run_backend.sh:22) [run_backend.sh:29](D:/a华东师范/2项目/1实践/Psych-new/run_backend.sh:29) [run_backend.sh:47](D:/a华东师范/2项目/1实践/Psych-new/run_backend.sh:47) [src/web/main.py:30](D:/a华东师范/2项目/1实践/Psych-new/src/web/main.py:30) [src/web/main.py:197](D:/a华东师范/2项目/1实践/Psych-new/src/web/main.py:197) [src/web/backend/psychagent_engine.py:73](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/psychagent_engine.py:73)

主要回复入口如下：

~~~text
POST /visits/{visit_id}/messages
  → visit_service.send_visit_message
  → main.call_llm
  → PsychAgentWebBackend.reply_from_visit
      → course.school_id → sect
      → visit.stage_key_snapshot → stage_idx
      → _build_candidate_skills → corse_filter
      → 最后一条 user 文本 + 此前对话 → retrive
      → render("counselor_system", suggested_skills=...)
      → system message + user/assistant 历史
      → _chat_once → backend.chat_text
~~~

路由和传递证据：[src/web/backend/routes/visits.py:45](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/routes/visits.py:45) [src/web/backend/services/visit_service.py:741](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/services/visit_service.py:741) [src/web/main.py:167](D:/a华东师范/2项目/1实践/Psych-new/src/web/main.py:167)；核心链路证据：[src/web/backend/psychagent_engine.py:84](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/psychagent_engine.py:84)。

关键时序：

- **每次调用 reply_from_visit 都执行粗筛**；只有库与 PromptManager 被复用，没有会谈级 candidate_skills 缓存。随后若存在 user_query，执行精筛。传入空 candidate 列表时，retrive 直接返回空结果，不自动重新粗筛。[src/web/backend/psychagent_engine.py:110](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/psychagent_engine.py:110) [src/web/backend/psychagent_engine.py:325](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/psychagent_engine.py:325) [src/sample/skill_manager.py:248](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:248)
- stage 使用当前 visit 的快照；school 映射为 behavioral→bt、cbt→cbt、humanistic→het、psychodynamic→pdt、postmodern→pmt。三阶段映射为 assessment→1、intervention→2、consolidation→3。[src/web/backend/domain.py:85](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/domain.py:85)
- query 是最后一条 user 发言；改写历史映射为 Counselor/Client 的 role/text 列表，不包含 system 消息。正常消息入口刚追加了 user，故 transcript[:-1] 对应排除本轮发言后的历史。[src/web/backend/psychagent_engine.py:111](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/psychagent_engine.py:111) [src/web/backend/psychagent_engine.py:492](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/psychagent_engine.py:492)
- 正常链路失败后会换成上游传入的 fallback_messages 再调用同一模型；它使用代码内的简短咨询师提示词，不读取 public/counselor_system.jinja2。[src/web/backend/psychagent_engine.py:143](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/psychagent_engine.py:143) [src/web/backend/services/visit_service.py:68](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/services/visit_service.py:68) [src/web/backend/services/visit_service.py:741](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/services/visit_service.py:741)

### 2.2 sample 批量入口

~~~text
python -m src.sample / python -m sample
  → sample.main.main → run_from_args
  → 加载 baseline/runtime/dataset
  → _build_runner → PsychAgentRunner
  → run_cases → SkillManager.load_library
  → _run_single_session
      → corse_filter，构建本次会谈候选池
      → _run_dialogue_rollout
          → 开场前 retrive
          → 每次 client 发言后 retrive
          → 更新 counselor_messages[0] 的 system prompt
          → 咨询师 chat
      → summary / profile
      → 下一会谈 stage、focus、history、homework
~~~

入口证据：[src/sample/__main__.py:5](D:/a华东师范/2项目/1实践/Psych-new/src/sample/__main__.py:5) [src/sample/main.py:78](D:/a华东师范/2项目/1实践/Psych-new/src/sample/main.py:78) [src/sample/main.py:124](D:/a华东师范/2项目/1实践/Psych-new/src/sample/main.py:124) [src/sample/runner.py:55](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:55) [src/sample/runner.py:84](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:84)。

与 Web 的关键差异：

| 项目 | Web | sample |
|---|---|---|
| 粗筛频率 | 每次回复一次 | 每个 session 一次 |
| 精筛频率 | 有 user_query 的回复前 | 开场前、此后每次 client 发言后 |
| 候选池 | 每次重新生成 | 会谈内复用，无法在精筛阶段找回本次粗筛排除的分支 |
| 会话目标 stage_title | 实际 stage.label | 写死为字符串“stage” |
| 精筛失败 | 进入简短 baseline prompt fallback | 重试耗尽后返回空技能，继续用流派咨询师模板 |
| 粗筛、改写日志返回值 | 调用者丢弃 | 调用者丢弃；保存 each_turn_system |

证据：[src/web/backend/psychagent_engine.py:105](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/psychagent_engine.py:105) [src/web/backend/psychagent_engine.py:143](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/psychagent_engine.py:143) [src/sample/runner.py:221](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:221) [src/sample/runner.py:320](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:320) [src/sample/runner.py:492](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:492) [src/sample/runner.py:522](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:522) [src/sample/runner.py:287](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:287)。

sample 开场检索的 query 是“这是第N次会话”，还没有真实来访者本轮内容；随后才根据 client 模拟器的发言逐轮检索。[src/sample/runner.py:340](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:340) [src/sample/runner.py:374](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:374)

会谈阶段会影响技能库，并非纯显示字段：sample 首次从“问题概念化与目标设定”开始，summary 的 next_session_stage 更新下一次状态。Web 也将会谈总结的下一阶段映射用于后续会谈。但这不是硬编码的逐阶段顺序推进或技能完成度状态机。[src/sample/runner.py:624](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:624) [src/sample/runner.py:274](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:274) [src/web/backend/psychagent_engine.py:215](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/psychagent_engine.py:215) [src/web/backend/services/visit_service.py:552](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/services/visit_service.py:552)

## 三、技能树怎样分层，哪些层实际有作用

### 3.1 数据结构：parent_ids 包含自身 ID

CBT stage1 中存在以下真实路径：

~~~text
meta 1  评估性会谈                       ["1"]
  meta 2  评估性会谈开始阶段              ["1","2"]
    meta 3  建立咨询关系                  ["1","2","3"]       ← meta leaf
      micro 32 表达理解与共情             ["1","2","3","32"]

meta 1
  meta 5  评估性会谈中间阶段
    meta 6  搜集问题的相关资料
      meta 7  通过咨询会谈搜集资料
        meta 8  收集来访者人口学与基本信息 ← meta leaf
          micro 40 询问来访者的基本人口学信息
            parent_ids = ["1","5","6","7","8","40"]
~~~

各节点原文：[assets/skills/sect/cbt/stage1/meta_skills.json:2](D:/a华东师范/2项目/1实践/Psych-new/assets/skills/sect/cbt/stage1/meta_skills.json:2) [assets/skills/sect/cbt/stage1/meta_skills.json:21](D:/a华东师范/2项目/1实践/Psych-new/assets/skills/sect/cbt/stage1/meta_skills.json:21) [assets/skills/sect/cbt/stage1/meta_skills.json:43](D:/a华东师范/2项目/1实践/Psych-new/assets/skills/sect/cbt/stage1/meta_skills.json:43) [assets/skills/sect/cbt/stage1/meta_skills.json:76](D:/a华东师范/2项目/1实践/Psych-new/assets/skills/sect/cbt/stage1/meta_skills.json:76) [assets/skills/sect/cbt/stage1/micro_skills.json:2](D:/a华东师范/2项目/1实践/Psych-new/assets/skills/sect/cbt/stage1/micro_skills.json:2) [assets/skills/sect/cbt/stage1/micro_skills.json:106](D:/a华东师范/2项目/1实践/Psych-new/assets/skills/sect/cbt/stage1/micro_skills.json:106)。

get_leaf_nodes 只在 meta 字典中检查：如果一个节点 ID 出现在任何其他 meta 节点的 parent_ids 中，则它不是 leaf；它不检查 micro 字典。因此“leaf 元技能”与“微技能”是两个不同概念。[src/sample/skill_manager.py:387](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:387)

find_skill_by_id 的子技能条件是：

~~~python
len(micro_parent_ids) == len(meta.parent_ids) + 1
micro_parent_ids[:-1] == meta.parent_ids
micro_parent_ids[-1] == str(micro.skill_id)
~~~

这是严格的完整路径前缀匹配，**不是选中一个高层节点后递归展开所有后代**。例如选中上例 meta 1，不会自动得到 meta 3 下面的 micro 32。源码：[src/sample/skill_manager.py:362](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:362)。

### 3.2 层级的运行作用

| 层或字段 | 运行作用 | 边界 |
|---|---|---|
| sect 流派 | 选择技能目录和流派提示词 | 没有 LLM 跨流派粗筛 |
| stage1/2/3 | 直接选库分区 | 每次 session/visit 内固定，不由每轮检索改写 |
| meta 中间层 | 定义 ancestry，影响 leaf 判定与路径归属 | 不做逐层 LLM 决策，父层描述不直接进入检索提示词 |
| meta leaf | LLM 粗筛的实际条目 | 输入移除了 parent_ids，只见扁平 leaf 内容 |
| parent_ids | 精确关联 leaf→micro | 无完整树 schema 校验；格式不符会导致匹配不到 |
| meta_skill 祖先名称串 | find_skill_by_id 会构造 | 两个主入口只取 micro_skills，祖先名称串在后续丢弃 |
| micro | 向量排序对象，最后提供给咨询师的具体技能 | 咨询师收到名称、描述、时机、触发线索，不收到完整树 |
| embedding_to_retrive | 与改写 query 的向量算余弦相似度 | 字段名确实拼作 retrive |
| embedding_to_merge | 启动时检查/补齐，候选缺失时也补齐 | 当前选择链路未用它合并技能、排序或执行进化 |

证据：[src/sample/skill_manager.py:127](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:127) [src/sample/skill_manager.py:199](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:199) [src/sample/skill_manager.py:263](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:263) [src/sample/skill_manager.py:346](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:346) [src/sample/skill_manager.py:403](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:403) [src/web/backend/psychagent_engine.py:309](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/psychagent_engine.py:309) [src/sample/runner.py:492](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:492) [prompts/psychagent/cbt/counsel/system.jinja2:174](D:/a华东师范/2项目/1实践/Psych-new/prompts/psychagent/cbt/counsel/system.jinja2:174)。

### 3.3 当前资源的只读核查结果

以下数字由实际 JSON 计算；“最大路径深度”从 meta 根为 1 起算，不把目录中的流派、阶段算入 parent_ids 深度。每行资源链接指向对应完整 meta JSON 的起始行，micro 数量由同目录 micro_skills.json 统计。

| 流派/阶段 | meta 节点 | meta leaf | micro | 最大 meta / micro 路径深度 |
|---|---:|---:|---:|---|
| BT stage1 | 58 | 41 | 390 | 5 / 6 |
| BT stage2 | 95 | 62 | 443 | 7 / 8 |
| BT stage3 | 3 | 2 | 21 | 2 / 3 |
| CBT stage1 | 31 | 22 | 504 | 5 / 6 |
| CBT stage2 | 54 | 40 | 609 | 5 / 6 |
| CBT stage3 | 18 | 11 | 259 | 5 / 6 |
| HET stage1 | 42 | 27 | 285 | 5 / 6 |
| HET stage2 | 81 | 58 | 409 | 6 / 7 |
| HET stage3 | 13 | 8 | 58 | 4 / 5 |
| PDT stage1 | 28 | 18 | 281 | 5 / 6 |
| PDT stage2 | 167 | 112 | 670 | 6 / 7 |
| PDT stage3 | 15 | 10 | 93 | 4 / 5 |
| PMT stage1 | 12 | 8 | 80 | 4 / 5 |
| PMT stage2 | 56 | 44 | 370 | 6 / 7 |
| PMT stage3 | 4 | 1 | 9 | 4 / 5 |

统计来源： BT：[assets/skills/sect/bt/stage1/meta_skills.json:1](D:/a华东师范/2项目/1实践/Psych-new/assets/skills/sect/bt/stage1/meta_skills.json:1) [assets/skills/sect/bt/stage2/meta_skills.json:1](D:/a华东师范/2项目/1实践/Psych-new/assets/skills/sect/bt/stage2/meta_skills.json:1) [assets/skills/sect/bt/stage3/meta_skills.json:1](D:/a华东师范/2项目/1实践/Psych-new/assets/skills/sect/bt/stage3/meta_skills.json:1)； CBT：[assets/skills/sect/cbt/stage1/meta_skills.json:1](D:/a华东师范/2项目/1实践/Psych-new/assets/skills/sect/cbt/stage1/meta_skills.json:1) [assets/skills/sect/cbt/stage2/meta_skills.json:1](D:/a华东师范/2项目/1实践/Psych-new/assets/skills/sect/cbt/stage2/meta_skills.json:1) [assets/skills/sect/cbt/stage3/meta_skills.json:1](D:/a华东师范/2项目/1实践/Psych-new/assets/skills/sect/cbt/stage3/meta_skills.json:1)； HET：[assets/skills/sect/het/stage1/meta_skills.json:1](D:/a华东师范/2项目/1实践/Psych-new/assets/skills/sect/het/stage1/meta_skills.json:1) [assets/skills/sect/het/stage2/meta_skills.json:1](D:/a华东师范/2项目/1实践/Psych-new/assets/skills/sect/het/stage2/meta_skills.json:1) [assets/skills/sect/het/stage3/meta_skills.json:1](D:/a华东师范/2项目/1实践/Psych-new/assets/skills/sect/het/stage3/meta_skills.json:1)； PDT：[assets/skills/sect/pdt/stage1/meta_skills.json:1](D:/a华东师范/2项目/1实践/Psych-new/assets/skills/sect/pdt/stage1/meta_skills.json:1) [assets/skills/sect/pdt/stage2/meta_skills.json:1](D:/a华东师范/2项目/1实践/Psych-new/assets/skills/sect/pdt/stage2/meta_skills.json:1) [assets/skills/sect/pdt/stage3/meta_skills.json:1](D:/a华东师范/2项目/1实践/Psych-new/assets/skills/sect/pdt/stage3/meta_skills.json:1)； PMT：[assets/skills/sect/pmt/stage1/meta_skills.json:1](D:/a华东师范/2项目/1实践/Psych-new/assets/skills/sect/pmt/stage1/meta_skills.json:1) [assets/skills/sect/pmt/stage2/meta_skills.json:1](D:/a华东师范/2项目/1实践/Psych-new/assets/skills/sect/pmt/stage2/meta_skills.json:1) [assets/skills/sect/pmt/stage3/meta_skills.json:1](D:/a华东师范/2项目/1实践/Psych-new/assets/skills/sect/pmt/stage3/meta_skills.json:1)。

合计 **677 个 meta、4481 个 micro**。以当前 get_leaf_nodes 和精确路径条件核查，4481 个 micro 全部可归属到某个 meta leaf，未见空 leaf 子库，也未见 meta 路径引用不存在的 meta ID 或不以自身 ID 结尾的问题。此结果说明当前资源能配合代码的路径约定，不代表加载器本身具备相应校验。

额外只读核查 15 个 micro_skills.pt：使用 zipfile 读取 data.pkl，并用禁止全局类加载和 persistent ID 的受限 Unpickler 读取纯数据，没有执行 torch.load。每组 .pt 与 JSON 的键集及去除两种 embedding 后的条目一致；所有 micro 的两类向量均为非空 1024 维列表。**这不能证明其来源模型一定与当前配置匹配**，文件缺少此项校验。

生产加载优先级是：有 torch 且 .pt 存在，优先 torch.load；否则才读 JSON。加载器不会把 .pt 出错自动变为 JSON 回退。当前只观察到文件内容，不声称目标部署已经安装 torch。[src/sample/skill_manager.py:545](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:545)

## 四、咨询师“选技能”的完整步骤和默认参数

### 4.1 粗筛：LLM 按会谈目标选 leaf 元技能

1. 输入 sect、stage、session_goals，默认 n=20。
2. 取该 stage 的 leaf 字典；leaf 为空直接返回空。
3. 从 leaf 条目移除 parent_ids、两类 embedding。
4. system 提示词渲染 number；user 提示词渲染 session_goals 和 skills_library。
5. 用与咨询师相同的 backend 调用 LLM。
6. 提取返回 JSON 的 skill_id，转成 (sect, str(id))。
7. 若 ids 为空，取 leaf 字典插入顺序前 n 个；随后按路径找 micro。
8. 调用者展开所有组的 micro_skills，得到候选池。没有另一个向量“粗筛”阶段。[src/sample/skill_manager.py:172](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:172) [src/sample/skill_manager.py:333](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:333) [src/web/backend/psychagent_engine.py:309](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/psychagent_engine.py:309) [src/sample/runner.py:492](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:492)

粗筛不是把 n 个 micro 提供给咨询师：它选的是 n 个 leaf，展开后候选 micro 可能有数百个。以 CBT stage1 为例，离线验证空 ID fallback 前 20 个 leaf 会展开成 **458 个 micro**；随后才执行 top_k 精筛。

saved、rerank 两个参数在函数开头被 del；model_kwgs 在 llm_response 中也被 del，不能据此配置重排器或单独的选择模型。[src/sample/skill_manager.py:182](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:182) [src/sample/skill_manager.py:333](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:333)

### 4.2 精筛：先 rewrite，再 embedding，再余弦排序

retrive 的默认参数为 top_n=20、top_k=5、threshold=None：

- candidate_skills is None 时才内部执行 corse_filter；正常两个入口均已传 candidate_skills，因此此处不重复粗筛。
- candidate_skills=[] 则直接返回空，不尝试全库兜底。
- rewrite 输入当前 query、session_goals、diag_hist；输出优先取 response 标签内容。
- 对该文本调用 embedding API。
- 为缺失向量的候选补齐 embedding。
- 逐候选计算 query_embedding 与 embedding_to_retrive 的余弦相似度，降序取前 top_k；只有显式传 threshold 才按阈值过滤。
- 深拷贝结果、附加 similarity、删除两个 embedding 字段。[src/sample/skill_manager.py:233](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:233) [src/sample/skill_manager.py:263](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:263) [src/sample/skill_manager.py:403](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:403)

**精筛不是另一个 LLM reranker**：LLM 用于改写 query；最终候选排序是余弦相似度。也没有选中后递归补齐祖先技能的步骤。[src/sample/skill_manager.py:276](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:276)

候选的检索向量补齐文本为：

~~~text
Trigger:{skill.trigger}
When_to_Use:{skill.when_to_use}
~~~

skill_name、skill_description、parent_ids 等参与的是另一种 embedding_to_merge 的 JSON 输入，当前精筛不使用它。[src/sample/skill_manager.py:97](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:97) [src/sample/skill_manager.py:113](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:113) [src/sample/skill_manager.py:413](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:413)

### 4.3 默认配置及实际消费位置

| 参数 | 默认值/当前默认 YAML | 实际作用 |
|---|---|---|
| psychagent_skill_base_dir | assets/skills/sect | 技能资源根目录 |
| psychagent_skill_sects | all，即 cbt、bt、pdt、het、pmt | 启动加载这五个流派各三个阶段 |
| 粗筛 n / top_n | 20 | Python 函数默认值，入口不覆盖 |
| 精筛 top_k | 5 | Python 函数默认值，入口不覆盖 |
| 精筛 threshold | None | 不设最低相似度 |
| psychagent_embedding_model | BAAI/bge-m3 | query 及补齐向量的 embedding 模型 |
| embedding base URL | https://api.siliconflow.cn/v1 | 配置中的地址；调查未访问 |
| embedding API key env | PSYCHAGENT_EMBEDDING_API_KEY | RuntimeConfig.validate 及 load_library 都要求存在 |
| embedding batch / max retries / sleep | 64 / 16 / 0.5 秒 | 批量补齐及失败重试；sleep 按 attempt 线性增加 |
| psychagent_counselor_system_filename | system.jinja2 | 流派 counsel 子目录的模板文件 |
| psychagent_max_retries | 16 | sample 外层粗筛、检索、回复等重试 |
| psychagent_max_turns | 45 | sample rollout 的咨询师轮次上限 |

证据：[configs/runtime/psychagent_sglang_local.yaml:21](D:/a华东师范/2项目/1实践/Psych-new/configs/runtime/psychagent_sglang_local.yaml:21) [src/sample/core/schemas.py:127](D:/a华东师范/2项目/1实践/Psych-new/src/sample/core/schemas.py:127) [src/sample/core/schemas.py:247](D:/a华东师范/2项目/1实践/Psych-new/src/sample/core/schemas.py:247) [src/sample/skill_manager.py:44](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:44) [src/sample/skill_manager.py:438](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:438) [src/sample/runner.py:374](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:374)。

粗筛和 rewrite 共用咨询师 backend：默认 baseline model=default、temperature=0.9、max_tokens=8196；没有另设选择模型。SkillManager 只传 messages，backend 从初始化 settings 取模型与生成参数。[configs/baselines/psychagent_sglang_local.yaml:3](D:/a华东师范/2项目/1实践/Psych-new/configs/baselines/psychagent_sglang_local.yaml:3) [src/sample/runner.py:77](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:77) [src/web/backend/psychagent_engine.py:58](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/psychagent_engine.py:58) [src/sample/skill_manager.py:333](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:333) [src/sample/backends/openai_api.py:66](D:/a华东师范/2项目/1实践/Psych-new/src/sample/backends/openai_api.py:66)

路径不是依赖 shell 当前目录：技能及检索提示词的相对路径通过 resolve_path 定位到项目根。[src/shared/file_utils.py:15](D:/a华东师范/2项目/1实践/Psych-new/src/shared/file_utils.py:15)

## 五、提示词文件、关键原文及拼接方式

### 5.1 粗筛提示词：确实加载且发送

- system：[prompts/psychagent/skill/select_skill/system.txt:1](D:/a华东师范/2项目/1实践/Psych-new/prompts/psychagent/skill/select_skill/system.txt:1)
- user：[prompts/psychagent/skill/select_skill/user.txt:1](D:/a华东师范/2项目/1实践/Psych-new/prompts/psychagent/skill/select_skill/user.txt:1)
- 加载函数：[src/sample/skill_manager.py:499](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:499)
- 渲染与调用：[src/sample/skill_manager.py:199](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:199)

关键原文：

> 依据【Session目标】，从【元技能库】中筛选 {{number}} 条最相关的元技能。

> 数量为恰好 {{number}} 个；全部互不重复。

返回形状示例：

~~~json
{"skill_id": ["3", "4", "8"]}
~~~

此处示例只说明格式，不表示默认 n=20 时数量满足要求。真实 user 模板仅包含 skills_library 和 session_goals；Jinja 对字典进行文本渲染，并非显式 json.dumps 的严格 JSON 序列化。[prompts/psychagent/skill/select_skill/user.txt:2](D:/a华东师范/2项目/1实践/Psych-new/prompts/psychagent/skill/select_skill/user.txt:2) [src/sample/skill_manager.py:205](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:205)

**两处已核实的问题：**

- system 同时写“恰好 n 个”和“只找到 0–2 个时就返回 0–2 个”；还假定调用方保证 n 不超过可用总数。代码不把 n 截断到 leaf 数量。[prompts/psychagent/skill/select_skill/system.txt:8](D:/a华东师范/2项目/1实践/Psych-new/prompts/psychagent/skill/select_skill/system.txt:8) [prompts/psychagent/skill/select_skill/system.txt:26](D:/a华东师范/2项目/1实践/Psych-new/prompts/psychagent/skill/select_skill/system.txt:26) [prompts/psychagent/skill/select_skill/system.txt:37](D:/a华东师范/2项目/1实践/Psych-new/prompts/psychagent/skill/select_skill/system.txt:37) [src/sample/skill_manager.py:205](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:205)
- system 的安全 SOP 要求扫描“历史会话”，但该次 LLM 调用并未传入 history、diag_hist 或当前 query，只有目标与 leaf 库。会谈目标可能概括风险，但不能据此声称已经逐轮执行历史危机扫描。[prompts/psychagent/skill/select_skill/system.txt:18](D:/a华东师范/2项目/1实践/Psych-new/prompts/psychagent/skill/select_skill/system.txt:18) [prompts/psychagent/skill/select_skill/user.txt:11](D:/a华东师范/2项目/1实践/Psych-new/prompts/psychagent/skill/select_skill/user.txt:11) [src/sample/skill_manager.py:206](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:206)

### 5.2 Query rewrite：确实调用，但“治疗结构”没有真正接入

- system：[prompts/psychagent/skill/rewrite/system.txt:1](D:/a华东师范/2项目/1实践/Psych-new/prompts/psychagent/skill/rewrite/system.txt:1)
- user：[prompts/psychagent/skill/rewrite/user.txt:1](D:/a华东师范/2项目/1实践/Psych-new/prompts/psychagent/skill/rewrite/user.txt:1)
- 调用：[src/sample/skill_manager.py:299](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:299)

system 指令要求将最新发言改写为两部分：

~~~text
Trigger: 第三人称描述本轮可观察的微观信号
When_to_Use: 描述所处背景、阶段、治疗目标和整体状态
~~~

文件中的实际例子是“未完成作业、质疑作业效用”的场景，response 内容包括：

> Trigger: 来访者直接承认未完成任务，使用“太忙”、“没用”、“反正”等合理化借口和宿命论语言……

> When_to_Use: 适用于CBT会谈的作业回顾阶段……

原文位置：[prompts/psychagent/skill/rewrite/system.txt:31](D:/a华东师范/2项目/1实践/Psych-new/prompts/psychagent/skill/rewrite/system.txt:31) [prompts/psychagent/skill/rewrite/system.txt:76](D:/a华东师范/2项目/1实践/Psych-new/prompts/psychagent/skill/rewrite/system.txt:76)。

实际输入为 Session_Goals、Dialogue_History、Current_Client_Query、Treatment_Structure。代码把 **Treatment_Structure 固定为 General**，并 del sect。虽然传了 stage 参数，但当前 user.txt 没有使用 stage 占位符；实际阶段能否进入改写上下文取决于目标、历史文本是否包含它。Web 的 stage_title 是真阶段；sample 则写死“stage”。因此不能说“完整流派治疗树/阶段地图已经注入 rewrite”。[src/sample/skill_manager.py:308](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:308) [prompts/psychagent/skill/rewrite/user.txt:3](D:/a华东师范/2项目/1实践/Psych-new/prompts/psychagent/skill/rewrite/user.txt:3) [src/sample/runner.py:221](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:221) [src/web/backend/psychagent_engine.py:105](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/psychagent_engine.py:105)

system 要求额外输出 think 中的 assessment/client_state，但用于 embedding 的通常只是 response；这些分析没有作为新的结构化 state 回写。若 response 标签缺失，extract_tag_content 会返回整个原文，可能把分析文字也一并嵌入。[src/sample/skill_manager.py:271](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:271) [src/sample/skill_manager.py:323](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:323) [src/sample/utils.py:13](D:/a华东师范/2项目/1实践/Psych-new/src/sample/utils.py:13)

### 5.3 咨询师提示词：加载指定流派，动态注入 micro 技能

文件如下：

- CBT：[prompts/psychagent/cbt/counsel/system.jinja2:174](D:/a华东师范/2项目/1实践/Psych-new/prompts/psychagent/cbt/counsel/system.jinja2:174)
- BT：[prompts/psychagent/bt/counsel/system.jinja2:166](D:/a华东师范/2项目/1实践/Psych-new/prompts/psychagent/bt/counsel/system.jinja2:166)
- HET：[prompts/psychagent/het/counsel/system.jinja2:192](D:/a华东师范/2项目/1实践/Psych-new/prompts/psychagent/het/counsel/system.jinja2:192)
- PDT：[prompts/psychagent/pdt/counsel/system.jinja2:189](D:/a华东师范/2项目/1实践/Psych-new/prompts/psychagent/pdt/counsel/system.jinja2:189)
- PMT：[prompts/psychagent/pmt/counsel/system.jinja2:179](D:/a华东师范/2项目/1实践/Psych-new/prompts/psychagent/pmt/counsel/system.jinja2:179)

PsychAgentPromptManager 用项目 prompts/psychagent 根目录、modality 和 runtime 的 counselor_system_filename，读取 modality/counsel/system.jinja2，编译为 Jinja Template。实例按流派缓存。[src/sample/prompt_manager.py:12](D:/a华东师范/2项目/1实践/Psych-new/src/sample/prompt_manager.py:12) [src/web/backend/psychagent_engine.py:325](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/psychagent_engine.py:325) [src/sample/runner.py:711](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:711)

CBT 技能列表原文：

~~~jinja2
{% for skill in suggested_skills %}
- 技能名称：{{ skill.skill_name }}
  技能描述：{{ skill.skill_description }}
  使用时机：{{ skill.when_to_use }}
  触发线索：{{ skill.trigger }}
{% endfor %}
~~~

咨询师看到的不是 JSON 树、ID 列表或向量，而是这四项自然语言信息；similarity 虽在返回对象中，也未展示。上层同时传入 client_info、history、session_stage、session_focus、homework_assigned_from_last_session。Web 生成新的 system message；sample 每轮替换 counselor_messages[0]，保留后续聊天历史。[prompts/psychagent/cbt/counsel/system.jinja2:174](D:/a华东师范/2项目/1实践/Psych-new/prompts/psychagent/cbt/counsel/system.jinja2:174) [src/web/backend/psychagent_engine.py:126](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/psychagent_engine.py:126) [src/sample/runner.py:326](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:326) [src/sample/runner.py:393](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:393)

对 micro 32，“表达理解与共情”的真实条目包含名称、描述、适用时机与“来访者表达困扰、情绪不稳定……”等触发线索，正好对应上述四字段。[assets/skills/sect/cbt/stage1/micro_skills.json:2](D:/a华东师范/2项目/1实践/Psych-new/assets/skills/sect/cbt/stage1/micro_skills.json:2)

咨询师的“最终选技能”是一次普通文本生成，提示词要求：

> 从下方「技能列表」中选出本轮将实际使用的若干个技能；仅按“技能名称”的形式书写，并用全角分号分隔；不得添加列表外技能，不得修改技能名称。

示例格式：

~~~xml
<think>
  <assessment>...</assessment>
  <client_state>...</client_state>
  <skill>表达理解与共情；询问精神科就诊经历</skill>
  <strategy>...</strategy>
</think>
<response>...</response>
~~~

原文：[prompts/psychagent/cbt/counsel/system.jinja2:133](D:/a华东师范/2项目/1实践/Psych-new/prompts/psychagent/cbt/counsel/system.jinja2:133) [prompts/psychagent/cbt/counsel/system.jinja2:158](D:/a华东师范/2项目/1实践/Psych-new/prompts/psychagent/cbt/counsel/system.jinja2:158)。没有程序拿这里的 skill 名称再去检索、执行某个技能函数或验证归属。

### 5.4 “文件存在”与“当前入口加载”分开看

| 提示词 | 当前调查入口中的状态 |
|---|---|
| skill/select_skill/system.txt、user.txt | 启动时读入；粗筛时渲染并发送 |
| skill/rewrite/system.txt、user.txt | 启动时读入；非空候选的精筛调用中发送 |
| 各流派 counsel/system.jinja2 | 首次创建该流派 PromptManager 时加载；每轮渲染 |
| 各流派 summary/profile 的 system/user | 同一 PromptManager 创建时全部加载；会谈收尾实际调用 |
| public/counselor_system.jinja2、session_opening.jinja2、public_recap.jinja2 | core PromptManager 有对应方法，但当前 sample/Web 咨询师链路没有调用这些方法 |
| Web fallback 提示词 | 来自 visit_service.build_visit_prompt 中的 Python 字符串，不是 public 模板 |

证据：[src/sample/skill_manager.py:499](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:499) [src/sample/prompt_manager.py:25](D:/a华东师范/2项目/1实践/Psych-new/src/sample/prompt_manager.py:25) [src/sample/runner.py:245](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:245) [src/web/backend/psychagent_engine.py:188](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/psychagent_engine.py:188) [src/sample/core/prompt_manager.py:48](D:/a华东师范/2项目/1实践/Psych-new/src/sample/core/prompt_manager.py:48) [src/sample/core/prompt_manager.py:86](D:/a华东师范/2项目/1实践/Psych-new/src/sample/core/prompt_manager.py:86) [src/sample/core/prompt_manager.py:94](D:/a华东师范/2项目/1实践/Psych-new/src/sample/core/prompt_manager.py:94) [src/web/backend/services/visit_service.py:68](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/services/visit_service.py:68)。

注意：sample 会创建 core PromptManager 供 client 模拟器使用，但创建实例本身不等于调用 public 咨询师模板；当前咨询师使用的是另一个 PsychAgentPromptManager。[src/sample/runner.py:60](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:60) [src/sample/runner.py:66](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:66) [src/sample/runner.py:326](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:326)

## 六、fallback 与校验边界

### 6.1 不同失败位置，不同后果

| 失败/异常条件 | 已核实行为 |
|---|---|
| embedding key 缺失 | RuntimeConfig.validate 就拒绝配置；load_library 也再次要求。不是等逐轮检索时才检查 |
| 缺少检索提示词文件 | load_library 直接 read_text 失败，没有缺文件时自动使用默认提示词 |
| leaf 库为空 | 粗筛直接返回空，后续可无技能继续 |
| 粗筛 LLM 异常、解析失败、空 ID 列表 | fallback 为 leaf 插入顺序前 n 个；不是相关度排序或安全技能兜底 |
| 返回非空无效 ID 列表 | find_skill_by_id 跳过不存在的 meta；不会因最终候选为空再次 fallback |
| 返回非 leaf 但存在的 meta ID | 可被接受；按严格直接路径匹配，通常没有 micro，不递归展开 |
| rewrite/embedding 失败 | sample 外层重试耗尽返回 []；Web 则由整条 prompt chain 的异常处理换到简短 fallback |
| 无候选 | retrive 返回 []，不做 rewrite，也不调用 query embedding |
| 启动时 load_library 失败 | Web 的 startup 在回复 try 之前、也在应用 startup 运行；正常回复 fallback 不能兜住启动失败 |

证据：[src/sample/core/schemas.py:247](D:/a华东师范/2项目/1实践/Psych-new/src/sample/core/schemas.py:247) [src/sample/skill_manager.py:127](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:127) [src/sample/skill_manager.py:190](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:190) [src/sample/skill_manager.py:211](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:211) [src/sample/skill_manager.py:248](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:248) [src/sample/skill_manager.py:499](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:499) [src/sample/skill_manager.py:351](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:351) [src/sample/runner.py:545](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:545) [src/web/backend/psychagent_engine.py:93](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/psychagent_engine.py:93) [src/web/backend/psychagent_engine.py:143](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/psychagent_engine.py:143)。

### 6.2 已离线验证的 ID 边界

使用原始 corse_filter、find_skill_by_id、get_leaf_nodes 等方法的 AST 片段，加载真实 CBT stage1 JSON；把 llm_response 替换为固定字符串返回的内存桩，没有创建网络客户端、没有 API。此验证覆盖 ID 解析/扩展控制流，不覆盖 Jinja 渲染或模型遵循情况。

| 固定返回内容 | 实际结果 |
|---|---|
| {"skill_id":["3"]} | 1 组、24 个候选 micro |
| {"skill_id":["3","3"]} | 2 组、48 个候选，只有 24 个唯一 micro |
| {"skill_id":["1"]} | 1 个 meta 组，0 个 micro；不递归收集后代 |
| {"skill_id":["NOT_REAL"]} | 0 组、0 micro；不触发空 ids fallback |
| {"skill_id":"32"} | 被按字符遍历成 "3"、"2"，而非一个 ID "32" |
| {"skill_id":[]} | fallback 20 个 leaf，458 个 micro |

以上不是虚构模型调用结果，而是受控的本地控制流测试。相关源码：[src/sample/skill_manager.py:212](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:212) [src/sample/skill_manager.py:218](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:218) [src/sample/skill_manager.py:346](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:346)。

所以提示词所写“数量与去重硬约束”并非程序硬约束：未检查数组类型、ID 是否属于 leaf、是否重复、数量是否等于 n、最终候选是否为空。重复候选可能在 top_k 中再次重复占位，排序阶段同样没有按 skill_id 去重。[src/sample/skill_manager.py:214](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:214) [src/sample/skill_manager.py:276](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:276)

### 6.3 向量、树、模板、阶段的其他边界

**向量有效性不足。**_cosine_similarity 对空向量、维度不一致、零模向量返回 -1.0；默认 threshold=None，意味着非空但维度错误/零模的候选仍可能入选（当正常候选不足时尤其明显）。空 list 会被 _vector_to_list 当作合法 list 返回，不按 None 缺失补齐，排序阶段则因 not vec 被跳过。没有验证向量来源模型或全部数值有限。[src/sample/skill_manager.py:274](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:274) [src/sample/skill_manager.py:598](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:598) [src/sample/skill_manager.py:620](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:620)

**完整树 schema 没有校验。**读取 JSON 只要求顶层和条目是字典；micro 缺 skill_id 时以 key 补齐。不存在统一检查 parent_ids 的类型、层级一致性、无环性或全部 micro 可达性的启动步骤。当前资源经过本次核查是可达的，不能把该数据现状误认为程序保证。[src/sample/skill_manager.py:536](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:536) [src/sample/skill_manager.py:545](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:545) [src/sample/skill_manager.py:387](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:387)

**stage 名称没有统一强枚举。**NextSessionPlan.next_session_stage 只是 str。sample 粗筛处使用 STAGE_MAP.get(stage,1)；SkillManager._resolve_stage 识别 1/2/3 整数、数字字符串及三个中文名称，未知内容默认 1，不识别字面 "stage2" 或 "intervention"。Web 主入口先把 stage_key 转为整数，正常路径没有此问题。summary 输出若发生非法阶段名称，sample 可能显示该原始名称却检索 stage1。[src/sample/models.py:8](D:/a华东师范/2项目/1实践/Psych-new/src/sample/models.py:8) [src/sample/runner.py:221](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:221) [src/sample/skill_manager.py:520](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:520) [src/web/backend/domain.py:93](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/domain.py:93)

**模板依赖与模板变量没有强保证。**PsychAgentPromptManager 和 SkillManager 使用普通 Template，不是 StrictUndefined；缺少 Jinja2 时直接返回原模板文本，技能和会谈上下文可能不被展开。本地系统 Python 缺 Jinja2，因此本次没有进行完整 Jinja 渲染验证；此观察不代表目标部署缺依赖。Web requirements 显式包含 Jinja2，但没有 torch。若部署也没有额外安装 torch，则只走 JSON 分支；当前 JSON 无 embedding，而 .pt 中已有向量不会被利用，启动会补齐两类向量，并且无 torch 时不保存 .pt，可能每次启动重复补齐。[src/sample/prompt_manager.py:6](D:/a华东师范/2项目/1实践/Psych-new/src/sample/prompt_manager.py:6) [src/sample/prompt_manager.py:40](D:/a华东师范/2项目/1实践/Psych-new/src/sample/prompt_manager.py:40) [src/sample/skill_manager.py:531](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:531) [src/web/requirements.txt:1](D:/a华东师范/2项目/1实践/Psych-new/src/web/requirements.txt:1) [src/sample/skill_manager.py:545](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:545) [src/sample/skill_manager.py:148](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:148)

**启动加载本身具有外部副作用。**即便只想“加载库”，load_library 也会检查并补齐所有已加载流派/阶段的两类 embedding，缺失时会调用 API，有 torch 时还会写回 micro_skills.pt。这也是本调查没有直接运行 load_library 的原因。当前 .pt 检查未见缺失，不等于没有 torch 的 JSON 分支不会补齐。[src/sample/skill_manager.py:73](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:73) [src/sample/skill_manager.py:146](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:146)

**严格选技能约束未校验。**咨询师只要给出非空文本就可能被接受；代码提取 response 并处理 end token，不验证 skill 标签或名称。在空技能列表情况下，模板依然写“只能从列表中选择”，没有专门的无技能说明。sample 的 each_turn_system 可供事后核对“模型当轮看到了什么”，但不证明实际使用了相应技能。[prompts/psychagent/cbt/counsel/system.jinja2:158](D:/a华东师范/2项目/1实践/Psych-new/prompts/psychagent/cbt/counsel/system.jinja2:158) [prompts/psychagent/cbt/counsel/system.jinja2:174](D:/a华东师范/2项目/1实践/Psych-new/prompts/psychagent/cbt/counsel/system.jinja2:174) [src/sample/runner.py:575](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:575) [src/sample/runner.py:294](D:/a华东师范/2项目/1实践/Psych-new/src/sample/runner.py:294) [src/web/backend/psychagent_engine.py:538](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/psychagent_engine.py:538)

**缺少对最终候选的危机技能保留规则。**即便粗筛把安全技能放前面，精筛又对所有 micro 重新按相似度排序，没有保留前两名或强制危机技能的代码规则。仅凭粗筛的 Safety First 提示词，不能断言最终 top_k 总含安全技能。[prompts/psychagent/skill/select_skill/system.txt:18](D:/a华东师范/2项目/1实践/Psych-new/prompts/psychagent/skill/select_skill/system.txt:18) [src/sample/skill_manager.py:276](D:/a华东师范/2项目/1实践/Psych-new/src/sample/skill_manager.py:276)

### 6.4 配置中的“开关”不能按名字推断生效

psychagent_load_library、psychagent_enable_coarse_skill_filter、psychagent_enable_turn_skill_retrieval、psychagent_skill_versions 已被列入 RUNTIME_REMOVED_FIELDS，不是当前可用开关。普通 load_runtime_config 对 removed/unknown 字段警告后忽略；strict=True 才因这些字段失败。默认 Web 不传 strict，sample 需显式 --strict-config。主链路本身直接加载库、粗筛和逐轮检索。[src/sample/core/schemas.py:266](D:/a华东师范/2项目/1实践/Psych-new/src/sample/core/schemas.py:266) [src/sample/io/config_loader.py:42](D:/a华东师范/2项目/1实践/Psych-new/src/sample/io/config_loader.py:42) [src/sample/io/config_loader.py:104](D:/a华东师范/2项目/1实践/Psych-new/src/sample/io/config_loader.py:104) [src/sample/main.py:62](D:/a华东师范/2项目/1实践/Psych-new/src/sample/main.py:62) [src/web/backend/psychagent_engine.py:52](D:/a华东师范/2项目/1实践/Psych-new/src/web/backend/psychagent_engine.py:52)。

## 七、给父代理整合的简短口径

**Psych-new 的多级技能树在“流派/阶段分区、meta leaf 判定和 leaf→micro 路径关联”上确实起作用；但运行不是沿整棵树逐层推理，而是先把 meta leaf 扁平交给 LLM 粗筛，再用经 LLM 改写的当前对话查询做 micro 向量精筛。Web 每轮粗筛，sample 每会谈粗筛、每轮精筛；默认 20 个 leaf / 5 个 micro / 无相似度阈值。检索结果以四项技能文本动态拼进流派咨询师 system prompt，咨询师用 skill 标签声明选择，没有 ReAct 工具循环，也没有最终技能归属与执行效果的程序校验。**

最值得保留的已核实风险是：粗筛 n=20 与小库大小冲突；ID 数组类型/数量/去重/leaf 成员资格未验证；无效非空 ID 不触发 fallback；祖先语义在候选展开后丢弃；rewrite 的治疗结构固定为 General，sample 的 stage_title 写死；两种失败路径可让对话继续但不再受检索技能约束。

未验证事项：目标部署 torch/Jinja2 是否安装、实际环境变量与配置覆盖、API 可用性、真实模型回复格式及技能落实程度、存量 embedding 的模型来源。本报告不把这些未验证项写成已发生故障。

