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
  $(".duration", node).value = String(v.duration || 3);
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
function reelBody() {
  const els = [...document.querySelectorAll(".scene")];
  const scenes = els.map((el) => ({
    visual_prompt: $(".visual", el).value.trim(),
    subtitle_ko: $(".subtitle", el).value.trim(),
    camera: $(".camera", el).value.trim(),
    duration_seconds: Number($(".duration", el).value),
  }));
  const picked = els.map((el, i) => ($(".pick-scene", el).checked ? i : -1)).filter((i) => i >= 0);
  return {
    title: $("#title").value.trim(), location: $("#location").value.trim(),
    style_notes: $("#style").value.trim(), extra_consistency_notes: $("#extra-rules").value.trim(),
    add_cta: $("#add-cta").checked, dry_run: $("#dry-run").checked,
    scene_indices: picked.length === scenes.length ? null : picked, scenes,
  };
}

$("#preview-btn").onclick = async () => {
  const out = $("#preview-out");
  out.innerHTML = `<p class="hint">미리보기 생성 중…</p>`;
  try {
    const p = await api("/api/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(reelBody()) });
    out.innerHTML = `<div class="preview">
      <p><strong>${esc(p.settings.label)}</strong> · ${esc(p.settings.resolution)} · 레퍼런스 ${p.reference_images}장 · 실제 생성 최대 ${p.max_clips_per_job}개 장면</p>
      ${p.warnings.map((w) => `<p class="error">${esc(w)}</p>`).join("")}
      ${p.scenes.map((sc) => `<details ${sc.selected ? "" : "class=muted"}>
        <summary>#${sc.index + 1} ${sc.selected ? "" : "(제외)"} · 생성 ${sc.generated_seconds}초 → 타임라인 ${sc.timeline_seconds}초
          ${sc.reusable ? `<span class="status done">재사용 (무료)</span>` : ""} — ${esc(sc.subtitle_ko)}</summary>
        <pre>${esc(JSON.stringify(sc.request_body, null, 2))}</pre></details>`).join("")}
      ${p.cta_text ? `<p class="hint">마지막 CTA: ${esc(p.cta_text)} (서버에서 FFmpeg로 삽입)</p>` : ""}</div>`;
  } catch (err) { out.innerHTML = `<p class="error">${esc(err.message)}</p>`; }
};

$("#create-job").onclick = async () => {
  const body = reelBody();
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
        ${sc.reused ? `<span class="status done">재사용 · $0</span>` : ""}
        ${j.mode === "live" && sc.estimate_usd != null && !sc.reused ? `<span class="hint">예상 ${usd(sc.estimate_usd)}</span>` : ""}
        ${sc.generated_seconds ? `<span class="hint">${sc.generated_seconds}초 생성</span>` : ""}
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
      모델 ${esc(j.model)} · ${esc(j.resolution || "")} · 생성 ${j.scenes.filter((s) => !s.clip_ready).length}개 장면<br>
      예상 비용 <strong>${usd(j.estimate_total_usd)}</strong> (Higgsfield 견적, USD)</p>
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
      ${j.mode === "live" ? `<span class="hint">모델 ${esc(j.model)} · ${esc(j.resolution || "")}</span>` : ""}
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
  const g = s.generation || {};
  if (g.warning) warn.push(g.warning);
  const syncButton = () => {
    const real = s.mode === "live" && !$("#dry-run").checked;
    $("#create-job").textContent = real ? `비용 확인하기 (선택 장면 최대 ${s.max_clips_per_job}개 · 승인 필요)` : "릴스 만들기 (MOCK · 무료)";
  };
  $("#dry-run").onchange = syncButton;
  if (s.mode !== "live") { $("#dry-run").checked = true; $("#dry-run").disabled = true; }
  syncButton();
  $("#server-info").textContent = s.mode === "live" ? "LIVE 서버: 체크를 해제하면 실제 생성 (비용 확인 → 승인 후)" : "MOCK 모드: 크레딧 사용 없음";
  $("#gen-settings").innerHTML = g.model
    ? `현재 모델 <strong>${esc(g.label)}</strong> (${esc(g.model)}) · 해상도 <strong>${esc(g.resolution)}</strong> · 생성 길이 <strong>${g.duration_policy === "minimum" ? `최소 ${g.min_duration}초` : "장면 길이"}</strong> · 작업당 최대 ${s.max_clips_per_job}개 장면 · 한도 $${Number(s.max_usd_per_job).toFixed(2)}`
    : esc(g.warning || "모델 설정 오류");
  if (warn.length) $("#form-msg").textContent = "⚠️ " + warn.join(" ");
});
// ---------- Model cost comparison ----------
function renderCompare(c, selected) {
  if (!c) return "";
  return `<table class="cmp"><thead><tr><th>모델</th><th>설정</th><th>견적</th><th></th></tr></thead><tbody>
    ${c.rows.map((r) => `<tr class="${r.model === selected ? "sel" : ""}">
      <td>${esc(r.label)}</td><td>${r.duration}초 · ${esc(r.resolution)}</td>
      <td>${r.usd != null ? usd(r.usd) : `<span class="error">${esc(r.error || "?")}</span>`}</td>
      <td>${r.model === selected ? "사용 중" : r.usd != null ? `<button class="btn secondary small" data-model="${esc(r.model)}">사용</button>` : ""}</td></tr>`).join("")}
    </tbody></table><p class="hint">견적 시각 ${esc(c.checked_at)} · 가장 저렴: ${esc(c.cheapest || "-")}. 모델은 직접 선택할 때만 바뀝니다.</p>`;
}
async function loadModels() {
  try { const m = await api("/api/models"); $("#compare-result").innerHTML = renderCompare(m.last_comparison, m.selected); } catch {}
}
$("#compare-models").onclick = async (e) => {
  e.target.disabled = true;
  $("#compare-result").innerHTML = `<p class="hint">무료 견적 요청 중… (영상은 생성되지 않습니다)</p>`;
  try { await api("/api/models/compare", { method: "POST" }); await loadModels(); }
  catch (err) { $("#compare-result").innerHTML = `<p class="error">${esc(err.message)}</p>`; }
  e.target.disabled = false;
};
$("#compare-result").addEventListener("click", async (e) => {
  const model = e.target.dataset?.model;
  if (!model || !confirm(`${model} 모델로 바꿀까요?`)) return;
  try { await api("/api/models/select", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model }) }); location.reload(); }
  catch (err) { alert(err.message); }
});

loadCharacter();
loadJobs();
loadModels();
