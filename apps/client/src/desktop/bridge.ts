export type DesktopAudioCapabilities = {
  platform: string;
  native_audio: boolean;
  physical_microphone: boolean;
  loopback_capture: boolean;
  virtual_microphone_output: boolean;
  virtual_microphone_note: string;
};

export type DesktopRuntimeProcessStatus = {
  base_url: string;
  owned_by_desktop: boolean;
  running: boolean;
  pid?: number | null;
};

function isTauri(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}

async function invokeDesktop<T>(command: string): Promise<T | null> {
  if (!isTauri()) return null;
  const { invoke } = await import('@tauri-apps/api/core');
  return invoke<T>(command);
}

export function getDesktopAudioCapabilities() {
  return invokeDesktop<DesktopAudioCapabilities>('desktop_audio_capabilities');
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

export { isTauri };
