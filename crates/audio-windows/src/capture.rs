use livetranslator_audio_core::{
    AudioCaptureConfig, AudioCaptureStats, AudioCaptureStream, AudioChunker, AudioPlatformError,
};
use livetranslator_protocol::{AudioBus, AudioFrame};
use std::collections::VecDeque;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, SyncSender, TrySendError};
use std::sync::Arc;
use std::thread::{self, JoinHandle};
use std::time::Duration;
use wasapi::{
    deinitialize, initialize_mta, DeviceEnumerator, Direction, SampleType, StreamMode, WaveFormat,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum CaptureKind {
    Microphone,
    Loopback,
}

pub(crate) struct WindowsWasapiCaptureStream {
    receiver: Receiver<AudioFrame>,
    stop_requested: Arc<AtomicBool>,
    active: Arc<AtomicBool>,
    frames_emitted: Arc<AtomicU64>,
    frames_dropped: Arc<AtomicU64>,
    worker: Option<JoinHandle<()>>,
}

impl AudioCaptureStream for WindowsWasapiCaptureStream {
    fn recv_timeout(&self, timeout: Duration) -> Result<Option<AudioFrame>, AudioPlatformError> {
        match self.receiver.recv_timeout(timeout) {
            Ok(frame) => Ok(Some(frame)),
            Err(RecvTimeoutError::Timeout) => Ok(None),
            Err(RecvTimeoutError::Disconnected) if !self.active.load(Ordering::SeqCst) => Ok(None),
            Err(RecvTimeoutError::Disconnected) => Err(AudioPlatformError::Platform(
                "WASAPI capture worker disconnected unexpectedly".into(),
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

    fn stats(&self) -> AudioCaptureStats {
        AudioCaptureStats {
            frames_emitted: self.frames_emitted.load(Ordering::Relaxed),
            frames_dropped: self.frames_dropped.load(Ordering::Relaxed),
        }
    }
}

impl Drop for WindowsWasapiCaptureStream {
    fn drop(&mut self) {
        self.stop();
    }
}

pub(crate) fn start_capture(
    kind: CaptureKind,
    config: AudioCaptureConfig,
) -> Result<Box<dyn AudioCaptureStream>, AudioPlatformError> {
    config.validate()?;

    let (tx, rx) = mpsc::sync_channel(config.queue_capacity);
    let (startup_tx, startup_rx) = mpsc::sync_channel::<Result<(), String>>(1);
    let stop_requested = Arc::new(AtomicBool::new(false));
    let active = Arc::new(AtomicBool::new(false));
    let frames_emitted = Arc::new(AtomicU64::new(0));
    let frames_dropped = Arc::new(AtomicU64::new(0));

    let worker_stop = Arc::clone(&stop_requested);
    let worker_active = Arc::clone(&active);
    let worker_emitted = Arc::clone(&frames_emitted);
    let worker_dropped = Arc::clone(&frames_dropped);

    let worker = thread::Builder::new()
        .name(match kind {
            CaptureKind::Microphone => "voxpassport-wasapi-microphone".into(),
            CaptureKind::Loopback => "voxpassport-wasapi-loopback".into(),
        })
        .spawn(move || {
            let result = capture_worker(
                kind,
                config,
                tx,
                &worker_stop,
                &worker_active,
                &worker_emitted,
                &worker_dropped,
                &startup_tx,
            );
            if let Err(error) = result {
                let _ = startup_tx.try_send(Err(error.to_string()));
            }
            worker_active.store(false, Ordering::SeqCst);
        })
        .map_err(|error| AudioPlatformError::Platform(format!("could not start WASAPI worker: {error}")))?;

    match startup_rx.recv_timeout(Duration::from_secs(8)) {
        Ok(Ok(())) => Ok(Box::new(WindowsWasapiCaptureStream {
            receiver: rx,
            stop_requested,
            active,
            frames_emitted,
            frames_dropped,
            worker: Some(worker),
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
                "WASAPI capture worker did not initialize: {error}"
            )))
        }
    }
}

fn capture_worker(
    kind: CaptureKind,
    config: AudioCaptureConfig,
    sender: SyncSender<AudioFrame>,
    stop_requested: &AtomicBool,
    active: &AtomicBool,
    frames_emitted: &AtomicU64,
    frames_dropped: &AtomicU64,
    startup: &SyncSender<Result<(), String>>,
) -> Result<(), AudioPlatformError> {
    initialize_mta()
        .ok()
        .map_err(|error| AudioPlatformError::Platform(format!("COM MTA initialization failed: {error}")))?;

    let result = capture_worker_initialized(
        kind,
        config,
        sender,
        stop_requested,
        active,
        frames_emitted,
        frames_dropped,
        startup,
    );
    deinitialize();
    result
}

fn capture_worker_initialized(
    kind: CaptureKind,
    config: AudioCaptureConfig,
    sender: SyncSender<AudioFrame>,
    stop_requested: &AtomicBool,
    active: &AtomicBool,
    frames_emitted: &AtomicU64,
    frames_dropped: &AtomicU64,
    startup: &SyncSender<Result<(), String>>,
) -> Result<(), AudioPlatformError> {
    let enumerator = DeviceEnumerator::new().map_err(wasapi_error)?;
    let endpoint_direction = match kind {
        CaptureKind::Microphone => Direction::Capture,
        CaptureKind::Loopback => Direction::Render,
    };
    let device = match config.endpoint_id.as_deref() {
        Some(endpoint_id) => enumerator.get_device(endpoint_id).map_err(wasapi_error)?,
        None => enumerator
            .get_default_device(&endpoint_direction)
            .map_err(wasapi_error)?,
    };

    if device.get_direction() != endpoint_direction {
        return Err(AudioPlatformError::InvalidConfiguration(format!(
            "endpoint direction {:?} does not match requested {:?} capture",
            device.get_direction(),
            kind
        )));
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
    // Render endpoint + Capture direction is the standard WASAPI loopback mode;
    // the wasapi crate applies AUDCLNT_STREAMFLAGS_LOOPBACK in this combination.
    audio_client
        .initialize_client(&desired_format, &Direction::Capture, &mode)
        .map_err(wasapi_error)?;
    let event = audio_client.set_get_eventhandle().map_err(wasapi_error)?;
    let capture_client = audio_client.get_audiocaptureclient().map_err(wasapi_error)?;

    let frames_per_chunk = ((config.sample_rate_hz as u64 * config.chunk_duration_ms as u64) / 1000)
        .max(1) as usize;
    let bytes_per_chunk = frames_per_chunk * block_align;
    let bus = match kind {
        CaptureKind::Microphone => AudioBus::PhysicalMic,
        CaptureKind::Loopback => AudioBus::RemoteConference,
    };
    let mut chunker = AudioChunker::new(
        bus,
        config.sample_rate_hz,
        config.channels,
        config.chunk_duration_ms,
    );
    let mut sample_queue = VecDeque::<u8>::with_capacity(bytes_per_chunk * 4);

    audio_client.start_stream().map_err(wasapi_error)?;
    active.store(true, Ordering::SeqCst);
    let _ = startup.send(Ok(()));

    while !stop_requested.load(Ordering::SeqCst) {
        // A timeout is not fatal: it provides a periodic opportunity to observe
        // stop_requested even when the endpoint is silent.
        let _ = event.wait_for_event(250);

        loop {
            let packet_frames = capture_client
                .get_next_packet_size()
                .map_err(wasapi_error)?
                .unwrap_or(0);
            if packet_frames == 0 {
                break;
            }
            let needed = packet_frames as usize * block_align;
            let additional = needed.saturating_sub(sample_queue.capacity() - sample_queue.len());
            sample_queue.reserve(additional);
            capture_client
                .read_from_device_to_deque(&mut sample_queue)
                .map_err(wasapi_error)?;
        }

        while sample_queue.len() >= bytes_per_chunk {
            let mut bytes = Vec::with_capacity(bytes_per_chunk);
            bytes.extend(sample_queue.drain(..bytes_per_chunk));
            let frame = chunker.process_raw_bytes(bytes);
            match sender.try_send(frame) {
                Ok(()) => {
                    frames_emitted.fetch_add(1, Ordering::Relaxed);
                }
                Err(TrySendError::Full(_)) => {
                    // Drop the newest frame. Preserving bounded latency is more
                    // important for live translation than preserving stale audio.
                    frames_dropped.fetch_add(1, Ordering::Relaxed);
                }
                Err(TrySendError::Disconnected(_)) => {
                    stop_requested.store(true, Ordering::SeqCst);
                    break;
                }
            }
        }
    }

    let _ = audio_client.stop_stream();
    active.store(false, Ordering::SeqCst);
    Ok(())
}

fn wasapi_error(error: impl std::fmt::Display) -> AudioPlatformError {
    AudioPlatformError::Platform(format!("WASAPI: {error}"))
}
