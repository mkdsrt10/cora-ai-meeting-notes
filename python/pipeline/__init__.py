"""Local meeting pipeline: audio -> transcript -> speakers -> notes, on-device.

Module map (dependencies flow downward):

    config      model selection, MLX memory limits
    common      timestamps, progress reporting
    audio       ffmpeg: probing, silence detection, clipping, mic/system mixing
    vocabulary  Whisper initial-prompt vocabulary, learned terms
    llm         traced local LLM generation, transcript chunking
    transcribe  MLX Whisper in pause-bounded chunks
    speakers    Accessibility timeline, mic/system tracks, roster, LLM naming
    notes       enhanced notes and summary variants
    runner      process_recording_local(): the end-to-end orchestration

Run on one recording:  python -m pipeline.runner <recording-folder-or-id>
"""
