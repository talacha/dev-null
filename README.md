# /dev/null API docs

An OpenAPI 3.1 description of `https://dev-null.sh/api`, with a Swagger UI page.

It covers 121 operations, which is every route in `routes/api.php` (`/v1` and `/cli`). It was written from
`nunomaduro/dev-null.sh@32315b3` (2026-11-09) by reading the routes, controllers, form requests, resources and
middleware.

## Files

| file | what |
|---|---|
| `openapi.yaml` / `openapi.json` | The spec |
| `openapi.js` | The same spec as `window.DEVNULL_OPENAPI`, so the page works without fetching anything |
| `index.html` | Swagger UI 5.34.0 (JS from jsDelivr, pinned with SRI). On `dev-null.sh` or `localhost` it turns on deep links and "Try it out" for public `GET`s |
| `swagger-ui.css` | Swagger UI's stylesheet |
| `build_spec.py` | Generates the spec. Run `python3 build_spec.py .` (needs PyYAML) |

## Hosting it on dev-null.sh

Copy the folder to `public/docs/api/`. It's then served at `https://dev-null.sh/docs/api/`, and no route is needed.
CORS isn't involved because the page and the API share an origin.

## Checks

- Every `routes/api.php` route is documented, with no extras.
- `openapi-spec-validator` and `redocly lint` pass. The one remaining warning is that no license is declared.
- Recorded responses from community clients (younes-io/ttyl fixtures) validate against the schemas.

## Keeping it current

The API changes almost daily. Two options:

1. Rerun `build_spec.py` after API changes, and diff it against `routes/api.php`.
2. Add `dedoc/scramble` to the app. eggplants/dev-null-tui already has a working config in `docs/openapi/scramble.php`.
   Use the generated document as the base and merge this file's descriptions and auth docs on top.
