/**
 * Eagle AI Financial Reconciliation Engine - Frontend Application Controller
 */

// ---------------------------------------------------------------------------
// 1. API Client
// ---------------------------------------------------------------------------
const API = {
  async getHealth() {
    const res = await fetch('/health');
    if (!res.ok) throw new Error('Failed to fetch engine health');
    return await res.json();
  },

  async getRuns(limit = 100) {
    const res = await fetch(`/runs?limit=${limit}`);
    if (!res.ok) throw new Error('Failed to fetch historical runs');
    return await res.json();
  },

  async getRun(runId) {
    const res = await fetch(`/runs/${encodeURIComponent(runId)}`);
    if (!res.ok) throw new Error(`Failed to fetch run ${runId}`);
    return await res.json();
  },

  async getMetrics(runId) {
    const res = await fetch(`/runs/${encodeURIComponent(runId)}/metrics`);
    if (!res.ok) throw new Error(`Failed to fetch metrics for ${runId}`);
    return await res.json();
  },

  async getResults(runId, params = {}) {
    const query = new URLSearchParams(params);
    const res = await fetch(`/runs/${encodeURIComponent(runId)}/results?${query.toString()}`);
    if (!res.ok) throw new Error(`Failed to fetch results for ${runId}`);
    return await res.json();
  },

  async getExceptions(runId, params = {}) {
    const query = new URLSearchParams(params);
    const res = await fetch(`/runs/${encodeURIComponent(runId)}/exceptions?${query.toString()}`);
    if (!res.ok) throw new Error(`Failed to fetch exceptions for ${runId}`);
    return await res.json();
  },

  async getCandidates(runId) {
    const res = await fetch(`/runs/${encodeURIComponent(runId)}/candidates`);
    if (!res.ok) throw new Error(`Failed to fetch candidate inspector data for ${runId}`);
    return await res.json();
  },

  async getAuditLogs(runId) {
    const res = await fetch(`/runs/${encodeURIComponent(runId)}/audit-logs`);
    if (!res.ok) throw new Error(`Failed to fetch audit logs for ${runId}`);
    return await res.json();
  },

  async createRun(formData) {
    const res = await fetch('/runs', {
      method: 'POST',
      body: formData,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Upload error' }));
      throw new Error(err.detail || 'Reconciliation execution failed');
    }
    return await res.json();
  },

  async getSyntheticDataSample() {
    const res = await fetch('/demo/synthetic-data');
    if (!res.ok) throw new Error('Synthetic sample dataset unavailable');
    return await res.json();
  },
};

// ---------------------------------------------------------------------------
// 2. Application State
// ---------------------------------------------------------------------------
const state = {
  activeRunId: null,
  activeRun: null,
  runs: [],
  metrics: null,
  results: [],
  filteredResults: [],
  exceptions: [],
  filteredExceptions: [],
  candidates: [],
  auditLogs: [],
  selectedGatewayFile: null,
  selectedBankFile: null,
};

// ---------------------------------------------------------------------------
// 3. UI Helpers & Formatting
// ---------------------------------------------------------------------------
function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);

  setTimeout(() => {
    toast.remove();
  }, 4000);
}

