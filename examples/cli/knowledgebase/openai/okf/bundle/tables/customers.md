---
type: BigQuery Table
title: Customers
description: One row per customer, keyed by the id the orders table references.
resource: bq://analytics/warehouse/customers
tags: [sales, customers]
status: draft
verified: [{by: "process:nightly-schema-crawl", at: "2026-02-03T02:15:00+00:00"}]
---

# Schema

| Column | Meaning |
| --- | --- |
| `customer_id` | Primary key, referenced by [orders](/tables/orders.md). |
| `region` | Billing region, used for the regional revenue split. |
| `signed_up_at` | When the account was created. |

# Notes

No person has signed off on this concept. Its `verified` block names an automated crawl rather
than a `human:` actor, so it reads back as `trust=machine-confirmed`: one tier below `orders.md`,
which a human checked, and one above `datasets/orders_db.md`, which carries no `verified` block at
all and so reads back as `trust=unverified`. All three are returned like any other concept —
trust is a signal for the agent, not a filter.
