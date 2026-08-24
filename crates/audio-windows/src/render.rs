use livetranslator_audio_core::{
    AudioPlatformError, AudioRenderConfig, AudioRenderStats, AudioRenderStream,
};
use livetranslator_protocol::{AudioFrame, SampleFormat};
use std::collections::VecDeque;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::{self, Receiver, SyncSender, TryRecvError, TrySendError};
use std::sync::Arc;
use std::thread::{self, JoinHandle};
use std::time::Duration;
use wasapi::{deinitialize, initialize_mta, DeviceEnumerator, Direction, SampleType, StreamMode, WaveFormat};

pub(crate) struct WindowsWasapiRenderStream {
    sender: SyncSender<AudioFrame>,
    stop_requested: Arc<AtomicBool>,
    active: Arc<AtomicBool>,
    frames_accepted: Arc<AtomicU64>,
    frames_dropped: Arc<AtomicU64>,
    worker: Option<JoinHandle<()>>,
    config: AudioRenderConfig,
}

impl AudioRenderStream for WindowsWasapiRenderStream {
    fn try_write(&self, frame: AudioFrame) -> Result<bool, AudioPlatformError> {
        if !self.active.load(Ordering::SeqCst) {
            return Err(AudioPlatformError::Platform("WASAPI render stream is not active".into()));
        }
        if frame.sample_rate_hz != self.config.sample_rate_hz
            || frame.channels != self.config.channels
            || frame.sample_format != SampleFormat::PcmS16le
        {
            return Err(AudioPlatformError::InvalidConfiguration(format!(
                "render frame must be PCM_S16LE {} Hz / {} channel(s)",
                self.config.sample_rate_hz, self.config.channels
            )));
        }
        match self.sender.try_send(frame) {
            Ok(()) => {
                self.frames_accepted.fetch_add(1, Ordering::Relaxed);
                Ok(true)
            }
            Err(TrySendError::Full(_)) => {
                self.frames_dropped.fetch_add(1, Ordering::Relaxed);
                Ok(false)
            }
            Err(TrySendError::Disconnected(_)) => Err(AudioPlatformError::Platform(
                "WASAPI render worker disconnected unexpectedly".into(),
            )),
        }
    }

    fn stop(&mut self) {
        self.stop_requested.store(true, Ordering::SeqCst);
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
        self.active.store(false, Ordering::SeqCst);
    }

    fn is_active(&self) -> bool {
        self.active.load(Ordering::SeqCst)
    }

    fn stats(&self) -> AudioRenderStats {
        AudioRenderStats {
            frames_accepted: self.frames_accepted.load(Ordering::Relaxed),
            frames_dropped: self.frames_dropped.load(Ordering::Relaxed),
        }
    }
}

impl Drop for WindowsWasapiRenderStream {
    fn drop(&mut self) {
        self.stop();
    }
}

pub(crate) fn start_render(
    config: AudioRenderConfig,
) -> Result<Box<dyn AudioRenderStream>, AudioPlatformError> {
    config.validate()?;
    let (sender, receiver) = mpsc::sync_channel(config.queue_capacity);
    let (startup_tx, startup_rx) = mpsc::sync_channel::<Result<(), String>>(1);
    let stop_requested = Arc::new(AtomicBool::new(false));
    let active = Arc::new(AtomicBool::new(false));
    let frames_accepted = Arc::new(AtomicU64::new(0));
    let frames_dropped = Arc::new(AtomicU64::new(0));

    let worker_stop = Arc::clone(&stop_requested);
    let worker_active = Arc::clone(&active);
    let worker_config = config.clone();
    let worker = thread::Builder::new()
        .name("voxpassport-wasapi-render".into())
        .spawn(move || {
            let result = render_worker(worker_config, receiver, &worker_stop, &worker_active, &startup_tx);
            if let Err(error) = result {
                let _ = startup_tx.try_send(Err(error.to_string()));
            }
            worker_active.store(false, Ordering::SeqCst);
        })
        .map_err(|error| AudioPlatformError::Platform(format!("could not start WASAPI render worker: {error}")))?;

    match startup_rx.recv_timeout(Duration::from_secs(8)) {
        Ok(Ok(())) => Ok(Box::new(WindowsWasapiRenderStream {
            sender,
            stop_requested,
            active,
            frames_accepted,
            frames_dropped,
            worker: Some(worker),
            config,
        })),
        Ok(Err(message)) => {
            stop_requested.store(true, Ordering::SeqCst);
            let _ = worker.join();
            Err(AudioPlatformError::Platform(message))
        }
        Err(error) => {
            stop_requested.store(true, Ordering::SeqCst);
            let _ = worker.join();
            Err(AudioPlatformError::Platform(format!(
                "WASAPI render worker did not initialize: {error}"
            )))
        }
    }
}

