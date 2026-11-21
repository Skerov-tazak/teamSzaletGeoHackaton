// The typed event bus between the map and the chat, exactly as agreed in docs/interfaces.md
// ("Events between map and chat"). main.ts creates one and passes it to every module in the context.

export interface AppEvents {
  "field:selected": { fieldId: number | null };   // null = no field selected
  "field:focus": { fieldId: number };
  "date:changed": { today: string };
  "risks:updated": { fieldIds: number[] };
}

export class EventBus {
  private target = new EventTarget();

  emit<K extends keyof AppEvents>(type: K, detail: AppEvents[K]): void {
    this.target.dispatchEvent(new CustomEvent(type, { detail }));
  }

  on<K extends keyof AppEvents>(type: K, handler: (detail: AppEvents[K]) => void): () => void {
    const listener = (event: Event) => handler((event as CustomEvent<AppEvents[K]>).detail);
    this.target.addEventListener(type, listener);
    return () => this.target.removeEventListener(type, listener); // call to stop listening
  }
}
