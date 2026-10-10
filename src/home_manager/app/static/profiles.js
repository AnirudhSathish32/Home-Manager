"use strict";
// Profiles and families: the sidebar switcher and Settings → Profiles & family.
// Each person's profile is its own library; a family profile adds its members up (app/family_sync.py).
let profilesKey = "", activeProfile = null, familyView = null, profileList = [], pendingMember = null, hubStatus = null;
const KIND_LABELS = {individual: "Person", family: "Family"};

// Who's here (core/actor.py): with one person the server knows it's them, so nothing is sent; with more, the choice is
// remembered for this browser session only and must still be one of the profile's people.
const WHO_KEY = "hm-who-is-here";
function renderWho(people = []) {
  let saved = null;
  try { saved = sessionStorage.getItem(WHO_KEY); } catch { saved = null; }
  whoIsHere = people.length > 1 && people.includes(saved) ? saved : null;
  $("who-picker").hidden = people.length < 2;
  const key = JSON.stringify(people);
  if ($("who-select").dataset.people !== key) {
    $("who-select").dataset.people = key;
    $("who-select").replaceChildren(new Option("Choose…", ""), ...people.map(name => new Option(name, name)));
  }
  $("who-select").value = whoIsHere || "";
}
$("who-select").addEventListener("change", () => {
  whoIsHere = $("who-select").value || null;
  try { if (whoIsHere) sessionStorage.setItem(WHO_KEY, whoIsHere); else sessionStorage.removeItem(WHO_KEY); } catch { /* Kept for this page only. */ }
});

function renderProfiles(settings) {
  renderWho(settings.people || []);
  profileList = settings.profiles || []; activeProfile = settings.profile; familyView = settings.family; hubStatus = settings.hub_status || null;
  // Polling calls this often; redraw only when something changed so half-typed forms survive.
  const key = JSON.stringify([profileList, activeProfile, familyView, hubStatus]);
  if (key === profilesKey) return;
  profilesKey = key;
  renderProfileSwitch(); renderProfileRows(); renderFamilySection();
  const person = activeProfile?.kind === "individual";
  $("family-include-me-label").textContent = person ? `Include me (${activeProfile.name})` : "Include this profile";
  $("family-include-me").closest("label").hidden = !person;
  $("family-form").hidden = familyMode;
}

function renderProfileSwitch() {
  const select = $("profile-select");
  $("profile-switch").hidden = !profileList.length;
  select.replaceChildren(...profileList.map(profile => new Option(profile.kind === "family" ? `${profile.name} · family` : profile.name, profile.id)));
  select.value = activeProfile?.id || "";
  const label = activeProfile ? `Profile: ${activeProfile.name}${activeProfile.kind === "family" ? " (family)" : ""}` : "Profiles";
  $("nav-profile").querySelector(".nav-label").textContent = label; $("nav-profile").title = label;
}
$("nav-profile").addEventListener("click", () => requestAnimationFrame(() => $("profiles-tab").click()));

async function switchProfile(id) {
  const profile = profileList.find(item => item.id === id);
  try {
    await api("/api/profiles/active", {method: "PUT", body: JSON.stringify({id})});
    $("home-currency-select").replaceChildren();  // The next profile has its own currencies.
    await sessionChanged();
    notice(profile?.kind === "family" ? `${profile.name} is open. Members' latest totals are being gathered.` : `${profile?.name || "Profile"} is open.`);
  } catch (error) {
    $("profile-select").value = activeProfile?.id || "";
    notice(error, true);
  }
}
$("profile-select").addEventListener("change", () => switchProfile($("profile-select").value));

function renderProfileRows() {
  const rows = profileList.map(profile => {
    const row = document.createElement("tr"), name = element("td", "", "profile-name");
    name.append(element("span", profile.name));
    const notes = [profile.id === activeProfile?.id ? "Open now" : "", profile.family && profile.kind === "individual" ? `In ${profile.family.family_name}` : ""].filter(Boolean);
    if (notes.length) name.append(element("small", notes.join(" · "), "muted block"));
    const folder = element("td", ""); folder.append(element("code", profile.folder));
    const actions = element("td"), buttons = element("div", "", "row-actions");
    if (profile.id !== activeProfile?.id) {
      const open = element("button", "Open", "small"); open.type = "button";
      open.addEventListener("click", () => switchProfile(profile.id));
      buttons.append(open);
    }
    const rename = element("button", "Rename"); rename.type = "button";
    rename.addEventListener("click", () => renameProfile(profile, name));
    const remove = element("button", "Remove from this list", "danger-text"); remove.type = "button"; remove.disabled = profile.id === activeProfile?.id;
    remove.addEventListener("click", () => removeProfile(profile));
    buttons.append(menu(`More actions for ${profile.name}`, [rename, remove]));
    actions.append(buttons);
    row.append(name, element("td", KIND_LABELS[profile.kind] || profile.kind, "nowrap"), folder, actions);
    return row;
  });
  if (!rows.length) {
    const row = document.createElement("tr"), td = element("td", "No profiles yet. Choose a library folder to make the first one.", "muted");
    td.colSpan = 4; row.append(td); rows.push(row);
  }
  $("profile-rows").replaceChildren(...rows);
}

