// AudioWorklet that converts mono float32 PCM (at the AudioContext's sample
// rate — we request 16000Hz) into int16 chunks and posts them back to the
// main thread. Chunked at 100ms (1600 samples @ 16kHz) so the WebSocket
// doesn't fragment audio into tiny frames.
class PcmWorklet extends AudioWorkletProcessor {
  constructor() {
    super();
    this._target = 1600;
    this._buf = new Float32Array(this._target);
    this._fill = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;
    const ch = input[0];
    let read = 0;
    while (read < ch.length) {
      const space = this._target - this._fill;
      const take = Math.min(space, ch.length - read);
      this._buf.set(ch.subarray(read, read + take), this._fill);
      this._fill += take;
      read += take;
      if (this._fill === this._target) {
        const pcm = new Int16Array(this._target);
        for (let i = 0; i < this._target; i++) {
          const s = Math.max(-1, Math.min(1, this._buf[i]));
          pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }
        this.port.postMessage(pcm.buffer, [pcm.buffer]);
        this._fill = 0;
      }
    }
    return true;
  }
}

registerProcessor('pcm-worklet', PcmWorklet);
