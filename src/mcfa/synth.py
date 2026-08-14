"""Dependency-free MCFA synthesis and transport core.

The real-time backend only asks this module for interleaved float32 frames.  That
keeps musical timing, state changes, fades, and tests independent of audio APIs.
"""

from __future__ import annotations

from array import array
from dataclasses import dataclass, field
import copy
import math
import random
import threading
import time
from typing import Any

try:  # The repository-local null backend remains usable before installation.
    import numpy as _np
except ImportError:  # pragma: no cover - both paths are exercised in separate test runs.
    _np = None

from .model import (
    Channel,
    MAX_CHANNELS,
    Step,
    ValidationError,
    default_channels,
    midi_frequency,
    random_seed_public,
    validate_at,
    validate_bpm,
    validate_channel_id,
)


EPSILON = 1e-9
_SYSTEM_RANDOM = random.SystemRandom()


def _resolve_random_seed_patch(patch: dict[str, Any]) -> None:
    """Resolve system entropy on the control thread, never per audio sample."""
    value = patch.get("random_seed")
    if isinstance(value, str) and value.strip().lower() == "system":
        patch["random_seed"] = _SYSTEM_RANDOM.getrandbits(128)


@dataclass
class Ramp:
    value: float
    target: float | None = None
    remaining: int = 0

    def __post_init__(self) -> None:
        if self.target is None:
            self.target = self.value

    def set(self, target: float, frames: int) -> None:
        self.target = float(target)
        self.remaining = max(0, int(frames))
        if self.remaining == 0:
            self.value = self.target

    def tick(self) -> float:
        if self.remaining > 0:
            self.value += (self.target - self.value) / self.remaining
            self.remaining -= 1
            if self.remaining == 0:
                self.value = self.target
        return self.value

    def advance(self, frames: int) -> float:
        """Advance a silent ramp without paying a Python call per sample."""
        if self.remaining > 0:
            steps = min(max(0, int(frames)), self.remaining)
            self.value += (self.target - self.value) * (steps / self.remaining)
            self.remaining -= steps
            if self.remaining == 0:
                self.value = self.target
        return self.value

    def block(self, frames: int):
        """Return an accelerated ramp block and advance its state."""
        if _np is None:
            raise RuntimeError("NumPy ramp requested without NumPy")
        count = max(0, int(frames))
        if self.remaining <= 0:
            return _np.full(count, self.value, dtype=_np.float64)
        steps = min(count, self.remaining)
        start = self.value
        end = start + (self.target - start) * (steps / self.remaining)
        first = _np.linspace(start + (end - start) / steps, end, steps, dtype=_np.float64)
        self.value = end
        self.remaining -= steps
        if self.remaining == 0:
            self.value = self.target
        if steps == count:
            return first
        return _np.concatenate((first, _np.full(count - steps, self.value, dtype=_np.float64)))


@dataclass
class Voice:
    midi: int
    velocity: float
    gate_frames: int
    sample_rate: int
    waveform: str
    detune: float
    attack: float
    decay: float
    sustain: float
    release: float
    phase_a: float = 0.0
    phase_b: float = 0.0
    age: int = 0
    alive: bool = True

    def __post_init__(self) -> None:
        base = midi_frequency(self.midi)
        if self.detune:
            ratio = 2.0 ** (self.detune / 2400.0)
            self.increment_a = (base / ratio) / self.sample_rate
            self.increment_b = (base * ratio) / self.sample_rate
        else:
            self.increment_a = base / self.sample_rate
            self.increment_b = self.increment_a
        self.attack_frames = max(1, int(self.attack * self.sample_rate))
        self.decay_frames = max(0, int(self.decay * self.sample_rate))
        self.release_frames = max(1, int(self.release * self.sample_rate))
        self.release_start = self.envelope_at(self.gate_frames)

    def envelope_at(self, frame: int) -> float:
        if frame < self.attack_frames:
            return frame / self.attack_frames
        if self.decay_frames and frame < self.attack_frames + self.decay_frames:
            progress = (frame - self.attack_frames) / self.decay_frames
            return 1.0 + (self.sustain - 1.0) * progress
        return self.sustain

    def next_sample(self, rng: random.Random) -> float:
        if not self.alive:
            return 0.0
        if self.age >= self.gate_frames:
            released = self.age - self.gate_frames
            if released >= self.release_frames:
                self.alive = False
                return 0.0
            envelope = self.release_start * (1.0 - released / self.release_frames)
        else:
            envelope = self.envelope_at(self.age)

        sample_a = _oscillator(self.waveform, self.phase_a, rng)
        if self.detune:
            sample_b = _oscillator(self.waveform, self.phase_b, rng)
            sample = 0.5 * (sample_a + sample_b)
        else:
            sample = sample_a
        self.phase_a = (self.phase_a + self.increment_a) % 1.0
        self.phase_b = (self.phase_b + self.increment_b) % 1.0
        self.age += 1
        return sample * envelope * self.velocity

    def render_numpy(self, frames: int, rng: Any):
        if _np is None or not self.alive:
            raise RuntimeError("NumPy voice rendering is unavailable")
        count = int(frames)
        ages = _np.arange(self.age, self.age + count, dtype=_np.float64)
        envelope = _np.full(count, self.sustain, dtype=_np.float64)
        attack_mask = ages < self.attack_frames
        envelope[attack_mask] = ages[attack_mask] / self.attack_frames
        if self.decay_frames:
            decay_mask = (ages >= self.attack_frames) & (ages < self.attack_frames + self.decay_frames)
            envelope[decay_mask] = 1.0 + (self.sustain - 1.0) * (
                (ages[decay_mask] - self.attack_frames) / self.decay_frames
            )
        release_mask = ages >= self.gate_frames
        envelope[release_mask] = self.release_start * (
            1.0 - (ages[release_mask] - self.gate_frames) / self.release_frames
        )
        envelope[ages >= self.gate_frames + self.release_frames] = 0.0
        offsets = _np.arange(count, dtype=_np.float64)
        phase_a = (self.phase_a + offsets * self.increment_a) % 1.0
        sample_a = _oscillator_numpy(self.waveform, phase_a, rng)
        if self.detune:
            phase_b = (self.phase_b + offsets * self.increment_b) % 1.0
            sample = 0.5 * (sample_a + _oscillator_numpy(self.waveform, phase_b, rng))
        else:
            sample = sample_a
        self.phase_a = (self.phase_a + count * self.increment_a) % 1.0
        self.phase_b = (self.phase_b + count * self.increment_b) % 1.0
        self.age += count
        if self.age >= self.gate_frames + self.release_frames:
            self.alive = False
        return sample * envelope * self.velocity


