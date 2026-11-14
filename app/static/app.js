const $ = (s, el = document) => el.querySelector(s);
const api = async (path, opts = {}) => {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch {}
    throw new Error(msg);
  }
  return res.json();
};
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ---------- Character ----------
async function loadCharacter() {
  const c = await api("/api/character");
  $("#outfit").value = c.default_outfit || "";
  $("#rules").value = (c.consistency_rules || []).join("\n");
  $("#refs").innerHTML = c.references.length
    ? c.references.map((n) => `<div class="ref"><img src="/api/character/references/${encodeURIComponent(n)}" alt=""><button data-name="${esc(n)}" aria-label="삭제">×</button></div>`).join("")
    : `<p class="hint">등록된 레퍼런스 이미지가 없습니다.</p>`;
}
$("#refs").addEventListener("click", async (e) => {
  const name = e.target.dataset?.name;
  if (!name || !confirm("이 이미지를 삭제할까요?")) return;
  await api(`/api/character/references/${encodeURIComponent(name)}`, { method: "DELETE" });
  loadCharacter();
});
$("#ref-input").addEventListener("change", async (e) => {
  for (const file of e.target.files) {
    const fd = new FormData();
    fd.append("file", file);
    try { await api("/api/character/references", { method: "POST", body: fd }); }
    catch (err) { alert(`업로드 실패: ${err.message}`); }
  }
  e.target.value = "";
  loadCharacter();
});
$("#save-character").addEventListener("click", async () => {
  await api("/api/character", {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ consistency_rules: $("#rules").value.split("\n"), default_outfit: $("#outfit").value }),
  });
  alert("저장되었습니다.");
});

// ---------- Scenes ----------
function addScene(v = {}) {
  const node = $("#scene-tpl").content.firstElementChild.cloneNode(true);
  $(".visual", node).value = v.visual || "";
  $(".subtitle", node).value = v.subtitle || "";
  $(".camera", node).value = v.camera || "";
  $(".duration", node).value = String(v.duration || 5);
  $(".remove", node).onclick = () => { node.remove(); renumber(); };
  $("#scenes").appendChild(node);
  renumber();
}
function renumber() { document.querySelectorAll(".scene-no").forEach((el, i) => (el.textContent = `#${i + 1}`)); }
$("#add-scene").onclick = () => addScene();

[
  { visual: "SEOA walks into a bright minimal hotel room and opens the white curtains, revealing the ocean", subtitle: "제주 애월, 오션뷰 숙소 도착 🌊", camera: "slow follow from behind" },
  { visual: "SEOA sits by the window with a coffee cup, smiling at the sea in soft morning light", subtitle: "아침 햇살 맞으며 커피 한 잔", camera: "slow dolly in" },
  { visual: "SEOA walks barefoot on the beach at golden hour, hair moving in the wind", subtitle: "노을까지 완벽했던 하루", camera: "side tracking shot" },
].forEach(addScene);