function renameProfile(profile, cell) {
  const form = element("form", "", "inline-edit"), input = element("input");
  input.value = profile.name; input.maxLength = 60; input.required = true; input.setAttribute("aria-label", `New name for ${profile.name}`);
  const save = element("button", "Save", "small primary"); save.type = "submit";
  const cancel = element("button", "Cancel", "small"); cancel.type = "button";
  cancel.addEventListener("click", () => { profilesKey = ""; renderProfileRows(); });
  form.addEventListener("submit", async event => {
    event.preventDefault();
    try {
      await api(`/api/profiles/${profile.id}`, {method: "PATCH", body: JSON.stringify({name: input.value.trim()})});
      profilesKey = ""; await loadSettings(); notice("Profile renamed.");
    } catch (error) { notice(error, true); }
  });
  form.append(input, save, cancel);
  cell.replaceChildren(form); input.focus(); input.select();
}

async function removeProfile(profile) {
  if (!await confirmAction({title: `Remove ${profile.name} from this computer's list?`, danger: true, confirmLabel: "Remove from list",
      message: `Nothing is deleted: the folder ${profile.folder} and everything in it stay on disk. Add it back any time with the same folder.`})) return;
  try { await api(`/api/profiles/${profile.id}`, {method: "DELETE"}); profilesKey = ""; await loadSettings(); notice(`${profile.name} was removed from the list. The folder is untouched.`); }
  catch (error) { notice(error, true); }
}

$("profile-form").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    const profile = await api("/api/profiles", {method: "POST", body: JSON.stringify({name: $("profile-name").value.trim(), folder: $("profile-folder").value.trim()})});
    $("profile-name").value = $("profile-folder").value = "";
    profilesKey = ""; await loadSettings();
    notice(`${profile.name}'s profile is ready. Open it from the Profile menu to start adding documents.`);
  } catch (error) { notice(error, true); }
});

$("family-form").addEventListener("submit", async event => {
  event.preventDefault();
  const members = $("family-members-input").value.split("\n").map(name => name.trim()).filter(Boolean);
  const includeMe = $("family-include-me").checked && activeProfile?.kind === "individual";
  try {
    const family = await api("/api/families", {method: "POST", body: JSON.stringify({name: $("family-name").value.trim(), folder: $("family-folder").value.trim(),
      members, my_profile: includeMe ? activeProfile.id : null})});
    for (const id of ["family-name", "family-folder", "family-members-input"]) $(id).value = "";
    profilesKey = ""; await loadSettings();
    if (await confirmAction({title: `Open ${family.name} now?`, confirmLabel: "Open family view",
        message: "From the family view you can invite each member or set them up on this computer. You can switch back to your own profile from the Profile menu at any time."}))
      await switchProfile(family.id);
    else notice(`${family.name} is ready. Open it from the Profile menu to invite its members.`);
  } catch (error) { notice(error, true); }
});

// Family section: depends on what the open profile is.
function renderFamilySection() {
  const target = $("family-section");
  if (familyView) target.replaceChildren(...familyMembersSection(familyView));
  else if (activeProfile?.kind === "individual" && activeProfile.family) target.replaceChildren(...membershipSection(activeProfile));
  else if (activeProfile?.kind === "individual") target.replaceChildren(...joinSection());
  else target.replaceChildren();
}

