# Map

**Owner:** Kuba

The interactive map of the farm: fields, their crops, their risk per threat, how that risk changes over the season, and the details of a selected field.

## Talking to the rest of the system

- Plain TypeScript, no framework. Map libraries (Leaflet, MapLibre, …) are fine: install them with `npm install` in [`frontend/`](../../), and esbuild bundles them into `static/frontend/dist/main.js`.
- Gets its data from the platform's JSON API; see <http://localhost:8000/api/docs/> while the server runs.
- *To be defined in the interfaces step:* how the map mounts into the page, the data endpoints and their format (GeoJSON), and the events shared with the chat (for example, a field being selected).
