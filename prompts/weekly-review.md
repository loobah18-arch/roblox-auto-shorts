# WEEKLY REVIEW PROMPT (verbatim from the playbook)

Export your posting data as CSV and paste it into this prompt on claude.ai.

---

```
Analyse this CSV of my own Whop campaign posts.

Do not claim causation from small samples. Separate observations from hypotheses. Flag campaigns that cannot be compared because their rates, caps, or approval rules differ.

Return:
1. The three strongest patterns among posts with the best qualified-view performance.
2. The three patterns among weak posts.
3. Results by hook type, source type, clip length, platform, and value-add layer.
4. Five next tests. Each test must change only one variable.
5. Data-quality issues: pending approvals, caps, missing fields, or non-comparable campaigns.

CSV:
[PASTE YOUR EXPORT]
```

---

### How to use it

1. Export your tracker (`../tracker/tracker.csv`) or platform analytics as CSV.
2. Paste after `[PASTE YOUR EXPORT]`.
3. Use the five tests to decide next week's single-variable experiments (`playbook/05-30day-plan.md`).
