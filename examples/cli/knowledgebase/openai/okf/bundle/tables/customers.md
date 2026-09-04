---
type: BigQuery Table
title: Customers
description: One row per customer, keyed by the id the orders table references.
resource: bq://analytics/warehouse/customers
tags: [sales, customers]
status: draft
---

# Schema

| Column | Meaning |
| --- | --- |
| `customer_id` | Primary key, referenced by [orders](/tables/orders.md). |
| `region` | Billing region, used for the regional revenue split. |
| `signed_up_at` | When the account was created. |

# Notes

Nobody has reviewed this concept yet, so it carries no `verified` block and reads back as
`trust=unverified`. It is returned like any other concept — trust is a signal for the agent, not
a filter.
