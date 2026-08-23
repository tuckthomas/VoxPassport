export type DesktopAudioCapabilities = {
  platform: string;
  native_audio_boundary: boolean;
  microphone_enumeration: boolean;
  microphone_capture: boolean;
  render_enumeration: boolean;
  loopback_capture: boolean;
  virtual_microphone_output: boolean;
  note: string;
};

export type DesktopAudioDeviceRole =
  | 'physical_microphone'
  | 'render_output'
  | 'loopback_source'
  | 'virtual_microphone_sink';

export type DesktopAudioDevice = {
  id: string;
  name: string;
  role: DesktopAudioDeviceRole;
  is_default: boolean;
};

export type DesktopRuntimeProcessStatus = {
  base_url: string;
  owned_by_desktop: boolean;
  running: boolean;
  pid?: number | null;
};

export type DesktopRuntimeHttpResponse = {
  status: number;
  content_type?: string | null;
  body: string;
};

function isTauri(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}

async function invokeDesktop<T>(command: string, args?: Record<string, unknown>): Promise<T | null> {
  if (!isTauri()) return null;
  const { invoke } = await import('@tauri-apps/api/core');
  return invoke<T>(command, args);
}

export function getDesktopAudioCapabilities() {
  return invokeDesktop<DesktopAudioCapabilities>('desktop_audio_capabilities');
}

export function getDesktopAudioDevices() {
  return invokeDesktop<DesktopAudioDevice[]>('desktop_audio_devices');
}

export function getDesktopRuntimeStatus() {
  return invokeDesktop<DesktopRuntimeProcessStatus>('local_runtime_status');
}

export function startDesktopRuntime() {
  return invokeDesktop<DesktopRuntimeProcessStatus>('start_local_runtime');
}

export function stopDesktopRuntime() {
  return invokeDesktop<DesktopRuntimeProcessStatus>('stop_local_runtime');
}

export function requestLocalRuntime(
  baseUrl: string,
  path: string,
  method: string,
  body?: string | null,
) {
  return invokeDesktop<DesktopRuntimeHttpResponse>('local_runtime_request', {
    baseUrl,
    path,
    method,
    body: body ?? null,
  });
}

export { isTauri };
