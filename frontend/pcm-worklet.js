// Turns microphone audio into PCM16 little-endian mono frames of exactly FRAME_BYTES (512 samples
// at 16 kHz). The page asks for a 16 kHz AudioContext, so normally no resampling happens here;
// if the browser gave a different rate, a linear-interpolation resampler brings it to 16 kHz.
// Each frame is posted to the page together with its RMS level (for the "listening" bars).

class Pcm16Framer extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const o = (options && options.processorOptions) || {};
    this.targetRate = o.targetRate || 16000;
    this.frameSamples = (o.frameBytes || 1024) / 2;
    this.step = sampleRate / this.targetRate; // input samples per output sample
    this.t = 0; // resampler read position, relative to the current block
    this.prev = 0; // last sample of the previous block
    this.newFrame();
    this.running = true;
    this.port.onmessage = (e) => {
      if (e.data === "stop") this.running = false;
    };
  }

  newFrame() {
    this.view = new DataView(new ArrayBuffer(this.frameSamples * 2));
    this.n = 0;
    this.sumSq = 0;
  }

  push(x) {
    const s = x > 1 ? 1 : x < -1 ? -1 : x;
    this.view.setInt16(this.n * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    this.sumSq += s * s;
    this.n += 1;
    if (this.n === this.frameSamples) {
      const pcm = this.view.buffer;
      this.port.postMessage({ pcm, rms: Math.sqrt(this.sumSq / this.n) }, [pcm]);
      this.newFrame();
    }
  }

  process(inputs) {
    if (!this.running) return false;
    const ch = inputs[0] && inputs[0][0];
    if (!ch || ch.length === 0) return true;
    if (this.step === 1) {
      for (let i = 0; i < ch.length; i++) this.push(ch[i]);
      return true;
    }
    const len = ch.length;
    while (this.t < len - 1) {
      const i = Math.floor(this.t);
      const f = this.t - i;
      const a = i < 0 ? this.prev : ch[i];
      const b = ch[i + 1];
      this.push(a + (b - a) * f);
      this.t += this.step;
    }
    this.t -= len;
    this.prev = ch[len - 1];
    return true;
  }
}

registerProcessor("pcm16-framer", Pcm16Framer);
