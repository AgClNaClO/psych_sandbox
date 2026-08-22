# `assets/profiles/`

本目录是从 Psych-new 保留的五流派 sample/rft 人物画像资产，用于来源核查和后续数据实验，
不是当前 `psych-sandbox simulate` 的病例加载入口。

```text
profiles/
  <bt|cbt|het|pdt|pmt>/
    sample/*.json
    rft/*.json
  _excluded/                  未并入上述切分的来源记录
```

当前共有 1,027 个 JSON：五个流派各 196 个，另有 `_excluded` 47 个。这里的 ID 空间和切分来自
Psych-new 资产组织方式，不等于当前沙盒的 341 个可运行案例。

运行时 `CaseRepository.from_project()` 实际读取 `data/<therapy>/*.json`（或可重建的
`data/processed/psycheval/all.jsonl`）；它不会递归索引本目录的 `sample/rft` 文件。若未来要启用
这些画像，应先设计显式 dataset adapter、ID 映射、去重规则和测试，不能仅靠修改文档或路径。
