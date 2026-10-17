/* ==========================================================================
   MediaPipe hand tracking, loaded from a CDN on demand.

   Pinned to the same version as the desktop app's Python package so both
   track hands identically. Nothing is bundled: the module and the model are
   fetched at runtime (so the page needs internet the first time, and works
   from the browser cache after that).
   ========================================================================== */

export const MEDIAPIPE_CDN = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@1.1.1";
export const MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/hand_landmarker/" +
  "hand_landmarker/float16/1/hand_landmarker.task";

/* Does this machine actually have a GPU?
 *
 * With no GPU, asking MediaPipe for the "GPU" delegate silently lands on a
 * software renderer (SwiftShader / llvmpipe), which is *slower* than the
 * CPU/WASM path. So probe once and choose deliberately. Returns true, false,
 * or null when the answer can't be determined - callers then assume "yes" so
 * the nicer delegate is kept on machines that hide the renderer string. */
export function hasHardwareGPU() {
  try {
    const canvas = document.createElement("canvas");
    const gl = canvas.getContext("webgl2") || canvas.getContext("webgl");
    if (!gl) return false;
    const ext = gl.getExtension("WEBGL_debug_renderer_info");
    const renderer = ext ? String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) || "") : "";
    if (!renderer) return null;
    const soft = /swiftshader|software|llvmpipe|basic render|microsoft basic|offscreen/i;
    return !soft.test(renderer);
  } catch {
    return null;
  }
}

export async function loadHandLandmarker() {
  let mp;
  try {
    // @vite-ignore keeps Vite from trying to bundle this runtime CDN URL
    mp = await import(/* @vite-ignore */ `${MEDIAPIPE_CDN}/vision_bundle.mjs`);
  } catch {
    throw new Error("Hand tracking could not load (offline?) - click the keys to play.");
  }

  const vision = await mp.FilesetResolver.forVisionTasks(`${MEDIAPIPE_CDN}/wasm`);
  const gpu = hasHardwareGPU() !== false;
  const options = {
    baseOptions: { modelAssetPath: MODEL_URL, delegate: gpu ? "GPU" : "CPU" },
    runningMode: "VIDEO",
    numHands: 2,
    minHandDetectionConfidence: 0.6,
    minTrackingConfidence: 0.5,
  };

  try {
    const landmarker = await mp.HandLandmarker.createFromOptions(vision, options);
    return { landmarker, delegate: gpu ? "gpu" : "cpu" };
  } catch {
    try {
      // no usable GPU delegate after all - fall back to the CPU/WASM path
      options.baseOptions = { modelAssetPath: MODEL_URL, delegate: "CPU" };
      const landmarker = await mp.HandLandmarker.createFromOptions(vision, options);
      return { landmarker, delegate: "cpu" };
    } catch {
      throw new Error("Hand tracking could not start - click the keys to play.");
    }
  }
}
