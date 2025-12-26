// main.js - IMU Data Analysis Frontend
const WS_HOST = window.location.hostname;
const WS_PORT = 8765;
const WS_PATH = "/ui";
let ws = null;
let wsBackoff = 1000;

// DOM Elements
const startBtn = document.getElementById("startBtn");
const stopBtn = document.getElementById("stopBtn");
const stateEl = document.getElementById("state");
const filenameEl = document.getElementById("filename");

// Live data elements
const liveTimeEl = document.getElementById("liveTime");
const liveAccelEl = document.getElementById("liveAccel");
const liveGyroEl = document.getElementById("liveGyro");
const liveMagnitudeEl = document.getElementById("liveMagnitude");
const liveRMSEl = document.getElementById("liveRMS");
const liveMeanEl = document.getElementById("liveMean");

// Statistics elements
const statMaxAccelEl = document.getElementById("statMaxAccel");
const statMinAccelEl = document.getElementById("statMinAccel");
const statAvgAccelEl = document.getElementById("statAvgAccel");
const statPeakFreqEl = document.getElementById("statPeakFreq");
const statPeaksEl = document.getElementById("statPeaks");
const statSamplesEl = document.getElementById("statSamples");

// Plotly traces
let accelTraceX, accelTraceY, accelTraceZ;
let fftTrace;
let magnitudeTrace;
let vectorTrace;

// Data buffers
const dataBuffers = {
    timestamps: [],
    ax: [], ay: [], az: [],
    gx: [], gy: [], gz: [],
    magnitude: [],
    fftFreq: [],
    fftAmp: []
};

// Statistics
let stats = {
    maxAccel: -Infinity,
    minAccel: Infinity,
    avgAccel: 0,
    peakFreq: 0,
    peaksDetected: 0,
    sampleCount: 0
};

// Initialize date picker
document.getElementById('date').valueAsDate = new Date();

// Initialize plots
function initPlots() {
    // Acceleration vs Time plot
    accelTraceX = {
        x: [],
        y: [],
        name: 'X-axis',
        mode: 'lines',
        line: { color: '#ff6b6b' }
    };
    
    accelTraceY = {
        x: [],
        y: [],
        name: 'Y-axis',
        mode: 'lines',
        line: { color: '#51cf66' }
    };
    
    accelTraceZ = {
        x: [],
        y: [],
        name: 'Z-axis',
        mode: 'lines',
        line: { color: '#4dabf7' }
    };
    
    Plotly.newPlot('accelPlot', [accelTraceX, accelTraceY, accelTraceZ], {
        title: 'Acceleration (g) vs Time',
        xaxis: { title: 'Time (s)', gridcolor: '#f0f0f0' },
        yaxis: { title: 'Acceleration (g)', gridcolor: '#f0f0f0' },
        plot_bgcolor: '#fff',
        paper_bgcolor: '#fff',
        showlegend: true,
        legend: { x: 1, xanchor: 'right', y: 1 }
    });
    
    // FFT plot
    fftTrace = {
        x: [],
        y: [],
        type: 'bar',
        marker: { color: '#7950f2' }
    };
    
    Plotly.newPlot('fftPlot', [fftTrace], {
        title: 'Frequency Spectrum',
        xaxis: { title: 'Frequency (Hz)', gridcolor: '#f0f0f0' },
        yaxis: { title: 'Amplitude', gridcolor: '#f0f0f0' },
        plot_bgcolor: '#fff',
        paper_bgcolor: '#fff'
    });
    
    // Magnitude plot
    magnitudeTrace = {
        x: [],
        y: [],
        mode: 'lines',
        line: { color: '#fab005' },
        name: 'Magnitude'
    };
    
    Plotly.newPlot('magnitudePlot', [magnitudeTrace], {
        title: 'Magnitude vs Time',
        xaxis: { title: 'Time (s)', gridcolor: '#f0f0f0' },
        yaxis: { title: 'Magnitude (g)', gridcolor: '#f0f0f0' },
        plot_bgcolor: '#fff',
        paper_bgcolor: '#fff'
    });
    
    // 3D Vector plot
    vectorTrace = {
        x: [0], y: [0], z: [0],
        u: [0], v: [0], w: [0],
        type: 'cone',
        sizemode: 'absolute',
        sizeref: 0.5,
        anchor: 'tail',
        colorscale: 'Viridis'
    };
    
    Plotly.newPlot('vectorPlot', [vectorTrace], {
        title: '3D Acceleration Vector',
        scene: {
            xaxis: { title: 'X', range: [-2, 2] },
            yaxis: { title: 'Y', range: [-2, 2] },
            zaxis: { title: 'Z', range: [-2, 2] }
        },
        margin: { l: 0, r: 0, b: 0, t: 30 }
    });
}