function familyMembersSection(family) {
  const heading = element("h2", `${family.name}: members`);
  const intro = element("p", "Members on other computers send their copies to this computer over Tailscale while Home Manager is open here. Each person's records stay in their own profile.", "muted small");
  // Where the family hub listens (app/family_hub.py), or why members' computers can't reach it yet.
  const hub = hubStatus?.listening
    ? element("p", `Members' computers reach this one at ${hubStatus.address}. Documents from members: ${sizeText(family.documents_bytes || 0)}, stored encrypted.`, "small")
    : alertBox(`Members on other computers can't send copies yet. ${hubStatus?.reason || ""}`.trim(), {tone: "warning"});
  const rows = family.members.map(member => {
    const row = document.createElement("tr");
    const profile = profileList.find(item => item.id === member.profile_id);
    const where = member.source === "local" ? `This computer${profile ? ` · ${profile.name}` : ""}` : "Their own computer";
    const status = element("td", ""); status.append(statusBadge(member.status));
    if (member.error) status.append(element("small", member.error, "error-text"));
    const invite = element("button", "Create invite…"); invite.type = "button"; invite.addEventListener("click", () => openInvite(member));
    const local = element("button", "Set up on this computer…"); local.type = "button"; local.addEventListener("click", () => openLocalMember(member));
    const remove = element("button", "Remove from family", "danger-text"); remove.type = "button"; remove.addEventListener("click", () => removeMember(member));
    const actions = element("td"), buttons = element("div", "", "row-actions");
    buttons.append(menu(`Actions for ${member.name}`, [invite, local, remove])); actions.append(buttons);
    row.append(element("td", member.name), element("td", where), element("td", asOfText(member.as_of)), status, actions);
    return row;
  });
  const wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table");
  const head = document.createElement("thead"), tr = document.createElement("tr"), body = document.createElement("tbody");
  for (const text of ["Person", "Where", "Data as of", "Status", ""]) { const th = element("th", text); th.scope = "col"; tr.append(th); }
  if (!rows.length) { const row = document.createElement("tr"), td = element("td", "No members yet. Add the first one below.", "muted"); td.colSpan = 5; row.append(td); rows.push(row); }
  head.append(tr); body.append(...rows); table.append(head, body); wrap.append(table);
  const update = element("button", "Update now"); update.type = "button";
  update.addEventListener("click", async () => {
    try { await api("/api/family-refreshes", {method: "POST", body: "{}"}); busy.capture = true; notice("Gathering members' latest totals…"); }
    catch (error) { notice(error, true); }
  });
  const form = element("form", "", "inline-form"), field = element("div", "", "field"), label = element("label", "Add a member"), input = element("input");
  input.id = "family-new-member"; input.required = true; input.maxLength = 60; input.autocomplete = "off"; input.placeholder = "Name"; label.htmlFor = input.id;
  const add = element("button", "Add member", "primary"); add.type = "submit";
  field.append(label, input); form.append(field, add);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    try {
      const member = await api(`/api/families/${activeProfile.id}/members`, {method: "POST", body: JSON.stringify({name: input.value.trim()})});
      profilesKey = ""; await loadSettings(); notice(`${member.name} was added. Create an invite for their computer, or set them up on this one.`);
    } catch (error) { notice(error, true); }
  });
  const actions = element("div", "", "button-row"); actions.append(update);
  return [heading, intro, hub, wrap, actions, form];
}

// The member's line about the family hub: synced, waiting for the family computer, or refused.
function syncStatus(link) {
  const last = link.last_sync ? ` · last synced ${asOfText(link.last_sync)}` : "";
  if (link.hub_state === "refused") return alertBox(`The family computer refused this profile's copy. ${link.hub_error || ""}`.trim(), {tone: "error"});
  if (link.hub_state === "ok") return element("p", `Synced ${asOfText(link.last_sync)}.`, "small");
  const why = link.hub_error ? ` ${link.hub_error}` : "";
  return alertBox(`Waiting for the family computer${last}.${why} Your copy is kept and sent when it's back.`, {tone: "info"});
}

function membershipSection(profile) {
  const link = profile.family, heading = element("h2", `Your family: ${link.family_name}`);
  if (link.local) return [heading, element("p", `${link.family_name} reads this profile directly on this computer. Nothing is sent over the network.`, "muted small")];
  if (link.rejoin) {
    // A membership from before the hub: it named a sync folder, which is no longer used.
    return [heading, alertBox(`Re-join needed. ${link.family_name} now shares over Tailscale. Ask the family computer for a new invite, then open it below.`, {tone: "warning"}),
      ...joinSection()];
  }
  const parts = [heading, element("p", `This profile sends an encrypted copy of its records (no documents or images) to ${link.family_name}'s computer over Tailscale. Only computers with the family's key can read it.`, "muted small")];
  parts.push(syncStatus(link));
  if (link.published_at) parts.push(element("p", `Last copy made ${asOfText(link.published_at)}.`, "muted small"));
  const auto = element("label", "", "check-field"), box = element("input"); box.type = "checkbox"; box.checked = link.publishing !== false;
  auto.append(box, document.createTextNode(" Share changes automatically (at most every 10 minutes)"));
  box.addEventListener("change", async () => {
    try { await api("/api/family-membership", {method: "PUT", body: JSON.stringify({publishing: box.checked})}); profilesKey = ""; await loadSettings(); }
    catch (error) { box.checked = !box.checked; notice(error, true); }
  });
  const share = element("button", "Share now", "primary"); share.type = "button";
  share.addEventListener("click", async () => {
    try { await api("/api/family-publishes", {method: "POST", body: "{}"}); busy.capture = true; notice(`Sharing your latest totals with ${link.family_name}…`); }
    catch (error) { notice(error, true); }
  });
  const leave = element("button", "Leave family", "danger"); leave.type = "button";
  leave.addEventListener("click", async () => {
    if (!await confirmAction({title: `Leave ${link.family_name}?`, danger: true, confirmLabel: "Leave family",
        message: "This profile stops sharing. The copy the family computer already has stays until the family removes you; ask them to. Your own records are not changed."})) return;
    try { await api("/api/family-membership", {method: "DELETE"}); profilesKey = ""; await loadSettings(); notice(`You left ${link.family_name}.`); }
    catch (error) { notice(error, true); }
  });
  const buttons = element("div", "", "button-row"); buttons.append(share, leave);
  parts.push(auto, buttons);
  return parts;
}