fn render_worker(
    config: AudioRenderConfig,
    receiver: Receiver<AudioFrame>,
    stop_requested: &AtomicBool,
    active: &AtomicBool,
    startup: &SyncSender<Result<(), String>>,
) -> Result<(), AudioPlatformError> {
    initialize_mta()
        .ok()
        .map_err(|error| AudioPlatformError::Platform(format!("COM MTA initialization failed: {error}")))?;
    let result = render_worker_initialized(config, receiver, stop_requested, active, startup);
    deinitialize();
    result
}

fn render_worker_initialized(
    config: AudioRenderConfig,
    receiver: Receiver<AudioFrame>,
    stop_requested: &AtomicBool,
    active: &AtomicBool,
    startup: &SyncSender<Result<(), String>>,
) -> Result<(), AudioPlatformError> {
    let enumerator = DeviceEnumerator::new().map_err(wasapi_error)?;
    let device = match config.endpoint_id.as_deref() {
        Some(endpoint_id) => enumerator.get_device(endpoint_id).map_err(wasapi_error)?,
        None => enumerator.get_default_device(&Direction::Render).map_err(wasapi_error)?,
    };
    if device.get_direction() != Direction::Render {
        return Err(AudioPlatformError::InvalidConfiguration(
            "render output requires a Windows render endpoint".into(),
        ));
    }

    let mut audio_client = device.get_iaudioclient().map_err(wasapi_error)?;
    let desired_format = WaveFormat::new(
        16,
        16,
        &SampleType::Int,
        config.sample_rate_hz as usize,
        config.channels as usize,
        None,
    );
    let block_align = desired_format.get_blockalign() as usize;
    let (default_period, _) = audio_client.get_device_period().map_err(wasapi_error)?;
    let mode = StreamMode::EventsShared {
        autoconvert: true,
        buffer_duration_hns: default_period,
    };
    audio_client
        .initialize_client(&desired_format, &Direction::Render, &mode)
        .map_err(wasapi_error)?;
    let event = audio_client.set_get_eventhandle().map_err(wasapi_error)?;
    let render_client = audio_client.get_audiorenderclient().map_err(wasapi_error)?;
    let mut sample_queue = VecDeque::<u8>::new();

    // Prime the shared buffer with silence before Start, as recommended by WASAPI.
    let initial_frames = audio_client.get_available_space_in_frames().map_err(wasapi_error)? as usize;
    if initial_frames > 0 {
        let silence = vec![0u8; initial_frames * block_align];
        render_client
            .write_to_device(initial_frames, &silence, None)
            .map_err(wasapi_error)?;
    }

    audio_client.start_stream().map_err(wasapi_error)?;
    active.store(true, Ordering::SeqCst);
    let _ = startup.send(Ok(()));

    while !stop_requested.load(Ordering::SeqCst) {
        let _ = event.wait_for_event(250);
        let available_frames = audio_client.get_available_space_in_frames().map_err(wasapi_error)? as usize;
        if available_frames == 0 {
            continue;
        }
        let needed_bytes = available_frames * block_align;
        while sample_queue.len() < needed_bytes {
            match receiver.try_recv() {
                Ok(frame) => sample_queue.extend(frame.data),
                Err(TryRecvError::Empty) => {
                    sample_queue.resize(needed_bytes, 0);
                    break;
                }
                Err(TryRecvError::Disconnected) => {
                    stop_requested.store(true, Ordering::SeqCst);
                    sample_queue.resize(needed_bytes, 0);
                    break;
                }
            }
        }
        render_client
            .write_to_device_from_deque(available_frames, &mut sample_queue, None)
            .map_err(wasapi_error)?;
    }

    let _ = audio_client.stop_stream();
    active.store(false, Ordering::SeqCst);
    Ok(())
}

fn wasapi_error(error: impl std::fmt::Display) -> AudioPlatformError {
    AudioPlatformError::Platform(format!("WASAPI: {error}"))
}
