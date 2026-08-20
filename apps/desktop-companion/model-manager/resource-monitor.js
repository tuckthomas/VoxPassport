(function initializeResourceMonitorComponent() {
  'use strict';

  const STORAGE_COLLAPSED = 'voxpassport.resourceMonitor.collapsed';
  const STORAGE_COMPACT_MODE = 'voxpassport.resourceMonitor.compactMode';
  const POLL_INTERVAL_MS = 2000;

  const ICONS = {
    monitor: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="2" y="3" width="20" height="14" rx="2"></rect><path d="M8 21h8M12 17v4"></path></svg>',
    gpu: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="3" y="6" width="18" height="12" rx="2"></rect><path d="M7 10h6v4H7zM17 9v6M3 10H1M3 14H1M23 10h-2M23 14h-2"></path></svg>',
    memory: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="5" y="5" width="14" height="14" rx="2"></rect><path d="M9 9h6v6H9zM9 1v4M15 1v4M9 19v4M15 19v4M1 9h4M1 15h4M19 9h4M19 15h4"></path></svg>',
    cpu: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"></rect><path d="M9 9h6v6H9zM9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"></path></svg>',
    collapse: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" aria-hidden="true"><path d="m6 9 6 6 6-6"></path></svg>',
    expand: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" aria-hidden="true"><path d="m6 15 6-6 6 6"></path></svg>',
  };

  class ResourceMonitor {
    constructor(options = {}) {
      this.apiUrl = options.apiUrl || `${window.location.origin}/api/resources`;
      this.pollIntervalMs = options.pollIntervalMs || POLL_INTERVAL_MS;
      this.collapsed = localStorage.getItem(STORAGE_COLLAPSED) === 'true';
      this.compactMode = localStorage.getItem(STORAGE_COMPACT_MODE) || 'allocation';
      this.timer = null;
      this.snapshot = null;
      this.root = this.build();
      this.bindEvents();
    }

    build() {
      const root = document.createElement('footer');
      root.className = 'resource-monitor';
      root.id = 'resourceMonitor';
      root.dataset.collapsed = String(this.collapsed);
      root.dataset.connected = 'false';
      root.innerHTML = `
        <div class="resource-monitor__expanded" id="resourceMonitorExpanded">
          <div class="resource-monitor__header">
            <div class="resource-monitor__title-group">
              <span class="resource-monitor__title-icon">${ICONS.monitor}</span>
              <span class="resource-monitor__title">System Resource Monitor</span>
            </div>
            <div class="resource-monitor__header-actions">
              <span class="resource-monitor__status"><span class="resource-monitor__status-dot"></span><span data-resource-status>Connecting</span></span>
              <button class="resource-monitor__icon-button" type="button" data-resource-collapse aria-label="Minimize resource monitor" aria-expanded="true" aria-controls="resourceMonitorExpanded">${ICONS.collapse}</button>
            </div>
          </div>
          <div class="resource-monitor__metrics">
            ${this.metricMarkup('gpu', 'GPU Load', ICONS.gpu)}
            ${this.metricMarkup('vram', 'VRAM', ICONS.memory)}
            ${this.metricMarkup('cpu', 'CPU', ICONS.cpu)}
            ${this.metricMarkup('ram', 'System RAM', ICONS.memory)}
          </div>
        </div>
        <div class="resource-monitor__compact">
          <div class="resource-monitor__compact-metrics">
            <span class="resource-monitor__compact-chip"><span class="resource-monitor__compact-icon">${ICONS.gpu}</span><span data-resource-compact-gpu>GPU --</span></span>
            <button class="resource-monitor__compact-reading" type="button" data-resource-compact-toggle aria-label="Show VRAM as percentage">
              <span class="resource-monitor__compact-icon">${ICONS.memory}</span>
              <span data-resource-compact-vram>VRAM --</span>
            </button>
            <span class="resource-monitor__compact-chip"><span class="resource-monitor__compact-icon">${ICONS.cpu}</span><span data-resource-compact-cpu>CPU --</span></span>
            <span class="resource-monitor__compact-chip"><span class="resource-monitor__compact-icon">${ICONS.memory}</span><span data-resource-compact-ram>RAM --</span></span>
          </div>
          <button class="resource-monitor__icon-button" type="button" data-resource-expand aria-label="Expand resource monitor" aria-expanded="false" aria-controls="resourceMonitorExpanded">${ICONS.expand}</button>
        </div>
      `;
      return root;
    }

    metricMarkup(key, label, icon) {
      return `
        <div class="resource-monitor__metric" data-resource-metric="${key}">
          <div class="resource-monitor__metric-header">
            <span class="resource-monitor__metric-label"><span class="resource-monitor__metric-icon">${icon}</span>${label}</span>
            <span class="resource-monitor__metric-value" data-resource-value>--</span>
          </div>
          <div class="resource-monitor__track" aria-hidden="true"><div class="resource-monitor__fill" data-resource-fill></div></div>
          <div class="resource-monitor__metric-detail" data-resource-detail>Waiting for telemetry</div>
        </div>
      `;
    }

    bindEvents() {
      this.root.querySelector('[data-resource-collapse]').addEventListener('click', () => this.setCollapsed(true));
      this.root.querySelector('[data-resource-expand]').addEventListener('click', () => this.setCollapsed(false));
      this.root.querySelector('[data-resource-compact-toggle]').addEventListener('click', () => this.toggleCompactMode());
      document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
          this.stopPolling();
        } else {
          this.startPolling();
        }
      });
    }

    mount(target) {
      if (!target || this.root.isConnected) return;
      target.appendChild(this.root);
      this.setCollapsed(this.collapsed, false);
      this.startPolling();
    }

    setCollapsed(collapsed, persist = true) {
      this.collapsed = Boolean(collapsed);
      this.root.dataset.collapsed = String(this.collapsed);
      this.root.querySelector('[data-resource-collapse]').setAttribute('aria-expanded', String(!this.collapsed));
      this.root.querySelector('[data-resource-expand]').setAttribute('aria-expanded', String(!this.collapsed));
      if (persist) localStorage.setItem(STORAGE_COLLAPSED, String(this.collapsed));
    }

    toggleCompactMode() {
      this.compactMode = this.compactMode === 'allocation' ? 'percent' : 'allocation';
      localStorage.setItem(STORAGE_COMPACT_MODE, this.compactMode);
      this.renderCompactValues();
    }

    startPolling() {
      this.stopPolling();
      this.refresh();
      this.timer = window.setInterval(() => this.refresh(), this.pollIntervalMs);
    }

    stopPolling() {
      if (this.timer) window.clearInterval(this.timer);
      this.timer = null;
    }

    async refresh() {
      try {
        const response = await fetch(this.apiUrl, { cache: 'no-store' });
        if (!response.ok) throw new Error(`Resource endpoint returned ${response.status}`);
        this.snapshot = await response.json();
        this.root.dataset.connected = 'true';
        this.root.querySelector('[data-resource-status]').textContent = 'Live · 2s refresh';
        this.render();
      } catch (error) {
        this.root.dataset.connected = 'false';
        this.root.querySelector('[data-resource-status]').textContent = 'Telemetry unavailable';
      }
    }

    render() {
      if (!this.snapshot) return;
      const gpu = this.snapshot.gpu || {};
      const cpu = this.snapshot.cpu || {};
      const memory = this.snapshot.memory || {};
      this.updateMetric('gpu', gpu.usage_percent, this.formatPercent(gpu.usage_percent), gpu.temperature_c == null ? gpu.name : `${gpu.name} · ${this.formatNumber(gpu.temperature_c, 0)}°C`);
      this.updateMetric('vram', gpu.memory_percent, this.formatAllocation(gpu.memory_used_gb, gpu.memory_total_gb), `${this.formatPercent(gpu.memory_percent)} allocated`);
      this.updateMetric('cpu', cpu.usage_percent, this.formatPercent(cpu.usage_percent), `${cpu.logical_cores || 1} logical processors`);
      this.updateMetric('ram', memory.usage_percent, this.formatAllocation(memory.used_gb, memory.total_gb), `${this.formatPercent(memory.usage_percent)} allocated`);
      this.renderCompactValues();
    }

    updateMetric(key, percent, value, detail) {
      const metric = this.root.querySelector(`[data-resource-metric="${key}"]`);
      const normalized = Math.max(0, Math.min(100, Number(percent) || 0));
      const fill = metric.querySelector('[data-resource-fill]');
      metric.querySelector('[data-resource-value]').textContent = value;
      metric.querySelector('[data-resource-detail]').textContent = detail || 'Unavailable';
      fill.style.width = `${normalized}%`;
      fill.dataset.level = normalized >= 90 ? 'critical' : (normalized >= 70 ? 'warning' : 'normal');
    }

    renderCompactValues() {
      const snapshot = this.snapshot || {};
      const gpu = snapshot.gpu || {};
      const cpu = snapshot.cpu || {};
      const memory = snapshot.memory || {};
      const vramValue = this.compactMode === 'percent'
        ? `VRAM ${this.formatPercent(gpu.memory_percent)}`
        : `VRAM ${this.formatAllocation(gpu.memory_used_gb, gpu.memory_total_gb)}`;
      const gpuTemperature = gpu.temperature_c == null
        ? ''
        : ` · ${this.formatNumber(gpu.temperature_c, 0)}°C`;
      this.root.querySelector('[data-resource-compact-gpu]').textContent = `GPU ${this.formatPercent(gpu.usage_percent)}${gpuTemperature}`;
      this.root.querySelector('[data-resource-compact-vram]').textContent = vramValue;
      this.root.querySelector('[data-resource-compact-cpu]').textContent = `CPU ${this.formatPercent(cpu.usage_percent)}`;
      this.root.querySelector('[data-resource-compact-ram]').textContent = `RAM ${this.formatAllocation(memory.used_gb, memory.total_gb)}`;
      this.root.querySelector('[data-resource-compact-toggle]').setAttribute(
        'aria-label',
        this.compactMode === 'allocation' ? 'Show VRAM as percentage' : 'Show VRAM allocation',
      );
    }

    formatPercent(value) {
      return value == null ? '--' : `${this.formatNumber(value, 0)}%`;
    }

    formatAllocation(used, total) {
      if (used == null || total == null || Number(total) <= 0) return '-- / --';
      return `${this.formatNumber(used, 1)} / ${this.formatNumber(total, 1)} GB`;
    }

    formatNumber(value, digits) {
      const number = Number(value);
      return Number.isFinite(number) ? number.toFixed(digits) : '--';
    }
  }

  window.ResourceMonitor = ResourceMonitor;
  window.addEventListener('DOMContentLoaded', () => {
    const workspace = document.querySelector('.main-workspace');
    if (!workspace || document.getElementById('resourceMonitor')) return;
    const monitor = new ResourceMonitor();
    monitor.mount(workspace);
    window.voxPassportResourceMonitor = monitor;
  });
})();
