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
  try { await api("/api/jobs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); $("#form-msg").textContent = "작업이 시작되었습니다."; }
  catch (err) { $("#form-msg").textContent = `오류: ${err.message}`; }
  finally { btn.disabled = false; loadJobs(); }
};

const STATUS_KO = { queued: "대기", generating: "생성 중", editing: "편집 중", done: "완료", failed: "실패" };
async function loadJobs() {
  const jobs = await api("/api/jobs");
  $("#jobs").innerHTML = jobs.length ? jobs.map((j) => `
    <div class="job">
      <div class="job-head"><strong>${esc(j.request.title)}</strong>
        <span class="status ${j.status}">${STATUS_KO[j.status] || j.status} · ${j.mode.toUpperCase()}</span></div>
      <progress max="1" value="${j.progress}"></progress>
      <span class="hint">${esc(j.message)}</span>
      ${j.status === "done" ? `<video src="/api/jobs/${j.id}/video" controls playsinline preload="metadata"></video>
        <a href="/api/jobs/${j.id}/video" download>MP4 다운로드</a>` : ""}
    </div>`).join("") : `<p class="hint">아직 작업이 없습니다.</p>`;
  if (jobs.some((j) => !["done", "failed"].includes(j.status))) setTimeout(loadJobs, 2000);
}

api("/api/status").then((s) => { $("#cta-text").textContent = s.cta_text; if (!s.ffmpeg_available) $("#form-msg").textContent = "⚠️ 서버에 FFmpeg가 설치되어 있지 않습니다."; });
loadCharacter();
loadJobs();