function joinSection() {
  const form = element("form", "", "form");
  form.append(element("h3", "Join a family"), element("p", "Open the invite file someone in your family sent you. This profile then shares an encrypted copy of its records with the family; you can stop at any time.", "muted small"));
  const fields = [["join-invite", "Invite file", "text", "C:\\Users\\you\\Downloads\\The Smiths - You.hminvite", true],
                  ["join-passphrase", "Passphrase", "password", "", true]];
  for (const [id, text, type, placeholder, required] of fields) {
    const field = element("div", "", "field"), label = element("label", text), input = element("input");
    input.id = id; input.type = type; input.placeholder = placeholder; input.required = required; input.autocomplete = "off"; input.spellcheck = false; label.htmlFor = id;
    field.append(label, input);
    form.append(field);
  }
  form.append(element("p", "Both computers need Tailscale connected. Your copy waits on this computer whenever the family computer is off.", "muted small"));
  const join = element("button", "Join family", "primary"); join.type = "submit";
  const row = element("div", "", "button-row"); row.append(join); form.append(row);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    try {
      const profile = await api("/api/family-membership", {method: "POST", body: JSON.stringify({invite_file: $("join-invite").value.trim(),
        passphrase: $("join-passphrase").value})});
      $("join-passphrase").value = "";
      profilesKey = ""; await loadSettings(); notice(`You joined ${profile.family.family_name}. Your first share is on its way.`);
    } catch (error) { $("join-passphrase").value = ""; notice(error, true); }
  });
  return [form];
}

// Family inbox: who each upload is for (Review page, family profile only) ----------------------
let routingLoad = 0;
async function loadFamilyRouting() {
  const load = ++routingLoad, data = await api("/api/family/routing");
  if (load !== routingLoad) return;
  const list = $("family-routing");
  if (!data.records.length) { list.replaceChildren(element("li", "Everything uploaded to the family has been sent to someone.", "muted small")); return; }
  list.replaceChildren(...data.records.map(record => routingRow(record, data.people)));
}
function routingRow(record, people) {
  const row = element("li", "", "routing-row"), what = element("div", "", "routing-what"), key = `${record.record_type}-${record.id}`;
  const title = element("strong", `${RECORD_KINDS?.[record.record_type] || statusLabel(record.record_type)} · ${record.name || "Name not found"}`);
  const facts = element("span", "", "small");
  facts.append(dateDisplay(record.date), document.createTextNode(" · "), amount(record.amount || "—", {signed: false}));
  const suggested = people.find(person => person.member_id === record.suggested?.member_id);
  what.append(title, facts, element("small", suggested ? `Suggested: ${suggested.name} · ${record.suggested.reason}` : record.suggested?.reason || "", "muted"));
  if (record.document_id) what.append(homeLink("Open the document", `#/documents/${record.document_id}`, "small"));
  const form = element("form", "", "routing-decision"), field = element("div", "", "field"), label = element("label", "For"), select = element("select");
  select.id = `route-${key}`; label.htmlFor = select.id; select.required = true;
  select.append(new Option("Choose…", ""), ...people.map(person => new Option(person.name, person.member_id)));
  if (record.shareable) select.append(new Option("Shared by the family", "shared"));
  select.value = suggested ? suggested.member_id : "";
  field.append(label, select);
  const split = element("fieldset", "", "routing-people"); split.hidden = true;
  split.append(element("legend", "Split equally between"));
  for (const person of people) {
    const check = element("label", "", "check-field"), box = element("input"); box.type = "checkbox"; box.checked = true; box.value = person.member_id;
    check.append(box, document.createTextNode(` ${person.name}`)); split.append(check);
  }
  select.addEventListener("change", () => { split.hidden = select.value !== "shared"; });
  const send = element("button", "Send", "primary"); send.type = "submit";
  form.append(field, split, send);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const shared = select.value === "shared";
    const members = shared ? [...split.querySelectorAll("input:checked")].map(box => box.value) : [select.value];
    if (!members.length) { notice("Tick at least one person to share it.", true); return; }
    send.disabled = true;
    try {
      const result = await api(`/api/family/routing/${record.record_type}/${record.id}`, {method: "PUT", body: JSON.stringify({mode: shared ? "shared" : "member", members})});
      notice(shared ? `Shared: ${result.shares.map(part => `${part.name} ${part.share?.display || ""}`).join(" · ")}. Each person's profile gets the document and their part.`
                    : `Sent to ${result.shares[0]?.name}.`);
      busy.capture = true;
      await loadFamilyRouting();
    } catch (error) { send.disabled = false; notice(error, true); }
  });
  row.append(what, form);
  return row;
}

