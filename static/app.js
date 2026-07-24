(function () {
    'use strict';

    /* ── state ── */
    let allItems = [];

    /* ── DOM refs ── */
    const $ = id => document.getElementById(id);
    const els = {
        refresh:           $('refreshButton'),
        totalRetirements:  $('totalRetirements'),
        withImpact:        $('retirementsWithImpact'),
        totalResources:    $('totalResources'),
        nextDeadline:      $('nextDeadline'),
        generatedAt:       $('generatedAt'),
        coverageNotice:    $('coverageNotice'),
        statusMessage:     $('statusMessage'),
        cards:             $('retirementCards'),
        search:            $('searchFilter'),
        service:           $('serviceFilter'),
        region:            $('regionFilter'),
        subscription:      $('subscriptionFilter'),
        resourceGroup:     $('resourceGroupFilter'),
        impact:            $('impactFilter'),
    };

    /* ── helpers ── */
    function esc(v) {
        return String(v ?? '')
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function formatDate(iso) {
        if (!iso) return 'No date set';
        const d = new Date(iso);
        return isNaN(d) ? iso : d.toLocaleDateString('en-GB', {
            day: 'numeric', month: 'short', year: 'numeric'
        });
    }

    function daysUntil(iso) {
        if (!iso) return null;
        return Math.ceil((new Date(iso) - Date.now()) / 86_400_000);
    }

    function daysLabel(days) {
        if (days === null)    return 'No date set';
        if (days < 0)         return `${Math.abs(days)}d overdue`;
        if (days === 0)       return 'Retires today';
        return `${days.toLocaleString()}d remaining`;
    }

    function daysColor(days) {
        if (days === null || days > 180) return '';
        if (days <= 90)  return 'color:#9d1d32';
        return 'color:#b85c00';
    }

    function pills(arr, extraClass = '') {
        if (!arr?.length) return '';
        return `<div class="pills">${
            arr.map(v => `<span class="pill ${extraClass}">${esc(v)}</span>`).join('')
        }</div>`;
    }

    function resourceTable(resources) {
        if (!resources?.length) return '';
        const rows = resources.map(r => `
            <tr>
                <td>${esc(r.resourceName || '—')}</td>
                <td>${esc(r.resourceType || '—')}</td>
                <td>${esc(r.region || '—')}</td>
                <td>${esc(r.resourceGroup || '—')}</td>
                <td>${esc(r.subscriptionId || '—')}</td>
            </tr>`).join('');
        return `
            <details>
                <summary class="resource-details">
                    ${resources.length} impacted resource${resources.length !== 1 ? 's' : ''}
                </summary>
                <table class="resource-table">
                    <thead>
                        <tr>
                            <th>Name</th><th>Type</th>
                            <th>Region</th><th>Resource Group</th><th>Subscription</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </details>`;
    }

    function renderCard(item) {
        const days  = daysUntil(item.retirementDate);
        const color = daysColor(days);

        const titleHtml = item.link
            ? `<a href="${esc(item.link)}" target="_blank" rel="noopener noreferrer">${esc(item.service)}</a>`
            : esc(item.service);

        const impactDisplay = item.impactedCount > 0
            ? item.impactedCount.toLocaleString()
            : item.impactAnalysisAvailable ? '?' : '—';

        const hasTable = item.impactedResources?.length > 0;

        return `
            <article class="retirement-card">
                <div>
                    <h3>${titleHtml}</h3>
                    ${item.description
                        ? `<p class="card-description">${esc(item.description)}</p>`
                        : ''}
                    ${item.solution
                        ? `<p class="card-description">
                               <strong>Recommended action:</strong> ${esc(item.solution)}
                           </p>`
                        : ''}
                    ${pills(item.regions)}
                    ${pills(item.resourceTypes)}
                </div>
                <div class="deadline">
                    <span class="deadline-date">${formatDate(item.retirementDate)}</span>
                    <span class="days-remaining" style="${color}">${daysLabel(days)}</span>
                    <span class="impact-count">${impactDisplay}</span>
                    <span class="impact-caption">impacted resources</span>
                </div>
                ${hasTable
                    ? `<div class="resource-details">${resourceTable(item.impactedResources)}</div>`
                    : ''}
            </article>`;
    }

    /* ── filter helpers ── */
    function populateSelect(selectEl, values) {
        const prev = selectEl.value;
        while (selectEl.options.length > 1) selectEl.remove(1);
        [...new Set(values)].filter(Boolean).sort().forEach(v => {
            const o = new Option(v, v);
            selectEl.appendChild(o);
        });
        if (prev && [...selectEl.options].some(o => o.value === prev)) {
            selectEl.value = prev;
        }
    }

    function buildFilterOptions(items) {
        populateSelect(els.service,       items.map(i => i.service));
        populateSelect(els.region,        items.flatMap(i => i.regions));
        populateSelect(els.subscription,  items.flatMap(i => i.subscriptions));
        populateSelect(els.resourceGroup, items.flatMap(i => i.resourceGroups));
    }

    function applyFilters() {
        const search  = els.search.value.trim().toLowerCase();
        const service = els.service.value;
        const region  = els.region.value;
        const sub     = els.subscription.value;
        const rg      = els.resourceGroup.value;
        const impact  = els.impact.value;

        const visible = allItems.filter(item => {
            if (search) {
                const hay = [item.service, item.description, item.solution].join(' ').toLowerCase();
                if (!hay.includes(search)) return false;
            }
            if (service && item.service !== service)             return false;
            if (region  && !item.regions.includes(region))       return false;
            if (sub     && !item.subscriptions.includes(sub))    return false;
            if (rg      && !item.resourceGroups.includes(rg))    return false;

            if (impact === 'impacted'    && item.impactedCount === 0)      return false;
            if (impact === 'analysis'    && !item.impactAnalysisAvailable) return false;
            if (impact === 'unavailable' && item.impactAnalysisAvailable)  return false;

            return true;
        });

        if (visible.length === 0) {
            els.cards.innerHTML = '';
            els.statusMessage.textContent = 'No retirements match the current filters.';
            els.statusMessage.className   = 'status-message';
            els.statusMessage.style.display = '';
        } else {
            els.statusMessage.style.display = 'none';
            els.cards.innerHTML = visible.map(renderCard).join('');
        }
    }

    function updateSummary(items) {
        const withImpact  = items.filter(i => i.impactedCount > 0).length;
        const totalRes    = items.reduce((s, i) => s + (i.impactedCount || 0), 0);
        const earliest    = items
            .filter(i => i.retirementDate)
            .sort((a, b) => a.retirementDate.localeCompare(b.retirementDate))[0];

        els.totalRetirements.textContent = items.length.toLocaleString();
        els.withImpact.textContent       = withImpact.toLocaleString();
        els.totalResources.textContent   = totalRes.toLocaleString();
        els.nextDeadline.textContent     = earliest ? formatDate(earliest.retirementDate) : '—';
    }

    /* ── data load ── */
    async function loadData() {
        els.statusMessage.textContent   = 'Loading Azure retirement data…';
        els.statusMessage.className     = 'status-message';
        els.statusMessage.style.display = '';
        els.cards.innerHTML             = '';
        els.refresh.disabled            = true;

        try {
            const res = await fetch('/api/retirements');
            if (!res.ok) throw new Error(`HTTP ${res.status} — ${res.statusText}`);
            const data = await res.json();
            if (data.error) throw new Error(data.error);

            allItems = data.items || [];

            if (data.generatedAt) {
                els.generatedAt.textContent =
                    `Data as of ${new Date(data.generatedAt).toLocaleString()}`;
            }

            if (data.notice) {
                els.coverageNotice.textContent = data.notice;
                els.coverageNotice.style.display = '';
            } else {
                els.coverageNotice.style.display = 'none';
            }

            updateSummary(allItems);
            buildFilterOptions(allItems);
            applyFilters();

        } catch (err) {
            els.statusMessage.textContent = `Failed to load data: ${err.message}`;
            els.statusMessage.className   = 'status-message error';
        } finally {
            els.refresh.disabled = false;
        }
    }

    /* ── event wiring ── */
    [els.search, els.service, els.region, els.subscription,
     els.resourceGroup, els.impact
    ].forEach(el => el.addEventListener('input', applyFilters));

    els.refresh.addEventListener('click', loadData);

    loadData();
})();
