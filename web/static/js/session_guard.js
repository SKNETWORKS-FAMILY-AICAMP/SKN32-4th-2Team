/**
 * 로그인 이후 화면에서만 로드된다 (layout/app_base.html).
 *
 * window.fetch를 래핑하여 모든 API 요청의 401 응답을 전역 처리한다.
 * 세션이 만료된 경우 세션 만료 안내를 표시한 뒤 로그인 화면으로 이동시킨다.
 *
 * 페이지별 JavaScript(users.js, user_modal.js 등)에서 401 처리를 반복하지 않고,
 * 이 파일을 먼저 로드하는 것만으로 전체 API 호출에 동일한 동작을 적용할 수 있다.
 *
 * 참고:
 * /auth/login의 로그인 실패 401 응답은 일반 form 제출 방식이므로 fetch를 거치지 않는다.
 * 따라서 이 로직의 세션 만료 처리와 충돌하지 않는다.
 */
(function () {
  const originalFetch = window.fetch;
  let alreadyHandling = false; // 한 화면에서 여러 요청이 동시에 401을 받아도 알림은 한 번만

  window.fetch = async function (...args) {
    const response = await originalFetch(...args);

    if (response.status === 401 && !alreadyHandling) {
      alreadyHandling = true;
      alert("세션이 만료되었습니다. 다시 로그인해주세요.");
      window.location.href = "/login";
    }

    return response;
  };
})();