// WebSocket connection
function connectWS() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
    
    const url = `ws://${WS_HOST}:${WS_PORT}${WS_PATH}`;
    console.log("[UI] connecting to", url);
    ws = new WebSocket(url);
    
    ws.onopen = () => {
        console.log("[UI] ws open");
        wsBackoff = 1000;
        showAlert("Connected to server", "success");
    };
    
    ws.onmessage = (evt) => {
        try {
            const packet = JSON.parse(evt.data);
            if (packet.type === 'imu_data') {
                updateUI(packet.data);
                updatePlots(packet.data, packet.analysis);
                updateStats(packet.data);
            }
        } catch (err) {
            console.error("Parse error:", err);
        }
    };
    
    ws.onclose = () => {
        console.log("[UI] ws closed, will reconnect in", wsBackoff);
        showAlert("Connection lost, reconnecting...", "warning");
        setTimeout(connectWS, wsBackoff);
        wsBackoff = Math.min(16000, wsBackoff * 2);
    };
    
    ws.onerror = (e) => {
        console.error("[UI] ws error", e);
        showAlert("WebSocket error", "error");
        ws.close();
    };
}

// Update UI with latest data
function updateUI(data) {
    liveTimeEl.textContent = `${data.date} ${data.time}`;
    liveAccelEl.textContent = `X: ${data.ax_g?.toFixed(3) || 0}g Y: ${data.ay_g?.toFixed(3) || 0}g Z: ${data.az_g?.toFixed(3) || 0}g`;
    liveGyroEl.textContent = `X: ${data.gx_dps?.toFixed(1) || 0}°/s Y: ${data.gy_dps?.toFixed(1) || 0}°/s Z: ${data.gz_dps?.toFixed(1) || 0}°/s`;
    liveMagnitudeEl.textContent = `${data.magnitude?.toFixed(3) || 0} g`;
    liveRMSEl.textContent = data.rms_magnitude ? data.rms_magnitude.toFixed(3) : '-';
    liveMeanEl.textContent = data.mean_magnitude ? data.mean_magnitude.toFixed(3) : '-';
    
    // Update buffers
    const now = Date.now() / 1000;
    dataBuffers.timestamps.push(now);
    dataBuffers.ax.push(data.ax_g || 0);
    dataBuffers.ay.push(data.ay_g || 0);
    dataBuffers.az.push(data.az_g || 0);
    dataBuffers.magnitude.push(data.magnitude || 0);
    
    // Keep last 200 samples
    const maxSamples = 200;
    if (dataBuffers.timestamps.length > maxSamples) {
        dataBuffers.timestamps.shift();
        dataBuffers.ax.shift();
        dataBuffers.ay.shift();
        dataBuffers.az.shift();
        dataBuffers.magnitude.shift();
    }
    
    // Update FFT data if available
    if (data.fft_freq && data.fft_amp) {
        dataBuffers.fftFreq = data.fft_freq;
        dataBuffers.fftAmp = data.fft_amp;
    }
}

// Update plots
function updatePlots(data, analysis) {
    const now = Date.now() / 1000;
    
    // Acceleration plot
    Plotly.extendTraces('accelPlot', {
        x: [[now], [now], [now]],
        y: [[data.ax_g || 0], [data.ay_g || 0], [data.az_g || 0]]
    }, [0, 1, 2]);
    
    // Keep plot window reasonable
    if (dataBuffers.timestamps.length > 100) {
        Plotly.relayout('accelPlot', {
            'xaxis.range': [now - 10, now]
        });
    }
    
    // FFT plot
    if (dataBuffers.fftFreq.length > 0 && dataBuffers.fftAmp.length > 0) {
        Plotly.react('fftPlot', [{
            x: dataBuffers.fftFreq,
            y: dataBuffers.fftAmp,
            type: 'bar',
            marker: { color: '#7950f2' }
        }], {
            title: 'Frequency Spectrum',
            xaxis: { title: 'Frequency (Hz)' },
            yaxis: { title: 'Amplitude' }
        });
    }
    
    // Magnitude plot
    Plotly.extendTraces('magnitudePlot', {
        x: [[now]],
        y: [[data.magnitude || 0]]
    }, [0]);
    
    if (dataBuffers.timestamps.length > 100) {
        Plotly.relayout('magnitudePlot', {
            'xaxis.range': [now - 10, now]
        });
    }
    
    // 3D Vector plot
    if (data.ax_g && data.ay_g && data.az_g) {
        Plotly.react('vectorPlot', [{
            x: [0], y: [0], z: [0],
            u: [data.ax_g], v: [data.ay_g], w: [data.az_g],
            type: 'cone',
            sizemode: 'absolute',
            sizeref: 1,
            anchor: 'tail',
            colorscale: 'Viridis',
            showscale: false
        }], {
            scene: {
                xaxis: { title: 'X', range: [-2, 2] },
                yaxis: { title: 'Y', range: [-2, 2] },
                zaxis: { title: 'Z', range: [-2, 2] }
            }
        });
    }
}

