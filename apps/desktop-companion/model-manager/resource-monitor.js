(function initializeResourceMonitorComponent() {
  'use strict';

  const STORAGE_COLLAPSED = 'voxpassport.resourceMonitor.collapsed';
  const STORAGE_ENABLED = 'voxpassport.resourceMonitor.enabled';
  const STORAGE_COMPACT_VRAM_MODE = 'voxpassport.resourceMonitor.compactVramMode';
  const STORAGE_COMPACT_RAM_MODE = 'voxpassport.resourceMonitor.compactRamMode';
  const POLL_INTERVAL_MS = 2000;
  const GPU_TEMP_WARNING_C = 70;
  const GPU_TEMP_CRITICAL_C = 85;

  const ICONS = {
    monitor: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="2" y="3" width="20" height="14" rx="2"></rect><path d="M8 21h8M12 17v4"></path></svg>',
    gpu: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="3" y="6" width="18" height="12" rx="2"></rect><path d="M7 10h6v4H7zM17 9v6M3 10H1M3 14H1M23 10h-2M23 14h-2"></path></svg>',
    memory: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="5" y="5" width="14" height="14" rx="2"></rect><path d="M9 9h6v6H9zM9 1v4M15 1v4M9 19v4M15 19v4M1 9h4M1 15h4M19 9h4M19 15h4"></path></svg>',
    cpu: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"></rect><path d="M9 9h6v6H9zM9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"></path></svg>',
    power: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path d="M12 2v10"></path><path d="M6.4 5.6a8 8 0 1 0 11.2 0"></path></svg>',
    collapse: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" aria-hidden="true"><path d="m6 9 6 6 6-6"></path></svg>',
    expand: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" aria-hidden="true"><path d="m6 15 6-6 6 6"></path></svg>',
  };

  class ResourceMonitor {
    constructor(options = {}) {
      this.apiUrl = options.apiUrl || `${window.location.origin}/api/resources`;
      this.wsUrl = options.wsUrl || `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws/resources`;
      this.pollIntervalMs = options.pollIntervalMs || POLL_INTERVAL_MS;
      this.collapsed = localStorage.getItem(STORAGE_COLLAPSED) === 'true';
      this.enabled = localStorage.getItem(STORAGE_ENABLED) !== 'false';
      this.compactVramMode = localStorage.getItem(STORAGE_COMPACT_VRAM_MODE)
        || localStorage.getItem('voxpassport.resourceMonitor.compactMode')
        || 'allocation';
      this.compactRamMode = localStorage.getItem(STORAGE_COMPACT_RAM_MODE) || 'allocation';
      this.timer = null;
      this.requestController = null;
      this.resourceSocket = null;
      this.reconnectTimer = null;
      this.snapshot = null;
      this.root = this.build();
      this.bindEvents();
    }

    build() {
      const root = document.createElement('footer');
      root.className = 'resource-monitor';
      root.id = 'resourceMonitor';
      root.dataset.collapsed = String(this.collapsed);
      root.dataset.enabled = String(this.enabled);
      root.dataset.connected = 'false';
      root.innerHTML = `
        <div class="resource-monitor__expanded" id="resourceMonitorExpanded">
          <div class="resource-monitor__header">
            <div class="resource-monitor__header-left">
              ${this.powerButtonMarkup()}
              <div class="resource-monitor__title-group">
                <span class="resource-monitor__title-icon">${ICONS.monitor}</span>
                <span class="resource-monitor__title">System Resource Monitor</span>
              </div>
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
            ${this.runtimeMetricMarkup()}
          </div>
        </div>
        <div class="resource-monitor__compact">
          ${this.powerButtonMarkup()}
          <div class="resource-monitor__compact-metrics">
            <span class="resource-monitor__compact-chip"><span class="resource-monitor__compact-icon">${ICONS.gpu}</span><span data-resource-compact-gpu>GPU --</span><span class="resource-monitor__temperature" data-resource-compact-temperature></span></span>
            <button class="resource-monitor__compact-reading" type="button" data-resource-compact-vram-toggle aria-label="Show VRAM as percentage">
              <span class="resource-monitor__compact-icon">${ICONS.memory}</span>
              <span data-resource-compact-vram>VRAM --</span>
            </button>
            <span class="resource-monitor__compact-chip"><span class="resource-monitor__compact-icon">${ICONS.cpu}</span><span data-resource-compact-cpu>CPU --</span></span>
            <button class="resource-monitor__compact-reading" type="button" data-resource-compact-ram-toggle aria-label="Show RAM as percentage">
              <span class="resource-monitor__compact-icon">${ICONS.memory}</span>
              <span data-resource-compact-ram>RAM --</span>
            </button>
          </div>
          <button class="resource-monitor__icon-button" type="button" data-resource-expand aria-label="Expand resource monitor" aria-expanded="false" aria-controls="resourceMonitorExpanded">${ICONS.expand}</button>
        </div>
      `;
      return root;
    }

    powerButtonMarkup() {
      return `<button class="resource-monitor__power-button" type="button" data-resource-power data-tooltip="Disable resource monitor" data-tooltip-pos="top" aria-label="Disable resource monitor" aria-pressed="true">${ICONS.power}</button>`;
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

    runtimeMetricMarkup() {
      return `
        <div class="resource-monitor__metric" data-resource-metric="tts-runtime" style="grid-column: 1 / -1">
          <div class="resource-monitor__metric-header">
            <span class="resource-monitor__metric-label"><span class="resource-monitor__metric-icon">${ICONS.monitor}</span>TTS Runtime Profiles</span>
            <span class="resource-monitor__metric-value" data-resource-value>Idle</span>
          </div>
          <div class="resource-monitor__track" aria-hidden="true"><div class="resource-monitor__fill" data-resource-fill></div></div>
          <div class="resource-monitor__metric-detail" data-resource-detail>No TTS worker running</div>
        </div>
      `;
    }

    bindEvents() {
      this.root.querySelector('[data-resource-collapse]').addEventListener('click', () => this.setCollapsed(true));
      this.root.querySelector('[data-resource-expand]').addEventListener('click', () => this.setCollapsed(false));
      this.root.querySelectorAll('[data-resource-power]').forEach((button) => {
        button.addEventListener('click', () => this.setEnabled(!this.enabled));
      });
      this.root.querySelector('[data-resource-compact-vram-toggle]').addEventListener('click', () => this.toggleCompactMode('vram'));
      this.root.querySelector('[data-resource-compact-ram-toggle]').addEventListener('click', () => this.toggleCompactMode('ram'));
      document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
          this.stopPolling();
        } else if (this.enabled) {
          this.startPolling();
        }
      });
    }

    mount(target) {
      if (!target || this.root.isConnected) return;
      target.appendChild(this.root);
      this.setCollapsed(this.collapsed, false);
      this.setEnabled(this.enabled, false);
    }

    setCollapsed(collapsed, persist = true) {
      this.collapsed = Boolean(collapsed);
      this.root.dataset.collapsed = String(this.collapsed);
      this.root.querySelector('[data-resource-collapse]').setAttribute('aria-expanded', String(!this.collapsed));
      this.root.querySelector('[data-resource-expand]').setAttribute('aria-expanded', String(!this.collapsed));
      if (persist) localStorage.setItem(STORAGE_COLLAPSED, String(this.collapsed));
    }

    setEnabled(enabled, persist = true) {
      this.enabled = Boolean(enabled);
      this.root.dataset.enabled = String(this.enabled);
      this.root.querySelectorAll('[data-resource-power]').forEach((button) => {
        const label = this.enabled ? 'Disable resource monitor' : 'Enable resource monitor';
        button.setAttribute('aria-label', label);
        button.setAttribute('data-tooltip', label);
        button.setAttribute('aria-pressed', String(this.enabled));
      });
      if (persist) localStorage.setItem(STORAGE_ENABLED, String(this.enabled));
      if (this.enabled) {
        this.root.querySelector('[data-resource-status]').textContent = 'Connecting';
        if (!document.hidden) this.startPolling();
      } else {
        this.stopPolling();
        this.root.dataset.connected = 'false';
        this.root.querySelector('[data-resource-status]').textContent = 'Off';
      }
    }

    toggleCompactMode(resource) {
      if (resource === 'ram') {
        this.compactRamMode = this.compactRamMode === 'allocation' ? 'percent' : 'allocation';
        localStorage.setItem(STORAGE_COMPACT_RAM_MODE, this.compactRamMode);
      } else {
        this.compactVramMode = this.compactVramMode === 'allocation' ? 'percent' : 'allocation';
        localStorage.setItem(STORAGE_COMPACT_VRAM_MODE, this.compactVramMode);
      }
      this.renderCompactValues();
    }

    startPolling() {
      this.stopPolling();
      this.connectResourceStream();
    }

    stopPolling() {
      if (this.timer) window.clearInterval(this.timer);
      this.timer = null;
      if (this.reconnectTimer) window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
      if (this.resourceSocket) {
        this.resourceSocket.close(1000, 'Resource monitor disabled');
        this.resourceSocket = null;
      }
      if (this.requestController) this.requestController.abort();
      this.requestController = null;
    }

    connectResourceStream() {
      if (!this.enabled || document.hidden || this.resourceSocket) return;
      let socket;
      try {
        socket = new WebSocket(this.wsUrl);
      } catch (error) {
        this.handleResourceStreamFailure();
        return;
      }
      this.resourceSocket = socket;
      socket.addEventListener('open', () => {
        if (this.resourceSocket !== socket) return;
        this.root.dataset.connected = 'true';
        this.root.querySelector('[data-resource-status]').textContent = 'Live';
      });
      socket.addEventListener('message', (event) => {
        if (!this.enabled || this.resourceSocket !== socket) return;
        try {
          const message = JSON.parse(event.data);
          if (message.type !== 'resources' || !message.data) return;
          this.snapshot = message.data;
          this.root.dataset.connected = 'true';
          this.root.querySelector('[data-resource-status]').textContent = 'Live';
          this.render();
        } catch (error) {
          this.root.dataset.connected = 'false';
          this.root.querySelector('[data-resource-status]').textContent = 'Telemetry unavailable';
        }
      });
      socket.addEventListener('error', () => this.handleResourceStreamFailure(socket));
      socket.addEventListener('close', () => {
        if (this.resourceSocket !== socket) return;
        this.resourceSocket = null;
        if (this.enabled && !document.hidden) this.handleResourceStreamFailure();
      });
    }

    handleResourceStreamFailure(socket = null) {
      if (socket && this.resourceSocket === socket) {
        this.resourceSocket = null;
        socket.close();
      }
      if (!this.enabled || document.hidden || this.reconnectTimer) return;
      this.root.dataset.connected = 'false';
      this.root.querySelector('[data-resource-status]').textContent = 'Telemetry unavailable';
      this.reconnectTimer = window.setTimeout(() => {
        this.reconnectTimer = null;
        this.connectResourceStream();
      }, 3000);
    }

    async refresh() {
      if (!this.enabled || this.requestController) return;
      const controller = new AbortController();
      this.requestController = controller;
      try {
        const response = await fetch(this.apiUrl, { cache: 'no-store', signal: controller.signal });
        if (!response.ok) throw new Error(`Resource endpoint returned ${response.status}`);
        if (!this.enabled) return;
        this.snapshot = await response.json();
        this.root.dataset.connected = 'true';
        this.root.querySelector('[data-resource-status]').textContent = 'Live';
        this.render();
      } catch (error) {
        if (error.name === 'AbortError' || !this.enabled) return;
        this.root.dataset.connected = 'false';
        this.root.querySelector('[data-resource-status]').textContent = 'Telemetry unavailable';
      } finally {
        if (this.requestController === controller) this.requestController = null;
      }
    }

    render() {
      if (!this.snapshot) return;
      this.root.dataset.sampledAt = String(this.snapshot.sampled_at_ms || '');
      const gpu = this.snapshot.gpu || {};
      const cpu = this.snapshot.cpu || {};
      const memory = this.snapshot.memory || {};
      this.updateMetric('gpu', gpu.usage_percent, this.formatPercent(gpu.usage_percent), gpu.name);
      this.renderGpuTemperature(gpu.name, gpu.temperature_c);
      this.updateMetric('vram', gpu.memory_percent, this.formatAllocation(gpu.memory_used_gb, gpu.memory_total_gb), `${this.formatPercent(gpu.memory_percent)} allocated`);
      this.updateMetric('cpu', cpu.usage_percent, this.formatPercent(cpu.usage_percent), `${cpu.logical_cores || 1} logical processors`);
      this.updateMetric('ram', memory.usage_percent, this.formatAllocation(memory.used_gb, memory.total_gb), `${this.formatPercent(memory.usage_percent)} allocated`);
      this.renderTtsRuntime(this.snapshot.tts_runtime || {});
      this.renderCompactValues();
    }

    renderTtsRuntime(runtime) {
      const metric = this.root.querySelector('[data-resource-metric="tts-runtime"]');
      if (!metric) return;
      const profiles = Array.isArray(runtime.profiles) ? runtime.profiles : [];
      const backends = Array.isArray(runtime.backends) ? runtime.backends : [];
      const activeProfile = runtime.active_profile_id || '';
      const activeModel = runtime.active_model_id || '';
      const backendStates = backends.map((backend) => {
        let state = 'stopped';
        if (backend.unexpected_exit || (backend.running && backend.health && backend.health.reachable === false)) {
          state = 'broken';
        } else if (backend.running) {
          state = 'running';
        }
        return { backend, state };
      });
      const activeBackend = backendStates.find(({ backend }) => backend.model_id === activeModel);
      const states = profiles.map((profile) => {
        let state = 'ready';
        if (!profile.installed) {
          state = 'missing';
        } else if (profile.unexpected_exit || (profile.running && profile.health && profile.health.reachable === false)) {
          state = 'broken';
        } else if (profile.running) {
          state = 'running';
        }
        if (profile.profile_id === activeProfile && activeBackend && activeBackend.state === 'broken') {
          state = 'broken';
        }
        return { profile, state };
      });
      const broken = states.some((item) => item.state === 'broken')
        || backendStates.some((item) => item.state === 'broken');
      const missing = states.some((item) => item.state === 'missing');
      const running = states.some((item) => item.state === 'running');
      metric.querySelector('[data-resource-value]').textContent = activeProfile || 'Idle';
      const profileDetail = states.length
        ? states.map(({ profile, state }) => `${profile.profile_id}: ${state}`).join(' · ')
        : 'No supervised TTS runtime initialized';
      const backendDetail = backendStates.length
        ? ` · backend ${backendStates.map(({ backend, state }) => `${backend.model_id}: ${state}`).join(', ')}`
        : '';
      metric.querySelector('[data-resource-detail]').textContent = activeModel
        ? `${activeModel} · ${profileDetail}${backendDetail}`
        : `${profileDetail}${backendDetail}`;
      const fill = metric.querySelector('[data-resource-fill]');
      fill.style.width = running ? '100%' : (missing || broken ? '35%' : '0%');
      fill.dataset.level = broken ? 'critical' : (missing ? 'warning' : 'normal');
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
      const vramValue = this.compactVramMode === 'percent'
        ? `VRAM ${this.formatPercent(gpu.memory_percent)}`
        : `VRAM ${this.formatAllocation(gpu.memory_used_gb, gpu.memory_total_gb)}`;
      const ramValue = this.compactRamMode === 'percent'
        ? `RAM ${this.formatPercent(memory.usage_percent)}`
        : `RAM ${this.formatAllocation(memory.used_gb, memory.total_gb)}`;
      this.root.querySelector('[data-resource-compact-gpu]').textContent = `GPU ${this.formatPercent(gpu.usage_percent)}`;
      this.updateTemperatureElement(this.root.querySelector('[data-resource-compact-temperature]'), gpu.temperature_c, true);
      this.root.querySelector('[data-resource-compact-vram]').textContent = vramValue;
      this.root.querySelector('[data-resource-compact-cpu]').textContent = `CPU ${this.formatPercent(cpu.usage_percent)}`;
      this.root.querySelector('[data-resource-compact-ram]').textContent = ramValue;
      this.root.querySelector('[data-resource-compact-vram-toggle]').setAttribute(
        'aria-label',
        this.compactVramMode === 'allocation' ? 'Show VRAM as percentage' : 'Show VRAM allocation',
      );
      this.root.querySelector('[data-resource-compact-ram-toggle]').setAttribute(
        'aria-label',
        this.compactRamMode === 'allocation' ? 'Show RAM as percentage' : 'Show RAM allocation',
      );
    }

    renderGpuTemperature(name, temperature) {
      const detail = this.root.querySelector('[data-resource-metric="gpu"] [data-resource-detail]');
      detail.textContent = name || 'Unavailable';
      if (temperature == null) return;
      detail.append(' · ');
      const value = document.createElement('span');
      value.className = 'resource-monitor__temperature';
      this.updateTemperatureElement(value, temperature, false);
      detail.append(value);
    }

    updateTemperatureElement(element, temperature, includeSeparator) {
      if (temperature == null) {
        element.textContent = '';
        delete element.dataset.level;
        return;
      }
      const numericTemperature = Number(temperature);
      const level = numericTemperature >= GPU_TEMP_CRITICAL_C
        ? 'critical'
        : (numericTemperature >= GPU_TEMP_WARNING_C ? 'warning' : 'normal');
      element.dataset.level = level;
      element.textContent = `${includeSeparator ? '· ' : ''}${this.formatNumber(numericTemperature, 0)}°C`;
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