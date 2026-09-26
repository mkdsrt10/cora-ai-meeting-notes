// Cloud credentials: status, forms, test/save, modal.
// Classic script sharing global scope with the other files in index.html (load order matters).

let currentCreds = null;
let activeOnboardingProvider = 'vertex';
let activeModalProvider = 'vertex';

async function fetchCredentialsStatus() {
  try {
    const res = await api('/api/credentials/status');
    currentCreds = res.credentials || {};
    return currentCreds;
  } catch (e) {
    return null;
  }
}

function syncCredentialsUI(prefix, creds) {
  if (!creds) return;
  const isModal = prefix === 'modal';
  const isVertex = (creds.provider || 'vertex') === 'vertex';

  if (isModal) {
    activeModalProvider = isVertex ? 'vertex' : 'ai_studio';
    $('#modalTabVertex')?.classList.toggle('active', isVertex);
    $('#modalTabAiStudio')?.classList.toggle('active', !isVertex);
    if ($('#modalVertexForm')) $('#modalVertexForm').style.display = isVertex ? 'block' : 'none';
    if ($('#modalAiStudioForm')) $('#modalAiStudioForm').style.display = isVertex ? 'none' : 'block';

    if (creds.has_adc && $('#modalAdcBadge')) $('#modalAdcBadge').style.display = 'block';
    if ($('#modalVertexProject')) $('#modalVertexProject').value = creds.vertex_project || creds.detected_gcloud_project || '';
    if ($('#modalVertexLocation')) $('#modalVertexLocation').value = creds.vertex_location || 'us-central1';
    if ($('#modalVertexAuthType')) {
      $('#modalVertexAuthType').value = creds.vertex_auth_type || (creds.has_adc ? 'adc' : 'service_account');
      toggleAuthTypeFields('modal');
    }
  } else {
    activeOnboardingProvider = isVertex ? 'vertex' : 'ai_studio';
    $('#tabVertex')?.classList.toggle('active', isVertex);
    $('#tabAiStudio')?.classList.toggle('active', !isVertex);
    if ($('#vertexForm')) $('#vertexForm').style.display = isVertex ? 'block' : 'none';
    if ($('#aiStudioForm')) $('#aiStudioForm').style.display = isVertex ? 'none' : 'block';

    if (creds.has_adc && $('#adcDetectedBadge')) $('#adcDetectedBadge').style.display = 'block';
    if ($('#vertexProject')) $('#vertexProject').value = creds.vertex_project || creds.detected_gcloud_project || '';
    if ($('#vertexLocation')) $('#vertexLocation').value = creds.vertex_location || 'us-central1';
    if ($('#vertexAuthType')) {
      $('#vertexAuthType').value = creds.vertex_auth_type || (creds.has_adc ? 'adc' : 'service_account');
      toggleAuthTypeFields('');
    }
  }
}

function toggleAuthTypeFields(prefix) {
  const select = prefix === 'modal' ? $('#modalVertexAuthType') : $('#vertexAuthType');
  const val = select ? select.value : 'adc';
  const saField = prefix === 'modal' ? $('#modalFieldVertexSa') : $('#fieldVertexSa');
  const keyField = prefix === 'modal' ? $('#modalFieldVertexApiKey') : $('#fieldVertexApiKey');
  if (saField) saField.style.display = val === 'service_account' ? 'block' : 'none';
  if (keyField) keyField.style.display = val === 'api_key' ? 'block' : 'none';
}

function readCredentialsForm(prefix) {
  const isModal = prefix === 'modal';
  const provider = isModal ? activeModalProvider : activeOnboardingProvider;
  if (provider === 'vertex') {
    return {
      provider: 'vertex',
      project: (isModal ? $('#modalVertexProject') : $('#vertexProject'))?.value?.trim(),
      location: (isModal ? $('#modalVertexLocation') : $('#vertexLocation'))?.value?.trim() || 'us-central1',
      auth_type: (isModal ? $('#modalVertexAuthType') : $('#vertexAuthType'))?.value || 'adc',
      service_account_json: (isModal ? $('#modalVertexSaJson') : $('#vertexSaJson'))?.value?.trim(),
      api_key: (isModal ? $('#modalVertexApiKey') : $('#vertexApiKey'))?.value?.trim(),
    };
  } else {
    return {
      provider: 'ai_studio',
      api_key: (isModal ? $('#modalAiStudioApiKey') : $('#onboardingApiKey'))?.value?.trim(),
    };
  }
}

async function doTestCredentials(prefix) {
  const errorEl = prefix === 'modal' ? $('#modalCredError') : $('#onboardingApiKeyError');
  const successEl = prefix === 'modal' ? $('#modalCredSuccess') : $('#onboardingApiKeySuccess');
  const testBtn = prefix === 'modal' ? $('#modalBtnTest') : $('#btnTestCredentials');
  if (errorEl) errorEl.style.display = 'none';
  if (successEl) successEl.style.display = 'none';

  const payload = readCredentialsForm(prefix);
  const oldText = testBtn.textContent;
  testBtn.textContent = 'Testing...';
  testBtn.disabled = true;

  try {
    const res = await api('/api/credentials/test', { method: 'POST', body: JSON.stringify(payload) });
    if (successEl) {
      successEl.textContent = res.message || 'Connection verified successfully!';
      successEl.style.display = 'block';
    }
    toast('Credentials verified successfully');
  } catch (err) {
    if (errorEl) {
      errorEl.textContent = err.message;
      errorEl.style.display = 'block';
    }
  } finally {
    testBtn.textContent = oldText;
    testBtn.disabled = false;
  }
}

async function doSaveCredentials(prefix, onSuccess) {
  const errorEl = prefix === 'modal' ? $('#modalCredError') : $('#onboardingApiKeyError');
  const successEl = prefix === 'modal' ? $('#modalCredSuccess') : $('#onboardingApiKeySuccess');
  const saveBtn = prefix === 'modal' ? $('#modalBtnSave') : $('#onboardingApiKeySave');
  if (errorEl) errorEl.style.display = 'none';
  if (successEl) successEl.style.display = 'none';

  const payload = readCredentialsForm(prefix);
  const oldText = saveBtn.textContent;
  saveBtn.textContent = 'Verifying & saving...';
  saveBtn.disabled = true;

  try {
    const res = await api('/api/credentials/save', { method: 'POST', body: JSON.stringify(payload) });
    currentCreds = res.credentials;
    if (successEl) {
      successEl.textContent = 'Credentials verified & securely saved!';
      successEl.style.display = 'block';
    }
    toast('AI configuration securely saved');
    if (onSuccess) onSuccess();
  } catch (err) {
    if (errorEl) {
      errorEl.textContent = err.message;
      errorEl.style.display = 'block';
    }
  } finally {
    saveBtn.textContent = oldText;
    saveBtn.disabled = false;
  }
}

async function openCredentialsModal() {
  const modal = $('#credentialsModal');
  if (!modal) return;
  modal.classList.add('open');
  const creds = await fetchCredentialsStatus();
  syncCredentialsUI('modal', creds);
}

function closeCredentialsModal() {
  $('#credentialsModal')?.classList.remove('open');
  load().catch(err => toast(err.message, true));
}
