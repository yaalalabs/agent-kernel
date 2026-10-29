# #786 Research

Supporting research behind [design.md](../design.md). Not requirements: where a file and the design disagree, the
design wins. External facts link their official source; repo facts name the file.

| File | Takeaway | Status |
|---|---|---|
| [platform-scaling-and-cost.md](platform-scaling-and-cost.md) | How worker counts, queue depth, step end and cost are read per platform (ECS, Lambda, K8s, later GCP / Azure), the fetcher candidates and why, autoscaling timings, billed vs estimated cost, per-run prices | Fetchers bound; ECS / Lambda fetcher choice decided after the first runs |
| [resource-usage.md](resource-usage.md) | Where worker CPU / memory comes from on each host (ECS service metrics, Container Insights, Lambda `REPORT` lines, Lambda Insights, metrics-server, `psutil`) and what each source can and can't give | Agreed 2026-10-29; Lambda Insights fields and Fargate events checked on first runs |
| [load-generator-health.md](load-generator-health.md) | How other load tools spot an overloaded load generator | Decided not tracked (review issue 7); reference only |
