# kb/ — 知识资产层：「索引是契约，原件是证据，切片是耗材」

```
kb/
├── index/    分域小 JSON：certs / people / cases / solutions / bids_history   ✅ 进 Git（元数据，不含敏感编号）
├── raw/      原件（文件名规范化，永不改动）                                   ❌ 不进 Git（L2/L3）
└── slices/   切片（语义消费单元，frontmatter：来源/适用场景/敏感级）           ❌ 不进 Git
```

**消费走指针，不走搜索**（D10）：不做 RAG/向量；主 Agent 全读分域 index 做匹配，下游按 `slices/<file>#L<行号>` 指针精确取用。

生命周期（D9，llm-wiki-2.0 采纳项）：crystallization（案例→切片）· supersession（新教训标注取代旧教训）· 衰减（证照按有效期，案例带时效，超 1 年未引用且被取代标"沉淀"）· 摄取口脱敏（`rules/desensitize.py`）。

初始化（W2 2.3）：lingxi-claw 三标产物 + 历史投标文件 → raw 归档 → 半自动填 index → 高复用方案类做切片；简历/资质类只建索引不切片。

合规红线（设计 §14）：L3 材料（成本价/折扣/客户名单/证件号）**不进外部模型 prompt**；index 只存元数据。