// Member dialogs ------------------------------------------------------------------
function openInvite(member) {
  pendingMember = member;
  $("invite-title").textContent = `Invite ${member.name}`;
  $("invite-error").textContent = "";
  $("invite-passphrase").value = $("invite-passphrase-again").value = "";
  $("invite-dialog").showModal(); $("invite-destination").focus();
}
$("cancel-invite").addEventListener("click", () => $("invite-dialog").close());
$("invite-form").addEventListener("submit", async event => {
  event.preventDefault();
  const passphrase = $("invite-passphrase").value;
  if (passphrase !== $("invite-passphrase-again").value) { $("invite-error").textContent = "The two passphrases differ."; return; }
  try {
    const result = await api(`/api/families/${activeProfile.id}/members/${pendingMember.member_id}/invites`, {method: "POST",
      body: JSON.stringify({destination: $("invite-destination").value.trim(), passphrase})});
    $("invite-passphrase").value = $("invite-passphrase-again").value = "";
    $("invite-dialog").close(); profilesKey = ""; await loadSettings();
    notice(`Invite saved: ${result.path}. Send it to ${pendingMember.name}, and tell them the passphrase another way.`);
  } catch (error) { $("invite-error").textContent = error.message; }
});

function openLocalMember(member) {
  pendingMember = member;
  $("local-member-title").textContent = `Set up ${member.name} on this computer`;
  $("local-member-error").textContent = "";
  const people = profileList.filter(profile => profile.kind === "individual" && (!profile.family || profile.family.family_id === familyView.family_id));
  $("local-member-profile").replaceChildren(new Option(`A new profile for ${member.name}`, ""), ...people.map(profile => new Option(profile.name, profile.id)));
  $("local-member-profile").value = member.profile_id || "";
  showLocalFolder();
  $("local-member-dialog").showModal(); $("local-member-profile").focus();
}
function showLocalFolder() {
  const fresh = !$("local-member-profile").value;
  $("local-member-folder-field").hidden = !fresh; $("local-member-folder").required = fresh;
}
$("local-member-profile").addEventListener("change", showLocalFolder);
$("cancel-local-member").addEventListener("click", () => $("local-member-dialog").close());
$("local-member-form").addEventListener("submit", async event => {
  event.preventDefault();
  const profileId = $("local-member-profile").value;
  try {
    await api(`/api/families/${activeProfile.id}/members/${pendingMember.member_id}/local`, {method: "POST",
      body: JSON.stringify(profileId ? {profile_id: profileId} : {folder: $("local-member-folder").value.trim()})});
    $("local-member-dialog").close(); $("local-member-folder").value = "";
    await api("/api/family-refreshes", {method: "POST", body: "{}"}).catch(() => {});
    profilesKey = ""; await loadSettings();
    notice(`${pendingMember.name} is set up on this computer. Their totals appear in the family view once they have records.`);
  } catch (error) { $("local-member-error").textContent = error.message; }
});

async function removeMember(member) {
  if (!await confirmAction({title: `Remove ${member.name} from ${familyView.name}?`, danger: true, confirmLabel: "Remove from family",
      message: `${member.name}'s totals leave the family view. Their own profile and records are not changed, and their invite stops working.`})) return;
  try { await api(`/api/families/${activeProfile.id}/members/${member.member_id}`, {method: "DELETE"}); profilesKey = ""; await loadSettings(); if (currentRoute?.name === "home") await (uiV2Screens.includes("home") ? reloadToday() : loadHome()); }
  catch (error) { notice(error, true); }
}
