// Entry point of the frontend bundle (built to static/frontend/dist/main.js).
// For now it only checks that the platform API and database are reachable.

interface Health {
  status: string;
  database: boolean;
}

async function showPlatformStatus(element: HTMLElement): Promise<void> {
  try {
    const response = await fetch("/api/health/");
    const health = (await response.json()) as Health;
    element.textContent = health.database
      ? "Platform OK: API and database reachable."
      : "Platform up, but the database is not reachable. Is `docker compose up -d` running?";
    element.dataset.state = health.database ? "ok" : "error";
  } catch {
    element.textContent = "Platform API not reachable.";
    element.dataset.state = "error";
  }
}

const statusElement = document.getElementById("platform-status");
if (statusElement) {
  void showPlatformStatus(statusElement);
}
