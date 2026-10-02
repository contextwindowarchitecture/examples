---
id: api
title: The Fernway REST API
version: 5
updated: 2026-08-18T17:00:00Z
---
The Fernway REST API reads and writes projects, tasks, comments and members. Requests go to https://api.fernway.example/v2 and send a personal API token in the Authorization header as a bearer token.

Create a personal API token under Profile, then API tokens. A token acts with your permissions, so it sees only what you can see. Tokens do not expire, but you can revoke one at any time; revoked tokens stop working immediately.

Rate limits apply per workspace: 60 requests per minute on Free, 300 on Team and 1,000 on Business. A request over the limit gets HTTP 429 with a Retry-After header giving the seconds to wait.

List endpoints return at most 100 items per page. Follow the next_cursor value in the response to fetch the next page; a null next_cursor means there are no more pages.
