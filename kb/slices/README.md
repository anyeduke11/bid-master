# kb/slices/ — 切片（不进 Git）

语义消费单元，供规格单指针引用（`slices/<file>#L<start>-L<end>`）。

每片 frontmatter：
```yaml
---
source: kb/raw/solutions/xxx.docx      # 原件指针
fingerprint: sha256:…                    # 原件指纹
scene: [重保协防, 应急响应]              # 适用场景标签（LLM 标注 + 人抽检）
sensitivity: L1 | L2                     # L3 不切片
valid_until: 2027-06-30                  # 时效（案例类）
---
```
高复用方案类做切片；简历/资质类只建索引不切片（设计 §6.5）。
