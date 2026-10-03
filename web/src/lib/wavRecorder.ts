// マイク録音を WAV(非圧縮・16bit PCM・モノラル) で取得する。
// 収録仕様: サンプルレートはデバイス既定(通常48kHz≧44.1kHz)、モノラル、16bit PCM、WAV。
// MediaRecorder(webm/opus)は非可逆で前処理前に劣化するため、Web Audioで生PCMを収録する。

function mergeFloat32(chunks: Float32Array[]): Float32Array {
  const len = chunks.reduce((a, c) => a + c.length, 0);
  const out = new Float32Array(len);
  let o = 0;
  for (const c of chunks) { out.set(c, o); o += c.length; }
  return out;
}

/** Float32(-1..1) のモノラル信号を 16bit PCM WAV Blob へ符号化。 */
export function encodeWav(samples: Float32Array, sampleRate: number): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeStr = (o: number, s: string) => { for (let i = 0; i < s.length; i++) view.setUint8(o + i, s.charCodeAt(i)); };
  writeStr(0, 'RIFF');
  view.setUint32(4, 36 + samples.length * 2, true);
  writeStr(8, 'WAVE');
  writeStr(12, 'fmt ');
  view.setUint32(16, 16, true);          // fmt チャンクサイズ
  view.setUint16(20, 1, true);           // PCM
  view.setUint16(22, 1, true);           // モノラル
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); // バイト/秒 (sr * blockAlign)
  view.setUint16(32, 2, true);           // blockAlign (mono*16bit/8)
  view.setUint16(34, 16, true);          // 量子化ビット
  writeStr(36, 'data');
  view.setUint32(40, samples.length * 2, true);
  let off = 44;
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(off, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    off += 2;
  }
  return new Blob([view], { type: 'audio/wav' });
}

export class WavRecorder {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private node: ScriptProcessorNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private chunks: Float32Array[] = [];
  sampleRate = 48000;

  async start(): Promise<void> {
    // 生の声質を保つため各種プロセッシングは無効（仕様準拠のクリーン収録）
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: false, noiseSuppression: false, autoGainControl: false },
    });
    const AC: typeof AudioContext =
      window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    this.ctx = new AC();
    this.sampleRate = this.ctx.sampleRate; // 通常 48000（≧44.1kHz）
    this.source = this.ctx.createMediaStreamSource(this.stream);
    this.node = this.ctx.createScriptProcessor(4096, 1, 1);
    this.chunks = [];
    this.node.onaudioprocess = (e) => {
      this.chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
    };
    this.source.connect(this.node);
    this.node.connect(this.ctx.destination); // 一部ブラウザで onaudioprocess 発火に必要
  }

  /** 収録停止。WAV(16bit PCM/mono) Blob を返す。 */
  async stop(): Promise<Blob> {
    const sr = this.sampleRate;
    const data = mergeFloat32(this.chunks);
    this.dispose();
    return encodeWav(data, sr);
  }

  /** マイク/AudioContext を解放（アンマウント時等）。 */
  dispose(): void {
    try { this.node?.disconnect(); } catch { /* noop */ }
    try { this.source?.disconnect(); } catch { /* noop */ }
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ctx?.close().catch(() => {});
    this.node = null; this.source = null; this.stream = null; this.ctx = null; this.chunks = [];
  }
}
