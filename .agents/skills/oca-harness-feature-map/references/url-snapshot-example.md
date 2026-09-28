# URL and snapshot example

Use route templates as the durable identity of a product location. Keep environment-specific hosts optional, and store screenshots inside the harness with provenance that explains what code and state they represent.

```json
{
  "features": [
    {
      "name": "operator material issue workflow",
      "domain": "warehouse",
      "repositories": [
        "northstar/scanner-ui",
        "northstar/warehouse-api",
        "northstar/warehouse-execution",
        "northstar/inventory-ledger"
      ],
      "ground_truth": [
        "prds/warehouse-material-issue.md",
        "decisions/adr-014-material-issue-idempotency.md"
      ],
      "components": [
        {
          "repository": "northstar/scanner-ui",
          "role": "Assigned-pick and material-issue UX",
          "path_globs": ["src/features/material-issue/**"],
          "tests": ["tests/material-issue.spec.ts"]
        },
        {
          "repository": "northstar/warehouse-api",
          "role": "Pick lookup and issue-confirmation API",
          "path_globs": ["src/api/picks/**"],
          "tests": ["tests/test_pick_confirmation.py"]
        }
      ],
      "product_flows": [
        {
          "id": "handheld-material-issue",
          "name": "Confirm material issued to a work order",
          "persona": "Warehouse operator",
          "entrypoint": {
            "screen": "Assigned picks",
            "route": "/warehouses/{warehouseId}/picks/assigned",
            "url_template": "https://{tenantHost}/warehouses/{warehouseId}/picks/assigned",
            "frontend_repository": "northstar/scanner-ui",
            "code_symbol": "AssignedPicksPage",
            "screenshot": {
              "id": "assigned-picks-default",
              "path": "ux/screenshots/assigned-picks-default.png",
              "alt_text": "Assigned picks screen with one open material pick",
              "state": "default",
              "environment": "staging",
              "captured_at": "2026-09-28T10:00:00Z",
              "source_commit": "abc123",
              "viewport": {"width": 1280, "height": 800}
            }
          },
          "steps": [
            {
              "action": "Open the assigned pick",
              "screen": "Pick confirmation",
              "route": "/picks/{pickId}/confirm",
              "url_template": "https://{tenantHost}/picks/{pickId}/confirm",
              "frontend_repository": "northstar/scanner-ui",
              "code_symbol": "PickConfirmationPage",
              "api_calls": [
                {
                  "method": "GET",
                  "path": "/api/picks/{pickId}",
                  "backend_repository": "northstar/warehouse-api",
                  "code_symbol": "get_pick"
                }
              ],
              "screenshot": {
                "id": "pick-confirmation-ready",
                "path": "ux/screenshots/pick-confirmation-ready.png",
                "alt_text": "Pick confirmation screen with lot and quantity fields ready for entry",
                "state": "ready",
                "environment": "staging",
                "captured_at": "2026-09-28T10:02:00Z",
                "source_commit": "abc123"
              }
            },
            {
              "action": "Confirm the issued quantity",
              "screen": "Issue confirmation",
              "route": "/picks/{pickId}/confirm",
              "frontend_repository": "northstar/scanner-ui",
              "api_calls": [
                {
                  "method": "POST",
                  "path": "/api/picks/{pickId}/material-issue",
                  "backend_repository": "northstar/warehouse-api",
                  "code_symbol": "confirm_material_issue"
                }
              ],
              "screenshot": {
                "id": "material-issue-success",
                "path": "ux/screenshots/material-issue-success.png",
                "alt_text": "Success state showing the issued quantity and work-order reference",
                "state": "success",
                "environment": "staging",
                "source_commit": "abc123"
              }
            }
          ],
          "events": [
            {
              "name": "MaterialIssued",
              "producer_repository": "northstar/warehouse-execution",
              "consumer_repositories": ["northstar/inventory-ledger"],
              "code_symbols": ["MaterialIssued", "event_id"]
            }
          ],
          "success_state": "The issue is accepted once and updated availability is visible downstream."
        }
      ],
      "owners": ["Warehouse Systems"],
      "consumers": ["Inventory Platform", "Manufacturing Systems"],
      "tests": ["tests/e2e/material-issue-workflow.spec.ts"]
    }
  ]
}
```

`route`, `frontend_repository`, screenshot `path`, and screenshot `alt_text` are the core fields understood by the current harness. `url_template`, `code_symbol`, and screenshot provenance are useful durable metadata. Do not put real tenant names, customer IDs, cookies, access tokens, or signed URLs in the feature map.

Use a separate flow step when a loading, empty, error, or success state represents a materially different customer action or backend path. If several snapshots describe the same step without changing its semantics, an implementation may add a `snapshots` array, but its consumers and validator must be updated together; do not silently replace the supported singular `screenshot` field.
