(function () {
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

  const overlay = document.getElementById("user-modal-overlay");
  if (!overlay) return;

  const form = document.getElementById("user-modal-form");
  const notice = document.getElementById("user-modal-notice");
  const titleEl = document.getElementById("user-modal-title");
  const submitBtn = document.getElementById("user-modal-submit");

  const userIdInput = document.getElementById("user-modal-user-id");
  const checkIdBtn = document.getElementById("check-user-id-btn");
  const checkIdResult = document.getElementById("user-id-check-result");
  const passwdInput = document.getElementById("user-modal-passwd");
  const passwdConfirmInput = document.getElementById("user-modal-passwd-confirm");
  const passwdConfirmField = document.getElementById("field-passwd-confirm");
  const nameInput = document.getElementById("user-modal-name");
  const departmentInput = document.getElementById("user-modal-department");
  const adminStatusField = document.getElementById("field-admin-status");
  const isAdminInput = document.getElementById("user-modal-is-admin");
  const isDisabledInput = document.getElementById("user-modal-is-disabled");
  const signupHintField = document.getElementById("field-signup-hint");
  const deleteBtn = document.getElementById("delete-account-btn");

  // 모드별 차이점: 안내문구(회원가입만) / 아이디 수정가능여부 / 비번확인 표시여부 / 관리자·비활성 표시여부
  const MODE_CONFIG = {
    signup: {
      title: "회원가입", submitLabel: "가입하기",
      action: "/login/auth/signup", method: "POST",
      userIdEditable: true, showPasswdConfirm: true, passwdRequired: true,
      showAdminStatus: false, showSignupHint: true,
    },
    create: {
      title: "사용자 추가", submitLabel: "추가하기",
      action: "/admin/users/api/create", method: "POST",
      userIdEditable: true, showPasswdConfirm: true, passwdRequired: true,
      showAdminStatus: true, showSignupHint: false,
    },
    edit: {
      title: "사용자 정보 수정", submitLabel: "저장",
      action: null, method: "PATCH",
      userIdEditable: false, showPasswdConfirm: false, passwdRequired: false,
      showAdminStatus: true, showSignupHint: false,
    },
  };

  window.openUserModal = function (mode, prefill) {
    prefill = prefill || {};
    const config = MODE_CONFIG[mode];

    form.dataset.mode = mode;
    form.dataset.method = config.method;
    form.dataset.action = mode === "edit"
      ? `/admin/users/api/${encodeURIComponent(prefill.userId)}/update`
      : config.action;

    titleEl.textContent = config.title;
    submitBtn.textContent = config.submitLabel;

    userIdInput.value = prefill.userId || "";
    userIdInput.readOnly = !config.userIdEditable;
    checkIdBtn.classList.toggle("hidden", !config.userIdEditable);
    checkIdResult.className = "field-hint";
    checkIdResult.textContent = "";

    passwdInput.value = "";
    passwdInput.required = config.passwdRequired;
    passwdInput.placeholder = config.passwdRequired ? "8자 이상" : "변경할 때만 입력하세요";

    passwdConfirmInput.value = "";
    passwdConfirmField.classList.toggle("hidden", !config.showPasswdConfirm);

    nameInput.value = prefill.name || "";
    departmentInput.value = prefill.department || "";

    adminStatusField.classList.toggle("hidden", !config.showAdminStatus);
    isAdminInput.checked = !!prefill.isAdmin;
    isDisabledInput.checked = !!prefill.isDisabled;

    // 이용/채팅 내역 분석 안내는 '회원가입'에서만 노출 (사용자 관리 쪽 추가/수정에는 안 보임)
    signupHintField.classList.toggle("hidden", !config.showSignupHint);

    // 계정 삭제는 수정 모드에서만, 대상 아이디를 버튼에 기억해둔다
    deleteBtn.classList.toggle("hidden", mode !== "edit");
    deleteBtn.dataset.userId = prefill.userId || "";

    notice.className = "form-notice";
    notice.textContent = "";

    overlay.classList.add("open");
    (config.userIdEditable ? userIdInput : nameInput).focus();
  };

  function closeModal() {
    overlay.classList.remove("open");
    form.reset();
  }

  overlay.querySelectorAll("[data-modal-close]").forEach(function (btn) {
    btn.addEventListener("click", closeModal);
  });
  overlay.addEventListener("click", function (e) {
    if (e.target === overlay) closeModal();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && overlay.classList.contains("open")) closeModal();
  });

  userIdInput.addEventListener("input", function () {
    checkIdResult.className = "field-hint";
    checkIdResult.textContent = "";
  });

  checkIdBtn.addEventListener("click", async function () {
    const id = userIdInput.value.trim();

    if (!id) {
      checkIdResult.className = "field-hint error";
      checkIdResult.textContent = "아이디를 입력해주세요.";
      return;
    }

    checkIdResult.className = "field-hint";
    checkIdResult.textContent = "확인 중...";

    try {
      const res = await fetch(`/login/auth/check-user-id?user_id=${encodeURIComponent(id)}`);
      const data = await res.json();

      if (data.available) {
        checkIdResult.className = "field-hint success";
        checkIdResult.textContent = data.detail || "사용 가능한 아이디입니다.";
      } else {
        checkIdResult.className = "field-hint error";
        checkIdResult.textContent = data.detail || "이미 사용 중인 아이디입니다.";
      }
    } catch (err) {
      checkIdResult.className = "field-hint error";
      checkIdResult.textContent = "확인 중 오류가 발생했습니다.";
    }
  });

  deleteBtn.addEventListener("click", async function () {
    const userId = deleteBtn.dataset.userId;
    if (!userId) return;

    if (!confirm(`정말로 "${userId}" 계정을 삭제할까요? 이 작업은 되돌릴 수 없습니다.`)) {
      return;
    }

    try {
      const res = await fetch(`/admin/users/api/${encodeURIComponent(userId)}/delete`, { 
        method: "DELETE",
        headers: {
          'X-CSRFToken': getCookie('csrftoken')
        }
      });
      const data = await res.json();

      if (!res.ok) {
        notice.className = "form-notice error show";
        notice.textContent = data.detail || "삭제에 실패했습니다.";
        return;
      }

      notice.className = "form-notice success show";
      notice.textContent = data.detail;

      setTimeout(function () {
        closeModal();
        document.dispatchEvent(new CustomEvent("user-modal:success", {
          detail: { mode: "delete", userId: userId, message: data.detail },
        }));
      }, 600);
    } catch (err) {
      notice.className = "form-notice error show";
      notice.textContent = "네트워크 오류가 발생했습니다. 다시 시도해주세요.";
    }
  });

  form.addEventListener("submit", async function (e) {
    e.preventDefault();
    const mode = form.dataset.mode;

    if (mode !== "edit" && passwdInput.value !== passwdConfirmInput.value) {
      notice.className = "form-notice error show";
      notice.textContent = "비밀번호가 일치하지 않습니다.";
      return;
    }

    const formData = new FormData(form);
    const userId = userIdInput.value;

    if (mode === "edit") {
      formData.delete("user_id");
      formData.delete("passwd_confirm");
      if (!passwdInput.value) formData.delete("passwd");
      formData.set("is_admin", isAdminInput.checked ? "true" : "false");
      formData.set("is_disabled", isDisabledInput.checked ? "true" : "false");
    }

    try {
      const res = await fetch(form.dataset.action, { 
        method: form.dataset.method, 
        body: formData,
        headers: {
          'X-CSRFToken': getCookie('csrftoken')
        }
      });
      const data = await res.json();

      if (!res.ok) {
        notice.className = "form-notice error show";
        notice.textContent = data.detail || "처리에 실패했습니다.";
        return;
      }

      notice.className = "form-notice success show";
      notice.textContent = data.detail;

      setTimeout(function () {
        closeModal();
        document.dispatchEvent(new CustomEvent("user-modal:success", {
          detail: { mode: mode, userId: userId, message: data.detail },
        }));
      }, 800);
    } catch (err) {
      notice.className = "form-notice error show";
      notice.textContent = "네트워크 오류가 발생했습니다. 다시 시도해주세요.";
    }
  });
})();