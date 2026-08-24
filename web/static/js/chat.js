function getCookie(name) {
  let cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, name.length + 1) === (name + '=')) {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}

document.addEventListener("DOMContentLoaded", function () {
  const page = document.querySelector(".chat-page");
  if (!page) return;

  let chatroomId = page.dataset.chatroomId || null;
  const messagesEl = document.getElementById("chat-messages");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const submitBtn = form.querySelector('button[type="submit"]');

  function setSending(sending) {
    input.disabled = sending;
    submitBtn.disabled = sending;
    if (!sending) input.focus();
  }

  if (chatroomId) {
    loadMessages(chatroomId);
  }

  form.addEventListener("submit", async function (e) {
    e.preventDefault();

    const text = input.value.trim();
    if (!text || submitBtn.disabled) return;

    input.value = "";
    appendMessage("user", text);
    setSending(true);

    try {
      if (!chatroomId) {
        const room = await createChatroom();
        if (!room) {
          appendMessage("llm", "대화방을 생성하지 못했습니다. 잠시 후 다시 시도해주세요.");
          return;
        }
        chatroomId = room.chatroom_id;
        page.dataset.chatroomId = chatroomId;
        window.history.replaceState(null, "", `/chat/${chatroomId}`);
        activateChatroom(chatroomId);
      }

      const typingEl = appendMessage("llm", "…", true);

      const res = await fetch(`/chat/api/rooms/${chatroomId}/messages/send`, {
        method: "POST",
        headers: { 
          "Content-Type": "application/x-www-form-urlencoded",
          "X-CSRFToken": getCookie('csrftoken')
        },
        body: new URLSearchParams({ message: text }),
      });

      typingEl.remove();

      if (!res.ok) {
        appendMessage("llm", "응답을 가져오지 못했습니다. 잠시 후 다시 시도해주세요.");
        return;
      }

      const data = await res.json();
      appendMessage("llm", data.message, false, data.sources, data.rag_degraded);

      if (window.loadChatroomList) window.loadChatroomList();
    } finally {
      setSending(false);
    }
  });

  async function createChatroom() {
    const res = await fetch("/chat/api/rooms/create", { 
      method: "POST",
      headers: {
        "X-CSRFToken": getCookie('csrftoken')
      }
    });
    if (!res.ok) return null;
    return res.json();
  }

  function activateChatroom(id) {
    document.querySelectorAll(".app-sidebar .nav-item.active").forEach(el => el.classList.remove("active"));

    const list = document.getElementById("chatroom-list");
    if (list) list.dataset.activeId = id;

    if (window.loadChatroomList) window.loadChatroomList();
  }

  async function loadMessages(id) {
    const res = await fetch(`/chat/api/rooms/${id}/messages`);
    if (!res.ok) return;

    const data = await res.json();
    messagesEl.innerHTML = "";
    data.items.forEach(m => appendMessage(m.speaker, m.message, false, m.sources));
  }

  function formatSource(source) {
    const name = (source.original_file_name || "").replace(/\.[^/.]+$/, "");
    return source.page ? `${name} p.${source.page}` : name;
  }

  function appendMessage(speaker, text, isTyping, sources, ragDegraded) {
    const wrap = document.createElement("div");
    wrap.className = `chat-turn ${speaker}`;

    const bubble = document.createElement("div");
    bubble.className = `chat-message ${speaker}` + (isTyping ? " typing" : "");
    bubble.textContent = text;
    wrap.appendChild(bubble);

    if (speaker === "llm" && !isTyping && ((sources && sources.length) || ragDegraded)) {
      const src = document.createElement("div");
      const icon = document.createElement("span");
      const label = document.createElement("span");
      icon.className = "chat-sources-icon";
      label.className = "chat-sources-text";

      if (sources && sources.length && !ragDegraded) {
        src.className = "chat-sources";
        icon.textContent = "📄";
        label.textContent = `근거 문서 ${sources.length}건 · ${sources.map(formatSource).join(", ")}`;
        src.title = "근거 문서\n" + sources.map(formatSource).join("\n");
      } else {
        src.className = "chat-sources degraded";
        icon.textContent = "⚠️";
        label.textContent = "근거 문서를 찾지 못했습니다";
      }

      src.appendChild(icon);
      src.appendChild(label);
      wrap.appendChild(src);
    }

    messagesEl.appendChild(wrap);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return wrap;
  }
});