def _oscillator(waveform: str, phase: float, rng: random.Random) -> float:
    if waveform == "sine":
        return math.sin(2.0 * math.pi * phase)
    if waveform == "triangle":
        return 1.0 - 4.0 * abs(phase - 0.5)
    if waveform == "saw":
        return 2.0 * phase - 1.0
    if waveform == "square":
        return 1.0 if phase < 0.5 else -1.0
    return rng.random() * 2.0 - 1.0


def _oscillator_numpy(waveform: str, phase: Any, rng: Any):
    if waveform == "sine":
        return _np.sin(2.0 * _np.pi * phase)
    if waveform == "triangle":
        return 1.0 - 4.0 * _np.abs(phase - 0.5)
    if waveform == "saw":
        return 2.0 * phase - 1.0
    if waveform == "square":
        return _np.where(phase < 0.5, 1.0, -1.0)
    return rng.random(len(phase)) * 2.0 - 1.0


@dataclass
class ChannelRuntime:
    config: Channel
    sample_rate: int
    gain: Ramp = field(init=False)
    pan: Ramp = field(init=False)
    cutoff: Ramp = field(init=False)
    voices: list[Voice] = field(default_factory=list)
    step_index: int = 0
    next_step_beat: float | None = None
    next_step_frame: int | None = None
    clock_origin_frame: int = 0
    last_trigger_frame: int | None = None
    lfo_phase: float = 0.0
    buffers_silent: bool = True
    filter_low: float = 0.0
    filter_band: float = 0.0
    delay_position: int = 0
    reverb_position: int = 0
    peak: float = 0.0
    rms: float = 0.0
    last_trigger_beat: float | None = None

    def __post_init__(self) -> None:
        self.gain = Ramp(0.0 if self.config.muted or not self.config.active else self.config.volume)
        self.pan = Ramp(self.config.pan)
        self.cutoff = Ramp(self.config.synth.filter.cutoff)
        delay_size = int(self.sample_rate * 2.0) + 1
        reverb_size = max(4096, int(self.sample_rate * 0.12))
        if _np is not None:
            self.delay_buffer = _np.zeros(delay_size, dtype=_np.float64)
            self.reverb_buffer = _np.zeros(reverb_size, dtype=_np.float64)
        else:
            self.delay_buffer = [0.0] * delay_size
            self.reverb_buffer = [0.0] * reverb_size
        self._seed_generators()

    def _seed_generators(self) -> None:
        seed = self.config.random_seed
        if seed is None:
            seed = 0x50594245 + self.config.id
        self.rng = random.Random(seed)
        self.numpy_rng = _np.random.default_rng(seed) if _np is not None else None

    def apply(self, candidate: Channel, patch: dict[str, Any], fade_frames: int, beat: float, frame: int) -> None:
        restart_pattern = any(key in patch for key in ("pattern", "step_beats", "clock", "bpm", "active"))
        self.config = candidate
        if "random_seed" in patch:
            self._seed_generators()
        self.gain.set(0.0 if candidate.muted or not candidate.active else candidate.volume, fade_frames)
        self.pan.set(candidate.pan, fade_frames)
        self.cutoff.set(candidate.synth.filter.cutoff, fade_frames)
        if restart_pattern:
            self.step_index = 0
            self.clock_origin_frame = frame
            if candidate.pattern and candidate.active:
                if candidate.clock == "free":
                    self.next_step_frame = frame
                    self.next_step_beat = None
                else:
                    self.next_step_beat = beat
                    self.next_step_frame = None
            else:
                self.next_step_beat = None
                self.next_step_frame = None
        elif candidate.pattern and candidate.active and self.next_step_beat is None and self.next_step_frame is None:
            if candidate.clock == "free":
                self.next_step_frame = frame
            else:
                self.next_step_beat = beat

    def hard_silence(self) -> None:
        """Immediately discard one lane's voices and effect memory."""
        self.voices.clear()
        if not self.buffers_silent:
            if _np is not None and isinstance(self.delay_buffer, _np.ndarray):
                self.delay_buffer.fill(0.0)
                self.reverb_buffer.fill(0.0)
            else:
                self.delay_buffer[:] = [0.0] * len(self.delay_buffer)
                self.reverb_buffer[:] = [0.0] * len(self.reverb_buffer)
        self.buffers_silent = True
        self.filter_low = 0.0
        self.filter_band = 0.0
        self.gain.set(0.0, 0)
        self.peak = 0.0
        self.rms = 0.0

    def kill(self) -> None:
        self.hard_silence()
        self.next_step_beat = None
        self.next_step_frame = None

    def local_beat(self, frame: int, global_beat: float) -> float:
        if self.config.clock == "sync":
            return global_beat
        elapsed = max(0, frame - self.clock_origin_frame)
        return elapsed * self.config.bpm / (60.0 * self.sample_rate)

    def trigger_due(self, beat: float, bpm: float, frame: int) -> None:
        if not self.config.active:
            return
        if self.config.clock == "free":
            self._trigger_due_free(frame)
            return
        guard = 0
        while self.config.pattern and self.next_step_beat is not None and self.next_step_beat <= beat + EPSILON:
            step = self.config.pattern[self.step_index]
            if not self.config.muted and step.notes and self.rng.random() <= step.probability:
                self._trigger(step, bpm)
                self.last_trigger_beat = self.next_step_beat
                self.last_trigger_frame = frame
            self.step_index = (self.step_index + 1) % len(self.config.pattern)
            self.next_step_beat += self.config.step_beats
            guard += 1
            if guard > 512:
                # A transport jump must never wedge the audio thread.
                self.next_step_beat = beat + self.config.step_beats
                break

    def _trigger_due_free(self, frame: int) -> None:
        guard = 0
        step_frames = max(1, round(self.config.step_beats * 60.0 / self.config.bpm * self.sample_rate))
        while self.config.pattern and self.next_step_frame is not None and self.next_step_frame <= frame:
            step = self.config.pattern[self.step_index]
            if not self.config.muted and step.notes and self.rng.random() <= step.probability:
                self._trigger(step, self.config.bpm)
                self.last_trigger_frame = self.next_step_frame
                self.last_trigger_beat = self.local_beat(self.next_step_frame, 0.0)
            self.step_index = (self.step_index + 1) % len(self.config.pattern)
            self.next_step_frame += step_frames
            guard += 1
            if guard > 512:
                self.next_step_frame = frame + step_frames
                break

    def _trigger(self, step: Step, bpm: float) -> None:
        synth = self.config.synth
        envelope = synth.envelope
        gate_frames = max(1, round(step.gate * self.config.step_beats * 60.0 / bpm * self.sample_rate))
        for midi in step.notes:
            self.voices.append(
                Voice(
                    midi=midi,
                    velocity=step.velocity,
                    gate_frames=gate_frames,
                    sample_rate=self.sample_rate,
                    waveform=synth.waveform,
                    detune=synth.detune,
                    attack=envelope.attack,
                    decay=envelope.decay,
                    sustain=envelope.sustain,
                    release=envelope.release,
                )
            )
        self.buffers_silent = False
        # Bound accidental voice buildup from long releases or dense chords.
        if len(self.voices) > 64:
            self.voices = self.voices[-64:]

    def render_into(self, left: list[float], right: list[float], offset: int, frames: int) -> None:
        if _np is not None and isinstance(left, _np.ndarray):
            self._render_into_numpy(left, right, offset, frames)
            return
        if not self.config.active or (self.gain.target == 0.0 and self.gain.remaining == 0):
            self.hard_silence()
            self.pan.advance(frames)
            self.cutoff.advance(frames)
            return
        config = self.config
        synth = config.synth
        filter_config = synth.filter
        effects = synth.effects
        if not self.voices and effects.delay_mix == 0.0 and effects.reverb_mix == 0.0:
            self.gain.advance(frames)
            self.pan.advance(frames)
            self.cutoff.advance(frames)
            self.peak *= 0.9
            self.rms *= 0.9
            return
        sample_rate = self.sample_rate
        local_peak = 0.0
        power = 0.0
        delay_len = len(self.delay_buffer)
        reverb_len = len(self.reverb_buffer)
        delay_samples = min(delay_len - 1, max(1, int(effects.delay_time * sample_rate)))
        delay_read = (self.delay_position - delay_samples) % delay_len
        # Three short, incommensurate taps produce a deliberately modest room tail.
        reverb_taps = (
            max(1, int(0.0297 * sample_rate)),
            max(1, int(0.0371 * sample_rate)),
            max(1, int(0.0411 * sample_rate)),
        )
        coefficient = _filter_coefficient(self.cutoff.value, sample_rate)
        steady_gain_pan = self.gain.remaining == 0 and self.pan.remaining == 0
        if steady_gain_pan:
            fixed_gain = self.gain.value
            fixed_left_gain = math.sqrt(0.5 * (1.0 - self.pan.value))
            fixed_right_gain = math.sqrt(0.5 * (1.0 + self.pan.value))
        voices = self.voices
        modulation = synth.modulation

        for frame in range(frames):
            dry = 0.0
            for voice in voices:
                dry += voice.next_sample(self.rng)

            lfo = self._next_lfo() if modulation.target != "off" and modulation.depth else 0.0

            if effects.drive:
                drive_gain = 1.0 + 12.0 * effects.drive
                dry = math.tanh(dry * drive_gain) / math.tanh(drive_gain)

            cutoff = self.cutoff.tick()
            if modulation.target == "cutoff":
                cutoff *= 2.0 ** (lfo * modulation.depth * 4.0)
            if (self.cutoff.remaining or modulation.target == "cutoff") and frame % 16 == 0:
                coefficient = _filter_coefficient(cutoff, sample_rate)
            if filter_config.type != "off":
                # A stable one-pole core with a bounded brightness boost.  This is
                # intentionally conservative: real-time safety matters more than
                # self-oscillation in this small instrument.
                bright = dry + filter_config.resonance * 0.5 * (dry - self.filter_low)
                self.filter_low += coefficient * (bright - self.filter_low)
                high = dry - self.filter_low
                self.filter_band += coefficient * (high - self.filter_band)
                if filter_config.type == "lowpass":
                    dry = self.filter_low
                elif filter_config.type == "highpass":
                    dry = high
                else:
                    dry = self.filter_band

            delayed = self.delay_buffer[delay_read]
            self.delay_buffer[self.delay_position] = dry + delayed * effects.delay_feedback
            self.delay_position = (self.delay_position + 1) % delay_len
            delay_read = (delay_read + 1) % delay_len
            wet = dry * (1.0 - effects.delay_mix) + delayed * effects.delay_mix

            reverberated = 0.0
            for tap in reverb_taps:
                reverberated += self.reverb_buffer[(self.reverb_position - tap) % reverb_len]
            reverberated /= len(reverb_taps)
            self.reverb_buffer[self.reverb_position] = wet + reverberated * 0.68
            self.reverb_position = (self.reverb_position + 1) % reverb_len
            wet = wet * (1.0 - effects.reverb_mix) + reverberated * effects.reverb_mix

            if steady_gain_pan:
                gain = fixed_gain
                left_gain = fixed_left_gain
                right_gain = fixed_right_gain
            else:
                gain = self.gain.tick()
                pan = self.pan.tick()
                left_gain = math.sqrt(0.5 * (1.0 - pan))
                right_gain = math.sqrt(0.5 * (1.0 + pan))
            if modulation.target == "amplitude":
                gain *= max(0.0, 1.0 + lfo * modulation.depth)
            elif modulation.target == "pan":
                base_pan = self.pan.value if steady_gain_pan else pan
                modulated_pan = max(-1.0, min(1.0, base_pan + lfo * modulation.depth))
                left_gain = math.sqrt(0.5 * (1.0 - modulated_pan))
                right_gain = math.sqrt(0.5 * (1.0 + modulated_pan))
            value = wet * gain
            left[offset + frame] += value * left_gain
            right[offset + frame] += value * right_gain
            magnitude = abs(value)
            local_peak = max(local_peak, magnitude)
            power += value * value

        self.voices = [voice for voice in voices if voice.alive]
        measured_rms = math.sqrt(power / frames) if frames else 0.0
        self.peak = max(local_peak, self.peak * 0.9)
        self.rms = max(measured_rms, self.rms * 0.9)

    def _render_into_numpy(self, left: Any, right: Any, offset: int, frames: int) -> None:
        if not self.config.active or (self.gain.target == 0.0 and self.gain.remaining == 0):
            self.hard_silence()
            self.pan.advance(frames)
            self.cutoff.advance(frames)
            return
        config = self.config
        synth = config.synth
        effects = synth.effects
        count = int(frames)
        if not self.voices and effects.delay_mix == 0.0 and effects.reverb_mix == 0.0:
            self.gain.advance(count)
            self.pan.advance(count)
            self.cutoff.advance(count)
            self.peak *= 0.9
            self.rms *= 0.9
            return

        dry = _np.zeros(count, dtype=_np.float64)
        voices = self.voices
        for voice in voices:
            if voice.alive:
                dry += voice.render_numpy(count, self.numpy_rng)
        self.voices = [voice for voice in voices if voice.alive]

        if effects.drive:
            drive_gain = 1.0 + 12.0 * effects.drive
            dry = _np.tanh(dry * drive_gain) / math.tanh(drive_gain)

        modulation = synth.modulation
        lfo = self._lfo_block(count) if modulation.target != "off" and modulation.depth else None
        cutoff_start = self.cutoff.value
        cutoff_end = self.cutoff.advance(count)
        filter_type = synth.filter.type
        if filter_type != "off":
            cutoff = 0.5 * (cutoff_start + cutoff_end)
            if modulation.target == "cutoff" and lfo is not None:
                cutoff *= 2.0 ** (float(_np.mean(lfo)) * modulation.depth * 4.0)
            coefficient = _filter_coefficient(cutoff, self.sample_rate)
            effective = min(0.98, coefficient * (1.0 + 0.5 * synth.filter.resonance))
            low, self.filter_low = _one_pole_numpy(dry, self.filter_low, effective)
            high = dry - low
            if filter_type == "lowpass":
                dry = low
            elif filter_type == "highpass":
                dry = high
            else:
                dry, self.filter_band = _one_pole_numpy(high, self.filter_band, effective)

        delay_samples = min(len(self.delay_buffer) - 1, max(1, int(effects.delay_time * self.sample_rate)))
        delayed = _np.empty(count, dtype=_np.float64)
        position = 0
        while position < count:
            chunk = min(delay_samples, count - position)
            offsets = _np.arange(chunk)
            read_indices = (self.delay_position - delay_samples + offsets) % len(self.delay_buffer)
            write_indices = (self.delay_position + offsets) % len(self.delay_buffer)
            values = self.delay_buffer[read_indices]
            delayed[position : position + chunk] = values
            self.delay_buffer[write_indices] = dry[position : position + chunk] + values * effects.delay_feedback
            self.delay_position = (self.delay_position + chunk) % len(self.delay_buffer)
            position += chunk
        wet = dry * (1.0 - effects.delay_mix) + delayed * effects.delay_mix

        taps = (
            max(1, int(0.0297 * self.sample_rate)),
            max(1, int(0.0371 * self.sample_rate)),
            max(1, int(0.0411 * self.sample_rate)),
        )
        reverberated = _np.empty(count, dtype=_np.float64)
        position = 0
        minimum_tap = min(taps)
        while position < count:
            chunk = min(minimum_tap, count - position)
            offsets = _np.arange(chunk)
            values = sum(
                self.reverb_buffer[(self.reverb_position - tap + offsets) % len(self.reverb_buffer)]
                for tap in taps
            ) / len(taps)
            reverberated[position : position + chunk] = values
            write_indices = (self.reverb_position + offsets) % len(self.reverb_buffer)
            self.reverb_buffer[write_indices] = wet[position : position + chunk] + values * 0.68
            self.reverb_position = (self.reverb_position + chunk) % len(self.reverb_buffer)
            position += chunk
        wet = wet * (1.0 - effects.reverb_mix) + reverberated * effects.reverb_mix

        gains = self.gain.block(count)
        pans = self.pan.block(count)
        if modulation.target == "amplitude" and lfo is not None:
            gains *= _np.maximum(0.0, 1.0 + lfo * modulation.depth)
        elif modulation.target == "pan" and lfo is not None:
            pans = _np.clip(pans + lfo * modulation.depth, -1.0, 1.0)
        values = wet * gains
        left[offset : offset + count] += values * _np.sqrt(0.5 * (1.0 - pans))
        right[offset : offset + count] += values * _np.sqrt(0.5 * (1.0 + pans))
        local_peak = float(_np.max(_np.abs(values))) if count else 0.0
        measured_rms = float(_np.sqrt(_np.mean(values * values))) if count else 0.0
        self.peak = max(local_peak, self.peak * 0.9)
        self.rms = max(measured_rms, self.rms * 0.9)

    def _next_lfo(self) -> float:
        modulation = self.config.synth.modulation
        value = _lfo_wave(modulation.waveform, self.lfo_phase)
        self.lfo_phase = (self.lfo_phase + modulation.rate_hz / self.sample_rate) % 1.0
        return value

    def _lfo_block(self, frames: int):
        modulation = self.config.synth.modulation
        offsets = _np.arange(frames, dtype=_np.float64)
        phases = (self.lfo_phase + offsets * modulation.rate_hz / self.sample_rate) % 1.0
        if modulation.waveform == "sine":
            values = _np.sin(2.0 * _np.pi * phases)
        elif modulation.waveform == "triangle":
            values = 1.0 - 4.0 * _np.abs(phases - 0.5)
        else:
            values = _np.where(phases < 0.5, 1.0, -1.0)
        self.lfo_phase = (self.lfo_phase + frames * modulation.rate_hz / self.sample_rate) % 1.0
        return values

    def runtime_public(self, frame: int, global_beat: float) -> dict[str, Any]:
        return {
            "active_voices": len(self.voices),
            "step_index": self.step_index,
            "next_step_beat": _rounded(self.next_step_beat),
            "next_step_frame": self.next_step_frame,
            "local_beat": _rounded(self.local_beat(frame, global_beat)),
            "last_trigger_beat": _rounded(self.last_trigger_beat),
            "last_trigger_frame": self.last_trigger_frame,
            "level": {"peak": round(self.peak, 5), "rms": round(self.rms, 5)},
            "transition": {
                "gain": round(self.gain.value, 5),
                "gain_target": round(float(self.gain.target), 5),
                "pan": round(self.pan.value, 5),
                "cutoff": round(self.cutoff.value, 2),
                "frames_remaining": max(self.gain.remaining, self.pan.remaining, self.cutoff.remaining),
            },
        }


