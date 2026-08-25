document.addEventListener("DOMContentLoaded", function () {
  loadChatroomList();
});

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function getCookie(name) {
  const cookies = document.cookie ? document.cookie.split(";") : [];
  for (const cookie of cookies) {
    const trimmed = cookie.trim();
    if (trimmed.startsWith(`${name}=`)) {
      return decodeURIComponent(trimmed.slice(name.length + 1));
    }
  }
  return null;
}

async function loadChatroomList() {
  const container = document.getElementById("chatroom-list");
  if (!container) return;

  const res = await fetch("/chat/api/rooms");
  if (!res.ok) return;

  const data = await res.json();
  const activeId = container.dataset.activeId;

  if (!data.items.length) {
    container.innerHTML = `<div class="chatroom-empty">대화 내역이 없습니다</div>`;
    return;
  }

  container.innerHTML = data.items.map(room => `
        <div class="chatroom-item ${room.chatroom_id === activeId ? "active" : ""}">
            <a class="chatroom-link" href="/chat/${room.chatroom_id}">${escapeHtml(room.chatroom_name)}</a>
            <button type="button" class="chatroom-delete" data-chatroom-id="${room.chatroom_id}" title="삭제">×</button>
        </div>
    `).join("");
}

document.addEventListener("click", async function (e) {
  const delBtn = e.target.closest(".chatroom-delete");
  if (!delBtn) return;
  e.preventDefault();

  if (!confirm("이 대화를 삭제할까요?")) return;

  const chatroomId = delBtn.dataset.chatroomId;

  try {
    const res = await fetch(`/chat/api/rooms/${encodeURIComponent(chatroomId)}/delete`, {
      method: "DELETE",
      headers: { "X-CSRFToken": getCookie("csrftoken") },
      credentials: "same-origin",
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      alert(data.detail || "대화 삭제에 실패했습니다. 잠시 후 다시 시도해주세요.");
      return;
    }
  } catch (error) {
    console.error("Chatroom deletion failed:", error);
    alert("대화 삭제에 실패했습니다. 네트워크 상태를 확인해주세요.");
    return;
  }

  if (window.location.pathname === `/chat/${chatroomId}`) {
    window.location.href = "/chat";
    return;
  }

  loadChatroomList();
});