// ---------- Jobs ----------
$("#create-job").onclick = async () => {
  const scenes = [...document.querySelectorAll(".scene")].map((el) => ({
    visual_prompt: $(".visual", el).value.trim(),
    subtitle_ko: $(".subtitle", el).value.trim(),
    camera: $(".camera", el).value.trim(),
    duration_seconds: Number($(".duration", el).value),
  }));
  const body = {
    title: $("#title").value.trim(), location: $("#location").value.trim(),
    style_notes: $("#style").value.trim(), extra_consistency_notes: $("#extra-rules").value.trim(),
    add_cta: $("#add-cta").checked, scenes,
  };
  const btn = $("#create-job");
  btn.disabled = true; $("#form-msg").textContent = "작업 생성 중…";
  try {
    const job = await api("/api/jobs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    $("#form-msg").textContent = job.mode === "live"
      ? "비용을 확인하는 중입니다. 작업 목록에서 승인해야 실제 생성이 시작됩니다."
      : "작업이 시작되었습니다 (MOCK, 무료).";
  }
  catch (err) { $("#form-msg").textContent = `오류: ${err.message}`; }
  finally { btn.disabled = false; loadJobs(); }
};

const STATUS_KO = {
  queued: "대기", estimating: "비용 확인 중", awaiting_approval: "승인 대기", generating: "생성 중",
  editing: "편집 중", done: "완료", failed: "실패", canceled: "취소됨",
};
const SCENE_KO = {
  pending: "대기", submitted: "요청됨", queued: "Higgsfield 대기열", in_progress: "생성 중", completed: "완료",
  failed: "실패", nsfw: "검수 차단", canceled: "취소", timeout: "시간 초과",
};
const ACTIVE = ["queued", "estimating", "generating", "editing"];
const usd = (v) => (v == null ? "?" : `$${Number(v).toFixed(2)}`);

function sceneRows(j) {
  return j.scenes.map((sc) => {
    const scene = j.request.scenes[sc.index] || {};
    const cls = sc.clip_ready ? "done" : ["failed", "nsfw", "timeout", "canceled"].includes(sc.status) ? "failed" : "";
    return `<li class="scene-row">
      <div><strong>#${sc.index + 1}</strong> <span class="status ${cls}">${SCENE_KO[sc.status] || esc(sc.status)}</span>
        ${j.mode === "live" && sc.estimate_usd != null ? `<span class="hint">예상 ${usd(sc.estimate_usd)}</span>` : ""}
        ${sc.clip_ready ? `<a href="/api/jobs/${j.id}/clips/${sc.index}" download>클립 다운로드</a>` : ""}</div>
      <div class="hint">${esc(scene.subtitle_ko || scene.visual_prompt || "")}</div>
      ${sc.error ? `<div class="error">${esc(sc.error)}</div>` : ""}
    </li>`;
  }).join("");
}

function jobActions(j) {
  if (j.status === "awaiting_approval") {
    return `<div class="approve-box">
      <p><strong>실제 Higgsfield 생성 승인</strong> — 크레딧이 사용됩니다.<br>
      장면 ${j.scenes.filter((s) => !s.clip_ready).length}개 · 예상 비용 <strong>${usd(j.estimate_total_usd)}</strong></p>
      <div class="row"><button class="btn primary" data-act="approve" data-id="${j.id}">승인하고 생성</button>
      <button class="btn secondary" data-act="cancel" data-id="${j.id}">취소</button></div></div>`;
  }
  if (j.status === "failed" && j.scenes.some((s) => !s.clip_ready)) {
    return `<button class="btn secondary" data-act="retry" data-id="${j.id}">실패 장면 다시 시도${j.mode === "live" ? " (비용 확인 후 승인)" : ""}</button>`;
  }
  return "";
}

$("#jobs").addEventListener("click", async (e) => {
  const { act, id } = e.target.dataset || {};
  if (!act) return;
  if (act === "approve" && !confirm("Higgsfield 크레딧을 사용해 실제 영상을 생성합니다. 진행할까요?")) return;
  e.target.disabled = true;
  try { await api(`/api/jobs/${id}/${act}`, { method: "POST" }); }
  catch (err) { alert(`오류: ${err.message}`); }
  loadJobs();
});

let pollTimer = null;
async function loadJobs() {
  clearTimeout(pollTimer);
  const jobs = await api("/api/jobs");
  $("#jobs").innerHTML = jobs.length ? jobs.map((j) => `
    <div class="job">
      <div class="job-head"><strong>${esc(j.request.title)}</strong>
        <span class="status ${j.status}">${STATUS_KO[j.status] || j.status} · ${j.mode.toUpperCase()}</span></div>
      <progress max="1" value="${j.progress}"></progress>
      <span class="hint">${esc(j.message)}</span>
      <ul class="scene-list">${sceneRows(j)}</ul>
      ${jobActions(j)}
      ${j.status === "done" ? `<video src="/api/jobs/${j.id}/video" controls playsinline preload="metadata"></video>
        <a class="btn secondary" href="/api/jobs/${j.id}/video" download>최종 릴스 MP4 다운로드</a>` : ""}
    </div>`).join("") : `<p class="hint">아직 작업이 없습니다.</p>`;
  if (jobs.some((j) => ACTIVE.includes(j.status))) pollTimer = setTimeout(loadJobs, 3000);
}

api("/api/status").then((s) => {
  $("#cta-text").textContent = s.cta_text;
  const warn = [];
  if (!s.ffmpeg_available) warn.push("서버에 FFmpeg가 설치되어 있지 않습니다.");
  if (s.mode === "live" && !s.password_protected) warn.push("live 모드에는 APP_PASSWORD 설정이 필요합니다.");
  if (s.higgsfield_credentials === "incomplete") warn.push("Higgsfield 키 형식이 KEY_ID:KEY_SECRET 이 아닙니다.");
  $("#create-job").textContent = s.mode === "live" ? "비용 확인하기 (생성 전 승인 필요)" : "릴스 만들기 (MOCK · 무료)";
  $("#server-info").textContent = s.mode === "live" ? `모델: ${s.model} · ${s.video_resolution_tier} · 9:16` : "MOCK 모드: 크레딧 사용 없음";
  if (warn.length) $("#form-msg").textContent = "⚠️ " + warn.join(" ");
});
loadCharacter();
loadJobs();
