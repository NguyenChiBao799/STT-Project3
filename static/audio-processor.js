class PCMProcessor extends AudioWorkletProcessor {
    constructor() {
        super();
        this.port.onmessage = (event) => {};
    }

    process(inputs, outputs, parameters) {
        const input = inputs[0];

        if (input && input[0]) {
            const floatSamples = input[0];

            // Chuyển float32 → int16 để backend dễ xử lý
            const buffer = new ArrayBuffer(floatSamples.length * 2);
            const view = new DataView(buffer);

            for (let i = 0; i < floatSamples.length; i++) {
                let s = Math.max(-1, Math.min(1, floatSamples[i]));
                view.setInt16(i * 2, s * 0x7fff, true);
            }

            this.port.postMessage(buffer, [buffer]);
        }

        return true;
    }
}

registerProcessor("pcm-processor", PCMProcessor);
