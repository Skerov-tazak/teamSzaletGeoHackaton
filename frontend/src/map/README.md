# Map

**Owner:** Kuba

The interactive map of the farm: fields, their crops, their risk per threat, how that risk changes over the season, and the details of a selected field.

## Talking to the rest of the system

- **Plain TypeScript, no framework.** Map libraries (Leaflet, MapLibre, …) are fine: install them with `npm install` in [`frontend/`](../../), and esbuild bundles them into `static/frontend/dist/main.js`.
- **Data comes from the platform's JSON API,** not the database directly; see <http://localhost:8000/api/docs/> while the server runs. What's behind it (fields, risks, units) is described in [docs/database.md](../../../docs/database.md).
- **The date is the platform's "today" (from the API), never the browser's `new Date()`.** The demo replays a past season.
- **What to expect from the data:**
  - field shapes are GeoJSON in EPSG:4326, with coordinates in **[lon, lat]** order;
  - a risk score is a number from 0 to 1, one per field, threat and day;
  - "season so far" means up to today, "coming days" means today + 1 … today + 7.
- *To be defined in the interfaces step:* how the map mounts into the page, the exact data endpoints and their format, the colour cut-offs for risk scores, and the events shared with the chat (for example, a field being selected).