function formatCurrency(amountStr) {
  if (!amountStr && amountStr !== '0' && amountStr !== 0) return '₹0.00';
  const val = parseFloat(amountStr);
  if (isNaN(val)) return '₹0.00';
  return '₹' + val.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatTimestamp(isoStr) {
  if (!isoStr) return '--';
  try {
    const d = new Date(isoStr);
    return d.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch (e) {
    return isoStr;
  }
}

// ---------------------------------------------------------------------------
// 4. Render Functions
// ---------------------------------------------------------------------------
function renderHeaderStatus(provider) {
  const el = document.getElementById('engineProviderLabel');
  el.textContent = `Engine: ${provider || 'Active'}`;
}

function renderRunSelector() {
  const select = document.getElementById('runSelect');
  select.innerHTML = '';

  if (state.runs.length === 0) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = 'No reconciliation runs found';
    select.appendChild(opt);
    return;
  }

  state.runs.forEach(r => {
    const opt = document.createElement('option');
    opt.value = r.run_id;
    opt.textContent = `${r.run_id} — ${formatTimestamp(r.created_at)} (${r.status})`;
    if (r.run_id === state.activeRunId) {
      opt.selected = true;
    }
    select.appendChild(opt);
  });
}

function renderActiveRunMeta() {
  const title = document.getElementById('displayRunId');
  const badge = document.getElementById('displayRunStatus');
  const time = document.getElementById('displayRunTimestamp');
  const btnCsv = document.getElementById('btnExportCsv');
  const btnJson = document.getElementById('btnExportJson');

  if (!state.activeRun) {
    title.textContent = 'No Run Selected';
    badge.className = 'run-status-badge badge-neutral';
    badge.textContent = 'IDLE';
    time.textContent = '--';
    btnCsv.disabled = true;
    btnJson.disabled = true;
    return;
  }

  title.textContent = state.activeRun.run_id;
  badge.textContent = state.activeRun.status;
  badge.className = `run-status-badge badge-${state.activeRun.status.toLowerCase()}`;
  time.textContent = `Completed: ${formatTimestamp(state.activeRun.completed_at || state.activeRun.created_at)}`;

  btnCsv.disabled = false;
  btnJson.disabled = false;
}

function renderKpis() {
  const m = state.metrics || {};
  document.getElementById('kpiTotalRecords').textContent = m.total_records || 0;
  document.getElementById('kpiRecordSplit').textContent = `${m.source_count || 0} Gateway / ${m.target_count || 0} Bank`;
  
  document.getElementById('kpiMatchedCount').textContent = m.matched_count || 0;
  document.getElementById('kpiMatchRate').textContent = `${(m.match_rate || 0).toFixed(1)}% Match Rate`;

  document.getElementById('kpiExceptionCount').textContent = m.exception_count || 0;
  document.getElementById('kpiExceptionRate').textContent = `${(m.exception_rate || 0).toFixed(1)}% Exceptions`;

  document.getElementById('kpiMissingCount').textContent = m.missing_count || 0;
  document.getElementById('kpiUnresolvedCount').textContent = m.unresolved_count || 0;
  document.getElementById('kpiReconciledAmount').textContent = formatCurrency(m.total_reconciled_amount);
}

function renderResultsTable() {
  const tbody = document.getElementById('resultsTableBody');
  const countEl = document.getElementById('countAllResults');
  tbody.innerHTML = '';

  countEl.textContent = state.filteredResults.length;

  if (state.filteredResults.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" class="table-empty">No reconciliation results match the current filters.</td></tr>`;
    return;
  }

  state.filteredResults.forEach(r => {
    const tr = document.createElement('tr');

    const sourceChips = (r.source_record_ids || []).map(id => `<span class="chip">${id}</span>`).join('');
    const targetChips = (r.target_record_ids || []).map(id => `<span class="chip">${id}</span>`).join('');

    const outcomeBadge = r.outcome === 'MATCHED'
      ? `<span class="badge-pill badge-pill-green">MATCHED</span>`
      : `<span class="badge-pill badge-pill-red">EXCEPTION</span>`;

    const classBadge = r.exception_type
      ? `<span class="badge-pill badge-pill-amber">${r.exception_type}</span>`
      : `<span class="badge-pill badge-pill-blue">EXACT MATCH</span>`;

    const reviewBadge = r.flag_for_review
      ? `<span class="badge-pill badge-pill-red">REVIEW REQUIRED</span>`
      : `<span class="badge-pill badge-pill-green">VERIFIED</span>`;

    tr.innerHTML = `
      <td><code>${r.relationship_id}</code></td>
      <td><strong>${r.relationship_type}</strong></td>
      <td><div class="participant-chips">${sourceChips || '<span class="text-muted">None</span>'}</div></td>
      <td><div class="participant-chips">${targetChips || '<span class="text-muted">None</span>'}</div></td>
      <td>${outcomeBadge}</td>
      <td>${classBadge}</td>
      <td><strong>${formatCurrency(r.reconciled_amount)}</strong></td>
      <td>${reviewBadge}</td>
    `;
    tbody.appendChild(tr);
  });
}

function renderExceptionsTable() {
  const tbody = document.getElementById('exceptionsTableBody');
  const countEl = document.getElementById('countExceptions');
  tbody.innerHTML = '';

  countEl.textContent = state.filteredExceptions.length;

  if (state.filteredExceptions.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" class="table-empty">No exception records found for this run.</td></tr>`;
    return;
  }

  state.filteredExceptions.forEach(e => {
    const tr = document.createElement('tr');

    const sourceChips = (e.source_record_ids || []).map(id => `<span class="chip">${id}</span>`).join('');
    const targetChips = (e.target_record_ids || []).map(id => `<span class="chip">${id}</span>`).join('');

    let sevBadge = '<span class="badge-pill badge-pill-blue">LOW</span>';
    if (e.severity === 'HIGH') sevBadge = '<span class="badge-pill badge-pill-red">HIGH</span>';
    if (e.severity === 'MEDIUM') sevBadge = '<span class="badge-pill badge-pill-amber">MEDIUM</span>';

    const actionBadge = e.flag_for_review
      ? '<span class="badge-pill badge-pill-red">Operator Action Required</span>'
      : '<span class="badge-pill badge-pill-green">Auto-Reconciled</span>';

    tr.innerHTML = `
      <td><code>${e.relationship_id}</code></td>
      <td><div class="participant-chips">${sourceChips || '—'}</div></td>
      <td><div class="participant-chips">${targetChips || '—'}</div></td>
      <td><span class="badge-pill badge-pill-amber">${e.exception_type || 'EXCEPTION'}</span></td>
      <td>${sevBadge}</td>
      <td><strong>${formatCurrency(e.reconciled_amount)}</strong></td>
      <td>${actionBadge}</td>
    `;
    tbody.appendChild(tr);
  });
}

function renderCandidateInspector() {
  const container = document.getElementById('candidateCardsContainer');
  const countEl = document.getElementById('countCandidates');
  container.innerHTML = '';

  countEl.textContent = state.candidates.length;

  if (state.candidates.length === 0) {
    container.innerHTML = `<div class="empty-state">No candidate pools recorded for this run.</div>`;
    return;
  }

  state.candidates.forEach((c, idx) => {
    const card = document.createElement('div');
    card.className = 'candidate-card';

    let statusBadgeClass = 'badge-pill-amber';
    if (c.validation_status === 'COMMITTED') statusBadgeClass = 'badge-pill-green';
    else if (c.validation_status === 'ABSTAINED') statusBadgeClass = 'badge-pill-blue';
    else if (c.validation_status === 'REJECTED' || c.validation_status === 'CLASSIFICATION_FAILED') statusBadgeClass = 'badge-pill-red';

    const optionsHtml = (c.candidate_options || []).map(opt => {
      const isSelected = opt.index === c.selected_candidate_index;
      const optClass = isSelected ? 'option-node selected-option' : 'option-node';
      const indicator = isSelected
        ? `<span class="badge-pill badge-pill-green">AI SELECTED</span>`
        : `<span class="badge-pill badge-pill-blue">OPTION ${opt.index}</span>`;

      const src = (opt.source_record_ids || []).join(', ');
      const tgt = (opt.target_record_ids || []).join(', ');

      return `
        <div class="${optClass}">
          <div class="option-left">
            <span class="option-index-badge">#${opt.index}</span>
            <div class="option-flow">
              <code>${src}</code>
              <span class="arrow-icon">➔</span>
              <code>${tgt}</code>
            </div>
          </div>
          <div>${indicator}</div>
        </div>
      `;
    }).join('');

    const aiSummary = c.ai_outcome
      ? `<span class="badge-pill badge-pill-blue" style="margin-right: 0.5rem;">AI Choice: ${c.ai_outcome}${c.ai_exception_type ? ' (' + c.ai_exception_type + ')' : ''}</span>`
      : '';

    card.innerHTML = `
      <div class="candidate-header">
        <div class="candidate-anchor">
          <span class="anchor-title">Anchor Record: ${c.anchor_record_id}</span>
          <span class="badge-pill badge-pill-blue">${(c.candidate_options || []).length} Legal Candidate Options</span>
        </div>
        <div class="candidate-verdict">
          ${aiSummary}
          <span class="badge-pill ${statusBadgeClass}">${c.validation_status}</span>
        </div>
      </div>

      <div class="candidate-options-tree">
        <div class="kpi-label">DETERMINISTIC SEARCH SPACE & SELECTION:</div>
        ${optionsHtml}
      </div>

      ${c.reasoning ? `<div class="candidate-reasoning"><strong>AI Reasoning & Signal:</strong> ${c.reasoning}</div>` : ''}
      ${c.rejection_reason ? `<div class="candidate-reasoning" style="border-left-color: var(--accent-rose); color: var(--accent-rose);"><strong>Safety Validator Verdict:</strong> ${c.rejection_reason}</div>` : ''}
    `;

    container.appendChild(card);
  });
}

function renderAuditTimeline() {
  const container = document.getElementById('auditTimelineContainer');
  const countEl = document.getElementById('countAuditLogs');
  container.innerHTML = '';

  countEl.textContent = state.auditLogs.length;

  if (state.auditLogs.length === 0) {
    container.innerHTML = `<div class="empty-state">No audit events recorded for this run.</div>`;
    return;
  }

  state.auditLogs.forEach(log => {
    const item = document.createElement('div');
    item.className = 'timeline-item';

    const detailsJson = log.details ? JSON.stringify(log.details, null, 2) : '';

    item.innerHTML = `
      <div class="timeline-dot"></div>
      <div class="timeline-content">
        <div class="timeline-header">
          <span class="timeline-event-name">${log.event_type}</span>
          <span class="timeline-time">${formatTimestamp(log.timestamp)}</span>
        </div>
        ${detailsJson ? `<pre class="timeline-details">${detailsJson}</pre>` : ''}
      </div>
    `;
    container.appendChild(item);
  });
}

// ---------------------------------------------------------------------------
// 5. Data Loading Orchestration
// ---------------------------------------------------------------------------
async function loadRunDetails(runId) {
  if (!runId) return;
  state.activeRunId = runId;

  try {
    const [run, metrics, resultsData, exceptionsData, candidatesData, auditData] = await Promise.all([
      API.getRun(runId),
      API.getMetrics(runId),
      API.getResults(runId),
      API.getExceptions(runId),
      API.getCandidates(runId),
      API.getAuditLogs(runId),
    ]);

    state.activeRun = run;
    state.metrics = metrics;
    state.results = resultsData.results || [];
    state.filteredResults = [...state.results];
    state.exceptions = exceptionsData.results || [];
    state.filteredExceptions = [...state.exceptions];
    state.candidates = candidatesData.candidates || [];
    state.auditLogs = auditData || [];

    renderActiveRunMeta();
    renderKpis();
    applyResultsFilters();
    applyExceptionFilters();
    renderCandidateInspector();
    renderAuditTimeline();
  } catch (err) {
    console.error('Failed to load run details:', err);
    showToast(`Error loading run details: ${err.message}`, 'error');
  }
}

async function refreshAllRuns(selectFirst = false) {
  try {
    const data = await API.getRuns();
    state.runs = data.runs || [];
    renderRunSelector();

    if (state.runs.length > 0) {
      const targetId = selectFirst || !state.activeRunId ? state.runs[0].run_id : state.activeRunId;
      await loadRunDetails(targetId);
    }
  } catch (err) {
    console.error('Failed to load historical runs:', err);
    showToast(`Failed to load historical runs: ${err.message}`, 'error');
  }
}

// ---------------------------------------------------------------------------
// 6. Filtering Logic
// ---------------------------------------------------------------------------
function applyResultsFilters() {
  const search = document.getElementById('filterSearch').value.toLowerCase().trim();
  const outcome = document.getElementById('filterOutcome').value;
  const relType = document.getElementById('filterType').value;
  const review = document.getElementById('filterReview').value;

  state.filteredResults = state.results.filter(r => {
    if (outcome && r.outcome !== outcome) return false;
    if (relType && r.relationship_type !== relType) return false;
    if (review !== '') {
      const isReview = review === 'true';
      if (r.flag_for_review !== isReview) return false;
    }
    if (search) {
      const matchId = r.relationship_id.toLowerCase().includes(search);
      const matchSrc = (r.source_record_ids || []).some(id => id.toLowerCase().includes(search));
      const matchTgt = (r.target_record_ids || []).some(id => id.toLowerCase().includes(search));
      const matchAmt = (r.reconciled_amount || '').toLowerCase().includes(search);
      if (!matchId && !matchSrc && !matchTgt && !matchAmt) return false;
    }
    return true;
  });

  renderResultsTable();
}

function applyExceptionFilters() {
  const sev = document.getElementById('filterExceptionSeverity').value;
  const type = document.getElementById('filterExceptionType').value;

  state.filteredExceptions = state.exceptions.filter(e => {
    if (sev && e.severity !== sev) return false;
    if (type && e.exception_type !== type) return false;
    return true;
  });

  renderExceptionsTable();
}

// ---------------------------------------------------------------------------
// 7. Event Handlers & Initialization
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', async () => {
  // 1. Initial Health Check
  try {
    const health = await API.getHealth();
    renderHeaderStatus(health.provider);
  } catch (e) {
    renderHeaderStatus('Offline');
  }

  // 2. Load historical runs
  await refreshAllRuns(true);

  // 3. Tab switching
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));

      btn.classList.add('active');
      const targetPane = document.getElementById(btn.dataset.tab);
      if (targetPane) targetPane.classList.add('active');
    });
  });

  // 4. Run selector dropdown
  document.getElementById('runSelect').addEventListener('change', e => {
    if (e.target.value) {
      loadRunDetails(e.target.value);
    }
  });

  document.getElementById('btnRefreshRuns').addEventListener('click', () => {
    refreshAllRuns();
    showToast('Refreshed runs list', 'info');
  });

  // 5. Results Filters
  document.getElementById('filterSearch').addEventListener('input', applyResultsFilters);
  document.getElementById('filterOutcome').addEventListener('change', applyResultsFilters);
  document.getElementById('filterType').addEventListener('change', applyResultsFilters);
  document.getElementById('filterReview').addEventListener('change', applyResultsFilters);

  // 6. Exceptions Filters
  document.getElementById('filterExceptionSeverity').addEventListener('change', applyExceptionFilters);
  document.getElementById('filterExceptionType').addEventListener('change', applyExceptionFilters);

  // 7. Export triggers
  document.getElementById('btnExportCsv').addEventListener('click', () => {
    if (state.activeRunId) {
      window.location.href = `/runs/${encodeURIComponent(state.activeRunId)}/export?format=csv`;
    }
  });

  document.getElementById('btnExportJson').addEventListener('click', () => {
    if (state.activeRunId) {
      window.location.href = `/runs/${encodeURIComponent(state.activeRunId)}/export?format=json`;
    }
  });

  // 8. Upload Modal Controls
  const modal = document.getElementById('uploadModal');
  const btnOpen = document.getElementById('btnOpenUpload');
  const btnClose = document.getElementById('btnCloseUploadModal');
  const btnCancel = document.getElementById('btnCancelUpload');

  btnOpen.addEventListener('click', () => modal.classList.remove('hidden'));
  btnClose.addEventListener('click', () => modal.classList.add('hidden'));
  btnCancel.addEventListener('click', () => modal.classList.add('hidden'));

  // 9. Drag and drop file handling
  setupDropzone('dropzoneGateway', 'fileGateway', 'textGateway', 'infoGateway', f => {
    state.selectedGatewayFile = f;
  });

  setupDropzone('dropzoneBank', 'fileBank', 'textBank', 'infoBank', f => {
    state.selectedBankFile = f;
  });

  // 10. Quick load synthetic data
  document.getElementById('btnQuickLoadSynthetic').addEventListener('click', async () => {
    try {
      showToast('Loading synthetic Gateway & Bank CSVs...', 'info');
      const data = await API.getSyntheticDataSample();

      const gtwBlob = new Blob([data.gateway_content], { type: 'text/csv' });
      const bankBlob = new Blob([data.bank_content], { type: 'text/csv' });

      state.selectedGatewayFile = new File([gtwBlob], data.gateway_filename, { type: 'text/csv' });
      state.selectedBankFile = new File([bankBlob], data.bank_filename, { type: 'text/csv' });

      document.getElementById('dropzoneGateway').classList.add('file-selected');
      document.getElementById('infoGateway').textContent = `Loaded ${data.gateway_filename} (40 transactions)`;

      document.getElementById('dropzoneBank').classList.add('file-selected');
      document.getElementById('infoBank').textContent = `Loaded ${data.bank_filename} (41 transactions)`;

      showToast('Synthetic test dataset loaded into upload form!', 'success');
    } catch (e) {
      showToast(`Quick-load error: ${e.message}`, 'error');
    }
  });

  // 11. Form Submission & Reconciliation Run
  document.getElementById('uploadForm').addEventListener('submit', async e => {
    e.preventDefault();

    if (!state.selectedGatewayFile || !state.selectedBankFile) {
      showToast('Please select both Gateway and Bank CSV files.', 'error');
      return;
    }

    const progressBox = document.getElementById('uploadProgressContainer');
    const progressBar = document.getElementById('uploadProgressBar');
    const progressText = document.getElementById('uploadProgressText');
    const submitBtn = document.getElementById('btnSubmitReconciliation');

    progressBox.classList.remove('hidden');
    submitBtn.disabled = true;

    progressBar.style.width = '30%';
    progressText.textContent = 'Uploading files to engine...';

    const formData = new FormData();
    formData.append('gateway_file', state.selectedGatewayFile);
    formData.append('bank_file', state.selectedBankFile);

    try {
      progressBar.style.width = '70%';
      progressText.textContent = 'Executing deterministic matching & AI classification...';

      const response = await API.createRun(formData);

      progressBar.style.width = '100%';
      progressText.textContent = 'Reconciliation completed!';

      showToast(`Run ${response.run_id} completed successfully!`, 'success');

      modal.classList.add('hidden');
      progressBox.classList.add('hidden');
      submitBtn.disabled = false;

      // Refresh and switch to the new run
      await refreshAllRuns();
      if (response.run_id) {
        await loadRunDetails(response.run_id);
      }
    } catch (err) {
      console.error(err);
      progressText.textContent = 'Reconciliation failed.';
      showToast(`Run failed: ${err.message}`, 'error');
      submitBtn.disabled = false;
    }
  });
});

function setupDropzone(zoneId, inputId, textId, infoId, onFileSelect) {
  const dropzone = document.getElementById(zoneId);
  const input = document.getElementById(inputId);
  const textEl = document.getElementById(textId);
  const infoEl = document.getElementById(infoId);

  input.addEventListener('change', e => {
    const file = e.target.files[0];
    if (file) {
      dropzone.classList.add('file-selected');
      infoEl.textContent = `Selected: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
      onFileSelect(file);
    }
  });

  dropzone.addEventListener('dragover', e => {
    e.preventDefault();
    dropzone.classList.add('dragover');
  });

  dropzone.addEventListener('dragleave', () => {
    dropzone.classList.remove('dragover');
  });

  dropzone.addEventListener('drop', e => {
    e.preventDefault();
    dropzone.classList.remove('dragover');
    const file = e.dataTransfer.files[0];
    if (file && file.name.endsWith('.csv')) {
      dropzone.classList.add('file-selected');
      infoEl.textContent = `Dropped: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
      onFileSelect(file);
    } else {
      showToast('Please upload a valid .csv file.', 'error');
    }
  });
}
