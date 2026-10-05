// First-run onboarding flow and permissions.
// Classic script sharing global scope with the other files in index.html (load order matters).

const ONBOARDING_STEPS = ['welcome', 'profile', 'meeting-types', 'people', 'permissions', 'models'];
let onboardingStepIndex = 0;
let onboardingSelectedMeetingTypes = new Set();
let onboardingPeople = [];
let onboardingSelectedWhisperModel = null;
let onboardingSelectedLiquidModel = null;

async function showOnboardingStep(index){
  onboardingStepIndex = index;
  const step = ONBOARDING_STEPS[index];
  // Match by data-step name, not DOM position — the DOM still holds a couple
  // of orphaned steps (api-key, the old identity step) that are no longer in
  // ONBOARDING_STEPS; positional indexing would show the wrong section for
  // every step after them.
  $$('.onboarding-step').forEach(el => el.hidden = el.dataset.step !== step);
  $('#onboardingSteps').innerHTML = ONBOARDING_STEPS.map((_, i) => `<span class="${i <= index ? 'done' : ''}"></span>`).join('');
  if(step === 'permissions') refreshPermissionStatus();
  if(step === 'meeting-types') loadOnboardingMeetingTypes();
  if(step === 'models') loadOnboardingModels();
}

function renderMeetingTypesChecklist(meetingTypes){
  $('#onboardingMeetingTypes').innerHTML = meetingTypes.map(mt => `
    <label>
      <input type="checkbox" data-meeting-type-id="${esc(mt.id)}" ${onboardingSelectedMeetingTypes.has(mt.id) ? 'checked' : ''}>
      <span><span class="option-title">${esc(mt.name)}</span><small class="option-sub">${esc(mt.description)}</small></span>
    </label>
  `).join('');
  $$('#onboardingMeetingTypes input[type=checkbox]').forEach(input => {
    input.addEventListener('change', () => {
      const id = Number(input.dataset.meetingTypeId);
      if(input.checked) onboardingSelectedMeetingTypes.add(id); else onboardingSelectedMeetingTypes.delete(id);
    });
  });
}

async function loadOnboardingMeetingTypes(){
  try{
    const res = await api('/api/onboarding/meeting-types');
    if(onboardingSelectedMeetingTypes.size === 0) (res.selected || []).forEach(id => onboardingSelectedMeetingTypes.add(id));
    renderMeetingTypesChecklist(res.meeting_types || []);
  }catch(error){ toast(error.message, true); }
}

function renderOnboardingPeopleList(){
  $('#onboardingPeopleList').innerHTML = onboardingPeople.map((p, i) => `
    <div class="person-row">
      <strong>${esc(p.name)}</strong>
      <span class="muted">${esc(p.role || '')}</span>
      <span class="muted">${esc(p.relationship || '')}</span>
      <button type="button" class="person-remove" data-remove-person="${i}">&times;</button>
    </div>
  `).join('') || '<p class="muted" style="font-size:12px">No one added yet — optional, you can skip this.</p>';
  $$('[data-remove-person]').forEach(btn => btn.addEventListener('click', () => {
    onboardingPeople.splice(Number(btn.dataset.removePerson), 1);
    renderOnboardingPeopleList();
  }));
}

async function loadOnboardingModels(){
  try{
    const res = await api('/api/onboarding/models');
    if(!onboardingSelectedWhisperModel) onboardingSelectedWhisperModel = (res.whisper_options || [])[0]?.id;
    if(!onboardingSelectedLiquidModel) onboardingSelectedLiquidModel = res.selected_liquid_model;
    const renderOptions = (containerId, options, selected, groupName) => {
      $(containerId).innerHTML = options.map(opt => `
        <label>
          <input type="radio" name="${groupName}" value="${esc(opt.id)}" ${opt.id === selected ? 'checked' : ''}>
          <span>
            <span class="option-title">${esc(opt.label)} ${opt.already_downloaded ? '· already on your Mac' : (opt.approx_size_gb ? `· ~${opt.approx_size_gb}GB` : '')}</span>
            <small class="option-sub">${esc(opt.tradeoff)}</small>
          </span>
        </label>
      `).join('');
    };
    renderOptions('#onboardingWhisperOptions', res.whisper_options || [], onboardingSelectedWhisperModel, 'whisperModel');
    renderOptions('#onboardingLiquidOptions', res.liquid_options || [], onboardingSelectedLiquidModel, 'liquidModel');
    $$('#onboardingWhisperOptions input').forEach(input => input.addEventListener('change', () => { onboardingSelectedWhisperModel = input.value; }));
    $$('#onboardingLiquidOptions input').forEach(input => input.addEventListener('change', () => { onboardingSelectedLiquidModel = input.value; }));
  }catch(error){ toast(error.message, true); }
}

$('#onboardingAddPerson')?.addEventListener('click', async () => {
  const name = $('#onboardingPersonName').value.trim();
  const role = $('#onboardingPersonTitle').value.trim();
  const relationship = $('#onboardingPersonRelationship').value;
  if(!name) return toast('Enter a name first', true);
  try{
    await api('/api/people/create', { method: 'POST', body: JSON.stringify({ name, role, relationship }) });
    onboardingPeople.push({ name, role, relationship });
    renderOnboardingPeopleList();
    $('#onboardingPersonName').value = '';
    $('#onboardingPersonTitle').value = '';
    $('#onboardingPersonRelationship').value = '';
  }catch(error){ toast(error.message, true); }
});