def _lfo_wave(waveform: str, phase: float) -> float:
    if waveform == "sine":
        return math.sin(2.0 * math.pi * phase)
    if waveform == "triangle":
        return 1.0 - 4.0 * abs(phase - 0.5)
    return 1.0 if phase < 0.5 else -1.0


def _decision_summary(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Keep an auditable history without copying entire patterns into every entry."""

    def patch_summary(patch: dict[str, Any]) -> dict[str, Any]:
        summary: dict[str, Any] = {"fields": sorted(patch)}
        for key in ("name", "active", "muted", "clock", "bpm", "volume", "pan", "step_beats", "random_seed"):
            if key in patch:
                summary[key] = random_seed_public(patch[key]) if key == "random_seed" else patch[key]
        if "pattern" in patch:
            pattern = patch["pattern"]
            summary["pattern_steps"] = len(pattern)
            summary["pattern_notes"] = [
                "+".join(step.get("notes", [])) or "." for step in pattern[:8]
            ]
        if "synth" in patch:
            synth = patch["synth"]
            summary["synth_fields"] = sorted(synth)
            if "waveform" in synth:
                summary["waveform"] = synth["waveform"]
            if "modulation" in synth:
                summary["modulation"] = dict(synth["modulation"])
        return summary

    if kind == "batch":
        return {
            "updates": [
                {"channel": item["channel"], **patch_summary(item.get("patch", {}))}
                for item in payload.get("items", [])
            ]
        }
    if "patch" in payload:
        return patch_summary(payload["patch"])
    return {key: value for key, value in payload.items() if key in {"bpm", "volume", "seconds", "deadline_fade", "cancel"}}


def _filter_coefficient(cutoff: float, sample_rate: int) -> float:
    safe_cutoff = min(float(cutoff), sample_rate * 0.20)
    return min(0.95, 1.0 - math.exp(-2.0 * math.pi * safe_cutoff / sample_rate))


def _one_pole_numpy(values: Any, previous: float, coefficient: float) -> tuple[Any, float]:
    """Exact block form of y[n] = a*y[n-1] + b*x[n]."""
    count = len(values)
    if count == 0:
        return values.copy(), previous
    decay = 1.0 - coefficient
    powers = decay ** _np.arange(count, dtype=_np.float64)
    kernel = coefficient * powers
    output = _np.convolve(values, kernel, mode="full")[:count]
    output += previous * decay ** _np.arange(1, count + 1, dtype=_np.float64)
    return output, float(output[-1])


@dataclass(order=True)
class ScheduledEvent:
    at_beat: float
    sequence: int
    kind: str = field(compare=False)
    payload: dict[str, Any] = field(compare=False)
    fade: float = field(compare=False, default=0.05)

    def public(self, current_beat: float) -> dict[str, Any]:
        summary: dict[str, Any] = {"kind": self.kind}
        if "channel" in self.payload:
            summary["channel"] = self.payload["channel"]
        if self.kind == "batch":
            summary["channels"] = [item["channel"] for item in self.payload["items"]]
        return {
            "id": self.sequence,
            "at_beat": round(self.at_beat, 6),
            "in_beats": round(max(0.0, self.at_beat - current_beat), 6),
            "fade_seconds": self.fade,
            **summary,
        }


class SynthEngine:
    """Thread-safe transport, scheduler, state model, and stereo renderer."""

    def __init__(
        self,
        *,
        bpm: float = 120.0,
        sample_rate: int = 44100,
        master_volume: float = 0.8,
        backend_name: str = "unstarted",
        duration: float | None = None,
        deadline_fade: float = 3.0,
    ) -> None:
        self.bpm = validate_bpm(bpm)
        self.sample_rate = int(sample_rate)
        if not 8000 <= self.sample_rate <= 192000:
            raise ValidationError("sample rate must be between 8000 and 192000")
        self.channels = [ChannelRuntime(channel, self.sample_rate) for channel in default_channels(self.bpm)]
        self.entropy_stamp = f"{_SYSTEM_RANDOM.getrandbits(128):032x}"
        self.master = Ramp(float(master_volume))
        self.backend_name = backend_name
        self.frame = 0
        self.beat = 0.0
        self.bar_beats = 4.0
        self.started_monotonic = time.monotonic()
        self.started_wall = time.time()
        self.events: list[ScheduledEvent] = []
        self.sequence = 0
        self.history: list[dict[str, Any]] = []
        self.running = True
        self.stop_reason: str | None = None
        self.stop_at_frame: int | None = None
        self.deadline_frame: int | None = None
        self.deadline_fade_frames = max(0, int(float(deadline_fade) * self.sample_rate))
        self.deadline_fade_started = False
        self.underruns = 0
        self.lock = threading.RLock()
        if duration is not None and duration > 0:
            self.deadline_frame = int(duration * self.sample_rate)

    def schedule(self, kind: str, payload: dict[str, Any], *, at: str = "now", fade: float = 0.05) -> dict[str, Any]:
        with self.lock:
            if not self.running:
                raise ValidationError("engine is stopping or stopped")
            at = validate_at(at)
            fade = float(fade)
            if not 0.0 <= fade <= 60.0:
                raise ValidationError("fade must be between 0 and 60 seconds")
            normalized = self._validate_command(kind, payload)
            target = self._target_beat(at, normalized)
            self.sequence += 1
            event = ScheduledEvent(target, self.sequence, kind, normalized, fade)
            self.events.append(event)
            self.events.sort()
            self._record_history("scheduled", event)
            # Immediate commands become observable without waiting for the next audio block.
            if target <= self.beat + EPSILON:
                self._apply_due_events()
            return event.public(self.beat)

    def _record_history(self, phase: str, event: ScheduledEvent) -> None:
        self.history.append(
            self._history_entry(phase, event.kind, event.sequence, event.payload, event.at_beat, event.fade)
        )
        if len(self.history) > 2048:
            del self.history[: len(self.history) - 2048]

    def _history_entry(
        self,
        phase: str,
        kind: str,
        event_id: int | None,
        payload: dict[str, Any],
        at_beat: float | None = None,
        fade: float = 0.0,
    ) -> dict[str, Any]:
        channels: list[int] = []
        if "channel" in payload:
            channels = [int(payload["channel"])]
        elif kind == "batch":
            channels = [int(item["channel"]) for item in payload.get("items", [])]
        return {
            "id": event_id,
            "phase": phase,
            "kind": kind,
            "frame": self.frame,
            "seconds": round(self.frame / self.sample_rate, 6),
            "beat": round(self.beat, 6),
            "at_beat": None if at_beat is None else round(at_beat, 6),
            "fade_seconds": round(float(fade), 6),
            "channels": channels,
            "decision": _decision_summary(kind, payload),
        }

    def panic(self) -> None:
        with self.lock:
            for runtime in self.channels:
                runtime.hard_silence()
            self.events.clear()
            self.master.set(0.0, 0)
            self.stop_reason = "panic"
            self.running = False
            self.history.append(self._history_entry("applied", "panic", None, {}))

    def _validate_command(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = copy.deepcopy(payload)
        if kind in {"set", "clear", "mute", "kill", "restart"}:
            channel = validate_channel_id(normalized.get("channel"))
            normalized["channel"] = channel
            if kind == "clear":
                normalized["patch"] = {"pattern": []}
            elif kind == "mute":
                normalized["patch"] = {"muted": bool(normalized.get("muted", True))}
            elif kind == "kill":
                normalized["patch"] = {"active": False}
            elif kind == "restart":
                normalized["patch"] = {"active": True, "muted": False}
            patch = dict(normalized.get("patch", {}))
            _resolve_random_seed_patch(patch)
            candidate = copy.deepcopy(self.channels[channel - 1].config)
            candidate.update(patch)
            normalized["patch"] = patch
        elif kind == "batch":
            raw_items = normalized.get("items")
            if not isinstance(raw_items, list) or not raw_items:
                raise ValidationError("batch requires a non-empty items list")
            if len(raw_items) > MAX_CHANNELS:
                raise ValidationError(f"batch cannot contain more than {MAX_CHANNELS} channel updates")
            seen: set[int] = set()
            items: list[dict[str, Any]] = []
            for raw in raw_items:
                channel = validate_channel_id(raw.get("channel"))
                if channel in seen:
                    raise ValidationError(f"channel {channel} occurs twice in batch")
                seen.add(channel)
                patch = dict(raw.get("patch", {}))
                _resolve_random_seed_patch(patch)
                candidate = copy.deepcopy(self.channels[channel - 1].config)
                candidate.update(patch)
                items.append({"channel": channel, "patch": patch})
            normalized = {"items": items}
        elif kind == "tempo":
            normalized = {"bpm": validate_bpm(normalized.get("bpm"))}
        elif kind == "master":
            volume = float(normalized.get("volume"))
            if not 0.0 <= volume <= 1.0:
                raise ValidationError("master volume must be between 0 and 1")
            normalized = {"volume": volume}
        elif kind == "deadline":
            if normalized.get("cancel"):
                normalized = {"cancel": True}
            else:
                seconds = float(normalized.get("seconds"))
                deadline_fade = float(normalized.get("deadline_fade", 3.0))
                if not 0.05 <= seconds <= 86400:
                    raise ValidationError("deadline seconds must be between 0.05 and 86400")
                if not 0.0 <= deadline_fade <= seconds:
                    raise ValidationError("deadline fade must be between 0 and the deadline duration")
                normalized = {"seconds": seconds, "deadline_fade": deadline_fade}
        elif kind == "stop":
            normalized = {}
        else:
            raise ValidationError(f"unknown engine command {kind!r}")
        return normalized

    def _target_beat(self, at: str, payload: dict[str, Any]) -> float:
        current = self.beat
        if at == "now":
            return current
        channel = payload.get("channel")
        runtime = self.channels[int(channel) - 1] if channel else None
        if runtime is not None and runtime.config.clock == "free":
            lane_beat = runtime.local_beat(self.frame, current)
            if at == "next-step" and runtime.next_step_frame is not None:
                frame_distance = max(0, runtime.next_step_frame - self.frame)
                return current + frame_distance * self.bpm / (60.0 * self.sample_rate)
            if at == "next-beat":
                lane_distance = math.floor(lane_beat + EPSILON) + 1.0 - lane_beat
                return current + lane_distance * self.bpm / runtime.config.bpm
            if at == "next-bar":
                lane_target = (math.floor((lane_beat + EPSILON) / self.bar_beats) + 1.0) * self.bar_beats
                return current + (lane_target - lane_beat) * self.bpm / runtime.config.bpm
        if at == "next-beat":
            return math.floor(current + EPSILON) + 1.0
        if at == "next-bar":
            return (math.floor((current + EPSILON) / self.bar_beats) + 1.0) * self.bar_beats
        if at == "next-step":
            step = 0.25
            if channel:
                step = self.channels[int(channel) - 1].config.step_beats
            return (math.floor((current + EPSILON) / step) + 1.0) * step
        value = at[1:]
        if value.endswith("beats"):
            value = value[:-5]
        elif value.endswith("beat"):
            value = value[:-4]
        distance = float(value)
        if runtime is not None and runtime.config.clock == "free":
            return current + distance * self.bpm / runtime.config.bpm
        return current + distance

    def _apply_due_events(self) -> None:
        while self.events and self.events[0].at_beat <= self.beat + EPSILON:
            event = self.events.pop(0)
            fade_frames = int(event.fade * self.sample_rate)
            if event.kind in {"set", "clear", "mute"}:
                self._apply_channel(event.payload["channel"], event.payload["patch"], fade_frames, event.at_beat)
            elif event.kind == "kill":
                self._apply_channel(event.payload["channel"], event.payload["patch"], 0, event.at_beat)
                self.channels[event.payload["channel"] - 1].kill()
            elif event.kind == "restart":
                self._apply_channel(event.payload["channel"], event.payload["patch"], fade_frames, event.at_beat)
            elif event.kind == "batch":
                # Validate every candidate before committing any of them.
                candidates = []
                for item in event.payload["items"]:
                    runtime = self.channels[item["channel"] - 1]
                    candidate = copy.deepcopy(runtime.config)
                    candidate.update(item["patch"])
                    candidates.append((runtime, candidate, item["patch"]))
                for runtime, candidate, patch in candidates:
                    runtime.apply(candidate, patch, fade_frames, event.at_beat, self.frame)
            elif event.kind == "tempo":
                self.bpm = event.payload["bpm"]
            elif event.kind == "master":
                self.master.set(event.payload["volume"], fade_frames)
            elif event.kind == "deadline":
                if event.payload.get("cancel"):
                    self.deadline_frame = None
                    self.deadline_fade_started = False
                else:
                    self.deadline_frame = self.frame + int(event.payload["seconds"] * self.sample_rate)
                    self.deadline_fade_frames = int(event.payload["deadline_fade"] * self.sample_rate)
                    self.deadline_fade_started = False
            elif event.kind == "stop":
                self.request_stop(event.fade)
            self._record_history("applied", event)

    def _apply_channel(self, channel: int, patch: dict[str, Any], fade_frames: int, beat: float) -> None:
        runtime = self.channels[channel - 1]
        candidate = copy.deepcopy(runtime.config)
        candidate.update(patch)
        runtime.apply(candidate, patch, fade_frames, beat, self.frame)

    def request_stop(self, fade: float = 2.0) -> None:
        with self.lock:
            if not self.running:
                return
            frames = max(0, int(float(fade) * self.sample_rate))
            self.stop_reason = "graceful-stop"
            if frames == 0:
                self.master.set(0.0, 0)
                self.running = False
            else:
                self.master.set(0.0, frames)
                self.stop_at_frame = self.frame + frames

    def render(self, frames: int) -> array:
        with self.lock:
            frame_count = int(frames)
            if _np is not None:
                left = _np.zeros(frame_count, dtype=_np.float64)
                right = _np.zeros(frame_count, dtype=_np.float64)
            else:
                left = [0.0] * frame_count
                right = [0.0] * frame_count
            cursor = 0
            while cursor < frame_count and self.running:
                self._handle_deadline()
                self._apply_due_events()
                for runtime in self.channels:
                    runtime.trigger_due(self.beat, self.bpm, self.frame)
                if not self.running:
                    break

                segment = frame_count - cursor
                beats_per_frame = self.bpm / (60.0 * self.sample_rate)
                if self.events:
                    distance = self.events[0].at_beat - self.beat
                    if distance > EPSILON:
                        segment = min(segment, max(1, math.ceil(distance / beats_per_frame - EPSILON)))
                for runtime in self.channels:
                    if runtime.next_step_beat is not None:
                        distance = runtime.next_step_beat - self.beat
                        if distance > EPSILON:
                            segment = min(segment, max(1, math.ceil(distance / beats_per_frame - EPSILON)))
                    elif runtime.next_step_frame is not None and runtime.next_step_frame > self.frame:
                        segment = min(segment, runtime.next_step_frame - self.frame)
                for boundary in self._frame_boundaries():
                    if boundary is not None and boundary > self.frame:
                        segment = min(segment, boundary - self.frame)

                for runtime in self.channels:
                    runtime.render_into(left, right, cursor, segment)
                if _np is not None:
                    gains = self.master.block(segment)
                    left_values = left[cursor : cursor + segment] * gains
                    right_values = right[cursor : cursor + segment] * gains
                    left[cursor : cursor + segment] = left_values / (1.0 + _np.abs(left_values))
                    right[cursor : cursor + segment] = right_values / (1.0 + _np.abs(right_values))
                else:
                    for index in range(cursor, cursor + segment):
                        gain = self.master.tick()
                        left[index] = _soft_limit(left[index] * gain)
                        right[index] = _soft_limit(right[index] * gain)
                self.frame += segment
                self.beat += segment * beats_per_frame
                cursor += segment

            output = array("f")
            if _np is not None:
                interleaved = _np.empty(frame_count * 2, dtype=_np.float32)
                interleaved[0::2] = left
                interleaved[1::2] = right
                output.frombytes(interleaved.tobytes())
            else:
                for index in range(frame_count):
                    output.append(left[index])
                    output.append(right[index])
            return output

    def _frame_boundaries(self) -> tuple[int | None, int | None, int | None]:
        fade_start = None
        if self.deadline_frame is not None and not self.deadline_fade_started:
            fade_start = max(self.frame, self.deadline_frame - self.deadline_fade_frames)
        return fade_start, self.deadline_frame, self.stop_at_frame

    def _handle_deadline(self) -> None:
        if self.stop_at_frame is not None and self.frame >= self.stop_at_frame:
            self.master.set(0.0, 0)
            self.running = False
            self.history.append(self._history_entry("applied", f"{self.stop_reason or 'stop'}-complete", None, {}))
            return
        if self.deadline_frame is None:
            return
        fade_start = self.deadline_frame - self.deadline_fade_frames
        if not self.deadline_fade_started and self.frame >= fade_start:
            remaining = max(0, self.deadline_frame - self.frame)
            self.master.set(0.0, remaining)
            self.deadline_fade_started = True
            self.stop_reason = "deadline"
            self.stop_at_frame = self.deadline_frame
            self.history.append(self._history_entry("applied", "deadline-fade", None, {}))

    def _seconds_remaining(self) -> float | None:
        if self.deadline_frame is None:
            return None
        return max(0.0, (self.deadline_frame - self.frame) / self.sample_rate)

    def status(self) -> dict[str, Any]:
        with self.lock:
            beat_in_bar = self.beat % self.bar_beats
            channel_data = []
            for runtime in self.channels:
                data = runtime.config.public()
                data["runtime"] = runtime.runtime_public(self.frame, self.beat)
                channel_data.append(data)
            return {
                "schema_version": 2,
                "entropy_stamp": self.entropy_stamp,
                "running": self.running,
                "backend": self.backend_name,
                "sample_rate": self.sample_rate,
                "bpm": round(self.bpm, 6),
                "master_volume": round(float(self.master.target), 5),
                "transport": {
                    "frame": self.frame,
                    "seconds": round(self.frame / self.sample_rate, 6),
                    "beat": round(self.beat, 6),
                    "bar": int(self.beat // self.bar_beats) + 1,
                    "beat_in_bar": round(beat_in_bar, 6),
                    "beats_per_bar": self.bar_beats,
                },
                "deadline": {
                    "active": self.deadline_frame is not None,
                    "seconds_remaining": _rounded(self._seconds_remaining()),
                    "fade_seconds": round(self.deadline_fade_frames / self.sample_rate, 6),
                },
                "scheduled": [event.public(self.beat) for event in self.events],
                "channels": channel_data,
                "health": {"underruns": self.underruns},
                "history": copy.deepcopy(self.history[-256:]),
                "stop_reason": self.stop_reason,
                "started_at_unix": self.started_wall,
            }

    def compact_status(self, history_limit: int = 16) -> dict[str, Any]:
        with self.lock:
            limit = max(0, min(int(history_limit), 256))
            channels = []
            for runtime in self.channels:
                config = runtime.config
                live = runtime.runtime_public(self.frame, self.beat)
                channels.append(
                    {
                        "id": config.id,
                        "name": config.name,
                        "active": config.active,
                        "muted": config.muted,
                        "clock": config.clock,
                        "bpm": config.bpm,
                        "step_beats": config.step_beats,
                        "random_seed": random_seed_public(config.random_seed),
                        "loop_steps": len(config.pattern),
                        "loop_seconds": round(len(config.pattern) * config.step_beats * 60.0 / config.bpm, 6),
                        "waveform": config.synth.waveform,
                        "volume": config.volume,
                        "pan": config.pan,
                        "modulation": config.synth.modulation.target,
                        "voices": live["active_voices"],
                        "local_beat": live["local_beat"],
                        "level": live["level"],
                    }
                )
            return {
                "schema_version": 2,
                "entropy_stamp": self.entropy_stamp,
                "running": self.running,
                "backend": self.backend_name,
                "sample_rate": self.sample_rate,
                "bpm": round(self.bpm, 6),
                "master_volume": round(float(self.master.target), 5),
                "transport": {
                    "frame": self.frame,
                    "seconds": round(self.frame / self.sample_rate, 6),
                    "beat": round(self.beat, 6),
                },
                "deadline": {
                    "active": self.deadline_frame is not None,
                    "seconds_remaining": _rounded(self._seconds_remaining()),
                    "fade_seconds": round(self.deadline_fade_frames / self.sample_rate, 6),
                },
                "scheduled": [event.public(self.beat) for event in self.events],
                "channels": channels,
                "health": {"underruns": self.underruns},
                "history": copy.deepcopy(self.history[-limit:]) if limit else [],
                "stop_reason": self.stop_reason,
            }

    def history_since(self, after_id: int | None = None, limit: int = 64) -> list[dict[str, Any]]:
        with self.lock:
            entries = self.history
            if after_id is not None:
                entries = [entry for entry in entries if entry.get("id") is None or entry.get("id") > after_id]
            return copy.deepcopy(entries[-max(1, min(int(limit), 512)) :])


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def _soft_limit(value: float) -> float:
    return value / (1.0 + abs(value))
