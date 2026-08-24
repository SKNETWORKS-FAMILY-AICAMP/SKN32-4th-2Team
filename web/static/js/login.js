(function () {
  const overlay = document.getElementById("signup-overlay");
  const openBtn = document.getElementById("open-signup");
  const closeBtn = document.getElementById("close-signup");
  const form = document.getElementById("signup-form");
  const notice = document.getElementById("signup-notice");

  function openModal() {
    overlay.classList.add("open");
    notice.className = "form-notice";
    notice.textContent = "";
    document.getElementById("signup-user-id").focus();
  }

  function closeModal() {
    overlay.classList.remove("open");
    form.reset();
  }

  openBtn.addEventListener("click", openModal);
  closeBtn.addEventListener("click", closeModal);
  overlay.addEventListener("click", function (e) {
    if (e.target === overlay) closeModal();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && overlay.classList.contains("open")) closeModal();
  });

  form.addEventListener("submit", async function (e) {
    e.preventDefault();

    const passwd = document.getElementById("signup-passwd").value;
    const passwdConfirm = document.getElementById("signup-passwd-confirm").value;

    if (passwd !== passwdConfirm) {
      notice.className = "form-notice error show";
      notice.textContent = "비밀번호가 일치하지 않습니다.";
      return;
    }

    const formData = new FormData(form);

    try {
      const res = await fetch("/auth/signup", { method: "POST", body: formData });
      const data = await res.json();

      if (!res.ok) {
        notice.className = "form-notice error show";
        notice.textContent = data.detail || "회원가입에 실패했습니다.";
        return;
      }

      notice.className = "form-notice success show";
      notice.textContent = data.detail;

      setTimeout(function () {
        closeModal();
        document.getElementById("login-user-id").value = formData.get("user_id");
        document.getElementById("login-passwd").focus();
      }, 1200);
    } catch (err) {
      notice.className = "form-notice error show";
      notice.textContent = "네트워크 오류가 발생했습니다. 다시 시도해주세요.";
    }
  });
})();
