const form = document.getElementById("stats-form");
const submitBtn = document.getElementById("submit-btn");
const errorMessage = document.getElementById("error-message");
const result = document.getElementById("result");
const resultLink = document.getElementById("result-link");
const resultAliasBadge = document.getElementById("result-alias-badge");
const statClicks = document.getElementById("stat-clicks");
const statCreated = document.getElementById("stat-created");
const statExpires = document.getElementById("stat-expires");

function extractShortCode(input) {
  const trimmed = input.trim();
  if (!trimmed) return "";

  try {
    const url = new URL(trimmed);
    const segments = url.pathname.split("/").filter(Boolean);
    return segments.length ? segments[segments.length - 1] : "";
  } catch (err) {
    // Not a full URL - treat it as a bare code, but still strip any slashes.
    const segments = trimmed.split("/").filter(Boolean);
    return segments.length ? segments[segments.length - 1] : trimmed;
  }
}

function showError(message) {
  errorMessage.textContent = message;
  errorMessage.hidden = false;
  result.hidden = true;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  submitBtn.disabled = true;
  submitBtn.querySelector(".btn-label").textContent = "Checking...";

  const code = extractShortCode(document.getElementById("code_input").value);

  if (!code) {
    showError("Please enter a short code or link.");
    submitBtn.disabled = false;
    submitBtn.querySelector(".btn-label").textContent = "Check";
    return;
  }

  try {
    const response = await fetch(`/api/url/${encodeURIComponent(code)}/stats`);
    const body = await response.json();

    if (!response.ok || !body.status) {
      showError(body.message || "Could not find that link.");
      return;
    }

    const data = body.data;
    errorMessage.hidden = true;
    const shortUrl = `${window.location.origin}/${data.short_code}`;
    resultLink.textContent = shortUrl;
    resultLink.href = shortUrl;
    resultAliasBadge.hidden = !data.is_custom_alias;
    statClicks.textContent = data.click_count;
    statCreated.textContent = new Date(data.created_at).toLocaleString();
    statExpires.textContent = data.expires_at
      ? new Date(data.expires_at).toLocaleString()
      : "Never";
    result.hidden = false;
  } catch (err) {
    showError("Network error - please check your connection and try again.");
  } finally {
    submitBtn.disabled = false;
    submitBtn.querySelector(".btn-label").textContent = "Check";
  }
});