// Update statistics
function updateStats(data) {
    stats.sampleCount++;
    
    // Update max/min acceleration
    const magnitude = data.magnitude || 0;
    stats.maxAccel = Math.max(stats.maxAccel, magnitude);
    stats.minAccel = Math.min(stats.minAccel, magnitude);
    
    // Update average
    stats.avgAccel = (stats.avgAccel * (stats.sampleCount - 1) + magnitude) / stats.sampleCount;
    
    // Update peak frequency
    if (data.fft_peaks && data.fft_peaks.length > 0) {
        const maxPeak = data.fft_peaks.reduce((max, peak) => peak.amp > max.amp ? peak : max);
        stats.peakFreq = maxPeak.freq;
        stats.peaksDetected += data.fft_peaks.length;
    }
    
    // Update UI
    statMaxAccelEl.textContent = `${stats.maxAccel.toFixed(3)} g`;
    statMinAccelEl.textContent = `${stats.minAccel.toFixed(3)} g`;
    statAvgAccelEl.textContent = `${stats.avgAccel.toFixed(3)} g`;
    statPeakFreqEl.textContent = `${stats.peakFreq.toFixed(1)} Hz`;
    statPeaksEl.textContent = stats.peaksDetected;
    statSamplesEl.textContent = stats.sampleCount;
}

// Alert notification
function showAlert(message, type = 'info') {
    const alert = document.createElement('div');
    alert.className = `alert ${type}`;
    alert.textContent = message;
    document.body.appendChild(alert);
    
    setTimeout(() => {
        alert.style.opacity = '0';
        setTimeout(() => alert.remove(), 300);
    }, 3000);
}

// API calls
async function postJson(path, obj) {
    const res = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(obj)
    });
    return res.json();
}

// Event listeners
startBtn.addEventListener("click", async () => {
    const readingType = document.getElementById("reading_type").value.trim();
    const date = document.getElementById("date").value;
    
    if (!readingType || !date) {
        showAlert("Please fill reading type and date fields.", "error");
        return;
    }
    
    try {
        const resp = await postJson("/start", { reading_type: readingType, date });
        console.log("start resp", resp);
        stateEl.textContent = "Recording";
        filenameEl.textContent = resp.file || '-';
        showAlert("Recording started", "success");
        
        // Reset stats for new recording
        stats = {
            maxAccel: -Infinity,
            minAccel: Infinity,
            avgAccel: 0,
            peakFreq: 0,
            peaksDetected: 0,
            sampleCount: 0
        };
    } catch (e) {
        console.error("Start failed", e);
        showAlert("Start failed", "error");
    }
});

stopBtn.addEventListener("click", async () => {
    try {
        const resp = await postJson("/stop", {});
        console.log("stop resp", resp);
        stateEl.textContent = "Idle";
        filenameEl.textContent = '-';
        showAlert("Recording stopped", "success");
    } catch (e) {
        console.error("Stop failed", e);
        showAlert("Stop failed", "error");
    }
});

// Status polling
async function pollStatus() {
    try {
        const r = await fetch("/status");
        const j = await r.json();
        stateEl.textContent = j.record ? "Recording" : "Idle";
        filenameEl.textContent = j.session?.filename ? 
            `File: ${j.session.filename.split('/').pop()}` : '-';
    } catch (e) {
        stateEl.textContent = "Error";
        filenameEl.textContent = '-';
    }
    setTimeout(pollStatus, 1000);
}

// Initialize
initPlots();
connectWS();
pollStatus();

// Window resize handling
window.addEventListener('resize', () => {
    Plotly.Plots.resize('accelPlot');
    Plotly.Plots.resize('fftPlot');
    Plotly.Plots.resize('magnitudePlot');
    Plotly.Plots.resize('vectorPlot');
});