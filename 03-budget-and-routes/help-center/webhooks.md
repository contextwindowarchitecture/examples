---
id: webhooks
title: Webhooks
version: 2
updated: 2026-06-30T12:00:00Z
---
Webhooks send an HTTP POST to your URL when something happens in a workspace: a task is created, updated, completed or deleted, or a comment is added. Admins create webhooks under Settings, then Integrations, then Webhooks.

Each delivery carries an X-Fernway-Signature header: an HMAC-SHA256 of the request body, keyed with the webhook's signing secret. Compute the same HMAC on your side and compare before trusting the payload.

Your endpoint must answer with a 2xx status within 10 seconds. Failed deliveries are retried 3 times over one hour. After 50 consecutive failures, Fernway disables the webhook and emails the Admin who created it.
