// The chat window, shown on the right when the "Asystent" button is pressed.
// HTTP contract: docs/interfaces.md -> Chat. Answers are markdown and are always sanitised
// before they reach the page; the model's output is never inserted as raw HTML.

import { marked } from "marked";
import DOMPurify from "dompurify";
import type { AppContext } from "../app-context";
import { humaniseError } from "../api/client";
import type { ChatMessage, Citation, Conversation } from "../types";
import { byId, el } from "../ui/dom";

const WELCOME =
  "Cześć! Jestem asystentem upraw. Zapytaj o ryzyko na działce, chorobę lub oprysk — " +
  "odpowiedzi pochodzą z oficjalnych metodyk i danych platformy.";

export function initChat(ctx: AppContext): void {
  const drawer = byId("chat-drawer");
  const toggle = byId<HTMLButtonElement>("chat-toggle");
  const closeButton = byId<HTMLButtonElement>("chat-close");
  const newChatButton = byId<HTMLButtonElement>("chat-new");
  const historyButton = byId<HTMLButtonElement>("chat-history");
  const historyList = byId("chat-history-list");
  const messagesHost = byId("chat-messages");
  const contextBanner = byId("chat-context");
  const form = byId<HTMLFormElement>("chat-form");
  const input = byId<HTMLTextAreaElement>("chat-input");
  const sendButton = byId<HTMLButtonElement>("chat-send");

  let conversationId: number | null = null;
  let selectedFieldId: number | null = null;
  let selectedFieldName: string | null = null;
  let pending = false;

  const setOpen = (open: boolean): void => {
    drawer.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    toggle.classList.toggle("is-active", open);
    if (open) {
      historyButton.setAttribute("aria-expanded", historyList.hidden ? "false" : "true");
      input.focus();
      scrollToEnd();
    }
  };

  const scrollToEnd = (): void => {
    messagesHost.scrollTop = messagesHost.scrollHeight;
  };

  const addMessage = (role: "user" | "assistant" | "system", node: HTMLElement): HTMLElement => {
    const wrapper = el("article", `message message-${role}`);
    wrapper.append(node);
    messagesHost.append(wrapper);
    scrollToEnd();
    return wrapper;
  };

  const renderText = (text: string): HTMLElement => {
    const body = el("div", "message-text");
    body.innerHTML = DOMPurify.sanitize(marked.parse(text, { async: false }) as string);
    return body;
  };

  const renderCitations = (citations: Citation[]): HTMLElement | null => {
    if (!citations || citations.length === 0) return null;
    const list = el("div", "citations");
    for (const citation of citations) {
      if (citation.type === "risk") {
        const button = el(
          "button",
          "citation citation-risk",
          `Ryzyko: działka #${citation.field_id}, ${citation.threat_code} (${citation.date})`,
        );
        button.type = "button";
        button.addEventListener("click", () => ctx.events.emit("field:focus", { fieldId: citation.field_id }));
        list.append(button);
      } else {
        list.append(el("span", "citation", `Źródło: ${citation.document}, s. ${citation.page}`));
      }
    }
    return list;
  };

  const renderMessage = (message: ChatMessage): void => {
    const node = message.role === "assistant" ? renderText(message.text) : el("p", "message-text", message.text);
    const wrapper = el("div", "message-body");
    wrapper.append(node);
    const citations = renderCitations(message.citations);
    if (citations) wrapper.append(citations);
    addMessage(message.role, wrapper);

    if (message.role === "assistant") {
      if (message.focus_field_id !== null) ctx.events.emit("field:focus", { fieldId: message.focus_field_id });
      if (message.updated_field_ids.length > 0) {
        ctx.events.emit("risks:updated", { fieldIds: message.updated_field_ids });
      }
    }
  };

  const renderConversation = (conversation: Conversation): void => {
    messagesHost.replaceChildren();
    if (conversation.messages.length === 0) {
      addMessage("assistant", el("p", "message-text", WELCOME));
    }
    for (const message of conversation.messages) renderMessage(message);
    scrollToEnd();
  };

  const updateContextBanner = (): void => {
    if (selectedFieldId === null) {
      contextBanner.textContent = "Brak wybranej działki — możesz zadać ogólne pytanie.";
      contextBanner.dataset.state = "none";
    } else {
      contextBanner.textContent = `Pytasz o: ${selectedFieldName ?? `działkę #${selectedFieldId}`}`;
      contextBanner.dataset.state = "field";
    }
  };

  const loadConversations = async (): Promise<void> => {
    historyList.replaceChildren(el("li", "muted", "Wczytywanie…"));
    try {
      const conversations = await ctx.api.getConversations();
      historyList.replaceChildren();
      if (conversations.length === 0) {
        historyList.append(el("li", "muted", "Brak zapisanych rozmów."));
        return;
      }
      for (const conversation of conversations) {
        const item = el("li");
        const button = el("button", "history-item", conversation.title || `Rozmowa #${conversation.id}`);
        button.type = "button";
        button.addEventListener("click", () => void openConversation(conversation.id));
        item.append(button);
        historyList.append(item);
      }
    } catch (error) {
      historyList.replaceChildren(el("li", "muted", humaniseError(error)));
    }
  };

  const openConversation = async (id: number): Promise<void> => {
    try {
      const conversation = await ctx.api.getConversation(id);
      conversationId = conversation.id;
      renderConversation(conversation);
      historyList.hidden = true;
      historyButton.setAttribute("aria-expanded", "false");
    } catch (error) {
      addMessage("system", el("p", "error", humaniseError(error)));
    }
  };

  const startNewConversation = (): void => {
    conversationId = null;
    messagesHost.replaceChildren();
    addMessage("assistant", el("p", "message-text", WELCOME));
    historyList.hidden = true;
    historyButton.setAttribute("aria-expanded", "false");
    input.focus();
  };

  const send = async (): Promise<void> => {
    const text = input.value.trim();
    if (!text || pending) return;

    pending = true;
    sendButton.disabled = true;
    input.value = "";

    addMessage("user", el("p", "message-text", text));
    const thinking = addMessage("assistant", el("p", "thinking", "Myślę…"));

    try {
      const reply = await ctx.api.sendChat({
        conversation_id: conversationId,
        message: text,
        field_id: selectedFieldId,
      });
      conversationId = reply.conversation_id;
      thinking.remove();
      renderMessage(reply.message);
    } catch (error) {
      thinking.replaceChildren(el("p", "error", humaniseError(error)));
    } finally {
      pending = false;
      sendButton.disabled = false;
      input.focus();
    }
  };

  // --- Wiring -------------------------------------------------------------------------------

  toggle.addEventListener("click", () => setOpen(drawer.hidden === true));
  closeButton.addEventListener("click", () => setOpen(false));
  newChatButton.addEventListener("click", startNewConversation);  historyButton.addEventListener("click", () => {
    const willShow = historyList.hidden;
    historyList.hidden = !willShow;
    historyButton.setAttribute("aria-expanded", willShow ? "true" : "false");
    if (willShow) void loadConversations();
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    void send();
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void send();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !drawer.hidden) setOpen(false);
  });
  ctx.shell.on("chat:toggle", ({ open }) => setOpen(open));
  ctx.events.on("field:selected", ({ fieldId }) => {
    selectedFieldId = fieldId;
    selectedFieldName = null;
    updateContextBanner();
    if (fieldId !== null) {
      ctx.api
        .getField(fieldId)
        .then((field) => {
          if (selectedFieldId === fieldId) {
            selectedFieldName = field.name;
            updateContextBanner();
          }
        })
        .catch(() => undefined);
    }
  });

  setOpen(false);
  updateContextBanner();
}
