"""Local meeting pipeline: audio -> transcript -> speakers -> notes, on-device.

Module map (dependencies flow downward):

    config      model selection, MLX memory limits
    common      timestamps, progress reporting
    audio       ffmpeg: probing, silence detection, clipping, mic/system mixing
    vocabulary  Whisper initial-prompt vocabulary, learned terms
    text_model  the Text model: every text-generation call (local MLX or hosted)
    transcriber the Transcriber: every speech-to-text call (MLX Whisper, Gemini, OpenAI-compatible)
    llm         usage stats, transcript chunking for the text passes
    transcribe  MLX Whisper in pause-bounded chunks (the Transcriber's local engine)
    windowed    hosted engines' window ladder: retry, split, validate (asr_validate)
    speakers    Accessibility timeline, mic/system tracks, roster, LLM naming
    notes       enhanced notes and summary variants
    runner      process_recording_local(): the end-to-end orchestration

Run on one recording:  python -m pipeline.runner <recording-folder-or-id>
"""
