document.addEventListener("DOMContentLoaded", function () {
  loadChatroomList();
});

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
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
  const res = await fetch(`/chat/api/rooms/${chatroomId}`, { method: "DELETE" });
  if (!res.ok) return;

  if (window.location.pathname === `/chat/${chatroomId}`) {
    window.location.href = "/chat";
    return;
  }

  loadChatroomList();
});
