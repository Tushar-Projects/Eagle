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

  async extractPreview(file, sourceType = 'GATEWAY') {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`/runs/extract-preview?source_type=${encodeURIComponent(sourceType)}`, {
      method: 'POST',
      body: formData,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Preview extraction error' }));
      throw new Error(err.detail || 'Preview extraction failed');
    }
    return await res.json();
  },

  async getSyntheticDataSample() {
    const res = await fetch('/demo/synthetic-data');
    if (!res.ok) throw new Error('Synthetic sample dataset unavailable');
    return await res.json();
  },

  async askQa(question, runId = null) {
    const payload = { question, run_id: runId };
    const url = runId ? `/runs/${encodeURIComponent(runId)}/qa` : '/qa';
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Q&A query error' }));
      throw new Error(err.detail || 'Q&A query failed');
    }
    return await res.json();
  },

  async getRecords(runId, source = null) {
    const url = source
      ? `/runs/${encodeURIComponent(runId)}/records?source=${encodeURIComponent(source)}`
      : `/runs/${encodeURIComponent(runId)}/records`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Failed to fetch records for ${runId}`);
    return await res.json();
  },

  async submitCorrection(runId, relationshipId, payload) {
    const res = await fetch(`/runs/${encodeURIComponent(runId)}/results/${encodeURIComponent(relationshipId)}/correct`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Correction submission failed' }));
      throw new Error(err.detail || 'Correction submission failed');
    }
    return await res.json();
  },

  async getCorrections(runId) {
    const res = await fetch(`/runs/${encodeURIComponent(runId)}/corrections`);
    if (!res.ok) throw new Error(`Failed to fetch corrections for ${runId}`);
    return await res.json();
  },

  async getCorrection(runId, correctionId) {
    const res = await fetch(`/runs/${encodeURIComponent(runId)}/corrections/${encodeURIComponent(correctionId)}`);
    if (!res.ok) throw new Error(`Failed to fetch correction ${correctionId}`);
    return await res.json();
  },

  async getRules(activeOnly = false) {
    const res = await fetch(`/rules?active_only=${activeOnly}`);
    if (!res.ok) throw new Error('Failed to fetch rules');
    return await res.json();
  },

  async toggleRule(ruleId, isActive) {
    const res = await fetch(`/rules/${encodeURIComponent(ruleId)}/toggle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_active: isActive }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Failed to toggle rule' }));
      throw new Error(err.detail || `Failed to toggle rule ${ruleId}`);
    }
    return await res.json();
  },

  async rerunWithRules(runId, applyRules = true) {
    const res = await fetch(`/runs/${encodeURIComponent(runId)}/rerun`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apply_rules: applyRules }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Rerun execution failed' }));
      throw new Error(err.detail || 'Rerun execution failed');
    }
    return await res.json();
  },

  async getRule(ruleId) {
    const res = await fetch(`/rules/${encodeURIComponent(ruleId)}`);
    if (!res.ok) throw new Error(`Failed to fetch rule ${ruleId}`);
    return await res.json();
  },

  async createRule(payload) {
    const res = await fetch('/rules', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Failed to create rule' }));
      throw new Error(err.detail || 'Failed to create rule');
    }
    return await res.json();
  },

  async validateRule(payload) {
    const res = await fetch('/rules/validate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Rule validation failed' }));
      throw new Error(err.detail || 'Rule validation failed');
    }
    return await res.json();
  },

  async getRuleImpact(runId) {
    const res = await fetch(`/runs/${encodeURIComponent(runId)}/rule-impact`);
    if (!res.ok) throw new Error(`Failed to fetch rule impact for ${runId}`);
    return await res.json();
  },

  async deleteRun(runId) {
    const res = await fetch(`/runs/${encodeURIComponent(runId)}`, {
      method: 'DELETE',
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Failed to delete run' }));
      throw new Error(err.detail || `Failed to delete run ${runId}`);
    }
    return await res.json();
  },

  async deleteRule(ruleId) {
    const res = await fetch(`/rules/${encodeURIComponent(ruleId)}`, {
      method: 'DELETE',
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Failed to delete rule' }));
      throw new Error(err.detail || `Failed to delete rule ${ruleId}`);
    }
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
  records: [],
  corrections: [],
  rules: [],
  ruleImpact: null,
  selectedExceptionForCorrection: null,
  selectedRuleForDeletion: null,
  selectedGatewayFile: null,
  selectedBankFile: null,
};


// ---------------------------------------------------------------------------
// 3. UI Helpers & Formatting
// ---------------------------------------------------------------------------
function resetQaPanel() {
  const qaSection = document.getElementById('qaAnswerSection');
  const qaAnswerText = document.getElementById('qaAnswerText');
  const qaSourcesList = document.getElementById('qaSourcesList');
  const qaInput = document.getElementById('qaInput');
  if (qaSection) qaSection.classList.add('hidden');
  if (qaAnswerText) qaAnswerText.textContent = '';
  if (qaSourcesList) qaSourcesList.innerHTML = '';
  if (qaInput) qaInput.value = '';
}

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
  const btnDeleteHeader = document.getElementById('btnDeleteRunHeader');
  const btnDeleteActive = document.getElementById('btnDeleteCurrentRun');
  select.innerHTML = '';

  const disabled = state.runs.length === 0 || !state.activeRunId;
  if (btnDeleteHeader) btnDeleteHeader.disabled = disabled;
  if (btnDeleteActive) btnDeleteActive.disabled = disabled;

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
  const btnDeleteHeader = document.getElementById('btnDeleteRunHeader');
  const btnDeleteActive = document.getElementById('btnDeleteCurrentRun');

  if (!state.activeRun) {
    title.textContent = 'No Run Selected';
    badge.className = 'run-status-badge badge-neutral';
    badge.textContent = 'IDLE';
    time.textContent = '--';
    btnCsv.disabled = true;
    btnJson.disabled = true;
    if (btnDeleteHeader) btnDeleteHeader.disabled = true;
    if (btnDeleteActive) btnDeleteActive.disabled = true;

    const scopeBadge = document.getElementById('qaScopeBadge');
    if (scopeBadge) {
      scopeBadge.textContent = 'Scope: All Runs (Global)';
    }
    return;
  }

  title.textContent = state.activeRun.run_id;
  badge.textContent = state.activeRun.status;
  badge.className = `run-status-badge badge-${state.activeRun.status.toLowerCase()}`;
  time.textContent = `Completed: ${formatTimestamp(state.activeRun.completed_at || state.activeRun.created_at)}`;

  btnCsv.disabled = false;
  btnJson.disabled = false;
  if (btnDeleteHeader) btnDeleteHeader.disabled = false;
  if (btnDeleteActive) btnDeleteActive.disabled = false;
}


function renderKpis() {
  const m = state.metrics || {};
  document.getElementById('kpiTotalRecords').textContent = m.total_records || 0;
  document.getElementById('kpiRecordSplit').textContent = `${m.source_count || 0} Gateway / ${m.target_count || 0} Bank`;
  
  document.getElementById('kpiMatchedCount').textContent = m.matched_count || 0;
  document.getElementById('kpiMatchRate').textContent = `${(m.match_rate || 0).toFixed(1)}% Record Match`;

  const valEl = document.getElementById('kpiValueMatchRate');
  if (valEl) {
    valEl.textContent = `${(m.value_weighted_match_rate || 0).toFixed(1)}%`;
  }

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
    tbody.innerHTML = `<tr><td colspan="9" class="table-empty">No reconciliation results match the current filters.</td></tr>`;
    return;
  }

  // Build rule provenance lookup from audit logs for active run
  const ruleByRelId = {};
  (state.auditLogs || []).forEach(log => {
    if (log.event_type === 'RULE_APPLICATION_COMPLETED' && log.details && log.details.relationship_id) {
      ruleByRelId[log.details.relationship_id] = log.details.rule_id;
    }
  });

  state.filteredResults.forEach(r => {
    const tr = document.createElement('tr');

    const sourceChips = (r.source_record_ids || []).map(id => `<span class="chip">${id}</span>`).join('');
    const targetChips = (r.target_record_ids || []).map(id => `<span class="chip">${id}</span>`).join('');

    const outcomeBadge = r.outcome === 'MATCHED'
      ? `<span class="badge-pill badge-pill-green">MATCHED</span>`
      : `<span class="badge-pill badge-pill-red">EXCEPTION</span>`;

    let classBadge = r.exception_type
      ? `<span class="badge-pill badge-pill-amber">${r.exception_type}</span>`
      : `<span class="badge-pill badge-pill-blue">EXACT MATCH</span>`;

    if (ruleByRelId[r.relationship_id]) {
      classBadge = `<span class="badge-pill badge-pill-purple" title="Matched by learned rule ${ruleByRelId[r.relationship_id]}">RULE APPLIED (${ruleByRelId[r.relationship_id]})</span>`;
    }

    const reviewBadge = r.flag_for_review
      ? `<span class="badge-pill badge-pill-red">REVIEW REQUIRED</span>`
      : `<span class="badge-pill badge-pill-green">VERIFIED</span>`;

    const actionCell = (r.outcome !== 'MATCHED' || r.flag_for_review)
      ? `<button class="btn btn-sm btn-correct" data-rel-id="${r.relationship_id}">Correct</button>`
      : `<span class="text-muted">—</span>`;

    tr.innerHTML = `
      <td><code>${r.relationship_id}</code></td>
      <td><strong>${r.relationship_type}</strong></td>
      <td><div class="participant-chips">${sourceChips || '<span class="text-muted">None</span>'}</div></td>
      <td><div class="participant-chips">${targetChips || '<span class="text-muted">None</span>'}</div></td>
      <td>${outcomeBadge}</td>
      <td>${classBadge}</td>
      <td><strong>${formatCurrency(r.reconciled_amount)}</strong></td>
      <td>${reviewBadge}</td>
      <td>${actionCell}</td>
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
    tbody.innerHTML = `<tr><td colspan="8" class="table-empty">No exception records found for this run.</td></tr>`;
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
      <td><button class="btn btn-sm btn-correct" data-rel-id="${e.relationship_id}">Correct</button></td>
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

function resetQaPanel() {
  const qaSection = document.getElementById('qaAnswerSection');
  const qaAnswerText = document.getElementById('qaAnswerText');
  const qaSourcesList = document.getElementById('qaSourcesList');
  const qaLatencyMeta = document.getElementById('qaLatencyMeta');
  const qaEvidenceStatus = document.getElementById('qaEvidenceStatus');
  const qaInput = document.getElementById('qaInput');

  if (qaSection) qaSection.classList.add('hidden');
  if (qaAnswerText) qaAnswerText.textContent = '';
  if (qaSourcesList) qaSourcesList.innerHTML = '';
  if (qaLatencyMeta) qaLatencyMeta.textContent = 'Retrieval: -- | Generation: --';
  if (qaEvidenceStatus) qaEvidenceStatus.textContent = '';
  if (qaInput) qaInput.value = '';
}

function renderCorrectionsHistory() {
  const tbody = document.getElementById('correctionsTableBody');
  const countBadge = document.getElementById('countCorrections');
  const countSection = document.getElementById('countCorrectionsSection');
  if (!tbody) return;
  tbody.innerHTML = '';

  const corrections = state.corrections || [];
  if (countBadge) countBadge.textContent = corrections.length;
  if (countSection) countSection.textContent = corrections.length;

  if (corrections.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="table-empty">No operator corrections recorded for this run.</td></tr>';
    return;
  }

  corrections.forEach(c => {
    const tr = document.createElement('tr');
    const ruleBadge = c.generated_rule_id
      ? `<span class="badge-pill badge-pill-purple">${c.generated_rule_id}</span>`
      : '<span class="text-muted">None</span>';

    tr.innerHTML = `
      <td><code>${c.correction_id}</code></td>
      <td><code>${c.relationship_id}</code></td>
      <td>
        <span class="badge-pill ${c.original_outcome === 'MATCHED' ? 'badge-pill-green' : 'badge-pill-red'}">${c.original_outcome}</span>
        &rarr;
        <span class="badge-pill ${c.corrected_outcome === 'MATCHED' ? 'badge-pill-green' : 'badge-pill-red'}">${c.corrected_outcome}</span>
      </td>
      <td style="max-width: 250px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${c.operator_reason}">${c.operator_reason}</td>
      <td>${ruleBadge}</td>
      <td>${formatTimestamp(c.created_at)}</td>
      <td>
        <button class="btn btn-sm btn-outline btn-inspect-corr" data-corr-id="${c.correction_id}">Details</button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function renderRulesTable() {
  const tbody = document.getElementById('rulesTableBody');
  const countEl = document.getElementById('countRulesSection');
  const activeRulesBadge = document.getElementById('activeRulesBadge');
  const statActiveRules = document.getElementById('statActiveRules');
  const statCorrections = document.getElementById('statCorrections');
  const ruleScopeIndicator = document.getElementById('ruleScopeIndicator');
  const btnRerun = document.getElementById('btnRerunWithRules');
  const btnTabRerun = document.getElementById('btnTabRerunWithRules');
  if (!tbody) return;
  tbody.innerHTML = '';

  const rules = state.rules || [];
  if (countEl) countEl.textContent = rules.length;
  const activeCount = rules.filter(r => r.is_active).length;
  if (activeRulesBadge) activeRulesBadge.textContent = activeCount;
  if (statActiveRules) statActiveRules.textContent = activeCount;
  if (statCorrections) statCorrections.textContent = (state.corrections || []).length;

  if (ruleScopeIndicator) {
    ruleScopeIndicator.textContent = state.activeRunId
      ? `GLOBAL RULES (Applied to current run: ${state.activeRunId})`
      : 'GLOBAL RULES';
  }

  // Handle visibility of top active run rerun button
  if (btnRerun) {
    if (activeCount > 0 && state.activeRunId) {
      btnRerun.classList.remove('hidden');
    } else {
      btnRerun.classList.add('hidden');
    }
  }

  // Handle disabled state of tab rerun button
  if (btnTabRerun) {
    btnTabRerun.disabled = !state.activeRunId || activeCount === 0;
    btnTabRerun.title = activeCount === 0
      ? 'No active rules available to apply in rerun'
      : 'Rerun reconciliation applying active learned rules';
  }

  if (rules.length === 0) {
    tbody.innerHTML = '<tr><td colspan="10" class="table-empty">No learned rules available. Click "+ Add Reconciliation Rule" or submit an exception correction.</td></tr>';
    return;
  }

  rules.forEach(r => {
    const tr = document.createElement('tr');
    const predicateChips = [
      r.source_counterparty_pattern ? `<span class="predicate-tag"><span class="pred-k">CP</span> <span class="pred-v">"${r.source_counterparty_pattern}"</span></span>` : null,
      r.reference_prefix ? `<span class="predicate-tag"><span class="pred-k">Ref</span> <span class="pred-v">"${r.reference_prefix}"</span></span>` : null,
      r.currency ? `<span class="predicate-tag"><span class="pred-k">Curr</span> <span class="pred-v">${r.currency}</span></span>` : null,
      r.max_amount_difference ? `<span class="predicate-tag"><span class="pred-k">Tol</span> <span class="pred-v">₹${r.max_amount_difference}</span></span>` : null,
      r.max_settlement_delay_days ? `<span class="predicate-tag"><span class="pred-k">Delay</span> <span class="pred-v">${r.max_settlement_delay_days}d</span></span>` : null,
    ].filter(Boolean);

    const predicatesHtml = predicateChips.length > 0
      ? `<div class="predicate-tag-group">${predicateChips.join('')}</div>`
      : '<span class="text-muted">Wildcard (Any)</span>';

    const resultingBadge = r.resulting_outcome === 'MATCHED'
      ? '<span class="badge-pill badge-pill-green">MATCHED</span>'
      : `<span class="badge-pill badge-pill-red">${r.resulting_outcome} (${r.resulting_exception_type || 'EXCEPTION'})</span>`;

    const statusBadge = r.is_active
      ? '<span class="badge-pill badge-pill-green">ACTIVE</span>'
      : '<span class="badge-pill badge-pill-red">INACTIVE</span>';

    const createdFrom = r.source_correction_id
      ? `<span class="badge-pill badge-pill-purple" title="Synthesized from ${r.source_correction_id}">${r.source_correction_id}</span>`
      : '<span class="text-muted">Structured Builder</span>';

    tr.innerHTML = `
      <td><code>${r.rule_id}</code></td>
      <td><strong>${r.name}</strong></td>
      <td>${statusBadge}</td>
      <td><span class="scope-pill-badge" style="font-size:0.7rem;">GLOBAL RULE</span></td>
      <td>${predicatesHtml}</td>
      <td>${resultingBadge}</td>
      <td>${(r.confidence * 100).toFixed(0)}%</td>
      <td>${createdFrom}</td>
      <td>${formatTimestamp(r.created_at)}</td>
      <td>
        <div class="btn-rule-action-group">
          <button type="button" class="btn btn-sm btn-outline btn-view-rule" data-rule-id="${r.rule_id}" title="Inspect rule details">View</button>
          <button type="button" class="btn btn-sm ${r.is_active ? 'btn-secondary' : 'btn-primary'} btn-toggle-rule" data-rule-id="${r.rule_id}" data-active="${r.is_active}" title="${r.is_active ? 'Deactivate rule' : 'Activate rule'}">
            ${r.is_active ? 'Deactivate' : 'Activate'}
          </button>
          <button type="button" class="btn btn-sm btn-danger btn-delete-rule" data-rule-id="${r.rule_id}" title="Delete rule">Delete</button>
        </div>
      </td>

    `;
    tbody.appendChild(tr);
  });
}


function renderRuleImpact() {
  const container = document.getElementById('ruleImpactContainer');
  const grid = document.getElementById('impactGridContainer');
  const subtitle = document.getElementById('impactSubtitle');
  if (!container || !grid) return;

  if (!state.ruleImpact || !state.ruleImpact.has_rerun || !state.ruleImpact.before || !state.ruleImpact.after) {
    container.classList.add('hidden');
    grid.innerHTML = '';
    return;
  }

  const b = state.ruleImpact.before;
  const a = state.ruleImpact.after;
  const d = state.ruleImpact.delta || {};

  container.classList.remove('hidden');
  if (subtitle) {
    subtitle.textContent = `Baseline Run: ${b.run_id} &rarr; Rerun: ${a.run_id}`;
  }

  const mrDeltaStr = (d.match_rate_improvement >= 0 ? '+' : '') + d.match_rate_improvement.toFixed(1) + ' pp';
  const vmrDeltaStr = (d.value_weighted_improvement >= 0 ? '+' : '') + d.value_weighted_improvement.toFixed(1) + ' pp';
  const exDeltaStr = (d.resolved_exceptions > 0 ? `-${d.resolved_exceptions} (resolved)` : `${d.resolved_exceptions}`);

  grid.innerHTML = `
    <table class="impact-table">
      <thead>
        <tr>
          <th>Metric</th>
          <th>Before (Baseline: ${b.run_id})</th>
          <th>After (Rerun: ${a.run_id})</th>
          <th>Improvement</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><strong>Record Match Rate</strong></td>
          <td>${b.match_rate.toFixed(1)}%</td>
          <td><strong>${a.match_rate.toFixed(1)}%</strong></td>
          <td>
            <span class="impact-delta-pill ${d.match_rate_improvement > 0 ? 'positive' : 'neutral'}">
              ${mrDeltaStr}
            </span>
          </td>
        </tr>
        <tr>
          <td><strong>Value-Weighted Match Rate</strong></td>
          <td>${b.value_weighted_match_rate.toFixed(1)}%</td>
          <td><strong>${a.value_weighted_match_rate.toFixed(1)}%</strong></td>
          <td>
            <span class="impact-delta-pill ${d.value_weighted_improvement > 0 ? 'positive' : 'neutral'}">
              ${vmrDeltaStr}
            </span>
          </td>
        </tr>
        <tr>
          <td><strong>Exceptions Count</strong></td>
          <td>${b.exception_count}</td>
          <td><strong>${a.exception_count}</strong></td>
          <td>
            <span class="impact-delta-pill ${d.resolved_exceptions > 0 ? 'positive' : 'neutral'}">
              ${d.resolved_exceptions} resolved
            </span>
          </td>
        </tr>
        <tr>
          <td><strong>Matched Relationships</strong></td>
          <td>${b.matched_count}</td>
          <td><strong>${a.matched_count}</strong></td>
          <td>
            <span class="impact-delta-pill ${a.matched_count > b.matched_count ? 'positive' : 'neutral'}">
              +${a.matched_count - b.matched_count} matches
            </span>
          </td>
        </tr>
        <tr>
          <td><strong>Total Reconciled Volume</strong></td>
          <td>₹${parseFloat(b.total_reconciled_amount || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}</td>
          <td><strong>₹${parseFloat(a.total_reconciled_amount || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}</strong></td>
          <td>
            <span class="impact-delta-pill neutral">
              ${parseFloat(d.reconciled_amount_change || 0) >= 0 ? '+' : ''}₹${parseFloat(d.reconciled_amount_change || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
            </span>
          </td>
        </tr>
      </tbody>
    </table>
  `;
}

// ---------------------------------------------------------------------------
// 5. Data Loading Orchestration
// ---------------------------------------------------------------------------
async function loadRunDetails(runId) {
  if (!runId) return;
  state.activeRunId = runId;

  // Clear stale Q&A evidence, modals, and impact states immediately upon switching runs
  resetQaPanel();
  closeCorrectionModal();
  closeAddRuleModal();
  closeRuleDetailModal();
  state.selectedExceptionForCorrection = null;
  state.ruleImpact = null;


  try {
    const [run, metrics, resultsData, exceptionsData, candidatesData, auditData, recordsData, correctionsData, rulesData, impactData] = await Promise.all([
      API.getRun(runId),
      API.getMetrics(runId),
      API.getResults(runId),
      API.getExceptions(runId),
      API.getCandidates(runId),
      API.getAuditLogs(runId),
      API.getRecords(runId).catch(() => ({ records: [] })),
      API.getCorrections(runId).catch(() => ({ corrections: [] })),
      API.getRules().catch(() => ({ rules: [] })),
      API.getRuleImpact(runId).catch(() => ({ has_rerun: false })),
    ]);

    state.activeRun = run;
    state.metrics = metrics;
    state.results = resultsData.results || [];
    state.filteredResults = [...state.results];
    state.exceptions = exceptionsData.results || [];
    state.filteredExceptions = [...state.exceptions];
    state.candidates = candidatesData.candidates || [];
    state.auditLogs = auditData || [];
    state.records = recordsData.records || [];
    state.corrections = correctionsData.corrections || [];
    state.rules = rulesData.rules || [];
    state.ruleImpact = impactData;

    renderActiveRunMeta();
    renderKpis();
    applyResultsFilters();
    applyExceptionFilters();
    renderCandidateInspector();
    renderAuditTimeline();
    renderCorrectionsHistory();
    renderRulesTable();
    renderRuleImpact();

    const scopeBadge = document.getElementById('qaScopeBadge');
    if (scopeBadge) {
      scopeBadge.textContent = `Scope: ${runId}`;
    }
  } catch (err) {
    console.error('Failed to load run details:', err);
    showToast(`Error loading run details: ${err.message}`, 'error');
  }
}

function openCorrectionModal(relId) {
  const rel = state.results.find(r => r.relationship_id === relId) ||
              state.exceptions.find(r => r.relationship_id === relId);
  if (!rel) {
    showToast(`Relationship ${relId} not found in active run.`, 'error');
    return;
  }

  state.selectedExceptionForCorrection = rel;

  // 1. Populate Read-Only Box
  document.getElementById('origRelId').textContent = rel.relationship_id;
  document.getElementById('origTopology').textContent = rel.relationship_type || '1:1';
  document.getElementById('origAmount').textContent = formatCurrency(rel.reconciled_amount);

  const origOutcomeBadge = document.getElementById('origOutcomeBadge');
  origOutcomeBadge.textContent = rel.outcome;
  origOutcomeBadge.className = `badge-pill ${rel.outcome === 'MATCHED' ? 'badge-pill-green' : 'badge-pill-red'}`;

  const origExBadge = document.getElementById('origExceptionBadge');
  origExBadge.textContent = rel.exception_type || 'None';
  origExBadge.className = `badge-pill ${rel.exception_type ? 'badge-pill-amber' : 'badge-pill-blue'}`;

  const origReviewBadge = document.getElementById('origReviewFlag');
  origReviewBadge.textContent = rel.flag_for_review ? 'Review Required' : 'Verified';
  origReviewBadge.className = `badge-pill ${rel.flag_for_review ? 'badge-pill-red' : 'badge-pill-green'}`;

  const srcContainer = document.getElementById('origSourceChips');
  srcContainer.innerHTML = (rel.source_record_ids || []).map(id => `<span class="chip">${id}</span>`).join('') || '<span class="text-muted">None</span>';

  const tgtContainer = document.getElementById('origTargetChips');
  tgtContainer.innerHTML = (rel.target_record_ids || []).map(id => `<span class="chip">${id}</span>`).join('') || '<span class="text-muted">None</span>';

  // 2. Populate Pickers from active run records
  const gtwRecords = state.records.filter(r => r.source !== 'BANK');
  const bankRecords = state.records.filter(r => r.source === 'BANK');

  const corrSourcePicker = document.getElementById('corrSourcePicker');
  corrSourcePicker.innerHTML = '';
  if (gtwRecords.length === 0) {
    corrSourcePicker.innerHTML = '<div class="text-muted" style="padding:0.5rem;font-size:0.8rem;">No gateway records available</div>';
  } else {
    gtwRecords.forEach(r => {
      const isChecked = (rel.source_record_ids || []).includes(r.record_id);
      const item = document.createElement('label');
      item.className = 'record-picker-item';
      item.innerHTML = `
        <input type="checkbox" value="${r.record_id}" class="corr-source-checkbox" ${isChecked ? 'checked' : ''}>
        <span>${r.record_id}</span>
        <span class="record-picker-meta">₹${r.amount} | ${r.counterparty || 'N/A'}</span>
      `;
      corrSourcePicker.appendChild(item);
    });
  }

  const corrTargetPicker = document.getElementById('corrTargetPicker');
  corrTargetPicker.innerHTML = '';
  if (bankRecords.length === 0) {
    corrTargetPicker.innerHTML = '<div class="text-muted" style="padding:0.5rem;font-size:0.8rem;">No bank records available</div>';
  } else {
    bankRecords.forEach(r => {
      const isChecked = (rel.target_record_ids || []).includes(r.record_id);
      const item = document.createElement('label');
      item.className = 'record-picker-item';
      item.innerHTML = `
        <input type="checkbox" value="${r.record_id}" class="corr-target-checkbox" ${isChecked ? 'checked' : ''}>
        <span>${r.record_id}</span>
        <span class="record-picker-meta">₹${r.amount} | ${r.counterparty || 'N/A'}</span>
      `;
      corrTargetPicker.appendChild(item);
    });
  }

  // 3. Set Default Form State
  const outcomeSelect = document.getElementById('corrOutcome');
  outcomeSelect.value = rel.outcome === 'EXCEPTION' ? 'MATCHED' : 'EXCEPTION';

  const exGroup = document.getElementById('corrExceptionGroup');
  const exSelect = document.getElementById('corrExceptionType');
  if (outcomeSelect.value === 'MATCHED') {
    exGroup.style.display = 'none';
    exSelect.value = '';
  } else {
    exGroup.style.display = 'flex';
    exSelect.value = rel.exception_type || 'UNKNOWN';
  }

  document.getElementById('corrReason').value = '';
  document.getElementById('corrGenerateRule').checked = true;
  document.getElementById('corrValidationAlert').classList.add('hidden');
  document.getElementById('corrValidationAlert').textContent = '';

  // 4. Show Modal
  document.getElementById('correctionModal').classList.remove('hidden');
}

function closeCorrectionModal() {
  const modal = document.getElementById('correctionModal');
  if (modal) modal.classList.add('hidden');
  state.selectedExceptionForCorrection = null;
}

async function submitCorrectionForm(e) {
  e.preventDefault();
  if (!state.selectedExceptionForCorrection || !state.activeRunId) return;

  const rel = state.selectedExceptionForCorrection;
  const outcome = document.getElementById('corrOutcome').value;
  const exType = outcome === 'EXCEPTION' ? (document.getElementById('corrExceptionType').value || null) : null;
  const reason = document.getElementById('corrReason').value.trim();
  const generateRule = document.getElementById('corrGenerateRule').checked;

  const selectedSources = Array.from(document.querySelectorAll('.corr-source-checkbox:checked')).map(cb => cb.value);
  const selectedTargets = Array.from(document.querySelectorAll('.corr-target-checkbox:checked')).map(cb => cb.value);

  const alertBox = document.getElementById('corrValidationAlert');

  // Client-side validations
  if (selectedSources.length === 0 && selectedTargets.length === 0) {
    alertBox.textContent = 'At least one Gateway or Bank participant record must be selected.';
    alertBox.classList.remove('hidden');
    return;
  }

  if (selectedSources.length > 1 && selectedTargets.length > 1) {
    alertBox.textContent = 'General N:M relationship topology is prohibited. Supported topologies are 1:1, 1:N, N:1, 1:0, or 0:1.';
    alertBox.classList.remove('hidden');
    return;
  }

  if (reason.length < 3) {
    alertBox.textContent = 'Please provide an operational justification (minimum 3 characters).';
    alertBox.classList.remove('hidden');
    return;
  }

  alertBox.classList.add('hidden');
  const btnSubmit = document.getElementById('btnSubmitCorrection');
  btnSubmit.disabled = true;
  btnSubmit.textContent = 'Submitting...';

  try {
    const payload = {
      corrected_outcome: outcome,
      corrected_exception_type: exType,
      corrected_source_ids: selectedSources,
      corrected_target_ids: selectedTargets,
      operator_reason: reason,
      generate_rule: generateRule,
    };

    const res = await API.submitCorrection(state.activeRunId, rel.relationship_id, payload);

    closeCorrectionModal();

    if (res.generated_rule_id) {
      showToast(`Correction saved! Synthesized Rule: ${res.generated_rule_id}`, 'success');
    } else {
      showToast('Correction submitted successfully', 'success');
    }

    // Refresh run data to show updated corrections and rules
    await loadRunDetails(state.activeRunId);

    // Switch to Corrections & Rules tab so operator immediately sees new correction and rule
    const tabBtn = document.querySelector('.tab-btn[data-tab="tab-corrections"]');
    if (tabBtn) tabBtn.click();

  } catch (err) {
    console.error('Correction submission failed:', err);
    alertBox.textContent = err.message || 'Correction submission failed.';
    alertBox.classList.remove('hidden');
  } finally {
    btnSubmit.disabled = false;
    btnSubmit.textContent = 'Submit Correction';
  }
}

async function openCorrectionDetail(corrId) {
  try {
    const corr = await API.getCorrection(state.activeRunId, corrId);
    const body = document.getElementById('correctionDetailBody');
    body.innerHTML = `
      <div class="orig-box-grid">
        <div><span class="text-muted">Correction ID:</span> <code>${corr.correction_id}</code></div>
        <div><span class="text-muted">Run ID:</span> <code>${corr.run_id}</code></div>
        <div><span class="text-muted">Relationship ID:</span> <code>${corr.relationship_id}</code></div>
        <div><span class="text-muted">Original Outcome:</span> <span class="badge-pill ${corr.original_outcome === 'MATCHED' ? 'badge-pill-green' : 'badge-pill-red'}">${corr.original_outcome}</span></div>
        <div><span class="text-muted">Corrected Outcome:</span> <span class="badge-pill ${corr.corrected_outcome === 'MATCHED' ? 'badge-pill-green' : 'badge-pill-red'}">${corr.corrected_outcome}</span></div>
        <div><span class="text-muted">Corrected Exception:</span> <span class="badge-pill badge-pill-amber">${corr.corrected_exception_type || 'None'}</span></div>
      </div>
      <div style="margin-top: 1rem;">
        <span class="text-muted">Operator Justification:</span>
        <div style="background: var(--bg-app); border: 1px solid var(--border-subtle); padding: 0.75rem; border-radius: var(--radius-md); margin-top: 0.25rem;">
          ${corr.operator_reason}
        </div>
      </div>
      <div style="margin-top: 1rem; display: flex; justify-content: space-between; font-size: 0.85rem;">
        <div><span class="text-muted">Synthesized Rule:</span> ${corr.generated_rule_id ? `<code class="badge-pill badge-pill-purple">${corr.generated_rule_id}</code>` : '<span class="text-muted">None</span>'}</div>
        <div><span class="text-muted">Submitted At:</span> ${formatTimestamp(corr.created_at)}</div>
      </div>
    `;
    document.getElementById('correctionDetailModal').classList.remove('hidden');
  } catch (err) {
    showToast(`Failed to load correction details: ${err.message}`, 'error');
  }
}

function openRerunModal() {
  const activeRules = (state.rules || []).filter(r => r.is_active);
  if (activeRules.length === 0) {
    showToast('No active learned rules available to apply in rerun.', 'info');
    return;
  }
  document.getElementById('rerunParentId').textContent = state.activeRunId;
  document.getElementById('rerunRulesCount').textContent = activeRules.length;
  document.getElementById('rerunConfirmModal').classList.remove('hidden');
}

async function executeRerun() {
  if (!state.activeRunId) return;

  const btnConfirm = document.getElementById('btnExecuteRerun');
  btnConfirm.disabled = true;
  btnConfirm.textContent = 'Executing Rerun...';

  try {
    const res = await API.rerunWithRules(state.activeRunId, true);
    const modal = document.getElementById('rerunConfirmModal');
    if (modal) modal.classList.add('hidden');

    showToast(`Rerun complete! Created ${res.rerun_id}`, 'success');

    // Refresh runs list and switch to the new rerun
    await refreshAllRuns(false);
    await loadRunDetails(res.rerun_id);

    // Switch to tab-corrections to show the Before/After impact card!
    const tabBtn = document.querySelector('.tab-btn[data-tab="tab-corrections"]');
    if (tabBtn) tabBtn.click();

  } catch (err) {
    console.error('Rerun failed:', err);
    showToast(`Rerun failed: ${err.message}`, 'error');
  } finally {
    btnConfirm.disabled = false;
    btnConfirm.textContent = 'Execute Rerun';
  }
}

function openAddRuleModal() {
  const form = document.getElementById('addRuleForm');
  if (form) form.reset();

  const relTypeSelect = document.getElementById('ruleRelType');
  if (relTypeSelect) relTypeSelect.value = '1:1';

  const outcomeSelect = document.getElementById('ruleOutcome');
  if (outcomeSelect) outcomeSelect.value = 'MATCHED';

  const exGroup = document.getElementById('ruleExceptionTypeGroup');
  if (exGroup) exGroup.style.display = 'none';

  const alertBox = document.getElementById('addRuleValidationAlert');
  const successBox = document.getElementById('addRuleValidationSuccess');
  if (alertBox) {
    alertBox.classList.add('hidden');
    alertBox.textContent = '';
  }
  if (successBox) {
    successBox.classList.add('hidden');
    successBox.textContent = '';
  }

  updateRulePreview();
  const modal = document.getElementById('addRuleModal');
  if (modal) modal.classList.remove('hidden');
}

function closeAddRuleModal() {
  const modal = document.getElementById('addRuleModal');
  if (modal) modal.classList.add('hidden');
}

function updateRulePreview() {
  const cp = (document.getElementById('ruleCounterparty')?.value || '').trim();
  const curr = (document.getElementById('ruleCurrency')?.value || '').trim().toUpperCase();
  const maxDiff = (document.getElementById('ruleMaxAmountDiff')?.value || '').trim();
  const maxDelay = (document.getElementById('ruleMaxDelayDays')?.value || '').trim();
  const relType = document.getElementById('ruleRelType')?.value || '1:1';
  const outcome = document.getElementById('ruleOutcome')?.value || 'MATCHED';
  const exType = document.getElementById('ruleExceptionType')?.value || '';

  const prevCp = document.getElementById('prevCp');
  const prevCurr = document.getElementById('prevCurr');
  const prevMaxDiff = document.getElementById('prevMaxDiff');
  const prevMaxDelay = document.getElementById('prevMaxDelay');
  const prevRelType = document.getElementById('prevRelType');
  const prevOutcome = document.getElementById('prevOutcome');

  if (prevCp) prevCp.textContent = cp ? cp : 'Wildcard (Any)';
  if (prevCurr) prevCurr.textContent = curr ? curr : 'Wildcard (Any)';
  if (prevMaxDiff) prevMaxDiff.textContent = maxDiff ? `₹${parseFloat(maxDiff).toFixed(2)}` : 'None';
  if (prevMaxDelay) prevMaxDelay.textContent = maxDelay ? `${maxDelay} day(s)` : 'None';
  if (prevRelType) prevRelType.textContent = relType;
  if (prevOutcome) prevOutcome.textContent = outcome === 'EXCEPTION' ? `EXCEPTION (${exType || 'General'})` : 'MATCHED';
}

function gatherAddRulePayload() {
  const name = (document.getElementById('ruleName')?.value || '').trim();
  const cp = (document.getElementById('ruleCounterparty')?.value || '').trim() || null;
  const refPrefix = (document.getElementById('ruleRefPrefix')?.value || '').trim() || null;
  const curr = (document.getElementById('ruleCurrency')?.value || '').trim().toUpperCase() || null;
  const maxDiffVal = (document.getElementById('ruleMaxAmountDiff')?.value || '').trim();
  const maxDelayVal = (document.getElementById('ruleMaxDelayDays')?.value || '').trim();
  const outcome = document.getElementById('ruleOutcome')?.value || 'MATCHED';
  const exType = outcome === 'EXCEPTION' ? (document.getElementById('ruleExceptionType')?.value || null) : null;
  const desc = (document.getElementById('ruleDescription')?.value || '').trim() || '';

  return {
    name,
    description: desc,
    source_counterparty_pattern: cp,
    reference_prefix: refPrefix,
    currency: curr,
    max_amount_difference: maxDiffVal ? maxDiffVal : null,
    max_settlement_delay_days: maxDelayVal ? parseInt(maxDelayVal, 10) : null,
    target_action: 'PREFER_CANDIDATE',
    resulting_outcome: outcome,
    resulting_exception_type: exType,
    confidence: 1.0,
    is_active: true,
    run_id: state.activeRunId || null,
  };
}

async function validateRuleForm() {
  const alertBox = document.getElementById('addRuleValidationAlert');
  const successBox = document.getElementById('addRuleValidationSuccess');
  if (alertBox) alertBox.classList.add('hidden');
  if (successBox) successBox.classList.add('hidden');

  const payload = gatherAddRulePayload();
  if (!payload.name) {
    if (alertBox) {
      alertBox.textContent = 'Rule name is required (minimum 3 characters).';
      alertBox.classList.remove('hidden');
    }
    return false;
  }

  const hasPredicate = Boolean(
    payload.source_counterparty_pattern ||
    payload.reference_prefix ||
    payload.currency ||
    payload.max_amount_difference !== null ||
    payload.max_settlement_delay_days !== null
  );

  if (!hasPredicate) {
    if (alertBox) {
      alertBox.textContent = 'At least one generalized predicate (Counterparty, Reference Prefix, Currency, Amount Diff, or Settlement Delay) must be specified.';
      alertBox.classList.remove('hidden');
    }
    return false;
  }

  try {
    const res = await API.validateRule(payload);
    if (res.valid) {
      if (successBox) {
        successBox.textContent = res.summary || 'Rule predicates and safety checks passed!';
        successBox.classList.remove('hidden');
      }
      return true;
    } else {
      if (alertBox) {
        alertBox.innerHTML = `<strong>Validation Failed:</strong><ul style="margin: 0.25rem 0 0 1.25rem;">${res.errors.map(e => `<li>${e}</li>`).join('')}</ul>`;
        alertBox.classList.remove('hidden');
      }
      return false;
    }
  } catch (err) {
    if (alertBox) {
      alertBox.textContent = `Validation error: ${err.message}`;
      alertBox.classList.remove('hidden');
    }
    return false;
  }
}

async function submitAddRuleForm(e) {
  e.preventDefault();
  const alertBox = document.getElementById('addRuleValidationAlert');
  const successBox = document.getElementById('addRuleValidationSuccess');
  if (alertBox) alertBox.classList.add('hidden');
  if (successBox) successBox.classList.add('hidden');

  const btnSubmit = document.getElementById('btnSubmitAddRule');
  btnSubmit.disabled = true;
  btnSubmit.textContent = 'Creating Rule...';

  try {
    const payload = gatherAddRulePayload();
    const created = await API.createRule(payload);

    closeAddRuleModal();
    showToast(`Rule created: ${created.rule_id} (${created.name})`, 'success');

    // Refresh rules list from API
    const rulesData = await API.getRules();
    state.rules = rulesData.rules || [];
    renderRulesTable();

    // If active run, refresh audit logs so rule creation provenance displays immediately
    if (state.activeRunId) {
      const audit = await API.getAuditLogs(state.activeRunId).catch(() => []);
      state.auditLogs = audit;
      renderAuditTimeline();
    }
  } catch (err) {
    if (alertBox) {
      alertBox.textContent = err.message || 'Failed to create rule.';
      alertBox.classList.remove('hidden');
    }
  } finally {
    btnSubmit.disabled = false;
    btnSubmit.textContent = 'Create Rule';
  }
}

async function openRuleDetailModal(ruleId) {
  const rule = (state.rules || []).find(r => r.rule_id === ruleId);
  if (!rule) {
    showToast(`Rule ${ruleId} not found`, 'error');
    return;
  }

  const predicates = [
    rule.source_counterparty_pattern ? `Counterparty Pattern: <code>${rule.source_counterparty_pattern}</code>` : null,
    rule.reference_prefix ? `Reference Prefix: <code>${rule.reference_prefix}</code>` : null,
    rule.currency ? `Currency: <code>${rule.currency}</code>` : null,
    rule.max_amount_difference ? `Max Amount Difference: <code>₹${rule.max_amount_difference}</code>` : null,
    rule.max_settlement_delay_days !== null && rule.max_settlement_delay_days !== undefined ? `Max Settlement Delay: <code>${rule.max_settlement_delay_days} day(s)</code>` : null,
  ].filter(Boolean);

  const body = document.getElementById('ruleDetailBody');
  if (body) {
    body.innerHTML = `
      <div class="orig-box-grid">
        <div><span class="text-muted">Rule ID:</span> <code>${rule.rule_id}</code></div>
        <div><span class="text-muted">Scope:</span> <span class="scope-pill-badge">GLOBAL RULE</span></div>
        <div><span class="text-muted">Status:</span> <span class="badge-pill ${rule.is_active ? 'badge-pill-green' : 'badge-pill-red'}">${rule.is_active ? 'ACTIVE' : 'INACTIVE'}</span></div>
        <div><span class="text-muted">Confidence:</span> <strong>${(rule.confidence * 100).toFixed(0)}%</strong></div>
        <div><span class="text-muted">Resulting Outcome:</span> <span class="badge-pill ${rule.resulting_outcome === 'MATCHED' ? 'badge-pill-green' : 'badge-pill-red'}">${rule.resulting_outcome}</span></div>
        <div><span class="text-muted">Exception Type:</span> <span class="badge-pill badge-pill-amber">${rule.resulting_exception_type || 'None'}</span></div>
      </div>
      <div style="margin-top: 1rem;">
        <span class="text-muted">Rule Name:</span>
        <div style="font-weight: 600; font-size: 1.05rem; margin-top: 0.25rem;">${rule.name}</div>
      </div>
      <div style="margin-top: 0.75rem;">
        <span class="text-muted">Description / Rationale:</span>
        <div style="background: var(--bg-app); border: 1px solid var(--border-subtle); padding: 0.6rem 0.8rem; border-radius: var(--radius-md); margin-top: 0.25rem; font-size: 0.85rem;">
          ${rule.description || '<span class="text-muted">No description provided</span>'}
        </div>
      </div>
      <div style="margin-top: 1rem;">
        <span class="text-muted">Generalized Predicates:</span>
        <ul style="margin: 0.35rem 0 0 1.25rem; font-size: 0.85rem; color: var(--text-primary);">
          ${predicates.length ? predicates.map(p => `<li>${p}</li>`).join('') : '<li>Wildcard (Matches any candidate pool)</li>'}
        </ul>
      </div>
      <div style="margin-top: 1rem; display: flex; justify-content: space-between; font-size: 0.85rem;">
        <div><span class="text-muted">Created From:</span> ${rule.source_correction_id ? `<code>${rule.source_correction_id}</code>` : '<span>Structured Builder</span>'}</div>
        <div><span class="text-muted">Created At:</span> ${formatTimestamp(rule.created_at)}</div>
      </div>
    `;
  }

  const btnToggleInDetail = document.getElementById('btnToggleActiveInDetail');
  if (btnToggleInDetail) {
    btnToggleInDetail.textContent = rule.is_active ? 'Deactivate Rule' : 'Activate Rule';
    btnToggleInDetail.className = `btn ${rule.is_active ? 'btn-secondary' : 'btn-primary'}`;
    btnToggleInDetail.onclick = async () => {
      try {
        const newActive = !rule.is_active;
        await API.toggleRule(rule.rule_id, newActive);
        rule.is_active = newActive;
        renderRulesTable();
        openRuleDetailModal(rule.rule_id);
        showToast(`Rule ${rule.rule_id} is now ${newActive ? 'ACTIVE' : 'INACTIVE'}`, 'info');
      } catch (err) {
        showToast(`Failed to toggle rule: ${err.message}`, 'error');
      }
    };
  }

  const btnDeleteInDetail = document.getElementById('btnDeleteRuleInDetail');
  if (btnDeleteInDetail) {
    btnDeleteInDetail.onclick = () => {
      closeRuleDetailModal();
      openRuleDeleteModal(rule.rule_id);
    };
  }

  const modal = document.getElementById('ruleDetailModal');
  if (modal) modal.classList.remove('hidden');
}

function closeRuleDetailModal() {
  const modal = document.getElementById('ruleDetailModal');
  if (modal) modal.classList.add('hidden');
}

// ---------------------------------------------------------------------------
// Run & Rule Deletion Handlers
// ---------------------------------------------------------------------------

function openRunDeleteModal() {
  if (!state.activeRunId) {
    showToast('No run selected to delete.', 'info');
    return;
  }
  const modal = document.getElementById('runDeleteModal');
  const idEl = document.getElementById('deleteModalRunId');
  const typeEl = document.getElementById('deleteModalRunType');
  const statusEl = document.getElementById('deleteModalRunStatus');

  const isRerun = state.activeRunId.includes('-RERUN-');
  if (idEl) idEl.textContent = state.activeRunId;
  if (typeEl) typeEl.textContent = isRerun ? 'RERUN (Child Run)' : 'Normal Run';
  if (statusEl) {
    statusEl.textContent = state.activeRun?.status || 'COMPLETED';
    statusEl.className = `badge-pill ${state.activeRun?.status === 'COMPLETED' ? 'badge-pill-green' : 'badge-pill-amber'}`;
  }
  if (modal) modal.classList.remove('hidden');
}

function closeRunDeleteModal() {
  const modal = document.getElementById('runDeleteModal');
  if (modal) modal.classList.add('hidden');
}

async function confirmDeleteRun() {
  if (!state.activeRunId) return;
  const runIdToDelete = state.activeRunId;
  const btnConfirm = document.getElementById('btnConfirmDeleteRun');
  if (btnConfirm) {
    btnConfirm.disabled = true;
    btnConfirm.textContent = 'Deleting...';
  }

  try {
    const res = await API.deleteRun(runIdToDelete);
    closeRunDeleteModal();
    if (res.warning) {
      showToast(res.warning, 'info');
    } else {
      showToast(`Run ${runIdToDelete} deleted successfully.`, 'success');
    }

    // Refresh runs from backend
    const data = await API.getRuns();
    state.runs = data.runs || [];
    renderRunSelector();

    if (state.runs.length > 0) {
      await loadRunDetails(state.runs[0].run_id);
    } else {
      // Transition UI to clean empty state
      state.activeRunId = null;
      state.activeRun = null;
      state.metrics = null;
      state.results = [];
      state.filteredResults = [];
      state.exceptions = [];
      state.filteredExceptions = [];
      state.candidates = [];
      state.auditLogs = [];
      state.records = [];
      state.corrections = [];
      state.ruleImpact = null;
      renderActiveRunMeta();
      renderKpis();
      applyResultsFilters();
      applyExceptionFilters();
      renderCandidateInspector();
      renderAuditTimeline();
      renderCorrectionsHistory();
      renderRulesTable();
      renderRuleImpact();
      resetQaPanel();
    }
  } catch (err) {
    console.error('Failed to delete run:', err);
    showToast(`Delete run failed: ${err.message}`, 'error');
  } finally {
    if (btnConfirm) {
      btnConfirm.disabled = false;
      btnConfirm.textContent = 'Delete Run';
    }
  }
}

function openRuleDeleteModal(ruleId) {
  const rule = (state.rules || []).find(r => r.rule_id === ruleId);
  if (!rule) {
    showToast(`Rule ${ruleId} not found.`, 'error');
    return;
  }

  state.selectedRuleForDeletion = rule;

  const modal = document.getElementById('ruleDeleteModal');
  const idEl = document.getElementById('deleteModalRuleId');
  const nameEl = document.getElementById('deleteModalRuleName');
  const statusEl = document.getElementById('deleteModalRuleStatus');
  const warningEl = document.getElementById('ruleDeleteActiveWarning');

  if (idEl) idEl.textContent = rule.rule_id;
  if (nameEl) nameEl.textContent = rule.name;
  if (statusEl) {
    statusEl.textContent = rule.is_active ? 'ACTIVE' : 'INACTIVE';
    statusEl.className = `badge-pill ${rule.is_active ? 'badge-pill-green' : 'badge-pill-red'}`;
  }
  if (warningEl) {
    if (rule.is_active) {
      warningEl.classList.remove('hidden');
    } else {
      warningEl.classList.add('hidden');
    }
  }

  if (modal) modal.classList.remove('hidden');
}

function closeRuleDeleteModal() {
  const modal = document.getElementById('ruleDeleteModal');
  if (modal) modal.classList.add('hidden');
  state.selectedRuleForDeletion = null;
}

async function confirmDeleteRule() {
  if (!state.selectedRuleForDeletion) return;
  const rule = state.selectedRuleForDeletion;
  const btnConfirm = document.getElementById('btnConfirmDeleteRule');
  if (btnConfirm) {
    btnConfirm.disabled = true;
    btnConfirm.textContent = 'Deleting...';
  }

  try {
    const res = await API.deleteRule(rule.rule_id);
    closeRuleDeleteModal();
    closeRuleDetailModal();
    if (res.warning) {
      showToast(res.warning, 'info');
    } else {
      showToast(`Rule ${rule.rule_id} deleted successfully.`, 'success');
    }

    // Refresh rules list
    const rulesData = await API.getRules();
    state.rules = rulesData.rules || [];
    renderRulesTable();

    // Refresh audit log if active run is open
    if (state.activeRunId) {
      const audit = await API.getAuditLogs(state.activeRunId).catch(() => []);
      state.auditLogs = audit;
      renderAuditTimeline();
    }
  } catch (err) {
    console.error('Failed to delete rule:', err);
    showToast(`Delete rule failed: ${err.message}`, 'error');
  } finally {
    if (btnConfirm) {
      btnConfirm.disabled = false;
      btnConfirm.textContent = 'Delete Rule';
    }
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
      showToast('Please select both Gateway and Bank transaction files (CSV, JSON, PDF, or Image).', 'error');
      return;
    }

    const progressBox = document.getElementById('uploadProgressContainer');
    const progressBar = document.getElementById('uploadProgressBar');
    const progressText = document.getElementById('uploadProgressText');
    const submitBtn = document.getElementById('btnSubmitReconciliation');

    progressBox.classList.remove('hidden');
    submitBtn.disabled = true;

    progressBar.style.width = '25%';
    progressText.textContent = 'Ingesting & extracting document records...';

    const formData = new FormData();
    formData.append('gateway_file', state.selectedGatewayFile);
    formData.append('bank_file', state.selectedBankFile);

    try {
      progressBar.style.width = '60%';
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

  // 12. Initialize Grounded Q&A Panel
  initQaPanel();

  // 13. Operator Correction Modal Controls
  const btnCloseCorr = document.getElementById('btnCloseCorrectionModal');
  const btnCancelCorr = document.getElementById('btnCancelCorrection');
  if (btnCloseCorr) btnCloseCorr.addEventListener('click', closeCorrectionModal);
  if (btnCancelCorr) btnCancelCorr.addEventListener('click', closeCorrectionModal);

  const corrOutcomeSelect = document.getElementById('corrOutcome');
  const corrExGroup = document.getElementById('corrExceptionGroup');
  const corrExSelect = document.getElementById('corrExceptionType');
  if (corrOutcomeSelect && corrExGroup) {
    corrOutcomeSelect.addEventListener('change', () => {
      if (corrOutcomeSelect.value === 'MATCHED') {
        corrExGroup.style.display = 'none';
        if (corrExSelect) corrExSelect.value = '';
      } else {
        corrExGroup.style.display = 'flex';
        if (corrExSelect && !corrExSelect.value) corrExSelect.value = 'UNKNOWN';
      }
    });
  }

  const corrForm = document.getElementById('correctionForm');
  if (corrForm) {
    corrForm.addEventListener('submit', submitCorrectionForm);
  }

  // 14. Correction Detail Modal Controls
  const btnCloseCorrDetail = document.getElementById('btnCloseCorrectionDetailModal');
  const btnCloseDetailBtn = document.getElementById('btnCloseDetailModalBtn');
  const corrDetailModal = document.getElementById('correctionDetailModal');
  if (btnCloseCorrDetail && corrDetailModal) {
    btnCloseCorrDetail.addEventListener('click', () => corrDetailModal.classList.add('hidden'));
  }
  if (btnCloseDetailBtn && corrDetailModal) {
    btnCloseDetailBtn.addEventListener('click', () => corrDetailModal.classList.add('hidden'));
  }

  // 15. Rerun with Rules Controls
  const btnRerunWithRules = document.getElementById('btnRerunWithRules');
  const rerunModal = document.getElementById('rerunConfirmModal');
  const btnCloseRerun = document.getElementById('btnCloseRerunModal');
  const btnCancelRerun = document.getElementById('btnCancelRerun');
  const btnExecuteRerun = document.getElementById('btnExecuteRerun');

  if (btnRerunWithRules) {
    btnRerunWithRules.addEventListener('click', openRerunModal);
  }
  const btnTabRerunWithRules = document.getElementById('btnTabRerunWithRules');
  if (btnTabRerunWithRules) {
    btnTabRerunWithRules.addEventListener('click', openRerunModal);
  }
  if (btnCloseRerun && rerunModal) {
    btnCloseRerun.addEventListener('click', () => rerunModal.classList.add('hidden'));
  }
  if (btnCancelRerun && rerunModal) {
    btnCancelRerun.addEventListener('click', () => rerunModal.classList.add('hidden'));
  }
  if (btnExecuteRerun) {
    btnExecuteRerun.addEventListener('click', executeRerun);
  }

  // 16. Add Reconciliation Rule Modal Controls
  const btnOpenAddRule = document.getElementById('btnOpenAddRuleModal');
  const btnCloseAddRule = document.getElementById('btnCloseAddRuleModal');
  const btnCancelAddRule = document.getElementById('btnCancelAddRule');
  const btnValidateRule = document.getElementById('btnValidateRule');
  const addRuleForm = document.getElementById('addRuleForm');

  if (btnOpenAddRule) btnOpenAddRule.addEventListener('click', openAddRuleModal);
  if (btnCloseAddRule) btnCloseAddRule.addEventListener('click', closeAddRuleModal);
  if (btnCancelAddRule) btnCancelAddRule.addEventListener('click', closeAddRuleModal);
  if (btnValidateRule) btnValidateRule.addEventListener('click', () => validateRuleForm(false));
  if (addRuleForm) addRuleForm.addEventListener('submit', submitAddRuleForm);

  // Live rule preview input listeners
  const ruleInputs = ['ruleCounterparty', 'ruleRefPrefix', 'ruleCurrency', 'ruleMaxAmountDiff', 'ruleMaxDelayDays', 'ruleRelType', 'ruleOutcome', 'ruleExceptionType'];
  ruleInputs.forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener('input', updateRulePreview);
      el.addEventListener('change', updateRulePreview);
    }
  });

  const ruleOutcomeSelect = document.getElementById('ruleOutcome');
  const ruleExGroup = document.getElementById('ruleExceptionTypeGroup');
  if (ruleOutcomeSelect && ruleExGroup) {
    ruleOutcomeSelect.addEventListener('change', () => {
      if (ruleOutcomeSelect.value === 'EXCEPTION') {
        ruleExGroup.style.display = 'flex';
      } else {
        ruleExGroup.style.display = 'none';
      }
    });
  }

  // 17. Rule Detail Modal Controls
  const btnCloseRuleDetail = document.getElementById('btnCloseRuleDetailModal');
  const btnCloseRuleDetailBtn = document.getElementById('btnCloseRuleDetailBtn');
  if (btnCloseRuleDetail) btnCloseRuleDetail.addEventListener('click', closeRuleDetailModal);
  if (btnCloseRuleDetailBtn) btnCloseRuleDetailBtn.addEventListener('click', closeRuleDetailModal);

  // 18. Run & Rule Deletion Modal Controls
  const btnDeleteRunHeader = document.getElementById('btnDeleteRunHeader');
  const btnDeleteCurrentRun = document.getElementById('btnDeleteCurrentRun');
  const btnCloseRunDelete = document.getElementById('btnCloseRunDeleteModal');
  const btnCancelDeleteRun = document.getElementById('btnCancelDeleteRun');
  const btnConfirmDeleteRun = document.getElementById('btnConfirmDeleteRun');

  if (btnDeleteRunHeader) btnDeleteRunHeader.addEventListener('click', openRunDeleteModal);
  if (btnDeleteCurrentRun) btnDeleteCurrentRun.addEventListener('click', openRunDeleteModal);
  if (btnCloseRunDelete) btnCloseRunDelete.addEventListener('click', closeRunDeleteModal);
  if (btnCancelDeleteRun) btnCancelDeleteRun.addEventListener('click', closeRunDeleteModal);
  if (btnConfirmDeleteRun) btnConfirmDeleteRun.addEventListener('click', confirmDeleteRun);

  const btnCloseRuleDelete = document.getElementById('btnCloseRuleDeleteModal');
  const btnCancelDeleteRule = document.getElementById('btnCancelDeleteRule');
  const btnConfirmDeleteRule = document.getElementById('btnConfirmDeleteRule');

  if (btnCloseRuleDelete) btnCloseRuleDelete.addEventListener('click', closeRuleDeleteModal);
  if (btnCancelDeleteRule) btnCancelDeleteRule.addEventListener('click', closeRuleDeleteModal);
  if (btnConfirmDeleteRule) btnConfirmDeleteRule.addEventListener('click', confirmDeleteRule);

  // 19. Event Delegation for dynamic buttons: [Correct], [Details], [View Rule], [Toggle Rule], [Delete Rule]
  document.addEventListener('click', async e => {
    const correctBtn = e.target.closest('.btn-correct');
    if (correctBtn) {
      const relId = correctBtn.dataset.relId;
      if (relId) openCorrectionModal(relId);
      return;
    }

    const inspectBtn = e.target.closest('.btn-inspect-corr');
    if (inspectBtn) {
      const corrId = inspectBtn.dataset.corrId;
      if (corrId) openCorrectionDetail(corrId);
      return;
    }

    const viewRuleBtn = e.target.closest('.btn-view-rule');
    if (viewRuleBtn) {
      const ruleId = viewRuleBtn.dataset.ruleId;
      if (ruleId) openRuleDetailModal(ruleId);
      return;
    }

    const deleteRuleBtn = e.target.closest('.btn-delete-rule');
    if (deleteRuleBtn) {
      const ruleId = deleteRuleBtn.dataset.ruleId;
      if (ruleId) openRuleDeleteModal(ruleId);
      return;
    }

    const toggleRuleBtn = e.target.closest('.btn-toggle-rule');
    if (toggleRuleBtn) {
      const ruleId = toggleRuleBtn.dataset.ruleId;
      const currentActive = toggleRuleBtn.dataset.active === 'true';
      const newActive = !currentActive;
      try {
        await API.toggleRule(ruleId, newActive);
        const r = (state.rules || []).find(x => x.rule_id === ruleId);
        if (r) r.is_active = newActive;
        renderRulesTable();
        showToast(`Rule ${ruleId} set to ${newActive ? 'ACTIVE' : 'INACTIVE'}`, 'info');
      } catch (err) {
        showToast(`Failed to toggle rule: ${err.message}`, 'error');
      }
      return;
    }
  });

  document.addEventListener('change', async e => {
    if (e.target.classList.contains('rule-toggle-input')) {
      const ruleId = e.target.dataset.ruleId;
      const isActive = e.target.checked;
      try {
        await API.toggleRule(ruleId, isActive);
        const r = (state.rules || []).find(x => x.rule_id === ruleId);
        if (r) r.is_active = isActive;
        renderRulesTable();
        showToast(`Rule ${ruleId} set to ${isActive ? 'ACTIVE' : 'INACTIVE'}`, 'info');
      } catch (err) {
        e.target.checked = !isActive;
        showToast(`Failed to toggle rule: ${err.message}`, 'error');
      }
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

// ---------------------------------------------------------------------------
// 8. Grounded Q&A / Ask Eagle Panel Logic
// ---------------------------------------------------------------------------
function initQaPanel() {
  const qaForm = document.getElementById('qaForm');
  const qaInput = document.getElementById('qaInput');
  const btnSubmit = document.getElementById('btnSubmitQa');
  const qaSection = document.getElementById('qaAnswerSection');
  const qaAnswerText = document.getElementById('qaAnswerText');
  const qaLatencyMeta = document.getElementById('qaLatencyMeta');
  const qaEvidenceStatus = document.getElementById('qaEvidenceStatus');
  const qaSourcesList = document.getElementById('qaSourcesList');

  if (!qaForm || !qaInput) return;

  // Handle Query Submission
  async function submitQuery(query) {
    if (!query || !query.trim()) return;

    qaSection.classList.remove('hidden');
    qaAnswerText.textContent = 'Searching Eagle operational records and synthesizing grounded response...';
    qaLatencyMeta.textContent = 'Retrieval: ... | Generation: ...';
    qaEvidenceStatus.textContent = 'Verifying evidence...';
    qaSourcesList.innerHTML = '';
    btnSubmit.disabled = true;

    try {
      const response = await API.askQa(query.trim(), state.activeRunId || null);

      qaAnswerText.textContent = response.answer;
      qaLatencyMeta.textContent = `Retrieval: ${response.retrieval_latency_ms}ms | Generation: ${response.generation_latency_ms}ms`;

      if (response.has_sufficient_evidence) {
        qaEvidenceStatus.textContent = `Grounded in ${response.sources.length} Verified Sources`;
        qaEvidenceStatus.style.color = 'var(--accent-emerald)';
      } else {
        qaEvidenceStatus.textContent = 'Insufficient Evidence';
        qaEvidenceStatus.style.color = 'var(--accent-amber)';
      }

      // Defensive Scope Validation for Run-Scoped Queries
      if (state.activeRunId && response.sources && response.sources.length > 0) {
        const crossRunSources = response.sources.filter(
          s => s.run_id && s.run_id !== state.activeRunId
        );
        if (crossRunSources.length > 0) {
          console.error(
            `Q&A scope mismatch detected: expected run '${state.activeRunId}', but received evidence from run(s):`,
            crossRunSources.map(s => s.run_id)
          );
          qaAnswerText.textContent =
            'Q&A evidence scope mismatch. The retrieved evidence belongs to another reconciliation run.';
          qaEvidenceStatus.textContent = 'Scope Mismatch Error';
          qaEvidenceStatus.style.color = 'var(--accent-rose)';
          qaSourcesList.innerHTML =
            '<div style="font-size:0.85rem; color:var(--accent-rose); padding:0.5rem;">Evidence discarded due to cross-run scope mismatch.</div>';
          return;
        }
      }

      // Render Sources List
      if (response.sources && response.sources.length > 0) {
        qaSourcesList.innerHTML = response.sources.map(s => `
          <div class="qa-source-card">
            <div class="qa-source-header">
              <span class="qa-source-badge">${s.document_type}</span>
              <span class="qa-source-title">${s.title}</span>
            </div>
            <div class="qa-source-snippet">${s.snippet}</div>
          </div>
        `).join('');
      } else {
        qaSourcesList.innerHTML = '<div style="font-size:0.8rem; color:var(--text-muted);">No external source documents cited.</div>';
      }


    } catch (err) {
      console.error(err);
      qaAnswerText.textContent = `Error querying Eagle Q&A: ${err.message}`;
      qaEvidenceStatus.textContent = 'Query Failed';
      qaEvidenceStatus.style.color = 'var(--accent-rose)';
    } finally {
      btnSubmit.disabled = false;
    }
  }

  qaForm.addEventListener('submit', e => {
    e.preventDefault();
    submitQuery(qaInput.value);
  });

  // Handle Example Chip Clicks
  document.querySelectorAll('.qa-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const q = chip.dataset.query;
      if (q) {
        qaInput.value = q;
        submitQuery(q);
      }
    });
  });

  // Handle Quick "Ask Eagle" Action Button in Active Run Header
  const btnQuickAsk = document.getElementById('btnQuickAskEagle');
  if (btnQuickAsk) {
    btnQuickAsk.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));

      const qaTabBtn = document.querySelector('.tab-btn[data-tab="tab-qa"]');
      const qaPane = document.getElementById('tab-qa');
      if (qaTabBtn) qaTabBtn.classList.add('active');
      if (qaPane) qaPane.classList.add('active');

      if (qaInput) {
        qaInput.focus();
      }
    });
  }

  // Set initial Scope Badge
  const scopeBadge = document.getElementById('qaScopeBadge');
  if (scopeBadge && !state.activeRunId) {
    scopeBadge.textContent = 'Scope: All Runs (Global)';
  }
}


