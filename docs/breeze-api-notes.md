# Breeze API Notes

Official references:

- ICICI Breeze API Reference: https://api.icicidirect.com/breezeapi/documents/index.html
- Official Python SDK: https://github.com/Idirect-Tech/Breeze-Python-SDK

Current constraints observed from official docs:

- Breeze API is designed for 100 API calls per minute and 5,000 API calls per day.
- Orders must be placed only from the static IP registered with ICICI Direct while procuring the API key.
- Primary or secondary static IP can be updated only once per week.
- Unregistered algos using Breeze are restricted to routing orders through a single API key.
- Maximum combined order action limit is 10 per second, including placement, cancellation, modification, and square-off.
- Market orders are not permitted.
- Margin and Option Plus placement, modification, and cancellation via Breeze are prohibited.

## Implementation Position

The scaffold only includes a placeholder `BreezeBrokerAdapter`. It does not place live orders. Before implementing live calls:

- Re-check the official docs and current regulatory classification.
- Add API-level rate-limit accounting.
- Verify static IP setup.
- Add test doubles for every Breeze method.
- Keep credentials backend-only.
- Keep paper mode as default.
- Reject market orders.
- Require manual confirmation for every live action.
