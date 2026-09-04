---
type: Source System
title: Orders production database
description: The Postgres instance the orders table is loaded from every hour.
resource: postgres://orders-prod/orders
tags: [upstream, postgres]
owner: platform-team
---

# Overview

The hourly load is the reason a very recent purchase can be missing from the warehouse.

`type: Source System` is not one of the types the OKF specification names. Producers invent
types freely, so it is kept verbatim and shows up in the derived schema — nothing in the
knowledge-base tier dispatches on it.
