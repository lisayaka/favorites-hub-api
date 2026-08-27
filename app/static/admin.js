const keyForm = document.querySelector("#key-form");
const keyInput = document.querySelector("#admin-key");
const createForm = document.querySelector("#create-form");
const createButton = document.querySelector("#create-button");
const refreshButton = document.querySelector("#refresh-accounts");
const accountsBody = document.querySelector("#accounts-body");
const accountSummary = document.querySelector("#account-summary");
const emptyState = document.querySelector("#empty-state");
const tokenPanel = document.querySelector("#token-panel");
const tokenValue = document.querySelector("#token-value");
const copyTokenButton = document.querySelector("#copy-token");
const closeTokenButton = document.querySelector("#close-token");
const toast = document.querySelector("#toast");

const errorMessages = {
  account_email_exists: "该邮箱账户已经存在。",
  account_not_found: "账户不存在，请刷新列表。",
  account_not_rechargeable: "账户已撤销或 Token 已过期，无法充值。",
  idempotency_key_conflict: "充值请求冲突，请重新操作。",
  invalid_admin_api_key: "管理员密钥无效。",
  admin_api_key_not_configured: "服务端尚未配置管理员密钥。",
};

let toastTimer;

keyInput.value = sessionStorage.getItem("favoritesHubAdminKey") || "";

keyForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  sessionStorage.setItem("favoritesHubAdminKey", keyInput.value.trim());
  await loadAccounts();
});

createForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  createButton.disabled = true;
  createButton.textContent = "正在创建…";

  const data = new FormData(createForm);
  try {
    const created = await request("/v1/admin/accounts", {
      method: "POST",
      body: JSON.stringify({
        email: data.get("email"),
        token_type: data.get("token_type"),
        expires_in_days: Number(data.get("expires_in_days")),
        total_quota: Number(data.get("total_quota")),
      }),
    });
    tokenValue.value = created.app_token;
    tokenPanel.hidden = false;
    createForm.elements.email.value = "";
    showToast(`已创建 ${created.account.email}`);
    await loadAccounts(false);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    createButton.disabled = false;
    createButton.textContent = "创建并签发 Token";
  }
});

refreshButton.addEventListener("click", () => loadAccounts());

accountsBody.addEventListener("click", async (event) => {
  const rechargeButton = event.target.closest("[data-recharge-id]");
  if (rechargeButton && !rechargeButton.disabled) {
    const value = window.prompt(`为 ${rechargeButton.dataset.email} 充值多少 credit？`, "100");
    if (value === null) return;
    const credits = Number(value);
    if (!Number.isInteger(credits) || credits < 1 || credits > 1000000) {
      showToast("请输入 1～1000000 的整数额度。", true);
      return;
    }
    rechargeButton.disabled = true;
    try {
      const result = await request(`/v1/admin/accounts/${rechargeButton.dataset.rechargeId}/credits`, {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ credits }),
      });
      showToast(`已充值 ${result.credits} credit，剩余 ${result.remaining_quota}`);
      await loadAccounts(false);
    } catch (error) {
      showToast(error.message, true);
      rechargeButton.disabled = false;
    }
    return;
  }

  const button = event.target.closest("[data-revoke-id]");
  if (!button || button.disabled) return;
  if (!window.confirm(`确认撤销账户 ${button.dataset.email}？撤销后应用 Token 将立即失效。`)) return;

  button.disabled = true;
  try {
    await request(`/v1/admin/accounts/${button.dataset.revokeId}/revoke`, { method: "POST" });
    showToast("账户已撤销");
    await loadAccounts(false);
  } catch (error) {
    showToast(error.message, true);
    button.disabled = false;
  }
});

copyTokenButton.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(tokenValue.value);
  } catch {
    tokenValue.select();
    document.execCommand("copy");
  }
  showToast("Token 已复制");
});

closeTokenButton.addEventListener("click", () => {
  tokenPanel.hidden = true;
  tokenValue.value = "";
});

async function loadAccounts(notify = true) {
  if (!sessionStorage.getItem("favoritesHubAdminKey")) {
    keyInput.focus();
    showToast("请先输入管理员密钥。", true);
    return;
  }

  refreshButton.disabled = true;
  refreshButton.textContent = "加载中…";
  try {
    const accounts = await request("/v1/admin/accounts");
    renderAccounts(accounts);
    if (notify) showToast("账户列表已更新");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    refreshButton.disabled = false;
    refreshButton.textContent = "刷新";
  }
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Admin-Key": sessionStorage.getItem("favoritesHubAdminKey") || "",
      ...options.headers,
    },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const code = body.detail?.code;
    if (response.status === 401) keyInput.focus();
    throw new Error(errorMessages[code] || `请求失败（${response.status}）`);
  }
  return body;
}

function renderAccounts(accounts) {
  accountsBody.replaceChildren();
  emptyState.hidden = accounts.length > 0;
  emptyState.querySelector("strong").textContent = accounts.length ? "" : "还没有账户";
  emptyState.querySelector("span").textContent = accounts.length ? "" : "通过左侧表单创建第一个账户。";

  const activeCount = accounts.filter((account) => account.status === "active").length;
  accountSummary.textContent = `${accounts.length} 个账户 · ${activeCount} 个有效`;

  for (const account of accounts) {
    const token = account.tokens[0];
    const row = document.createElement("tr");
    row.append(
      cell(account.email),
      statusCell(account.status),
      cell(token ? `${token.token_type} · ${token.prefix}…` : "—", "token-type"),
      cell(token ? `${token.used_quota} / ${token.total_quota}` : "—"),
      cell(token ? formatDate(token.expires_at) : "—"),
      actionCell(account, token),
    );
    accountsBody.append(row);
  }
}

function cell(value, className) {
  const element = document.createElement("td");
  element.textContent = value;
  if (className) element.className = className;
  return element;
}

function statusCell(status) {
  const element = document.createElement("td");
  const badge = document.createElement("span");
  badge.className = `status status-${status}`;
  badge.textContent = status === "active" ? "有效" : "已撤销";
  element.append(badge);
  return element;
}

function actionCell(account, token) {
  const element = document.createElement("td");
  const actions = document.createElement("div");
  actions.className = "account-actions";
  const recharge = document.createElement("button");
  recharge.type = "button";
  recharge.className = "recharge-button";
  recharge.textContent = "充值";
  recharge.disabled = account.status !== "active" || token?.status !== "active" || new Date(token.expires_at) <= new Date();
  recharge.dataset.rechargeId = account.id;
  recharge.dataset.email = account.email;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "revoke-button";
  button.textContent = account.status === "active" ? "撤销" : "已撤销";
  button.disabled = account.status !== "active";
  button.dataset.revokeId = account.id;
  button.dataset.email = account.email;
  actions.append(recharge, button);
  element.append(actions);
  return element;
}

function formatDate(value) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(value));
}

function showToast(message, isError = false) {
  window.clearTimeout(toastTimer);
  toast.textContent = message;
  toast.className = isError ? "toast toast-error" : "toast";
  toast.hidden = false;
  toastTimer = window.setTimeout(() => {
    toast.hidden = true;
  }, 2800);
}
