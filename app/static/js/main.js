const form = document.getElementById("shorten-form");
const submitBtn = document.getElementById("submit-btn");
const errorMessage = document.getElementById("error-message");
const result = document.getElementById("result");
const resultLink = document.getElementById("result-link");
const resultExpiry = document.getElementById("result-expiry");
const resultAliasBadge = document.getElementById("result-alias-badge");
const copyBtn = document.getElementById("copy-btn");

const toggleAdvancedBtn = document.getElementById("toggle-advanced");
const advancedOptions = document.getElementById("advanced-options");
const customAliasInput = document.getElementById("custom_alias");
const ttlInput = document.getElementById("ttl");

toggleAdvancedBtn.addEventListener("click", () => {
  const isHidden = advancedOptions.hidden;
  advancedOptions.hidden = !isHidden;
  toggleAdvancedBtn.textContent = isHidden ? "- Hide options" : "+ Custom alias / expiry";
});

function showError(message) {
  errorMessage.textContent = message;
  errorMessage.hidden = false;
  result.hidden = true;
}

function showResult(shortUrl, expiresAt, usedCustomAlias) {
  errorMessage.hidden = true;
  resultLink.textContent = shortUrl;
  resultLink.href = shortUrl;
  resultExpiry.textContent = expiresAt
    ? `Expires ${new Date(expiresAt).toLocaleString()}`
    : "Never expires";
  resultAliasBadge.hidden = !usedCustomAlias;
  result.hidden = false;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  submitBtn.disabled = true;
  submitBtn.querySelector(".btn-label").textContent = "Shortening...";

  const longUrl = document.getElementById("long_url").value.trim();
  const customAlias = customAliasInput.value.trim();
  const ttl = ttlInput.value;

  const payload = { url: longUrl };
  if (customAlias) payload.custom_alias = customAlias;
  if (ttl) payload.ttl = parseInt(ttl, 10);

  try {
    const response = await fetch("/api/url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await response.json();

    if (!response.ok || !body.status) {
      showError(body.message || "Something went wrong. Please try again.");
      return;
    }

    const shortUrl = `${window.location.origin}/${body.data.short_code}`;
    showResult(shortUrl, body.data.expires_at, Boolean(customAlias));
    form.reset();
    advancedOptions.hidden = true;
    toggleAdvancedBtn.textContent = "+ Custom alias / expiry";
  } catch (err) {
    showError("Network error - please check your connection and try again.");
  } finally {
    submitBtn.disabled = false;
    submitBtn.querySelector(".btn-label").textContent = "Shorten";
  }
});

copyBtn.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(resultLink.href);
    const original = copyBtn.textContent;
    copyBtn.textContent = "Copied!";
    setTimeout(() => {
      copyBtn.textContent = original;
    }, 1500);
  } catch (err) {
    showError("Could not copy to clipboard - copy the link manually.");
  }
});
