# RA Domain — Rule ID Convention

## Format

```
{source}-art{N}-p{N}-{suffix}
```

## Components

| Part | Description | Example |
|------|-------------|---------|
| `{source}` | Source document ID from `_sources.yaml` | `kmdia-fc`, `kmdia-fc-detail` |
| `art{N}` | Article number (조) | `art7` |
| `p{N}` | Paragraph number (항) | `p1` |
| `{suffix}` | `main` for main text, `item{N}` for sub-clauses (호) | `main`, `item1` |

## Examples

```
kmdia-fc-art5-p1-main       # 제5조 제1항 본문
kmdia-fc-art7-p1-item3      # 제7조 제1항 제3호
kmdia-fc-detail-art3-p2-main # 세부운용기준 제3조 제2항 본문
```

## Atomicity Rules

- Each `item{N}` is a separate Rule Unit when it represents an independent obligation/prohibition
- Enumerated items (가~라) under the same clause are merged if they share one decision point
- Sequential procedure steps are merged if they form one process
