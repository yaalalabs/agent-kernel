---
type: BigQuery Table
title: Orders
description: One row per completed purchase, carrying the revenue amount.
resource: bq://analytics/warehouse/orders
tags: [sales, revenue, orders]
status: stable
verified: [{by: "human:jsmith", at: "2026-01-14T09:30:00+00:00"}]
sources: [{by: "datasets/orders_db.md"}]
---

# Schema

| Column | Meaning |
| --- | --- |
| `order_id` | Primary key. |
| `customer_id` | Foreign key into [customers](/tables/customers.md). |
| `amount_usd` | Revenue for the order, net of discounts. |
| `completed_at` | When the purchase completed. Orders that never complete are absent. |

# Notes

Revenue means `amount_usd` summed over completed orders. Refunds are not subtracted here; the
refunds table is a separate concept that does not exist yet.