async function refreshPermissionStatus(){
  if(!window.electronAPI?.getPermissionStatus) return;
  const status = await window.electronAPI.getPermissionStatus();
  const paint = (el, value) => { el.textContent = value; el.className = 'stage-pill ' + (value === 'granted' ? 'coached' : 'needs_diarization'); };
  paint($('#permMicStatus'), status.microphone);
  paint($('#permScreenStatus'), status.screen);
  if($('#permAccessibilityStatus')) paint($('#permAccessibilityStatus'), status.accessibility);
}

async function openOnboarding(){
  $('#onboardingOverlay').style.display = 'flex';
  $('.app-shell').style.display = 'none';
  try{
    const status = await api('/api/onboarding/status');
    if(status.self_name) $('#onboardingName').value = status.self_name;
    if(status.profession) $('#onboardingProfession').value = status.profession;
    if(status.credentials) syncCredentialsUI('', status.credentials);
  }catch{}
  renderOnboardingPeopleList();
  showOnboardingStep(0);
}

function closeOnboarding(){
  $('#onboardingOverlay').style.display = 'none';
  $('.app-shell').style.display = '';
  load().catch(error=>toast(error.message,true));
  // The model picked during onboarding may not actually be downloaded yet —
  // surface the same download-with-progress prompt used on later launches
  // immediately, instead of waiting for the next app start (or a recording
  // silently triggering a blind download with no UI feedback).
  checkModelsOnStartup();
}

// Onboarding tabs
$('#tabVertex')?.addEventListener('click', () => {
  activeOnboardingProvider = 'vertex';
  $('#tabVertex').classList.add('active');
  $('#tabAiStudio').classList.remove('active');
  $('#vertexForm').style.display = 'block';
  $('#aiStudioForm').style.display = 'none';
});

$('#tabAiStudio')?.addEventListener('click', () => {
  activeOnboardingProvider = 'ai_studio';
  $('#tabAiStudio').classList.add('active');
  $('#tabVertex').classList.remove('active');
  $('#aiStudioForm').style.display = 'block';
  $('#vertexForm').style.display = 'none';
});

$('#vertexAuthType')?.addEventListener('change', () => toggleAuthTypeFields(''));
$('#btnTestCredentials')?.addEventListener('click', () => doTestCredentials(''));
$('#onboardingApiKeySave')?.addEventListener('click', () => {
  doSaveCredentials('', () => showOnboardingStep(ONBOARDING_STEPS.indexOf('permissions')));
});

// Modal tabs
$('#modalTabVertex')?.addEventListener('click', () => {
  activeModalProvider = 'vertex';
  $('#modalTabVertex').classList.add('active');
  $('#modalTabAiStudio').classList.remove('active');
  $('#modalVertexForm').style.display = 'block';
  $('#modalAiStudioForm').style.display = 'none';
});

$('#modalTabAiStudio')?.addEventListener('click', () => {
  activeModalProvider = 'ai_studio';
  $('#modalTabAiStudio').classList.add('active');
  $('#modalTabVertex').classList.remove('active');
  $('#modalAiStudioForm').style.display = 'block';
  $('#modalVertexForm').style.display = 'none';
});

$('#modalVertexAuthType')?.addEventListener('change', () => toggleAuthTypeFields('modal'));
$('#modalBtnTest')?.addEventListener('click', () => doTestCredentials('modal'));
$('#modalBtnSave')?.addEventListener('click', () => {
  doSaveCredentials('modal', () => setTimeout(closeCredentialsModal, 700));
});

$('#closeCredentialsModal')?.addEventListener('click', closeCredentialsModal);
$('#credentialsModal')?.addEventListener('click', (e) => {
  if (e.target.id === 'credentialsModal') closeCredentialsModal();
});

$$('[data-onboarding-next]').forEach(btn => btn.addEventListener('click', () => showOnboardingStep(Math.min(onboardingStepIndex + 1, ONBOARDING_STEPS.length - 1))));
$$('[data-onboarding-back]').forEach(btn => btn.addEventListener('click', () => showOnboardingStep(Math.max(onboardingStepIndex - 1, 0))));

$('#permMicBtn')?.addEventListener('click', async () => { await window.electronAPI?.requestMicrophoneAccess(); refreshPermissionStatus(); });
$('#permScreenBtn')?.addEventListener('click', () => window.electronAPI?.openScreenRecordingSettings());
$('#permAccessibilityBtn')?.addEventListener('click', () => window.electronAPI?.openAccessibilitySettings());
$('#permRecheckBtn')?.addEventListener('click', refreshPermissionStatus);

async function saveSetting(key, value){
  await api('/api/settings', { method: 'POST', body: JSON.stringify({ key, value }) });
}

$('#onboardingFinish')?.addEventListener('click', async () => {
  const name = $('#onboardingName').value.trim();
  const profession = $('#onboardingProfession').value.trim();
  try{
    if(name) await api('/api/onboarding/name', { method: 'POST', body: JSON.stringify({ name }) });
    if(profession) await saveSetting('profession', profession);
    await saveSetting('meeting_types', [...onboardingSelectedMeetingTypes]);
    if(onboardingSelectedWhisperModel) await saveSetting('whisper_model_choice', onboardingSelectedWhisperModel);
    if(onboardingSelectedLiquidModel) await saveSetting('liquid_model', onboardingSelectedLiquidModel);
    await saveSetting('retain_audio', $('#onboardingRetainAudio').checked);
    await api('/api/onboarding/complete', { method: 'POST', body: '{}' });
    closeOnboarding();
  }catch(error){ toast(error.message, true); }
});
