// "Own data": upload a parcel outline (SHP/GeoPackage/GeoJSON) and see the parcels the user
// added. For now the files wait in a local queue — parsing and the backend upload are the next
// iteration (shp inside a ZIP, geometry into the platform API).

import type { AppContext } from "../app-context";
import { addParcel, listParcels, removeParcel, totalAreaHa, type ParcelRecord, type UploadFormat } from "./store";
import { byId, el } from "../ui/dom";

const ACCEPTED: Record<string, UploadFormat> = {
  shp: "shp",
  zip: "zip",
  gpkg: "gpkg",
  geojson: "geojson",
  json: "geojson",
};

const MAX_BYTES = 50 * 1024 * 1024;

function formatOf(file: File): UploadFormat | null {
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  return ACCEPTED[extension] ?? null;
}

function formatLabel(format: UploadFormat): string {
  switch (format) {
    case "shp":
      return "Shapefile (.shp — potrzebne też .dbf i .shx, zalecany ZIP)";
    case "zip":
      return "ZIP ze shapefile";
    case "gpkg":
      return "GeoPackage";
    default:
      return "GeoJSON";
  }
}

export function initOwnData(ctx: AppContext): void {
  const dropzone = byId("upload-dropzone");
  const fileInput = byId<HTMLInputElement>("upload-input");
  const queueHost = byId("upload-queue");
  const listHost = byId("parcel-list");
  const summary = byId("parcel-summary");
  const form = byId<HTMLFormElement>("upload-form");
  const nameInput = byId<HTMLInputElement>("upload-name");

  let queued: File[] = [];

  const renderQueue = (): void => {
    queueHost.replaceChildren();
    if (queued.length === 0) {
      queueHost.append(el("p", "muted", "Nie wybrano plików."));
      return;
    }
    for (const file of queued) {
      const format = formatOf(file);
      const item = el("li", "queue-item");
      item.append(el("span", undefined, file.name), el("span", "muted", format ? formatLabel(format) : "nierozpoznany"));
      queueHost.append(item);
    }
  };

  const acceptFiles = (files: FileList | null): void => {
    if (!files) return;
    const rejected: string[] = [];
    for (const file of Array.from(files)) {
      if (!formatOf(file)) {
        rejected.push(`${file.name} (dozwolone: shp, zip, gpkg, geojson)`);
      } else if (file.size > MAX_BYTES) {
        rejected.push(`${file.name} (maks. 50 MB)`);
      } else {
        queued.push(file);
      }
    }
    if (rejected.length > 0) {
      queueHost.replaceChildren(el("p", "error", `Odrzucono: ${rejected.join(", ")}`));
    }
    renderQueue();
  };

  const renderParcels = (): void => {
    const parcels = listParcels();
    listHost.replaceChildren();
    summary.textContent =
      parcels.length === 0
        ? "Brak przesłanych działek."
        : `${parcels.length} działka(e), łącznie ${totalAreaHa().toFixed(1).replace(".", ",")} ha`;
    if (parcels.length === 0) return;

    for (const parcel of parcels) {
      listHost.append(renderParcelRow(parcel));
    }
  };

  const renderParcelRow = (parcel: ParcelRecord): HTMLLIElement => {
    const item = el("li", "parcel-item");
    const info = el("div", "parcel-info");
    info.append(el("strong", undefined, parcel.name));
    info.append(
      el(
        "span",
        "muted",
        [
          parcel.areaHa === null ? "powierzchnia: —" : `powierzchnia: ${parcel.areaHa.toFixed(1)} ha`,
          formatLabel(parcel.format),
          parcel.fileNames.join(", "),
        ].join(" · "),
      ),
    );
    const remove = el("button", "icon-button", "×");
    remove.type = "button";
    remove.title = "Usuń działkę";
    remove.addEventListener("click", () => {
      removeParcel(parcel.id);
      renderParcels();
      document.dispatchEvent(new CustomEvent("fup:parcels-changed"));
    });
    item.append(info, remove);
    return item;
  };

  // --- Wiring -------------------------------------------------------------------------------

  dropzone.addEventListener("click", () => fileInput.click());
  dropzone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      fileInput.click();
    }
  });
  fileInput.addEventListener("change", () => {
    acceptFiles(fileInput.files);
    fileInput.value = "";
  });

  for (const type of ["dragenter", "dragover"]) {
    dropzone.addEventListener(type, (event) => {
      event.preventDefault();
      dropzone.classList.add("is-dragging");
    });
  }
  for (const type of ["dragleave", "drop"]) {
    dropzone.addEventListener(type, (event) => {
      event.preventDefault();
      dropzone.classList.remove("is-dragging");
    });
  }
  dropzone.addEventListener("drop", (event) => acceptFiles((event as DragEvent).dataTransfer?.files ?? null));

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (queued.length === 0) {
      queueHost.replaceChildren(el("p", "error", "Najpierw wybierz plik obrysu działki."));
      return;
    }
    const formats = new Set(queued.map((file) => formatOf(file)));
    addParcel({
      name: nameInput.value.trim() || queued[0].name.replace(/\.[^.]+$/, ""),
      areaHa: null,
      geometry: null,
      format: [...formats].find((value): value is UploadFormat => value !== null) ?? "geojson",
      fileNames: queued.map((file) => file.name),
    });
    queued = [];
    nameInput.value = "";
    renderQueue();
    renderParcels();
    document.dispatchEvent(new CustomEvent("fup:parcels-changed"));
    queueHost.replaceChildren(
      el(
        "p",
        "notice",
        "Plik zapisany w kolejce lokalnej. Parsowanie geometrii (SHP/GeoPackage → poligon na mapie) " +
          "zostanie dodane razem z endpointem uploadu w platformie.",
      ),
    );
  });

  document.addEventListener("fup:parcels-changed", renderParcels);
  ctx.shell.on("view:changed", ({ view: name }) => {
    if (name === "own-data") renderParcels();
  });

  renderQueue();
  renderParcels();
}
